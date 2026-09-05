# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the persistent translation cache.

The cache writes on a background thread, so the checks that care about writing either give it a
save interval long enough that it cannot fire on its own, or wait a generous multiple of a short one.
"""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)

from polyglot.common import cache as cacheModule  # noqa: E402
from polyglot.common.cache import TranslationCache  # noqa: E402

#: Long enough that the background writer cannot fire during a check that does not want it to.
NEVER = 3600.0


class CacheTestCase(unittest.TestCase):
	"""Give each check its own cache directory and a cache that is not shared with the last one."""

	def setUp(self) -> None:
		directory = tempfile.TemporaryDirectory()
		self.addCleanup(directory.cleanup)
		self.configPath = Path(directory.name)
		appArgs = getattr(sys.modules["globalVars"], "appArgs")
		patcher = patch.object(appArgs, "configPath", str(self.configPath))
		_unused = patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(self._forgetInstance)
		self._forgetInstance()

	def _forgetInstance(self) -> None:
		"""Drop the singleton, so the next cache built is a fresh one in the current directory."""
		instance = TranslationCache._instance
		if instance is not None and getattr(instance, "_isInitialized", False):
			instance.terminate()
		TranslationCache._instance = None

	def makeCache(self, maxSize: int = 10000, saveInterval: float = NEVER) -> TranslationCache:
		"""Return a new cache reading and writing in this check's own directory."""
		self._forgetInstance()
		return TranslationCache(maxSize=maxSize, saveInterval=saveInterval)

	@property
	def cachePath(self) -> Path:
		return self.configPath / cacheModule.CACHE_FILENAME

	@property
	def legacyPath(self) -> Path:
		return self.configPath / cacheModule.LEGACY_CACHE_FILENAME

	def readCacheRecords(self) -> list[Any]:
		"""Return the records on disk in the order they were written, superseded ones included."""
		text = self.cachePath.read_text(encoding="utf-8")
		return [json.loads(line) for line in text.splitlines() if line.strip()]

	def readCacheFile(self) -> dict[str, str]:
		"""Return the entries on disk, which are not necessarily what is in memory yet."""
		return dict(self.readCacheRecords())


class EvictionTest(CacheTestCase):
	"""Check that the cache drops what has gone unused rather than what was stored first."""

	def test_theLeastRecentlyUsedEntryIsEvicted(self) -> None:
		"""An entry still being read is kept even once it is the oldest one stored."""
		cache = self.makeCache(maxSize=3)
		for key in ("a", "b", "c"):
			cache.set(key, key.upper())
		# 'a' is the oldest, but reading it makes it the most recently used.
		self.assertEqual(cache.get("a"), "A")
		cache.set("d", "D")
		self.assertEqual(cache.get("a"), "A")
		self.assertIsNone(cache.get("b"), "the genuinely unused entry should have been evicted")
		self.assertEqual(cache.getItemCount(), 3)

	def test_rewritingAnEntryMakesItRecent(self) -> None:
		"""Storing over an existing entry counts as use, so it does not keep its old position."""
		cache = self.makeCache(maxSize=2)
		cache.set("a", "A")
		cache.set("b", "B")
		cache.set("a", "A2")
		cache.set("c", "C")
		self.assertEqual(cache.get("a"), "A2")
		self.assertIsNone(cache.get("b"))

	def test_theCacheNeverGrowsPastItsLimit(self) -> None:
		"""Eviction happens as entries are stored, so the count is right at once."""
		cache = self.makeCache(maxSize=5)
		for index in range(50):
			cache.set(f"key{index}", f"value{index}")
			self.assertLessEqual(cache.getItemCount(), 5)
		self.assertEqual(cache.getItemCount(), 5)

	def test_aMissingKeyIsNotAHit(self) -> None:
		"""Asking for something never stored returns nothing and stores nothing."""
		cache = self.makeCache()
		self.assertIsNone(cache.get("absent"))
		self.assertEqual(cache.getItemCount(), 0)


