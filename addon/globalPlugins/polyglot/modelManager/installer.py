# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Install, remove, and register ChromeAI model packages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import addonHandler
import requests

from ..common.secureScreen import SecureScreenError, isSecureScreen
from .catalog import ArchiveRef, ModelCatalog, ModelPackage, RuntimeEntry, pairDisplayName

addonHandler.initTranslation()

MODEL_OPERATION_LOCK = threading.Lock()


@dataclass(frozen=True)
class InstallProgress:
	"""Progress update emitted by model operations."""

	message: str
	percent: int | None = None


ProgressCallback = Callable[[InstallProgress], None]


class ModelInstaller:
	"""Installs ChromeAI model archives into the Polyglot ChromeAI profile."""

	def __init__(self, polyglotRoot: Path | None = None, tempDownloadDir: Path | None = None) -> None:
		"""Initialize model storage and temporary download locations."""
		self.polyglotRoot = polyglotRoot or getLocalAppData() / "Polyglot"
		self.tempDownloadDir = (
			tempDownloadDir or Path(tempfile.gettempdir()) / "PolyglotChromeAIModelDownloads"
		)

	@property
	def profileDir(self) -> Path:
		"""Return the ChromeAI profile directory."""
		return self.polyglotRoot / "ChromeAI"

	@property
	def legacyDownloadCacheDir(self) -> Path:
		"""Return the legacy download cache directory."""
		return self.polyglotRoot / "ChromeAIModelDownloads"

	def getInstalledPackageKeys(self, catalog: ModelCatalog) -> set[str]:
		"""Detect complete model packages installed for packages in the catalog."""
		installed: set[str] = set()
		localState = readJsonObject(self.profileDir / "Local State")
		translationState = getObject(localState, "on_device_translation")
		packagesState = getObject(translationState, "translate_kit_packages")
		for package in catalog.packages:
			if self.isPackageInstalled(package, packagesState):
				installed.add(package.key)
		return installed

	def isPackageInstalled(
		self,
		package: ModelPackage,
		packagesState: dict[str, object] | None = None,
	) -> bool:
		"""Return whether one model package is complete on disk."""
		if packagesState is None:
			localState = readJsonObject(self.profileDir / "Local State")
			translationState = getObject(localState, "on_device_translation")
			packagesState = getObject(translationState, "translate_kit_packages")
		registered = packagesState.get(f"{package.key}_registered") is True
		pathValue = packagesState.get(f"{package.key}_path")
		pathIsComplete = (
			registered and isinstance(pathValue, str) and self.isInstallPathComplete(package, Path(pathValue))
		)
		return pathIsComplete or self.isCurrentPackageComplete(package)

	def getRegisteredPackageKeys(self) -> set[str]:
		"""Return package keys registered in Chrome's Local State."""
		localState = readJsonObject(self.profileDir / "Local State")
		translationState = getObject(localState, "on_device_translation")
		packagesState = getObject(translationState, "translate_kit_packages")
		registeredSuffix = "_registered"
		return {
			key[: -len(registeredSuffix)]
			for key, value in packagesState.items()
			if key.endswith(registeredSuffix) and value is True and len(key) > len(registeredSuffix)
		}

	def hasRegisteredPackagesOutsideCatalog(self, catalog: ModelCatalog) -> bool:
		"""Return whether Local State contains registered packages not owned by this catalog."""
		managedKeys = {package.key.lower() for package in catalog.packages}
		return any(key.lower() not in managedKeys for key in self.getRegisteredPackageKeys())

	def hasRuntimeFiles(self, catalog: ModelCatalog) -> bool:
		"""Return whether any managed runtime files are present."""
		runtime = catalog.runtime
		libDir = self.pathFromRelative(runtime.libRelativeDir)
		binaryPath = self.pathFromRelative(runtime.binaryRelativePath)
		crxPath = self.pathFromRelative(runtime.crxRelativePath)
		return libDir.is_dir() or binaryPath.is_file() or bool(runtime.crxRelativePath and crxPath.is_file())

	def hasDownloadCacheFilesFast(self) -> bool:
		"""Return whether temp or legacy download cache directories contain entries."""
		return hasAnyFileSystemEntry(self.tempDownloadDir) or hasAnyFileSystemEntry(
			self.legacyDownloadCacheDir,
		)

	def getDownloadCacheSize(self) -> int:
		"""Return total bytes used by temp and legacy download caches."""
		return getDirectorySize(self.tempDownloadDir) + getDirectorySize(self.legacyDownloadCacheDir)

	def clearDownloadCache(self, progress: ProgressCallback | None = None) -> int:
		"""Clear temporary and legacy download caches."""
		bytesToClear = self.getDownloadCacheSize()
		deleteDirectoryIfExists(self.tempDownloadDir)
		deleteDirectoryIfExists(self.legacyDownloadCacheDir)
		if progress is not None:
			progress(
				InstallProgress(
					_("Cleared temporary downloads ({size:.1f} MiB).").format(
						size=bytesToClear / 1024 / 1024,
					),
					100,
				),
			)
		return bytesToClear

	def applySelection(
		self,
		catalog: ModelCatalog,
		selectedKeys: set[str],
		progress: ProgressCallback,
	) -> None:
		"""Apply selected model package keys, installing checked packages and removing unchecked packages."""
		self.profileDir.mkdir(parents=True, exist_ok=True)
		selectedKeys = set(selectedKeys)
		if selectedKeys:
			self.ensureRuntime(catalog, progress)
		else:
			progress(InstallProgress(_("No model packages selected."), 100))
		for key in sorted(selectedKeys, key=str.lower):
			package = getPackageByKey(catalog, key)
			if package is None:
				raise RuntimeError(_("Unknown package key: {key}").format(key=key))
			self.installPackage(catalog, package, progress)
		for package in catalog.packages:
			if package.key not in selectedKeys:
				self.removePackage(package, progress)
		if not selectedKeys and not self.hasRegisteredPackagesOutsideCatalog(catalog):
			self.removeRuntime(catalog.runtime, progress)
		if self.hasDownloadCacheFilesFast():
			self.clearDownloadCache(progress)
		self.syncComponentCache(catalog, selectedKeys)
		self.syncLocalState(catalog, selectedKeys)

	def ensurePackagesInstalled(
		self,
		catalog: ModelCatalog,
		packages: list[ModelPackage],
		progress: ProgressCallback,
	) -> None:
		"""Install one or more packages while preserving other complete catalog packages.

		:raises SecureScreenError: If NVDA is on a secure screen, where models must not be downloaded.
		"""
		if isSecureScreen():
			raise SecureScreenError()
		selectedKeys = self.getInstalledPackageKeys(catalog)
		for package in packages:
			selectedKeys.add(package.key)
		self.applySelection(catalog, selectedKeys, progress)

	def ensureRuntime(self, catalog: ModelCatalog, progress: ProgressCallback) -> None:
		"""Install TranslateKit runtime when it is not complete."""
		runtime = catalog.runtime
		binaryPath = self.pathFromRelative(runtime.binaryRelativePath)
		crxPath = self.pathFromRelative(runtime.crxRelativePath)
		if binaryPath.is_file() and (not runtime.crxRelativePath or crxPath.is_file()):
			progress(InstallProgress(_("TranslateKit runtime already installed."), 100))
			return
		runtimeArchivePath: Path | None = None
		try:
			if runtime.archive is None:
				raise RuntimeError(_("TranslateKit runtime does not have a downloadable archive."))
			progress(InstallProgress(_("Installing downloaded TranslateKit runtime.")))
			runtimeArchivePath = self.getArchive(catalog, runtime.archive, progress)
			self.extractArchiveFromFile(runtimeArchivePath, progress)
		except Exception:
			self.tryCleanupRuntime(runtime)
			raise
		finally:
			if runtimeArchivePath is not None:
				deleteFileIfExists(runtimeArchivePath)
				deleteFileIfExists(Path(str(runtimeArchivePath) + ".download"))
				removeEmptyDirectory(self.tempDownloadDir)

	def installPackage(
		self,
		catalog: ModelCatalog,
		package: ModelPackage,
		progress: ProgressCallback,
	) -> None:
		"""Install a model package if it is not already complete."""
		if self.isCurrentPackageComplete(package):
			progress(
				InstallProgress(
					_("{package} already installed.").format(package=pairDisplayName(package)),
					100,
				),
			)
			return
		if package.archive is None:
			raise RuntimeError(
				_("{package} does not have a downloadable archive.").format(package=pairDisplayName(package)),
			)
		archivePath = self.getArchive(catalog, package.archive, progress)
		try:
			self.extractArchiveFromFile(archivePath, progress)
		except Exception:
			self.tryCleanupPackage(package)
			raise
		finally:
			deleteFileIfExists(archivePath)
			deleteFileIfExists(Path(str(archivePath) + ".download"))
			removeEmptyDirectory(self.tempDownloadDir)

	def isCurrentPackageComplete(self, package: ModelPackage) -> bool:
		"""Return whether the package install directory and CRX cache entry are complete."""
		return self.isInstallPathComplete(package, self.pathFromRelative(package.installRelativeDir))

	def isInstallPathComplete(self, package: ModelPackage, installPath: Path) -> bool:
		"""Return whether an install path contains a complete package."""
		crxPath = self.pathFromRelative(package.crxRelativePath)
		return (
			installPath.is_dir()
			and (installPath / "manifest.json").is_file()
			and (not package.crxRelativePath or crxPath.is_file())
		)

	def getArchive(
		self,
		catalog: ModelCatalog,
		archive: ArchiveRef,
		progress: ProgressCallback,
	) -> Path:
		"""Get a verified archive from temp cache or by downloading it."""
		fileName = archiveFileName(archive.path)
		destination = self.tempDownloadDir / fileName
		if destination.is_file() and verifyArchive(destination, archive):
			progress(InstallProgress(_("Using cached archive {fileName}.").format(fileName=fileName), 100))
			return destination
		if destination.is_file():
			destination.unlink()
		url = catalog.archiveUrl(archive)
		progress(InstallProgress(_("Downloading {fileName}.").format(fileName=fileName), 0))
		downloadFile(url, destination, archive.size, progress)
		if not verifyArchive(destination, archive):
			deleteFileIfExists(destination)
			raise RuntimeError(
				_("Downloaded archive verification failed: {fileName}").format(fileName=fileName),
			)
		return destination

	def extractArchiveFromFile(self, archivePath: Path, progress: ProgressCallback) -> None:
		"""Extract a verified archive from disk."""
		with archivePath.open("rb") as stream:
			self.extractArchive(stream, progress)

	def extractArchive(self, archiveStream: Any, progress: ProgressCallback) -> None:
		"""Extract only payload entries from an archive, rejecting path traversal."""
		with zipfile.ZipFile(archiveStream, "r") as archive:
			entries = [
				entry
				for entry in archive.infolist()
				if entry.filename.lower().startswith("payload/") and not entry.is_dir()
			]
			rootFull = os.path.abspath(str(self.polyglotRoot))
			rootPrefix = rootFull if rootFull.endswith(os.sep) else rootFull + os.sep
			total = len(entries)
			for index, entry in enumerate(entries, start=1):
				relative = entry.filename[len("payload/") :].replace("/", os.sep).replace("\\", os.sep)
				destination = os.path.abspath(os.path.join(rootFull, relative))
				if not destination.startswith(rootPrefix):
					raise RuntimeError(
						_("Archive entry is outside the install root: {entry}").format(entry=entry.filename),
					)
				destinationPath = Path(destination)
				destinationPath.parent.mkdir(parents=True, exist_ok=True)
				with archive.open(entry, "r") as source, destinationPath.open("wb") as target:
					shutil.copyfileobj(source, target, 1024 * 1024)
				percent = int(index * 100 / total) if total else 100
				progress(
					InstallProgress(
						_("Extracting {fileName}.").format(fileName=Path(entry.filename).name),
						percent,
					),
				)

	def removePackage(self, package: ModelPackage, progress: ProgressCallback) -> None:
		"""Remove package files when present."""
		if self.removePackageFiles(package):
			progress(InstallProgress(_("Removed {package}.").format(package=pairDisplayName(package)), 100))

	def removePackageFiles(self, package: ModelPackage) -> bool:
		"""Remove model directory and CRX cache file for a package."""
		wasRemoved = False
		modelDir = self.pathFromRelative(package.modelRelativeDir)
		if modelDir.is_dir():
			shutil.rmtree(modelDir)
			wasRemoved = True
		if package.crxRelativePath:
			crxPath = self.pathFromRelative(package.crxRelativePath)
			if crxPath.is_file():
				crxPath.unlink()
				wasRemoved = True
		removeEmptyDirectory(self.profileDir / "TranslateKit" / "models")
		removeEmptyDirectory(self.profileDir / "TranslateKit")
		removeEmptyDirectory(self.profileDir / "component_crx_cache")
		return wasRemoved

	def tryCleanupPackage(self, package: ModelPackage) -> None:
		"""Best-effort cleanup after package install failure."""
		try:
			self.removePackageFiles(package)
		except Exception:
			pass

	def removeRuntime(self, runtime: RuntimeEntry, progress: ProgressCallback) -> None:
		"""Remove TranslateKit runtime when no models remain selected."""
		removedBytes = self.removeRuntimeFiles(runtime)
		if removedBytes > 0:
			progress(
				InstallProgress(
					_("Removed TranslateKit runtime ({size:.1f} MiB).").format(
						size=removedBytes / 1024 / 1024,
					),
					100,
				),
			)

	def removeRuntimeFiles(self, runtime: RuntimeEntry) -> int:
		"""Remove runtime library and CRX cache files."""
		removedBytes = deleteDirectoryIfExists(self.pathFromRelative(runtime.libRelativeDir))
		if runtime.crxRelativePath:
			removedBytes += deleteFileIfExists(self.pathFromRelative(runtime.crxRelativePath))
		removeEmptyDirectory(self.profileDir / "TranslateKit" / "lib")
		removeEmptyDirectory(self.profileDir / "TranslateKit")
		removeEmptyDirectory(self.profileDir / "component_crx_cache")
		return removedBytes

	def tryCleanupRuntime(self, runtime: RuntimeEntry) -> None:
		"""Best-effort cleanup after runtime install failure."""
		try:
			self.removeRuntimeFiles(runtime)
		except Exception:
			pass

	def syncComponentCache(self, catalog: ModelCatalog, selectedKeys: set[str]) -> None:
		"""Synchronize component_crx_cache metadata for selected models."""
		metadataPath = self.profileDir / "component_crx_cache" / "metadata.json"
		metadata = readJsonObject(metadataPath)
		hashes = getObject(metadata, "hashes")
		metadata["hashes"] = hashes
		preserveExistingRuntime = not selectedKeys and self.hasRegisteredPackagesOutsideCatalog(catalog)
		managedIds = {package.componentId for package in catalog.packages if package.componentId}
		if not preserveExistingRuntime and catalog.runtime.componentId:
			managedIds.add(catalog.runtime.componentId)
		for key, value in list(hashes.items()):
			if isinstance(value, dict) and value.get("appid") in managedIds:
				hashes.pop(key, None)
		if selectedKeys and catalog.runtime.componentId and catalog.runtime.crxHash:
			hashes[catalog.runtime.crxHash] = {"appid": catalog.runtime.componentId}
		for key in selectedKeys:
			package = getPackageByKey(catalog, key)
			if package is not None and package.componentId and package.crxHash:
				hashes[package.crxHash] = {"appid": package.componentId}
		writeJsonObject(metadataPath, metadata)

	def syncLocalState(self, catalog: ModelCatalog, selectedKeys: set[str]) -> None:
		"""Synchronize Chrome Local State registration entries for selected models."""
		localStatePath = self.profileDir / "Local State"
		localState = readJsonObject(localStatePath)
		translation = getObject(localState, "on_device_translation")
		localState["on_device_translation"] = translation
		packages = getObject(translation, "translate_kit_packages")
		for package in catalog.packages:
			packages.pop(f"{package.key}_path", None)
			packages.pop(f"{package.key}_registered", None)
		for key in sorted(selectedKeys, key=str.lower):
			package = getPackageByKey(catalog, key)
			if package is None:
				continue
			packages[f"{package.key}_path"] = str(self.pathFromRelative(package.installRelativeDir))
			packages[f"{package.key}_registered"] = True
		translation["translate_kit_packages"] = packages
		hasRegisteredPackages = any(
			key.endswith("_registered") and value is True for key, value in packages.items()
		)
		if selectedKeys:
			translation["translate_kit_binary_path"] = str(
				self.pathFromRelative(catalog.runtime.binaryRelativePath),
			)
			translation["translate_kit_registered"] = True
		elif hasRegisteredPackages:
			translation["translate_kit_registered"] = True
		else:
			translation.pop("translate_kit_binary_path", None)
			translation["translate_kit_registered"] = False

		updateClientData = getObject(localState, "updateclientdata")
		localState["updateclientdata"] = updateClientData
		apps = getObject(updateClientData, "apps")
		updateClientData["apps"] = apps
		preserveExistingRuntime = not selectedKeys and hasRegisteredPackages
		componentIdsToReplace = {package.componentId for package in catalog.packages if package.componentId}
		if not preserveExistingRuntime and catalog.runtime.componentId:
			componentIdsToReplace.add(catalog.runtime.componentId)
		for componentId in componentIdsToReplace:
			apps.pop(componentId, None)
		if selectedKeys and catalog.runtime.componentId:
			apps[catalog.runtime.componentId] = buildUpdateClientEntry(
				catalog.runtime.version,
				catalog.runtime.updateClientData,
			)
		for key in selectedKeys:
			package = getPackageByKey(catalog, key)
			if package is not None and package.componentId:
				apps[package.componentId] = buildUpdateClientEntry(package.version, package.updateClientData)
		writeJsonObject(localStatePath, localState)

	def pathFromRelative(self, relativePath: str) -> Path:
		"""Convert a catalog relative path to an OS path under the Polyglot root."""
		return self.polyglotRoot / toOsPath(relativePath)


