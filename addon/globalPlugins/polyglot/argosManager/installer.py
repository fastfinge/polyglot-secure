# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Install, update, and remove Argos Translate model packages.

An Argos package is a zip archive holding one language direction: a CTranslate2 model, the
tokenizer it was trained with, and a ``metadata.json`` naming the direction and version. Most
packages carry a SentencePiece model; the ones built from OPUS-MT carry BPE merges instead, and
those need the extras in :meth:`ArgosRuntime.install` on top of the runtime every package needs.
Packages are installed under the user's local application data, next to the runtime, so they survive
add-on updates and are never written into the add-on's own folder.
"""

from __future__ import annotations

import json
import shutil
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import addonHandler
import requests
from logHandler import log

from ..common.secureScreen import SecureScreenError, isSecureScreen
from ..modelManager.installer import (
	InstallProgress,
	ProgressCallback,
	deleteDirectoryIfExists,
	deleteFileIfExists,
	downloadFile,
	getDirectorySize,
	getLocalAppData,
	hasAnyFileSystemEntry,
	readJsonObject,
	removeEmptyDirectory,
	writeJsonObject,
)
from .catalog import ArgosCatalog, ArgosPackage, compareVersions, languageName, pairDisplayName
from .runtime import ArgosRuntime

addonHandler.initTranslation()

#: Held for the length of any operation that writes to the Argos directory.
ARGOS_OPERATION_LOCK = threading.Lock()

#: How long to wait when asking a download server only for a package's size.
_SIZE_REQUEST_TIMEOUT = 20

#: The tokenizer a package carries, in the order Argos Translate itself looks for them.
SENTENCEPIECE_TOKENIZER = "sentencepiece.model"
BPE_TOKENIZER = "bpe.model"
TOKENIZER_FILE_NAMES = (SENTENCEPIECE_TOKENIZER, BPE_TOKENIZER)


@dataclass(frozen=True)
class InstalledPackage:
	"""One Argos package that is installed on disk."""

	path: Path
	key: str
	fromCode: str
	toCode: str
	packageVersion: str
	tokenizerFileName: str = SENTENCEPIECE_TOKENIZER

	@property
	def displayName(self) -> str:
		"""Return the installed package's language pair, in Polyglot's own language names."""
		return _("{source} to {target}").format(
			source=languageName(self.fromCode),
			target=languageName(self.toCode),
		)

	@property
	def usesBpe(self) -> bool:
		"""Return whether this package is tokenized with BPE merges rather than SentencePiece."""
		return self.tokenizerFileName == BPE_TOKENIZER

	@property
	def tokenizerPath(self) -> Path:
		"""Return the tokenizer file this package is tokenized with."""
		return self.path / self.tokenizerFileName


class ArgosInstaller:
	"""Manages the Argos runtime and model packages under the user's local application data."""

	def __init__(self, polyglotRoot: Path | None = None, tempDownloadDir: Path | None = None) -> None:
		"""Initialize storage locations, defaulting to the ones Polyglot uses for Argos."""
		self.polyglotRoot = polyglotRoot or getLocalAppData() / "Polyglot"
		self.tempDownloadDir = tempDownloadDir or self.argosRoot / "downloads"
		self.runtime = ArgosRuntime(self.argosRoot, self.tempDownloadDir)

	@property
	def argosRoot(self) -> Path:
		"""Return the directory holding everything Argos Translate needs."""
		return self.polyglotRoot / "Argos"

	@property
	def packagesDir(self) -> Path:
		"""Return the directory installed model packages live in."""
		return self.argosRoot / "packages"

	@property
	def indexCachePath(self) -> Path:
		"""Return the file the last downloaded package index is saved to."""
		return self.argosRoot / "index.json"

	@property
	def sizeCachePath(self) -> Path:
		"""Return the file package download sizes are remembered in."""
		return self.argosRoot / "sizes.json"

	# --- Installed packages ---

	def getInstalledPackages(self) -> list[InstalledPackage]:
		"""Return every usable package installed on disk."""
		installed: list[InstalledPackage] = []
		if not self.packagesDir.is_dir():
			return installed
		for child in sorted(self.packagesDir.iterdir()):
			package = self.readInstalledPackage(child)
			if package is not None:
				installed.append(package)
		return installed

	def readInstalledPackage(self, path: Path) -> InstalledPackage | None:
		"""Read one installed package directory, or return None when it is not usable."""
		metadataPath = path / "metadata.json"
		if not path.is_dir() or not metadataPath.is_file():
			return None
		tokenizerFileName = next(
			(name for name in TOKENIZER_FILE_NAMES if (path / name).is_file()),
			"",
		)
		if not tokenizerFileName or not (path / "model").is_dir():
			return None
		try:
			metadata = json.loads(metadataPath.read_text(encoding="utf-8-sig"))
		except (OSError, ValueError, UnicodeError):
			log.debug("Argos: ignoring an unreadable package at %s.", path)
			return None
		if not isinstance(metadata, dict):
			return None
		fromCode = str(metadata.get("from_code") or "")
		toCode = str(metadata.get("to_code") or "")
		if not fromCode or not toCode:
			return None
		return InstalledPackage(
			path=path,
			key=f"translate-{fromCode}_{toCode}",
			fromCode=fromCode,
			toCode=toCode,
			packageVersion=str(metadata.get("package_version") or ""),
			tokenizerFileName=tokenizerFileName,
		)

	def getInstalledByKey(self) -> dict[str, InstalledPackage]:
		"""Return installed packages by their language-direction key."""
		return {package.key: package for package in self.getInstalledPackages()}

	def isPackageInstalled(self, package: ArgosPackage) -> bool:
		"""Return whether a package from the index is installed, at any version."""
		return package.key in self.getInstalledByKey()

	def needsBpeSupport(self) -> bool:
		"""Return whether any installed package is tokenized with BPE merges."""
		return any(package.usesBpe for package in self.getInstalledPackages())

	def isPackageOutdated(self, package: ArgosPackage, installed: InstalledPackage | None) -> bool:
		"""Return whether an installed package is older than the one the index offers."""
		if installed is None:
			return False
		return compareVersions(package.packageVersion, installed.packageVersion) > 0

	def getOutdatedKeys(self, catalog: ArgosCatalog) -> set[str]:
		"""Return the keys of installed packages the index offers a newer version of."""
		installedByKey = self.getInstalledByKey()
		return {
			package.key
			for package in catalog.packages
			if self.isPackageOutdated(package, installedByKey.get(package.key))
		}

	# --- Install and removal ---

	def applySelection(
		self,
		catalog: ArgosCatalog,
		selectedKeys: set[str],
		progress: ProgressCallback,
		keysToUpdate: set[str] | None = None,
	) -> None:
		"""Install the selected packages, remove the ones no longer selected, and update as asked.

		:param selectedKeys: Keys of every package that should end up installed.
		:param keysToUpdate: Keys of installed packages to reinstall at the index's newer version.
		"""
		self.packagesDir.mkdir(parents=True, exist_ok=True)
		keysToUpdate = keysToUpdate or set()
		installedByKey = self.getInstalledByKey()
		keysToInstall = [key for key in sorted(selectedKeys) if key not in installedByKey]
		keysToReinstall = [key for key in sorted(keysToUpdate) if key in installedByKey]
		keysToRemove = [key for key in sorted(installedByKey) if key not in selectedKeys]
		if keysToInstall or keysToReinstall:
			self.runtime.install(progress, withBpeSupport=self.needsBpeSupport())
		for key in keysToInstall + keysToReinstall:
			package = catalog.byKey.get(key)
			if package is None:
				raise RuntimeError(_("The Argos package index no longer offers {key}.").format(key=key))
			self.installPackage(package, progress)
		for key in keysToRemove:
			self.removeInstalledPackage(installedByKey[key], progress)
		if not selectedKeys:
			self.tryRemoveUnusedRuntime(progress)
		if self.hasDownloadCacheFiles():
			_unused = self.clearDownloadCache(progress)
		removeEmptyDirectory(self.packagesDir)

	def ensurePackagesInstalled(
		self,
		packages: list[ArgosPackage],
		progress: ProgressCallback,
	) -> None:
		"""Install the runtime and the given packages, leaving everything else alone.

		:raises SecureScreenError: If NVDA is on a secure screen, where models must not be downloaded.
		"""
		if isSecureScreen():
			raise SecureScreenError()
		self.packagesDir.mkdir(parents=True, exist_ok=True)
		self.runtime.install(progress, withBpeSupport=self.needsBpeSupport())
		installedByKey = self.getInstalledByKey()
		for package in packages:
			if package.key in installedByKey:
				continue
			self.installPackage(package, progress)
		if self.hasDownloadCacheFiles():
			_unused = self.clearDownloadCache(progress)

	def installPackage(self, package: ArgosPackage, progress: ProgressCallback) -> None:
		"""Download and install one package, replacing any version of it already installed."""
		fileName = f"{package.directoryName}.argosmodel"
		archivePath = self.tempDownloadDir / fileName
		expectedSize = self.getCachedSize(package)
		try:
			progress(
				InstallProgress(
					_("Downloading {package}.").format(package=pairDisplayName(package)),
					0,
				),
			)
			downloadFile(package.downloadUrl, archivePath, expectedSize, progress)
			self.rememberSize(package, archivePath.stat().st_size)
			existing = self.getInstalledByKey().get(package.key)
			if existing is not None:
				_unused = deleteDirectoryIfExists(existing.path)
			installed = self.extractPackage(archivePath, package, progress)
			# The index does not say which tokenizer a package carries, so the extras a BPE package
			# needs can only be fetched once its archive has been opened.
			if installed.usesBpe:
				self.runtime.install(progress, withBpeSupport=True)
		except Exception:
			self.tryCleanupPackage(package)
			raise
		finally:
			_unused = deleteFileIfExists(archivePath)
			_unused = deleteFileIfExists(Path(str(archivePath) + ".download"))
			removeEmptyDirectory(self.tempDownloadDir)
		progress(
			InstallProgress(
				_("Installed {package}.").format(package=pairDisplayName(package)),
				100,
			),
		)

	def extractPackage(
		self,
		archivePath: Path,
		package: ArgosPackage,
		progress: ProgressCallback,
	) -> InstalledPackage:
		"""Extract a package archive into the packages directory, rejecting unsafe entries.

		:return: The package as it now sits on disk.
		:raises RuntimeError: If the archive points outside the packages directory, or holds no
			package Polyglot can use.
		"""
		packagesRoot = self.packagesDir.resolve()
		with zipfile.ZipFile(archivePath, "r") as archive:
			entries = [entry for entry in archive.infolist() if not entry.is_dir()]
			total = len(entries)
			installedPath: Path | None = None
			for index, entry in enumerate(entries, start=1):
				targetPath = (packagesRoot / entry.filename).resolve()
				if packagesRoot not in targetPath.parents:
					raise RuntimeError(
						_("An entry in {package} points outside the packages directory.").format(
							package=pairDisplayName(package),
						),
					)
				if targetPath.name == "metadata.json" and targetPath.parent.parent == packagesRoot:
					installedPath = targetPath.parent
				targetPath.parent.mkdir(parents=True, exist_ok=True)
				with archive.open(entry, "r") as source, targetPath.open("wb") as target:
					shutil.copyfileobj(source, target, 1024 * 1024)
				progress(
					InstallProgress(
						_("Installing {package}.").format(package=pairDisplayName(package)),
						int(index * 100 / total) if total else 100,
					),
				)
		installed = self.readInstalledPackage(installedPath) if installedPath is not None else None
		if installed is None:
			raise RuntimeError(
				_("{package} does not hold a model Polyglot can use.").format(
					package=pairDisplayName(package),
				),
			)
		return installed

	def removeInstalledPackage(self, installed: InstalledPackage, progress: ProgressCallback) -> None:
		"""Remove one installed package from disk."""
		removedBytes = deleteDirectoryIfExists(installed.path)
		if removedBytes > 0:
			progress(
				InstallProgress(
					_("Removed {package} ({size:.1f} MiB).").format(
						package=installed.displayName,
						size=removedBytes / 1024 / 1024,
					),
					100,
				),
			)

	def tryRemoveUnusedRuntime(self, progress: ProgressCallback) -> None:
		"""Remove the runtime once the last package is gone, unless it is loaded into NVDA.

		Once a model has been translated with, the runtime's libraries stay locked until NVDA
		restarts. That is not worth failing an otherwise successful removal over, so the runtime is
		simply left in place and removed the next time the model manager runs.
		"""
		if self.getInstalledPackages():
			return
		try:
			_unused = self.runtime.remove(progress)
		except (RuntimeError, OSError) as error:
			log.debug("Argos: the runtime was left in place (%s).", error)

	def tryCleanupPackage(self, package: ArgosPackage) -> None:
		"""Best-effort cleanup of a half-installed package."""
		try:
			installed = self.getInstalledByKey().get(package.key)
			if installed is not None and self.readInstalledPackage(installed.path) is None:
				_unused = deleteDirectoryIfExists(installed.path)
			_unused = deleteDirectoryIfExists(self.packagesDir / package.directoryName)
		except Exception:
			log.debug("Argos: could not clean up a failed package install.", exc_info=True)

	def removeEverything(self, progress: ProgressCallback) -> int:
		"""Remove every installed package and the runtime, returning the bytes freed.

		:raises RuntimeError: If the runtime is loaded and so cannot be removed yet.
		"""
		removedBytes = deleteDirectoryIfExists(self.packagesDir)
		removedBytes += self.runtime.remove(progress)
		removedBytes += self.clearDownloadCache(progress)
		return removedBytes

	# --- Download cache ---

	def hasDownloadCacheFiles(self) -> bool:
		"""Return whether the download cache holds anything."""
		return hasAnyFileSystemEntry(self.tempDownloadDir)

	def getDownloadCacheSize(self) -> int:
		"""Return the bytes used by the download cache."""
		return getDirectorySize(self.tempDownloadDir)

	def clearDownloadCache(self, progress: ProgressCallback | None = None) -> int:
		"""Delete anything left in the download cache, returning the bytes freed."""
		clearedBytes = deleteDirectoryIfExists(self.tempDownloadDir)
		if clearedBytes > 0 and progress is not None:
			progress(
				InstallProgress(
					_("Cleared unfinished downloads ({size:.1f} MiB).").format(
						size=clearedBytes / 1024 / 1024,
					),
					100,
				),
			)
		return clearedBytes

	def getInstalledSize(self) -> int:
		"""Return the bytes used by installed packages and the runtime."""
		return getDirectorySize(self.packagesDir) + getDirectorySize(self.runtime.libDir)

	# --- Package sizes ---

	def getSizeCache(self) -> dict[str, int]:
		"""Return the remembered download size of each package URL."""
		sizes: dict[str, int] = {}
		for url, size in readJsonObject(self.sizeCachePath).items():
			try:
				sizes[str(url)] = int(size)
			except (TypeError, ValueError):
				continue
		return sizes

	def getCachedSize(self, package: ArgosPackage) -> int:
		"""Return a package's remembered download size, or zero when it is not known yet."""
		return self.getSizeCache().get(package.downloadUrl, 0)

	def rememberSize(self, package: ArgosPackage, size: int) -> None:
		"""Remember a package's download size, so it can be shown before downloading it again."""
		if size <= 0:
			return
		sizes = self.getSizeCache()
		if sizes.get(package.downloadUrl) == size:
			return
		sizes[package.downloadUrl] = size
		try:
			writeJsonObject(self.sizeCachePath, dict(sizes))
		except OSError:
			log.debug("Argos: could not save the package size cache.", exc_info=True)

	def fetchSizes(
		self,
		packages: list[ArgosPackage],
		onSize: Callable[[ArgosPackage, int], None] | None = None,
		shouldStop: Callable[[], bool] | None = None,
	) -> None:
		"""Ask each download server for the size of packages whose size is not known yet.

		The index does not carry package sizes, so they are collected once and remembered. Failures
		are ignored: a size that cannot be read is only a missing column in the model manager.

		:param onSize: Called with a package and its size as each one is learned.
		:param shouldStop: Called before each request; a true result abandons the rest.
		"""
		sizes = self.getSizeCache()
		unknown = [package for package in packages if package.downloadUrl not in sizes]
		if not unknown:
			return
		session = requests.Session()
		hasNewSizes = False
		try:
			for package in unknown:
				if shouldStop is not None and shouldStop():
					break
				try:
					response = session.head(
						package.downloadUrl,
						timeout=_SIZE_REQUEST_TIMEOUT,
						allow_redirects=True,
					)
					size = int(response.headers.get("Content-Length") or 0)
				except (requests.exceptions.RequestException, TypeError, ValueError):
					continue
				if size <= 0:
					continue
				sizes[package.downloadUrl] = size
				hasNewSizes = True
				if onSize is not None:
					onSize(package, size)
		finally:
			session.close()
			if hasNewSizes:
				try:
					writeJsonObject(self.sizeCachePath, dict(sizes))
				except OSError:
					log.debug("Argos: could not save the package size cache.", exc_info=True)

	# --- Package index cache ---

	def saveIndexCache(self, catalog: ArgosCatalog) -> None:
		"""Save a downloaded index, so the engine knows the current languages without the network."""
		try:
			self.indexCachePath.parent.mkdir(parents=True, exist_ok=True)
			tempPath = self.indexCachePath.with_name(self.indexCachePath.name + ".tmp")
			_unused = tempPath.write_text(catalog.serialize(), encoding="utf-8")
			_unused = tempPath.replace(self.indexCachePath)
		except OSError:
			log.debug("Argos: could not save the package index cache.", exc_info=True)

	def loadCachedIndex(self) -> ArgosCatalog | None:
		"""Return the last index that was downloaded successfully, or None when there is none."""
		return ArgosCatalog.loadCached(self.indexCachePath)


def formatFileInUseFailure(error: BaseException) -> str:
	"""Return a user-facing explanation for Argos files that are open and cannot be replaced."""
	return _(
		"Some Argos model files are in use and cannot be replaced or removed.\n\n"
		"Choose 'Unload models' in the Argos model manager and try again. If that does not help, "
		"restart NVDA and try once more.\n\n"
		"Error: {error}",
	).format(error=error)