class BatchedWritingTest(CacheTestCase):
	"""Check that a run of translations does not write to the disk once per translation."""

	def test_storingDoesNotWriteStraightAway(self) -> None:
		"""Auto-translation stores constantly, so a store must not reach the disk on its own."""
		cache = self.makeCache()
		for index in range(20):
			cache.set(f"key{index}", f"value{index}")
		self.assertFalse(self.cachePath.exists(), "storing should not have written the cache yet")

	def test_terminateWritesWhatIsStillPending(self) -> None:
		"""NVDA shutting down must not throw away the last few seconds of translations."""
		cache = self.makeCache()
		cache.set("key", "value")
		cache.terminate()
		self.assertEqual(self.readCacheFile(), {"key": "value"})

	def test_aBurstCostsOneWrite(self) -> None:
		"""Changes made close together are gathered up and written once."""
		cache = self.makeCache(saveInterval=0.2)
		writes: list[str] = []
		realAppendFile = cache._appendFile

		def recordingAppendFile(contents: str) -> None:
			# Recorded once the write is finished, so a recorded write is one the file already holds.
			realAppendFile(contents)
			writes.append(contents)

		with patch.object(cache, "_appendFile", recordingAppendFile):
			for index in range(20):
				cache.set(f"key{index}", f"value{index}")
			deadline = time.monotonic() + 5.0
			while not writes and time.monotonic() < deadline:
				time.sleep(0.02)
			self.assertEqual(len(writes), 1, "the burst should have been written exactly once")
		self.assertEqual(len(self.readCacheFile()), 20)

	def test_aLateChangeIsWrittenEvenAfterTerminate(self) -> None:
		"""A task still finishing during shutdown has nowhere else to put its result."""
		cache = self.makeCache()
		cache.terminate()
		cache.set("late", "value")
		self.assertEqual(self.readCacheFile(), {"late": "value"})

	def test_terminateWithNothingPendingWritesNothing(self) -> None:
		"""A session that cached nothing should not leave a cache file behind."""
		cache = self.makeCache()
		cache.terminate()
		self.assertFalse(self.cachePath.exists())


class AppendOnlyWritingTest(CacheTestCase):
	"""Check that writing costs what changed rather than everything ever cached."""

	def test_aWriteOnlyAddsWhatChanged(self) -> None:
		"""The point of the log: a new translation must not rewrite the ones already written."""
		cache = self.makeCache()
		for index in range(5):
			cache.set(f"key{index}", f"value{index}")
		cache.terminate()
		later = self.makeCache()
		with patch.object(later, "_writeFile") as writeFile:
			later.set("late", "value")
			later.terminate()
		writeFile.assert_not_called()
		records = self.readCacheRecords()
		self.assertEqual(len(records), 6, "the entries already on disk should not have been written again")
		self.assertEqual(records[-1], ["late", "value"])

	def test_theLastRecordForAKeyIsTheOneThatCounts(self) -> None:
		"""Storing over an entry appends rather than going back to change what was written."""
		cache = self.makeCache()
		cache.set("key", "first")
		cache.set("key", "second")
		cache.terminate()
		self.assertEqual(self.readCacheRecords(), [["key", "first"], ["key", "second"]])
		self.assertEqual(self.makeCache().get("key"), "second")

	def test_aTranslationWithLineBreaksStaysOnOneLine(self) -> None:
		"""A record has to be one line, whatever was in the text that was translated.

		U+2028 and U+2029 are in here because JSON does not escape them and real text does contain
		them: a record holding one would otherwise look like two lines to much of what might read it.
		"""
		translation = "first line\nsecond line\r\n\u2028 and \u2029 third"
		cache = self.makeCache()
		cache.set("key", translation)
		cache.terminate()
		self.assertEqual(len(self.cachePath.read_text(encoding="utf-8").splitlines()), 1)
		self.assertEqual(self.makeCache().get("key"), translation)