def getPackageByKey(catalog: ModelCatalog, key: str) -> ModelPackage | None:
	"""Get a catalog package by key using case-insensitive comparison."""
	return catalog.byKey.get(key.lower())


def archiveFileName(path: str) -> str:
	"""Return the file name part of an archive path or URL."""
	parsed = urlparse(path)
	fileName = Path(parsed.path or path).name
	if not fileName:
		raise RuntimeError(_("Archive path has no file name: {path}").format(path=path))
	return fileName


def downloadFile(url: str, destination: Path, expectedSize: int, progress: ProgressCallback) -> None:
	"""Download a file to a temporary path and atomically replace the destination.

	Every model download Polyglot makes, for ChromeAI and for Argos alike, goes through here, so
	this is where a secure screen is refused no matter which caller asked for the file.

	:raises SecureScreenError: If NVDA is on a secure screen.
	"""
	if isSecureScreen():
		raise SecureScreenError()
	destination.parent.mkdir(parents=True, exist_ok=True)
	tempPath = Path(str(destination) + ".download")
	try:
		with requests.get(url, stream=True, timeout=(15, 1800)) as response:
			response.raise_for_status()
			total = int(response.headers.get("Content-Length") or expectedSize or 0)
			readTotal = 0
			with tempPath.open("wb") as output:
				for chunk in response.iter_content(chunk_size=1024 * 1024):
					if not chunk:
						continue
					output.write(chunk)
					readTotal += len(chunk)
					if total > 0:
						progress(
							InstallProgress(
								_("Downloading {fileName}.").format(fileName=destination.name),
								int(readTotal * 100 / total),
							),
						)
		tempPath.replace(destination)
	except Exception:
		deleteFileIfExists(tempPath)
		raise


