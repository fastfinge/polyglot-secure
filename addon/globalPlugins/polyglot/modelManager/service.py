# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Shared model manager service used by ChromeAI and the Tools menu dialog."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto

import addonHandler
import gui
import gui.message
import queueHandler
import wx
from gui.guiHelper import wxCallOnMain
from logHandler import log

from ..common import cues
from ..common.secureScreen import isSecureScreen
from .catalog import ModelCatalog, ModelPackage, pairDisplayName
from .installer import (
	MODEL_OPERATION_LOCK,
	InstallProgress,
	ModelInstaller,
	formatFileInUseFailure,
	isFileInUseFailure,
)

addonHandler.initTranslation()


class EnsureModelDecision(Enum):
	"""User decision when a required model is not installed."""

	INSTALL = auto()
	USE_CHROME = auto()
	CANCEL = auto()


@dataclass
class _ActiveMissingModelRequest:
	"""Tracks one in-flight missing-model prompt and follow-up operation."""

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


class ModelManagerService:
	"""Coordinates catalog lookup and on-demand model installation."""

	def __init__(self) -> None:
		"""Initialize catalog state and missing-model request coordination."""
		super().__init__()
		self.installer = ModelInstaller()
		self._catalog: ModelCatalog | None = None
		self._chromeFallbackPackageKeys: set[str] = set()
		self._missingModelRequestLock = threading.Lock()
		self._activeMissingModelRequest: _ActiveMissingModelRequest | None = None

	def getCatalogSnapshot(self) -> ModelCatalog:
		"""Return the current catalog without remote IO."""
		if self._catalog is not None:
			return self._catalog
		catalog = ModelCatalog.loadBundled()
		self._catalog = catalog
		return catalog

	def findRequiredPackages(
		self,
		sourceLanguage: str,
		targetLanguage: str,
	) -> tuple[ModelCatalog, list[ModelPackage]] | None:
		"""Find the package or packages required for a requested language pair."""
		catalog = self.getCatalogSnapshot()
		packages = catalog.findPackagesForPair(sourceLanguage, targetLanguage)
		if not packages:
			return None
		return catalog, packages

	def isPackageInstalled(self, package: ModelPackage) -> bool:
		"""Return whether a package is already complete on disk."""
		return self.installer.isPackageInstalled(package)

	def ensureModelForPairInteractive(self, sourceLanguage: str, targetLanguage: str) -> bool:
		"""Ensure a model is ready, prompting the user only when installation is needed.

		Returns True when translation should continue. Returns False when the user cancelled
		or the native install path failed after user-visible feedback.

		On a secure screen the native installer is skipped entirely: NVDA is the system account there,
		so a download would land in a profile the user cannot reach. Chrome is left to supply the model
		as it does when the user declines the native install, rather than the translation being refused.
		"""
		if isSecureScreen():
			log.debug("Chrome AI: on a secure screen, leaving any model download to Chrome.")
			return True
		required = self.findRequiredPackages(sourceLanguage, targetLanguage)
		if required is None:
			return True
		catalog, packages = required
		missingPackages = [
			package
			for package in packages
			if package.key not in self._chromeFallbackPackageKeys and not self.isPackageInstalled(package)
		]
		if not missingPackages:
			return True
		return self._runMissingModelRequest(catalog, missingPackages)

	def _runMissingModelRequest(self, catalog: ModelCatalog, packages: list[ModelPackage]) -> bool:
		"""Run or join the in-flight prompt/install flow for the same missing packages."""
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
			request.done.wait()
			if request.error is not None:
				raise request.error
			return request.shouldContinue
		try:
			decision = self._promptForMissingModels(packages, request)
			if decision == EnsureModelDecision.USE_CHROME:
				for package in packages:
					self._chromeFallbackPackageKeys.add(package.key)
				request.shouldContinue = True
			elif decision == EnsureModelDecision.CANCEL:
				request.shouldContinue = False
			else:
				request.shouldContinue = self._installPackagesWithUi(catalog, packages)
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
		"""Raise the active missing-model dialog when a duplicate request appears."""
		request.dialogReady.wait(timeout=0.5)

		def focus() -> None:
			if request.done.is_set() or request.dialog is None:
				return
			try:
				request.dialog.Raise()
				request.dialog.SetFocus()
			except RuntimeError:
				pass

		wx.CallAfter(focus)

	def _promptForMissingModels(
		self,
		packages: list[ModelPackage],
		request: _ActiveMissingModelRequest,
	) -> EnsureModelDecision:
		"""Ask how to handle missing model packages."""
		packageNames = "\n".join(f"  - {pairDisplayName(package)}" for package in packages)
		message = _(
			"The following offline model package(s) are not installed:\n\n"
			"{packages}\n\n"
			"Choose Yes to download and install them with Polyglot's model manager. "
			"Use this if Chrome's model download service is slow, blocked, or unreliable on your network.\n"
			"Choose No to let Chrome download them.\n"
			"Choose Cancel to cancel this translation.",
		).format(packages=packageNames)

		def showDialog() -> gui.message.ReturnCode:
			dialog = gui.message.MessageDialog(
				parent=gui.mainFrame,
				message=message,
				title=_("Polyglot ChromeAI Model Manager"),
				buttons=gui.message.DefaultButtonSet.YES_NO_CANCEL,
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
		if answer == gui.message.ReturnCode.YES:
			return EnsureModelDecision.INSTALL
		if answer == gui.message.ReturnCode.NO:
			return EnsureModelDecision.USE_CHROME
		return EnsureModelDecision.CANCEL

	def _installPackagesWithUi(self, catalog: ModelCatalog, packages: list[ModelPackage]) -> bool:
		"""Install packages in the current background task."""
		if not MODEL_OPERATION_LOCK.acquire(blocking=False):
			wxCallOnMain(
				gui.messageBox,
				_("Another model operation is already running."),
				_("Polyglot ChromeAI Model Manager"),
				wx.OK | wx.ICON_INFORMATION,
			)
			return False
		try:
			progress = _SpeechProgress()
			cues.Beep.resetProgress()
			try:
				self.installer.ensurePackagesInstalled(catalog, packages, progress.report)
			except Exception as exc:
				if isFileInUseFailure(exc):
					self._showInstallFailure(RuntimeError(formatFileInUseFailure(exc)))
				else:
					self._showInstallFailure(exc)
				return False
			queueHandler.queueFunction(
				queueHandler.eventQueue,
				cues.Speech.message,
				_("Model installation complete."),
			)
			return True
		finally:
			cues.Beep.resetProgress()
			MODEL_OPERATION_LOCK.release()

	def _showInstallFailure(self, error: Exception) -> None:
		"""Report an on-demand model install failure to the user."""
		log.error("ChromeAI model install failed (%s).", type(error).__name__)
		wxCallOnMain(
			gui.messageBox,
			str(error),
			_("Polyglot ChromeAI Model Manager"),
			wx.OK | wx.ICON_ERROR,
		)


_service: ModelManagerService | None = None


def getModelManagerService() -> ModelManagerService:
	"""Return the process-wide model manager service."""
	global _service
	if _service is None:
		_service = ModelManagerService()
	return _service