class CompactionTest(CacheTestCase):
	"""Check that the file is rewritten once it is mostly records that have been superseded."""

	def test_aFileOfSupersededRecordsIsRewritten(self) -> None:
		"""Appending alone would grow the file without limit however few entries are really kept."""
		cache = self.makeCache(maxSize=3)
		with patch.object(cacheModule, "_COMPACTION_MINIMUM", 4):
			for index in range(10):
				cache.set("key", f"value{index}")
			cache.terminate()
		self.assertEqual(self.readCacheRecords(), [["key", "value9"]])

	def test_evictedEntriesGoWhenTheFileIsRewritten(self) -> None:
		"""An evicted entry stays on the disk until then, and must not still be there after."""
		cache = self.makeCache(maxSize=2)
		with patch.object(cacheModule, "_COMPACTION_MINIMUM", 3):
			for key in ("a", "b", "c", "d", "e", "f"):
				cache.set(key, key.upper())
			cache.terminate()
		self.assertEqual(self.readCacheFile(), {"e": "E", "f": "F"})

	def test_aFileThatIsMostlyLiveEntriesIsNotRewritten(self) -> None:
		"""Rewriting reclaims disk, so doing it when there is none to reclaim is pure cost."""
		cache = self.makeCache()
		for index in range(20):
			cache.set(f"key{index}", f"value{index}")
		with patch.object(cache, "_writeFile") as writeFile:
			cache.terminate()
		writeFile.assert_not_called()
		self.assertEqual(len(self.readCacheFile()), 20)

	def test_rewritingPutsReadRecencyOnTheDisk(self) -> None:
		"""Reads reorder only memory, so a rewrite is where that ordering reaches the disk."""
		cache = self.makeCache(maxSize=3)
		with patch.object(cacheModule, "_COMPACTION_MINIMUM", 3):
			for key in ("a", "b", "c"):
				cache.set(key, key.upper())
			for index in range(4):
				cache.set("filler", f"value{index}")
			# 'b' is the oldest of what is still cached, and reading it makes it the most recent.
			_unused = cache.get("b")
			cache.terminate()
		self.assertEqual([record[0] for record in self.readCacheRecords()], ["c", "filler", "b"])


class PersistenceTest(CacheTestCase):
	"""Check what survives a restart, and what a damaged file costs."""

	def test_entriesComeBackInTheOrderTheyWereWritten(self) -> None:
		"""The order written is the order eviction will use after a restart."""
		cache = self.makeCache()
		for key in ("a", "b", "c"):
			cache.set(key, key.upper())
		cache.terminate()
		reloaded = self.makeCache(maxSize=3)
		self.assertEqual(list(reloaded._cache), ["a", "b", "c"])
		reloaded.set("d", "D")
		self.assertIsNone(reloaded.get("a"), "the oldest entry from the previous session goes first")
		self.assertEqual(reloaded.get("b"), "B")

	def test_aFileOverTheLimitIsTrimmedAsItIsRead(self) -> None:
		"""The file holds what an earlier session kept, which need not be what this one will."""
		records = "".join(f'["key{index}", "value{index}"]\n' for index in range(10))
		self.cachePath.write_text(records, encoding="utf-8")
		cache = self.makeCache(maxSize=4)
		self.assertEqual(cache.getItemCount(), 4)
		self.assertEqual(cache.get("key9"), "value9", "the most recent entries are the ones kept")
		self.assertIsNone(cache.get("key0"))

	def test_anUnreadableCacheStartsEmpty(self) -> None:
		"""The cache is disposable, so damage to it costs misses rather than an error."""
		self.cachePath.write_text("{ this is not json", encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 0)

	def test_aRecordOfTheWrongShapeIsDropped(self) -> None:
		"""A line holding something other than a key and a translation is not usable."""
		self.cachePath.write_text('["not", "a", "pair"]\n{"key": "value"}\n', encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 0)

	def test_entriesThatAreNotTranslationsAreDropped(self) -> None:
		"""A hand-edited file must not put values into the cache that cannot be spoken."""
		self.cachePath.write_text(
			'["good", "value"]\n["bad", 42]\n["worse", null]\n[7, "key is not text"]\n',
			encoding="utf-8",
		)
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 1)
		self.assertEqual(cache.get("good"), "value")

	def test_aDamagedRecordDoesNotCostTheGoodOnes(self) -> None:
		"""One unreadable line is one cache miss, not a cache thrown away."""
		self.cachePath.write_text('["a", "A"]\nnot json at all\n["b", "B"]\n', encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 2)
		self.assertEqual(cache.get("b"), "B")

	def test_aDamagedFileIsRewrittenRatherThanAddedTo(self) -> None:
		"""A record cut short by a crash would swallow the next one appended after it."""
		self.cachePath.write_text('["good", "value"]\n["cut", "sh', encoding="utf-8")
		cache = self.makeCache()
		cache.set("new", "entry")
		cache.terminate()
		self.assertEqual(self.readCacheFile(), {"good": "value", "new": "entry"})

	def test_aFailedRewriteLeavesTheOldCacheIntact(self) -> None:
		"""A rewrite is put in place in one step, so an interrupted one cannot destroy the last."""
		cache = self.makeCache()
		cache.set("first", "value")
		cache.terminate()
		later = self.makeCache()
		later.set("second", "value")
		with later._lock:
			later._needsCompaction = True
		with patch.object(cacheModule.os, "replace", side_effect=OSError("disk full")):
			later.terminate()
		self.assertEqual(self.readCacheFile(), {"first": "value"})
		self.assertFalse(
			(self.configPath / (cacheModule.CACHE_FILENAME + ".tmp")).exists(),
			"a failed write should not leave its half-written file behind",
		)

	def test_aFailedAppendIsWrittenAgainFromMemory(self) -> None:
		"""An append that failed part-way cannot be retried: the file may hold half of it already."""
		cache = self.makeCache()
		cache.set("first", "value")
		with patch.object(cache, "_appendFile", side_effect=OSError("disk full")):
			self.assertFalse(cache._flush())
		cache.set("second", "value")
		with patch.object(cache, "_appendFile", side_effect=AssertionError("should have rewritten")):
			cache.terminate()
		self.assertEqual(self.readCacheFile(), {"first": "value", "second": "value"})


