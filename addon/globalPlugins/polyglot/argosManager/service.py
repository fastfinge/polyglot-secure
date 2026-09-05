# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Shared Argos model service used by the engine and by the Tools menu dialog."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import addonHandler
import gui
import gui.message
import queueHandler
import wx
from gui.guiHelper import wxCallOnMain
from logHandler import log

from ..common import cues
from ..common.secureScreen import SecureScreenError, isSecureScreen
from ..modelManager.installer import InstallProgress, isFileInUseFailure
from .catalog import ArgosCatalog, ArgosPackage, pairDisplayName
from .installer import ARGOS_OPERATION_LOCK, ArgosInstaller, formatFileInUseFailure
from .translator import ArgosTranslator, getArgosTranslator

addonHandler.initTranslation()

#: Title shown on every message box the Argos model manager puts up.
DIALOG_TITLE = _("Polyglot Argos model manager")


@dataclass
class _ActiveMissingModelRequest:
	"""Tracks one in-flight missing-model prompt and the install that may follow it."""

	key: tuple[str, ...]
	done: threading.Event = field(default_factory=threading.Event)
	dialogReady: threading.Event = field(default_factory=threading.Event)
	dialog: gui.message.MessageDialog | None = None
	shouldContinue: bool = False
	error: Exception | None = None


@dataclass
class _SpeechProgress:
	"""Throttles install progress spoken from a background translation task."""

	_lastMessage: str = ""
	_lastReportTime: float = 0

	def report(self, progress: InstallProgress) -> None:
		"""Queue a concise speech update for meaningful progress changes."""
		now = time.monotonic()
		if progress.percent is not None:
			cues.Beep.reportProgress(progress.percent, 100)
		isStageMessage = progress.percent is None or progress.percent in (0, 100)
		if not isStageMessage:
			return
		if progress.message == self._lastMessage:
			return
		if now - self._lastReportTime < 1.5:
			return
		self._lastMessage = progress.message
		self._lastReportTime = now
		queueHandler.queueFunction(queueHandler.eventQueue, cues.Speech.message, progress.message)