def verifyArchive(path: Path, archive: ArchiveRef) -> bool:
	"""Verify archive size and SHA-256 hash when provided."""
	if archive.size > 0 and path.stat().st_size != archive.size:
		return False
	if not archive.sha256:
		return True
	return computeSha256Hex(path) == archive.sha256.lower()


def computeSha256Hex(path: Path) -> str:
	"""Compute a file's SHA-256 hash in hex."""
	sha256 = hashlib.sha256()
	with path.open("rb") as inputFile:
		for chunk in iter(lambda: inputFile.read(1024 * 1024), b""):
			sha256.update(chunk)
	return sha256.hexdigest()


def readJsonObject(path: Path) -> dict[str, Any]:
	"""Read a JSON object, returning an empty object when the file is absent or invalid."""
	if not path.is_file():
		return {}
	try:
		data = json.loads(path.read_text(encoding="utf-8-sig"))
		return data if isinstance(data, dict) else {}
	except (json.JSONDecodeError, UnicodeError):
		return {}


def writeJsonObject(path: Path, node: dict[str, Any]) -> None:
	"""Write a compact JSON object atomically."""
	path.parent.mkdir(parents=True, exist_ok=True)
	tempPath = path.with_name(path.name + ".tmp")
	tempPath.write_text(json.dumps(node, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
	tempPath.replace(path)


def getObject(parent: dict[str, Any], key: str) -> dict[str, Any]:
	"""Get a nested JSON object or return a new object."""
	value = parent.get(key)
	if isinstance(value, dict):
		return value
	return {}


def buildUpdateClientEntry(version: str, source: dict[str, Any] | None) -> dict[str, Any]:
	"""Build a Chrome updateclientdata app entry."""
	entry = dict(source) if source is not None else {}
	entry["pv"] = str(entry.get("pv") or version)
	entry.setdefault("cohort", "1::")
	entry.setdefault("cohortname", "")
	entry.setdefault("dlrc", 0)
	entry.setdefault("fp", "")
	entry.setdefault("installdate", 0)
	entry.setdefault("max_pv", "0.0.0.0")
	entry.setdefault("pf", "")
	return entry


def deleteDirectoryIfExists(path: Path) -> int:
	"""Delete a directory and return the bytes removed."""
	if not path.is_dir():
		return 0
	bytesRemoved = getDirectorySize(path)
	shutil.rmtree(path)
	return bytesRemoved


def deleteFileIfExists(path: Path) -> int:
	"""Delete a file and return the bytes removed."""
	if not path.is_file():
		return 0
	bytesRemoved = path.stat().st_size
	path.unlink()
	return bytesRemoved


def removeEmptyDirectory(path: Path) -> None:
	"""Remove a directory only if it exists and is empty."""
	if path.is_dir() and not any(path.iterdir()):
		path.rmdir()


def hasAnyFileSystemEntry(path: Path) -> bool:
	"""Return whether a directory has any entries; assume yes on access errors."""
	try:
		return path.is_dir() and any(path.iterdir())
	except Exception:
		return True


def getDirectorySize(path: Path) -> int:
	"""Return recursive directory size in bytes."""
	if not path.is_dir():
		return 0
	total = 0
	for item in path.rglob("*"):
		if item.is_file():
			total += item.stat().st_size
	return total


def toOsPath(relativePath: str) -> str:
	"""Convert catalog path separators to the current OS separator."""
	return relativePath.replace("/", os.sep).replace("\\", os.sep)


def getLocalAppData() -> Path:
	"""Return the user's LocalAppData directory."""
	if localAppData := os.environ.get("LOCALAPPDATA"):
		return Path(localAppData)
	return Path.home() / "AppData" / "Local"


def isFileInUseFailure(error: BaseException) -> bool:
	"""Return whether an exception likely came from a file currently being used."""
	if isinstance(error, requests.exceptions.RequestException):
		return False
	if isinstance(error, OSError):
		winError = getattr(error, "winerror", None)
		return winError in (32, 33)
	return error.__cause__ is not None and isFileInUseFailure(error.__cause__)


def formatFileInUseFailure(error: BaseException) -> str:
	"""Return a user-facing explanation for locked model files."""
	return _(
		"Some model files are currently being used and cannot be replaced or removed.\n\n"
		"Please manually disable the {engine} translation engine, restart NVDA, and then try again.\n\n"
		"Error: {error}",
	).format(engine=_("Chrome AI (Offline)"), error=error)