class LegacyMigrationTest(CacheTestCase):
	"""Check the take-over of a cache written by a version that kept it as one JSON document."""

	def test_aCacheFromThePreviousFormatIsTakenOver(self) -> None:
		"""An upgrade should not cost the user everything already translated."""
		self.legacyPath.write_text('{"a": "A", "b": "B"}', encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 2)
		self.assertEqual(cache.get("a"), "A")
		self.assertEqual(self.readCacheFile(), {"a": "A", "b": "B"})

	def test_thePreviousFileIsRemovedOnceItsEntriesAreSafe(self) -> None:
		"""It is a plaintext record of what NVDA has spoken, and nothing else would remove it."""
		self.legacyPath.write_text('{"a": "A"}', encoding="utf-8")
		_unused = self.makeCache()
		self.assertFalse(self.legacyPath.exists())

	def test_thePreviousFileIsKeptWhenItsEntriesCannotBeWritten(self) -> None:
		"""Removing it before its entries are safely elsewhere would throw them away."""
		self.legacyPath.write_text('{"a": "A"}', encoding="utf-8")
		with patch.object(cacheModule.os, "replace", side_effect=OSError("disk full")):
			cache = self.makeCache()
		self.assertEqual(cache.get("a"), "A")
		self.assertTrue(self.legacyPath.exists())

	def test_thePreviousFileGoesWhenTheNewOneIsAlreadyInUse(self) -> None:
		"""Once the cache is being kept in the new file, the old one is only left over."""
		self.legacyPath.write_text('{"old": "value"}', encoding="utf-8")
		self.cachePath.write_text('["new", "value"]\n', encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 1)
		self.assertEqual(cache.get("new"), "value")
		self.assertFalse(self.legacyPath.exists())

	def test_anUnreadablePreviousCacheCostsNothingButMisses(self) -> None:
		"""A damaged old file cannot be used, and leaving it about would help nobody."""
		self.legacyPath.write_text("{ this is not json", encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 0)
		self.assertFalse(self.legacyPath.exists())

	def test_aPreviousCacheOverTheLimitIsTrimmed(self) -> None:
		"""The old file was written under whatever limit that version had, not this one."""
		entries = {f"key{index}": f"value{index}" for index in range(10)}
		self.legacyPath.write_text(json.dumps(entries), encoding="utf-8")
		cache = self.makeCache(maxSize=4)
		self.assertEqual(cache.getItemCount(), 4)
		self.assertEqual(len(self.readCacheFile()), 4)
		self.assertEqual(cache.get("key9"), "value9", "the most recent entries are the ones kept")