class ArgosService:
	"""Coordinates the package index, on-demand installation, and the loaded models."""

	def __init__(self) -> None:
		"""Initialize the service over Polyglot's Argos storage."""
		super().__init__()
		self.installer = ArgosInstaller()
		self._catalog: ArgosCatalog | None = None
		self._missingModelRequestLock = threading.Lock()
		self._activeMissingModelRequest: _ActiveMissingModelRequest | None = None

	@property
	def translator(self) -> ArgosTranslator:
		"""Return the process-wide translator."""
		return getArgosTranslator()

	def getCatalogSnapshot(self) -> ArgosCatalog:
		"""Return the package index without touching the network.

		The index last downloaded by the model manager is preferred, so a language added to Argos
		after this Polyglot release is still offered; the bundled snapshot is the fallback.
		"""
		if self._catalog is not None:
			return self._catalog
		catalog = self.installer.loadCachedIndex() or ArgosCatalog.loadBundled()
		self._catalog = catalog
		return catalog

	def setCatalog(self, catalog: ArgosCatalog) -> None:
		"""Adopt an index the model manager has just downloaded."""
		self._catalog = catalog

	def findRequiredPackages(self, sourceLanguage: str, targetLanguage: str) -> list[ArgosPackage]:
		"""Return the packages a language direction needs, pivoting through English when needed."""
		return self.getCatalogSnapshot().findPackagesForPair(sourceLanguage, targetLanguage)

	def getMissingPackages(self, sourceLanguage: str, targetLanguage: str) -> list[ArgosPackage]:
		"""Return the packages a direction needs that are not installed yet."""
		installedByKey = self.installer.getInstalledByKey()
		return [
			package
			for package in self.findRequiredPackages(sourceLanguage, targetLanguage)
			if package.key not in installedByKey
		]

	def ensureModelsForPairInteractive(self, sourceLanguage: str, targetLanguage: str) -> bool:
		"""Make sure a direction can be translated, asking before downloading anything.

		:return: True when translation should go ahead, False when the user cancelled or the
			install failed after the user was told about it.
		:raises SecureScreenError: If NVDA is on a secure screen. Nothing may be downloaded there, and
			the models the user installed are in their own profile, out of reach of the system account,
			so there is nothing to fall back on either.
		"""
		if isSecureScreen():
			raise SecureScreenError()
		if not self.installer.runtime.isHostSupported:
			self._showMessage(self.installer.runtime.unsupportedHostMessage, wx.ICON_ERROR)
			return False
		requiredPackages = self.findRequiredPackages(sourceLanguage, targetLanguage)
		if not requiredPackages:
			self._showMessage(
				_(
					"Argos Translate has no model for this language direction. "
					"Choose a different source or target language in Polyglot's settings.",
				),
				wx.ICON_ERROR,
			)
			return False
		installedByKey = self.installer.getInstalledByKey()
		missingPackages = [package for package in requiredPackages if package.key not in installedByKey]
		# A package already installed says whether this direction needs the BPE extras. A missing one
		# cannot: the index does not name its tokenizer, so the installer fetches them once it knows.
		needsBpeSupport = any(
			installedByKey[package.key].usesBpe
			for package in requiredPackages
			if package.key in installedByKey
		)
		runtimeBytes = self.installer.runtime.getMissingDownloadSize(withBpeSupport=needsBpeSupport)
		if not missingPackages and runtimeBytes == 0:
			return True
		return self._runMissingModelRequest(missingPackages, runtimeBytes)

	def _runMissingModelRequest(self, packages: list[ArgosPackage], runtimeBytes: int) -> bool:
		"""Run, or join, the prompt and install for the same set of missing packages."""
		cues.stopPeriodicCue()
		key = tuple(sorted(package.key for package in packages))
		with self._missingModelRequestLock:
			activeRequest = self._activeMissingModelRequest
			if activeRequest is not None and activeRequest.key == key:
				request = activeRequest
				isOwner = False
			else:
				request = _ActiveMissingModelRequest(key)
				self._activeMissingModelRequest = request
				isOwner = True
		if not isOwner:
			self._focusMissingModelDialog(request)
			_unused = request.done.wait()
			if request.error is not None:
				raise request.error
			return request.shouldContinue
		try:
			if not self._promptForMissingModels(packages, runtimeBytes, request):
				request.shouldContinue = False
			else:
				request.shouldContinue = self._installPackagesWithUi(packages)
			return request.shouldContinue
		except Exception as exc:
			request.error = exc
			raise
		finally:
			request.done.set()
			with self._missingModelRequestLock:
				if self._activeMissingModelRequest is request:
					self._activeMissingModelRequest = None

	def _focusMissingModelDialog(self, request: _ActiveMissingModelRequest) -> None:
		"""Raise the prompt that is already up when a second translation asks for the same models."""
		_unused = request.dialogReady.wait(timeout=0.5)

		def focus() -> None:
			if request.done.is_set() or request.dialog is None:
				return
			try:
				_unused = request.dialog.Raise()
				request.dialog.SetFocus()
			except RuntimeError:
				pass

		wx.CallAfter(focus)

	def _promptForMissingModels(
		self,
		packages: list[ArgosPackage],
		runtimeBytes: int,
		request: _ActiveMissingModelRequest,
	) -> bool:
		"""Ask whether to download what this translation needs."""
		message = self._buildMissingModelMessage(packages, runtimeBytes)

		def showDialog() -> gui.message.ReturnCode:
			dialog = gui.message.MessageDialog(
				parent=gui.mainFrame,
				message=message,
				title=DIALOG_TITLE,
				buttons=gui.message.DefaultButtonSet.YES_NO,
			)
			request.dialog = dialog
			request.dialogReady.set()
			try:
				return dialog.ShowModal()
			finally:
				request.dialog = None

		try:
			answer = wxCallOnMain(showDialog)
		finally:
			request.dialogReady.set()
		return answer == gui.message.ReturnCode.YES

	def _buildMissingModelMessage(self, packages: list[ArgosPackage], runtimeBytes: int) -> str:
		"""Describe what has to be downloaded before this translation can run."""
		lines: list[str] = []
		totalBytes = 0
		if runtimeBytes > 0:
			totalBytes += runtimeBytes
			lines.append(
				_("  - the Argos translation runtime ({size})").format(
					size=formatSize(runtimeBytes),
				),
			)
		for package in packages:
			packageBytes = self.installer.getCachedSize(package)
			totalBytes += packageBytes
			lines.append(
				_("  - {package} ({size})").format(
					package=pairDisplayName(package),
					size=formatSize(packageBytes),
				),
			)
		if len(packages) > 1:
			lines.append(_("Argos translates between these languages through English."))
		return _(
			"Argos Translate needs to download the following before it can translate offline:\n\n"
			"{items}\n\n"
			"Total download: about {total}. This is downloaded once and then works without a "
			"network connection.\n\n"
			"Download and install it now?",
		).format(items="\n".join(lines), total=formatSize(totalBytes))

	def _installPackagesWithUi(self, packages: list[ArgosPackage]) -> bool:
		"""Install what is missing from inside the translation task that asked for it."""
		if not ARGOS_OPERATION_LOCK.acquire(blocking=False):
			self._showMessage(_("Another Argos model operation is already running."), wx.ICON_INFORMATION)
			return False
		try:
			progress = _SpeechProgress()
			cues.Beep.resetProgress()
			try:
				self.installer.ensurePackagesInstalled(packages, progress.report)
			except Exception as exc:
				self._showInstallFailure(exc)
				return False
			queueHandler.queueFunction(
				queueHandler.eventQueue,
				cues.Speech.message,
				_("The Argos model is ready."),
			)
			return True
		finally:
			cues.Beep.resetProgress()
			ARGOS_OPERATION_LOCK.release()

	def _showInstallFailure(self, error: Exception) -> None:
		"""Report a failed on-demand install to the user."""
		log.error("Argos model install failed (%s).", type(error).__name__)
		message = formatFileInUseFailure(error) if isFileInUseFailure(error) else str(error)
		self._showMessage(message, wx.ICON_ERROR)

	def _showMessage(self, message: str, icon: int) -> None:
		"""Show a message from whichever thread is running a translation."""
		wxCallOnMain(gui.messageBox, message, DIALOG_TITLE, wx.OK | icon)


def formatSize(sizeInBytes: int) -> str:
	"""Return a download size in the units a user thinks in, or a placeholder when unknown."""
	if sizeInBytes <= 0:
		return _("size unknown")
	if sizeInBytes >= 1024 * 1024 * 1024:
		return _("{size:.1f} GB").format(size=sizeInBytes / 1024 / 1024 / 1024)
	return _("{size:.0f} MB").format(size=sizeInBytes / 1024 / 1024)


_service: ArgosService | None = None


def getArgosService() -> ArgosService:
	"""Return the process-wide Argos model service."""
	global _service
	if _service is None:
		_service = ArgosService()
	return _service
