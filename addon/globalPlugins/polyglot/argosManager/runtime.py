# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""The native libraries Argos Translate models are run with.

Argos models are CTranslate2 models, tokenized with SentencePiece in most packages and with
Moses rules and BPE merges in the rest. The libraries behind them are compiled extensions,
published only for 64-bit Windows, so they can be loaded into NVDA itself from NVDA 2026.1 onwards
and not before. They are far too large to ship inside an add-on, so Polyglot downloads them from
PyPI the first time they are needed, checking each download against a hash pinned in
``resources/runtime.json`` rather than trusting whatever the network returns.

The runtime comes in two parts. The core, CTranslate2 and SentencePiece, is what every package
needs. The BPE extras, ``sacremoses`` and ``subword-nmt`` with the libraries they import, are
another 1.5 MB fetched only once a package that carries a ``bpe.model`` is installed.

Nothing here imports the libraries at module level: importing them locks their DLLs for as long as
NVDA runs, which would stop the model manager from ever removing or updating them.
"""

from __future__ import annotations

import json
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import addonHandler
from logHandler import log

from ..common.secureScreen import SecureScreenError, isSecureScreen
from ..modelManager.installer import (
	InstallProgress,
	ProgressCallback,
	computeSha256Hex,
	deleteDirectoryIfExists,
	deleteFileIfExists,
	downloadFile,
	readJsonObject,
	removeEmptyDirectory,
	writeJsonObject,
)
from .catalog import getString

addonHandler.initTranslation()

#: The NVDA release that first ran 64-bit Python, and so the first that can load these libraries.
FIRST_SUPPORTED_NVDA_VERSION = "2026.1"

#: Modules the runtime provides, in the order they are imported.
_RUNTIME_MODULES = ("ctranslate2", "sentencepiece")


@dataclass(frozen=True)
class RuntimeComponent:
	"""One wheel making up the Argos runtime."""

	name: str = ""
	version: str = ""
	fileName: str = ""
	url: str = ""
	sha256: str = ""
	size: int = 0

	@classmethod
	def fromJson(cls, data: Any) -> "RuntimeComponent | None":
		"""Create a component from catalog JSON, or None when the entry is unusable."""
		if not isinstance(data, dict):
			return None
		try:
			size = int(data.get("size", 0))
		except (TypeError, ValueError):
			size = 0
		component = cls(
			name=getString(data, "name"),
			version=getString(data, "version"),
			fileName=getString(data, "fileName"),
			url=getString(data, "url"),
			sha256=getString(data, "sha256").lower(),
			size=size,
		)
		if not component.name or not component.url or not component.fileName:
			return None
		return component


@dataclass(frozen=True)
class RuntimeCatalog:
	"""The pinned runtime downloads, grouped by the Python build they are built for."""

	generatedAt: str = ""
	byPythonTag: dict[str, tuple[RuntimeComponent, ...]] = field(default_factory=dict)
	bpeByPythonTag: dict[str, tuple[RuntimeComponent, ...]] = field(default_factory=dict)

	@classmethod
	def loadBundled(cls) -> "RuntimeCatalog":
		"""Load the runtime catalog that ships with the add-on."""
		path = Path(__file__).with_name("resources") / "runtime.json"
		if not path.is_file():
			raise RuntimeError(_("The bundled Argos runtime catalog is missing."))
		rawData = json.loads(path.read_text(encoding="utf-8-sig"))
		if not isinstance(rawData, dict):
			raise RuntimeError(_("The Argos runtime catalog is invalid."))
		byPythonTag: dict[str, tuple[RuntimeComponent, ...]] = {}
		bpeByPythonTag: dict[str, tuple[RuntimeComponent, ...]] = {}
		rawRuntimes = rawData.get("runtimes")
		for entry in rawRuntimes if isinstance(rawRuntimes, list) else []:
			if not isinstance(entry, dict):
				continue
			pythonTag = getString(entry, "pythonTag")
			components = _readComponents(entry.get("components"))
			if not pythonTag or not components:
				continue
			byPythonTag[pythonTag] = components
			bpeByPythonTag[pythonTag] = _readComponents(entry.get("bpeComponents"))
		return cls(
			generatedAt=getString(rawData, "generatedAt"),
			byPythonTag=byPythonTag,
			bpeByPythonTag=bpeByPythonTag,
		)

	def getComponents(self, pythonTag: str) -> tuple[RuntimeComponent, ...]:
		"""Return the components for one Python build, or an empty tuple when it is not covered."""
		return self.byPythonTag.get(pythonTag, ())

	def getBpeComponents(self, pythonTag: str) -> tuple[RuntimeComponent, ...]:
		"""Return the BPE extras for one Python build, or an empty tuple when it is not covered."""
		return self.bpeByPythonTag.get(pythonTag, ())


def _readComponents(rawComponents: Any) -> tuple[RuntimeComponent, ...]:
	"""Read one list of catalog entries, dropping any that is unusable."""
	return tuple(
		component
		for component in (
			RuntimeComponent.fromJson(item)
			for item in (rawComponents if isinstance(rawComponents, list) else [])
		)
		if component is not None
	)


def getPythonTag() -> str:
	"""Return the tag of the Python build NVDA is running, as wheels name it."""
	return f"cp{sys.version_info.major}{sys.version_info.minor}"


def isSixtyFourBit() -> bool:
	"""Return whether NVDA is running as a 64-bit program."""
	return struct.calcsize("P") == 8


class ArgosRuntime:
	"""Installs, removes, and loads the libraries Argos models need."""

	def __init__(self, argosRoot: Path, tempDownloadDir: Path) -> None:
		"""Initialize the runtime over the Argos data directory and its download cache."""
		self.argosRoot = argosRoot
		self.tempDownloadDir = tempDownloadDir
		self._catalog: RuntimeCatalog | None = None

	@property
	def catalog(self) -> RuntimeCatalog:
		"""Return the pinned runtime catalog, reading it once."""
		if self._catalog is None:
			self._catalog = RuntimeCatalog.loadBundled()
		return self._catalog

	@property
	def libDir(self) -> Path:
		"""Return the directory the runtime is installed into.

		Each Python build gets its own directory, so an NVDA upgrade to a new Python version installs
		its own runtime next to the old one instead of loading libraries built for the wrong one.
		"""
		return self.argosRoot / "lib" / getPythonTag()

	@property
	def markerPath(self) -> Path:
		"""Return the file recording which components are installed."""
		return self.libDir / "polyglotRuntime.json"

	@property
	def components(self) -> tuple[RuntimeComponent, ...]:
		"""Return the components needed for the Python build NVDA is running."""
		return self.catalog.getComponents(getPythonTag())

	@property
	def bpeComponents(self) -> tuple[RuntimeComponent, ...]:
		"""Return the extras BPE-tokenized packages need, for the Python build NVDA is running."""
		return self.catalog.getBpeComponents(getPythonTag())

	@property
	def isHostSupported(self) -> bool:
		"""Return whether this NVDA can load the Argos runtime at all."""
		return sys.platform == "win32" and isSixtyFourBit() and bool(self.components)

	@property
	def unsupportedHostMessage(self) -> str:
		"""Return why this NVDA cannot run Argos Translate."""
		if sys.platform != "win32" or not isSixtyFourBit():
			return _(
				"Argos Translate needs the 64-bit build of NVDA, which is NVDA {version} or later. "
				"Use one of Polyglot's other engines on this version of NVDA.",
			).format(version=FIRST_SUPPORTED_NVDA_VERSION)
		return _(
			"Polyglot does not have Argos Translate libraries for the Python version this NVDA uses "
			"({pythonTag}). Check for a Polyglot update.",
		).format(pythonTag=getPythonTag())

	@property
	def downloadSize(self) -> int:
		"""Return the total download size of the runtime in bytes."""
		return sum(component.size for component in self.components)

	@property
	def isLoaded(self) -> bool:
		"""Return whether the runtime libraries are already imported into NVDA."""
		return all(moduleName in sys.modules for moduleName in _RUNTIME_MODULES)

	def isInstalled(self) -> bool:
		"""Return whether every component is installed at the pinned version."""
		if not self.components:
			return False
		installed = self.getInstalledVersions()
		return all(installed.get(component.name) == component.version for component in self.components)

	def isBpeInstalled(self) -> bool:
		"""Return whether the BPE extras are installed at the pinned version."""
		if not self.bpeComponents:
			return False
		installed = self.getInstalledVersions()
		return all(installed.get(component.name) == component.version for component in self.bpeComponents)

	def isAnythingInstalled(self) -> bool:
		"""Return whether any runtime files are present, including an outdated runtime."""
		return self.libDir.is_dir() and any(self.libDir.iterdir())

	def getInstalledVersions(self) -> dict[str, str]:
		"""Return the installed component versions, read from the install marker."""
		marker = readJsonObject(self.markerPath)
		rawComponents = marker.get("components")
		if not isinstance(rawComponents, dict):
			return {}
		return {
			str(name): str(version) for name, version in rawComponents.items() if isinstance(version, str)
		}

	def install(self, progress: ProgressCallback, withBpeSupport: bool = False) -> None:
		"""Download and install every component that is not present at the pinned version.

		:param withBpeSupport: Also install the extras a BPE-tokenized package needs.
		:raises RuntimeError: If the runtime cannot run on this NVDA.
		:raises SecureScreenError: If NVDA is on a secure screen, where nothing may be downloaded.
		"""
		if isSecureScreen():
			raise SecureScreenError()
		if not self.isHostSupported:
			raise RuntimeError(self.unsupportedHostMessage)
		needed = self.components + (self.bpeComponents if withBpeSupport else ())
		isReplacingEverything, missing = self._planInstall(withBpeSupport)
		if not missing:
			progress(InstallProgress(_("The Argos runtime is already installed."), 100))
			return
		if self.isLoaded:
			raise RuntimeError(
				_(
					"The Argos runtime that is already loaded cannot be replaced while NVDA is running. "
					"Restart NVDA and try again.",
				),
			)
		if isReplacingEverything:
			_unused = deleteDirectoryIfExists(self.libDir)
		self.libDir.mkdir(parents=True, exist_ok=True)
		try:
			for component in missing:
				self._installComponent(component, progress)
		except Exception:
			# A runtime that was already working is left alone: the marker still describes it, and
			# the half-extracted extras are written over by the next attempt.
			if isReplacingEverything:
				self.tryCleanup()
			raise
		self._writeMarker(needed)
		progress(InstallProgress(_("The Argos runtime is ready."), 100))

	def _planInstall(self, withBpeSupport: bool) -> tuple[bool, list[RuntimeComponent]]:
		"""Work out what an install would do, without doing any of it.

		Every component shares one directory, so the files an outdated one left behind cannot be told
		apart from the new one's: a component at the wrong version replaces the whole runtime. Extras
		added to a runtime that is already at the pinned version only need extracting next to it,
		which is what saves re-downloading CTranslate2 to install a BPE-tokenized package.

		:return: Whether the whole runtime is being replaced, and the components to download.
		"""
		needed = self.components + (self.bpeComponents if withBpeSupport else ())
		installedVersions = self.getInstalledVersions()
		isOutdated = any(
			component.name in installedVersions and installedVersions[component.name] != component.version
			for component in needed
		)
		if isOutdated or not self.isInstalled():
			return True, list(needed)
		return False, [component for component in needed if component.name not in installedVersions]

	def getMissingDownloadSize(self, withBpeSupport: bool = False) -> int:
		"""Return the bytes an install would download, leaving out what is already in place."""
		_unused, components = self._planInstall(withBpeSupport)
		return sum(component.size for component in components)

	def _writeMarker(self, components: tuple[RuntimeComponent, ...]) -> None:
		"""Record the components just installed, keeping what the marker already names."""
		versions = self.getInstalledVersions()
		versions.update({component.name: component.version for component in components})
		writeJsonObject(self.markerPath, {"pythonTag": getPythonTag(), "components": versions})

	def _installComponent(self, component: RuntimeComponent, progress: ProgressCallback) -> None:
		"""Download, verify, and extract one component."""
		archivePath = self.tempDownloadDir / component.fileName
		try:
			if not (archivePath.is_file() and self._verify(archivePath, component)):
				_unused = deleteFileIfExists(archivePath)
				progress(
					InstallProgress(
						_("Downloading {fileName}.").format(fileName=component.fileName),
						0,
					),
				)
				downloadFile(component.url, archivePath, component.size, progress)
				if not self._verify(archivePath, component):
					_unused = deleteFileIfExists(archivePath)
					raise RuntimeError(
						_("The download of {fileName} could not be verified.").format(
							fileName=component.fileName,
						),
					)
			progress(InstallProgress(_("Installing {fileName}.").format(fileName=component.fileName)))
			extractWheel(archivePath, self.libDir, progress)
		finally:
			_unused = deleteFileIfExists(archivePath)
			_unused = deleteFileIfExists(Path(str(archivePath) + ".download"))
			removeEmptyDirectory(self.tempDownloadDir)

	def _verify(self, path: Path, component: RuntimeComponent) -> bool:
		"""Return whether a downloaded component matches its pinned size and hash."""
		if component.size > 0 and path.stat().st_size != component.size:
			return False
		if not component.sha256:
			return False
		return computeSha256Hex(path) == component.sha256

	def remove(self, progress: ProgressCallback) -> int:
		"""Remove the installed runtime, returning the bytes freed.

		:raises RuntimeError: If the runtime is loaded, and so cannot be removed until NVDA restarts.
		"""
		if not self.isAnythingInstalled():
			return 0
		if self.isLoaded:
			raise RuntimeError(
				_(
					"The Argos runtime is in use and cannot be removed while NVDA is running. "
					"Restart NVDA and try again.",
				),
			)
		removedBytes = deleteDirectoryIfExists(self.libDir)
		removeEmptyDirectory(self.libDir.parent)
		if removedBytes > 0:
			progress(
				InstallProgress(
					_("Removed the Argos runtime ({size:.1f} MiB).").format(
						size=removedBytes / 1024 / 1024,
					),
					100,
				),
			)
		return removedBytes

	def tryCleanup(self) -> None:
		"""Best-effort cleanup after a failed runtime install."""
		try:
			_unused = deleteDirectoryIfExists(self.libDir)
		except Exception:
			log.debug("Argos: could not clean up an incomplete runtime install.", exc_info=True)

	def load(self) -> tuple[Any, Any]:
		"""Import the runtime libraries, adding them to NVDA's import path first.

		:return: The ``ctranslate2`` and ``sentencepiece`` modules.
		:raises RuntimeError: If the runtime cannot run here or is not installed.
		"""
		if not self.isHostSupported:
			raise RuntimeError(self.unsupportedHostMessage)
		if not self.isInstalled():
			raise RuntimeError(_("The Argos runtime is not installed."))
		self._addToImportPath()
		try:
			import ctranslate2
			import sentencepiece
		except ImportError as error:
			raise RuntimeError(
				_("The Argos runtime could not be loaded: {error}").format(error=error),
			) from error
		return ctranslate2, sentencepiece

	def loadBpe(self) -> tuple[Any, Any, Any, Any]:
		"""Import the Moses and BPE libraries a BPE-tokenized package is tokenized with.

		:return: The ``MosesPunctNormalizer``, ``MosesTokenizer``, and ``MosesDetokenizer`` classes,
			and the ``BPE`` class that applies a package's merges.
		:raises RuntimeError: If the extras are not installed.
		"""
		if not self.isBpeInstalled():
			raise RuntimeError(
				_(
					"The tokenizer this Argos model needs is not installed. Open the Argos model "
					"manager and install the model again.",
				),
			)
		self._addToImportPath()
		try:
			from sacremoses.normalize import MosesPunctNormalizer
			from sacremoses.tokenize import MosesDetokenizer, MosesTokenizer
			from subword_nmt.apply_bpe import BPE
		except ImportError as error:
			raise RuntimeError(
				_("The Argos runtime could not be loaded: {error}").format(error=error),
			) from error
		return MosesPunctNormalizer, MosesTokenizer, MosesDetokenizer, BPE

	def _addToImportPath(self) -> None:
		"""Put the installed runtime where NVDA's own import machinery will find it."""
		libPath = str(self.libDir)
		if libPath not in sys.path:
			# Appended, so nothing here can shadow a module NVDA or another add-on provides.
			sys.path.append(libPath)


def extractWheel(wheelPath: Path, destination: Path, progress: ProgressCallback) -> None:
	"""Extract a wheel into a directory, rejecting any entry that points outside it."""
	destinationRoot = destination.resolve()
	with zipfile.ZipFile(wheelPath, "r") as archive:
		entries = [entry for entry in archive.infolist() if not entry.is_dir()]
		total = len(entries)
		for index, entry in enumerate(entries, start=1):
			targetPath = (destinationRoot / entry.filename).resolve()
			if destinationRoot not in targetPath.parents:
				raise RuntimeError(
					_("An entry in {fileName} points outside the install directory.").format(
						fileName=wheelPath.name,
					),
				)
			targetPath.parent.mkdir(parents=True, exist_ok=True)
			with archive.open(entry, "r") as source, targetPath.open("wb") as target:
				_unused = _copyStream(source, target)
			progress(
				InstallProgress(
					_("Installing {fileName}.").format(fileName=wheelPath.name),
					int(index * 100 / total) if total else 100,
				),
			)


def _copyStream(source: Any, target: Any) -> int:
	"""Copy one archive entry, a megabyte at a time."""
	written = 0
	while chunk := source.read(1024 * 1024):
		written += target.write(chunk)
	return written