class ClearTest(CacheTestCase):
	"""Check that clearing the cache actually gets rid of it."""

	def test_clearingWritesAtOnce(self) -> None:
		"""A user clearing the cache expects it gone now, not in ten seconds' time."""
		cache = self.makeCache()
		cache.set("key", "value")
		cache.terminate()
		later = self.makeCache()
		self.assertEqual(later.getItemCount(), 1)
		later.clear()
		self.assertEqual(self.readCacheRecords(), [])
		self.assertEqual(later.getItemCount(), 0)

	def test_clearingSurvivesARestart(self) -> None:
		"""What was cleared must not come back when NVDA next starts."""
		cache = self.makeCache()
		cache.set("key", "value")
		cache.clear()
		cache.terminate()
		self.assertEqual(self.makeCache().getItemCount(), 0)


class ThreadSafetyTest(CacheTestCase):
	"""Check that concurrent translation tasks cannot damage the cache or each other."""

	def test_concurrentStoresAllArrive(self) -> None:
		"""Several tasks finish at once, and every result must survive the writing going on."""
		cache = self.makeCache(saveInterval=0)
		threadCount, perThread = 8, 50
		barrier = threading.Barrier(threadCount)
		failures: list[BaseException] = []

		def store(threadIndex: int) -> None:
			try:
				_unused = barrier.wait()
				for index in range(perThread):
					key = f"t{threadIndex}k{index}"
					cache.set(key, f"value{index}")
					_unused = cache.get(key)
			except BaseException as error:  # noqa: BLE001 - reported rather than lost in a thread
				failures.append(error)

		threads = [threading.Thread(target=store, args=(index,)) for index in range(threadCount)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=30)
		self.assertEqual(failures, [])
		self.assertEqual(cache.getItemCount(), threadCount * perThread)
		cache.terminate()
		self.assertEqual(len(self.readCacheFile()), threadCount * perThread)

	def test_storingWhileShuttingDownIsSafe(self) -> None:
		"""A task finishing as NVDA exits writes for itself while the writer may still be writing."""
		cache = self.makeCache(saveInterval=0)
		stop = threading.Event()
		failures: list[BaseException] = []

		def storeUntilStopped() -> None:
			try:
				index = 0
				while not stop.is_set():
					cache.set(f"key{index}", f"value{index}")
					index += 1
			except BaseException as error:  # noqa: BLE001 - reported rather than lost in a thread
				failures.append(error)

		thread = threading.Thread(target=storeUntilStopped)
		thread.start()
		try:
			time.sleep(0.1)
			cache.terminate()
		finally:
			stop.set()
			thread.join(timeout=30)
		self.assertFalse(thread.is_alive(), "storing during shutdown should not have deadlocked")
		self.assertEqual(failures, [])
		self.assertIsInstance(self.readCacheFile(), dict)


class DeleteCacheFileTest(CacheTestCase):
	"""Check the removal the uninstall clean-up relies on."""

	def test_theCacheIsRemoved(self) -> None:
		cache = self.makeCache()
		cache.set("key", "value")
		cache.terminate()
		self.assertTrue(cacheModule.deleteCacheFile())
		self.assertFalse(self.cachePath.exists())

	def test_aHalfWrittenCacheIsRemovedToo(self) -> None:
		"""An interrupted write can leave a temporary file, which holds translations just the same."""
		temporaryPath = self.configPath / (cacheModule.CACHE_FILENAME + ".tmp")
		temporaryPath.write_text('["key", "value"]\n', encoding="utf-8")
		self.assertTrue(cacheModule.deleteCacheFile())
		self.assertFalse(temporaryPath.exists())

	def test_theFileFromThePreviousFormatIsRemovedToo(self) -> None:
		"""A cache left by an older version holds the same kind of content and goes the same way."""
		self.legacyPath.write_text('{"key": "value"}', encoding="utf-8")
		self.assertTrue(cacheModule.deleteCacheFile())
		self.assertFalse(self.legacyPath.exists())

	def test_removingWhatIsNotThereIsNotAFailure(self) -> None:
		"""A user who never translated anything has no cache, which is not a problem."""
		self.assertFalse(cacheModule.deleteCacheFile())


if __name__ == "__main__":
	unittest.main()
