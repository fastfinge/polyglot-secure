# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Persistent cache for translation results.

Translations are kept in memory and written to NVDA's configuration directory by a background writer
that gathers changes for :data:`SAVE_INTERVAL` seconds and writes them once. Auto-translation can
finish a translation for every utterance NVDA speaks, and every result used to reach the disk on the
spot, so a full-sized cache was written several times a second.
:meth:`TranslationCache.terminate` writes whatever is still pending when the add-on is unloaded, so
the last few seconds of translations survive NVDA shutting down.

The file is a log rather than a document: one JSON ``[key, value]`` record to a line, and a write
appends only the entries that changed. Rewriting the whole file instead cost time in proportion to
everything ever cached rather than to the handful of new translations, which is what kept the cache
small enough to be worth rewriting. The last record for a key is the one that counts, so the file is
rewritten from memory once it holds :data:`_COMPACTION_RATIO` times more records than the cache
holds entries. That rewrite, called compaction here, is also what gets evicted and cleared entries
off the disk.

Entries are evicted least recently used first, so an entry that keeps being read is kept even once
it is one of the oldest. A read reorders the cache in memory but writes nothing, so read recency
reaches the disk only with the next compaction; losing some of that ordering to a crash costs
nothing but a few cache misses.

The cache is content the user never chose to keep: it records every string translated, which under
auto-translation is much of what NVDA has spoken. It is therefore bounded by
:data:`DEFAULT_MAX_SIZE` rather than kept indefinitely, and nothing else would clean it up, so it is
removed when the add-on is uninstalled. See :mod:`installTasks`.
"""

import contextlib
import hashlib
import json
import os
import threading
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any, Self  # Self is available in Python 3.11+

import globalVars
from logHandler import log

#: Name of the file the cache is written to, inside NVDA's configuration directory.
CACHE_FILENAME = "translation_cache.jsonl"

#: Name of the file used by versions that kept the whole cache in one JSON document.
LEGACY_CACHE_FILENAME = "translation_cache.json"

#: How many entries are kept. Appending rather than rewriting means the file no longer costs more to
#: write the fuller it gets, so this is set by what is reasonable to hold in memory and to keep about
#: at all, rather than by what is cheap to write.
DEFAULT_MAX_SIZE = 50000

#: How long changes are gathered before being written, in seconds. A burst of translations then costs
#: one write rather than one each, and a crash loses at most this much of a cache that is disposable.
SAVE_INTERVAL = 10.0

#: How long :meth:`TranslationCache.terminate` waits for the background writer to stop, in seconds.
_TERMINATE_TIMEOUT = 5.0

#: Suffix of the file a compacted cache is written to before it replaces the old one.
_TEMPORARY_SUFFIX = ".tmp"

#: How many records the file may hold per entry in the cache before it is worth rewriting.
_COMPACTION_RATIO = 2

#: How many records the file must hold before compacting it is worth doing at all. Without this, a
#: nearly empty cache would be rewritten over and over for no saving worth having.
_COMPACTION_MINIMUM = 1000


def getCachePath(filename: str = CACHE_FILENAME) -> str:
	"""Return the full path of the translation cache file."""
	return os.path.join(globalVars.appArgs.configPath, filename)


def _removeFile(path: str) -> bool:
	"""Remove one file, logging rather than raising when it cannot be removed.

	:return: Whether a file was found and removed.
	"""
	try:
		os.remove(path)
	except FileNotFoundError:
		return False
	except OSError:
		log.exception(f"Could not remove the translation cache file '{path}'.")
		return False
	return True


def deleteCacheFile(filename: str = CACHE_FILENAME) -> bool:
	"""Remove the translation cache from disk, with any half-written copy left by a failed write.

	The file written by versions that kept the cache as one JSON document goes too: it holds the same
	kind of content, and a user removing the add-on is not asking to keep the older half of it.
	Failures are logged rather than raised, so a file that cannot be removed does not stop the rest of
	the add-on's clean-up.

	:return: Whether a cache file was found and removed.
	"""
	paths: list[str] = []
	for name in (filename, LEGACY_CACHE_FILENAME):
		basePath = getCachePath(name)
		paths.append(basePath)
		paths.append(basePath + _TEMPORARY_SUFFIX)
	removedAny = False
	# The names coincide when a caller asks for the legacy file by name.
	for path in dict.fromkeys(paths):
		if _removeFile(path):
			removedAny = True
	return removedAny


#: Escapes for the line separators JSON leaves as they are. Translated text really does contain them,
#: and while this file is read a line at a time by a rule that does not treat them as breaks, a
#: record that looks like two lines to anything else reading the file is asking for trouble.
_LINE_SEPARATOR_ESCAPES = {0x2028: "\\u2028", 0x2029: "\\u2029"}


def _encodeRecords(records: Iterable[tuple[str, str]]) -> str:
	"""Return the given entries as one JSON record to a line.

	JSON escapes the ordinary line breaks inside a string, and :data:`_LINE_SEPARATOR_ESCAPES` covers
	the ones it does not, so a record cannot span more than one line however odd the text translated
	was. Text is left as it is otherwise: escaping it all would cost several times the disk on the
	non-Latin scripts this add-on exists to translate.
	"""
	return "".join(
		f"{json.dumps([key, value], ensure_ascii=False).translate(_LINE_SEPARATOR_ESCAPES)}\n"
		for key, value in records
	)


class TranslationCache:
	"""Provides a simple, persistent cache for translation results. Implemented as a singleton."""

	_instance: Self | None = None

	cachePath: str
	maxSize: int
	saveInterval: float
	_cache: "OrderedDict[str, str]"
	_lock: threading.RLock
	_writeLock: threading.Lock
	_pendingSave: threading.Event
	_stopping: threading.Event
	_writer: threading.Thread | None
	_pending: list[tuple[str, str]]
	_needsCompaction: bool
	_recordsOnDisk: int
	_isInitialized: bool

	def __new__(cls, *args: Any, **kwargs: Any) -> Self:
		"""Return the process-wide translation cache instance."""
		if not cls._instance:
			cls._instance = super().__new__(cls)
		return cls._instance

	def __init__(
		self,
		filename: str = CACHE_FILENAME,
		maxSize: int = DEFAULT_MAX_SIZE,
		saveInterval: float = SAVE_INTERVAL,
	) -> None:
		"""Initialize the singleton cache from NVDA's configuration directory."""
		super().__init__()
		if hasattr(self, "_isInitialized"):
			return
		self.cachePath = getCachePath(filename)
		self.maxSize = maxSize
		self.saveInterval = saveInterval
		self._lock = threading.RLock()
		self._writeLock = threading.Lock()
		self._pendingSave = threading.Event()
		self._stopping = threading.Event()
		self._writer = None
		self._pending = []
		self._needsCompaction = False
		self._recordsOnDisk = 0
		self._cache = self._load()
		self._prune()
		self._migrateLegacyCache()
		self._isInitialized = True
		log.debug("Translation cache initialized with %d items.", len(self._cache))

	def _load(self) -> "OrderedDict[str, str]":
		"""Read the cache from disk, returning an empty cache when it cannot be read.

		Sets :attr:`_recordsOnDisk` to what the file was found to hold, and asks for a compaction when
		part of it could not be read. The cache is disposable, so a file that is missing, unreadable,
		or not the shape this writes costs a fresh start rather than an error the user has to do
		something about.
		"""
		entries, recordCount, isDamaged = self._readRecords()
		self._recordsOnDisk = recordCount
		if isDamaged:
			# A record cut short by a crash has no newline after it, so appending would run the next
			# record onto the end of it and lose both. Rewriting the file settles that first.
			self._needsCompaction = True
		return entries

	def _readRecords(self) -> "tuple[OrderedDict[str, str], int, bool]":
		"""Read the log, keeping the last record written for each key.

		:return: The entries in the order they were last written, how many records the file held, and
			whether any of them could not be used.
		"""
		entries: "OrderedDict[str, str]" = OrderedDict()
		recordCount = 0
		isDamaged = False
		try:
			with open(self.cachePath, "r", encoding="utf-8") as f:
				for line in f:
					strippedLine = line.strip()
					if not strippedLine:
						continue
					recordCount += 1
					entry = self._decodeRecord(strippedLine)
					if entry is None:
						isDamaged = True
						continue
					key, value = entry
					entries[key] = value
					# A key written again is the most recently used, not still in its old position.
					entries.move_to_end(key)
		except FileNotFoundError:
			return OrderedDict(), 0, False
		except OSError:
			log.error("Failed to load the translation cache.", exc_info=True)
			return OrderedDict(), 0, False
		if isDamaged:
			log.debug("Part of the translation cache could not be read and has been dropped.")
		return entries, recordCount, isDamaged

	@staticmethod
	def _decodeRecord(line: str) -> tuple[str, str] | None:
		"""Return the entry one line of the log holds, or None when it does not hold a usable one.

		A line cut short by a crash, or a hand-edited one, can hold anything, and a value that is not
		text cannot be served as a translation.
		"""
		try:
			record: Any = json.loads(line)
		except ValueError:
			return None
		if not isinstance(record, list) or len(record) != 2:
			return None
		key: Any = record[0]
		value: Any = record[1]
		if not isinstance(key, str) or not isinstance(value, str):
			return None
		return key, value

	def _migrateLegacyCache(self) -> None:
		"""Take over the cache left by a version that kept the whole thing in one JSON document.

		The old file is removed once its entries are safely in the new one, and left alone when they
		could not be written. It is a plaintext record of what NVDA has spoken, so a copy of it left
		lying about is not harmless, and nothing else would ever remove it.
		"""
		legacyPath = getCachePath(LEGACY_CACHE_FILENAME)
		if not os.path.exists(legacyPath):
			return
		if os.path.exists(self.cachePath):
			# The cache is already being kept in the new file, so the old one is only left over.
			_unused = _removeFile(legacyPath)
			return
		entries = self._readLegacyRecords(legacyPath)
		with self._lock:
			self._cache = entries
			self._prune()
			# Written from here rather than by the background writer, which does not run until
			# something is cached, so a quiet session does not leave the old file behind.
			self._needsCompaction = True
		if self._flush():
			_unused = _removeFile(legacyPath)
			log.debug("Translation cache migrated %d items from the previous format.", len(self._cache))

	@staticmethod
	def _readLegacyRecords(path: str) -> "OrderedDict[str, str]":
		"""Read a cache written as one JSON object, returning nothing usable as an empty cache."""
		try:
			with open(path, "r", encoding="utf-8") as f:
				loadedData: Any = json.load(f, object_pairs_hook=OrderedDict)
		except (OSError, ValueError):
			log.error("Failed to load the previous translation cache.", exc_info=True)
			return OrderedDict()
		if not isinstance(loadedData, dict):
			log.error("The previous translation cache is not in the expected format and was discarded.")
			return OrderedDict()
		items: dict[Any, Any] = loadedData
		return OrderedDict(
			(key, value) for key, value in items.items() if isinstance(key, str) and isinstance(value, str)
		)

	def _ensureWriterStarted(self) -> None:
		"""Start the background writer, which is not needed until something is cached.

		The caller must hold the lock.
		"""
		if self._writer is not None:
			return
		self._writer = threading.Thread(
			target=self._writeLoop,
			name="PolyglotTranslationCacheWriter",
			daemon=True,
		)
		self._writer.start()

	def _writeLoop(self) -> None:
		"""Write pending changes on a background thread until the cache is terminated."""
		while True:
			_unused = self._pendingSave.wait()
			if self._stopping.is_set():
				break
			# Let further translations accumulate, so a burst costs one write rather than one each.
			if self._stopping.wait(self.saveInterval):
				break
			# Cleared before the write, so a change made while it runs schedules another one.
			self._pendingSave.clear()
			_unused = self._flush()

	def _scheduleWrite(self) -> bool:
		"""Ask the background writer to write what is pending.

		The caller must hold the lock. Writing cannot be done from here: :meth:`_flush` takes the write
		lock, and taking it while holding this one is the opposite of the order the background writer
		uses, which would eventually deadlock the two against each other.

		:return: Whether the caller has to write the change itself, the writer having stopped.
		"""
		if self._stopping.is_set():
			# The writer is stopping or gone, so a late change is written by the caller or not at all.
			return True
		self._ensureWriterStarted()
		self._pendingSave.set()
		return False

	def _shouldCompact(self) -> bool:
		"""Return whether the file holds enough superseded records to be worth rewriting.

		The caller must hold the lock.
		"""
		return self._recordsOnDisk > max(_COMPACTION_MINIMUM, len(self._cache) * _COMPACTION_RATIO)

	def _flush(self) -> bool:
		"""Write what is pending, doing nothing when nothing is.

		The caller must not hold the lock. Both the background writer and a translation finishing
		during shutdown can end up here at the same time, so the whole of taking the pending records
		and writing them is done under the write lock: two writers could otherwise append each other's
		records out of order, or move a half-written compaction into place over one another.

		:return: Whether the disk now holds everything that was pending.
		"""
		with self._writeLock:
			with self._lock:
				if not self._pending and not self._needsCompaction:
					return True
				isCompacting = self._needsCompaction
				records = list(self._cache.items()) if isCompacting else self._pending
				# A compaction replaces the file, so what it writes is all the file then holds.
				recordsWritten = len(records) if isCompacting else self._recordsOnDisk + len(records)
				# Taken before the write so a change made during it is not mistaken for written.
				self._pending = []
				self._needsCompaction = False
			contents = _encodeRecords(records)
			try:
				if isCompacting:
					self._writeFile(contents)
				else:
					self._appendFile(contents)
			except OSError:
				log.error("Failed to save the translation cache.", exc_info=True)
				with self._lock:
					# An append can have written part of its records, so the file is rewritten from
					# memory next time rather than added to.
					self._needsCompaction = True
				return False
			with self._lock:
				self._recordsOnDisk = recordsWritten
				if self._shouldCompact():
					self._needsCompaction = True
					# Compaction saves disk rather than work, so it waits for the writer like any
					# other change rather than holding up whatever produced the last one.
					if not self._stopping.is_set():
						self._pendingSave.set()
			return True

	def _appendFile(self, contents: str) -> None:
		"""Add records to the end of the cache file, starting one when there is not one yet."""
		with open(self.cachePath, "a", encoding="utf-8", newline="\n") as f:
			_unused = f.write(contents)

	def _writeFile(self, contents: str) -> None:
		"""Replace the cache file with the given contents, leaving the old one intact on failure.

		The new cache is written beside the old one and put in its place in a single step, so an
		interrupted compaction cannot leave a half-written file that the next start would have to
		read around.
		"""
		temporaryPath = self.cachePath + _TEMPORARY_SUFFIX
		try:
			with open(temporaryPath, "w", encoding="utf-8", newline="\n") as f:
				_unused = f.write(contents)
			os.replace(temporaryPath, self.cachePath)
		except OSError:
			with contextlib.suppress(OSError):
				os.remove(temporaryPath)
			raise

	def buildKey(self, langFrom: str, langTo: str, text: str) -> str:
		"""Generate a cache key from the language pair and normalized text."""
		# Normalize text by stripping whitespace to improve the cache hit rate.
		normalizedText = text.strip()
		keyString = f"{langFrom}:{langTo}:{normalizedText}"
		return hashlib.md5(keyString.encode("utf-8")).hexdigest()

	def get(self, key: str) -> str | None:
		"""Return a cached translation, or None when the key is absent.

		A hit counts as recent use, so an entry that goes on being read is not evicted for being old.
		"""
		with self._lock:
			value = self._cache.get(key)
			if value is None:
				return None
			self._cache.move_to_end(key)
			return value

	def set(self, key: str, value: str) -> None:
		"""Store a translation result and schedule it to be written."""
		with self._lock:
			self._cache[key] = value
			self._cache.move_to_end(key)
			self._pending.append((key, value))
			self._prune()
			writeHere = self._scheduleWrite()
		if writeHere:
			_unused = self._flush()

	def _prune(self) -> None:
		"""Evict least recently used entries until the cache is within its size limit.

		Nothing is written: an evicted entry stays in the file until the next compaction, where it
		costs a little disk, and comes back to be evicted again if the add-on stops before then.

		The caller must hold the lock.
		"""
		removedCount = 0
		while len(self._cache) > self.maxSize:
			_unused = self._cache.popitem(last=False)
			removedCount += 1
		if removedCount:
			log.debug("Translation cache pruned %d items.", removedCount)

	def getItemCount(self) -> int:
		"""Return the number of cached entries."""
		with self._lock:
			return len(self._cache)

	def clear(self) -> None:
		"""Remove all entries and write the empty cache out at once.

		Clearing is what a user reaches for to get rid of what has been kept, so it is not left to the
		background writer to do some seconds later, and the file is replaced rather than added to so
		that nothing cleared is still on the disk afterwards.
		"""
		with self._lock:
			self._cache = OrderedDict()
			self._pending = []
			self._needsCompaction = True
		_unused = self._flush()
		log.debug("Translation cache cleared.")

	def terminate(self) -> None:
		"""Stop the background writer and write whatever is still pending.

		Called when the add-on is unloaded, which includes NVDA shutting down, so the translations of
		the last few seconds are kept. Changes made after this are written as they are made, rather
		than starting a writer that a shutdown would not wait for.
		"""
		self._stopping.set()
		self._pendingSave.set()
		writer = self._writer
		if writer is not None and writer.is_alive():
			writer.join(timeout=_TERMINATE_TIMEOUT)
			if writer.is_alive():
				log.error("The translation cache writer did not stop in time.")
		if self._flush():
			# That write can have asked for a compaction, which there is no longer a writer to do.
			# The second call costs nothing when it did not.
			_unused = self._flush()
