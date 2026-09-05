# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks that the offline model downloaders stay off secure screens.

NVDA runs as the system account on the sign-in screen, the lock screen, and UAC prompts. A model
downloaded there would be written into that account's profile, so every path that downloads or
installs a ChromeAI or Argos model has to refuse before it reaches the network.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installGuiStubs, installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)
installGuiStubs()

import globalVars  # noqa: E402
from polyglot.argosManager.installer import ArgosInstaller  # noqa: E402
from polyglot.argosManager.service import ArgosService  # noqa: E402
from polyglot.common.secureScreen import SecureScreenError, isSecureScreen  # noqa: E402
from polyglot.modelManager import installer as modelInstallerModule  # noqa: E402
from polyglot.modelManager.installer import ModelInstaller, downloadFile  # noqa: E402
from polyglot.modelManager.service import ModelManagerService  # noqa: E402


class _NetworkWasReached(Exception):
	"""Raised in place of a request, so a check can tell that a download was started."""


class SecureScreenTestCase(unittest.TestCase):
	"""Give each check its own Polyglot directory, and put NVDA back on a normal screen after it."""

	def setUp(self) -> None:
		self._tempDir = tempfile.TemporaryDirectory()
		self.root = Path(self._tempDir.name)
		self.addCleanup(self._tempDir.cleanup)
		self.addCleanup(setattr, globalVars.appArgs, "secure", False)

	def useSecureScreen(self) -> None:
		"""Put NVDA on a secure screen for the rest of the check."""
		globalVars.appArgs.secure = True


class SecureScreenDetectionTestCase(SecureScreenTestCase):
	"""The whole guard rests on NVDA's own secure flag, so it is read rather than cached."""

	def test_followsNvdasSecureFlag(self) -> None:
		self.assertFalse(isSecureScreen())
		self.useSecureScreen()
		self.assertTrue(isSecureScreen())


class DownloadFileTestCase(SecureScreenTestCase):
	"""Every model download goes through one function, which is where a secure screen is refused."""

	def test_refusesOnASecureScreen(self) -> None:
		self.useSecureScreen()
		destination = self.root / "model.zip"
		with patch.object(modelInstallerModule.requests, "get", side_effect=_NetworkWasReached):
			with self.assertRaises(SecureScreenError):
				downloadFile("https://example.invalid/model.zip", destination, 0, Mock())
		self.assertFalse(destination.exists())
		self.assertFalse(destination.parent.joinpath("model.zip.download").exists())

	def test_startsTheDownloadOnANormalScreen(self) -> None:
		destination = self.root / "model.zip"
		with patch.object(modelInstallerModule.requests, "get", side_effect=_NetworkWasReached):
			with self.assertRaises(_NetworkWasReached):
				downloadFile("https://example.invalid/model.zip", destination, 0, Mock())


class ArgosInstallTestCase(SecureScreenTestCase):
	"""The Argos models and the runtime they need are both downloads."""

	def test_packageInstallRefusesOnASecureScreen(self) -> None:
		installer = ArgosInstaller(polyglotRoot=self.root / "Polyglot")
		self.useSecureScreen()
		with self.assertRaises(SecureScreenError):
			installer.ensurePackagesInstalled([], Mock())
		self.assertFalse(installer.packagesDir.exists())

	def test_runtimeInstallRefusesOnASecureScreen(self) -> None:
		installer = ArgosInstaller(polyglotRoot=self.root / "Polyglot")
		self.useSecureScreen()
		with self.assertRaises(SecureScreenError):
			installer.runtime.install(Mock())
		self.assertFalse(installer.runtime.libDir.exists())


class ChromeAiInstallTestCase(SecureScreenTestCase):
	"""The ChromeAI packages Polyglot installs itself are refused the same way."""

	def test_packageInstallRefusesOnASecureScreen(self) -> None:
		installer = ModelInstaller(polyglotRoot=self.root / "Polyglot")
		self.useSecureScreen()
		with self.assertRaises(SecureScreenError):
			installer.ensurePackagesInstalled(Mock(), [], Mock())


class ServiceTestCase(SecureScreenTestCase):
	"""A translation asking for a missing model must not put a download prompt on a secure screen."""

	def test_argosRefusesBeforeAskingToDownload(self) -> None:
		service = ArgosService()
		service.installer = Mock()
		self.useSecureScreen()
		with self.assertRaises(SecureScreenError):
			_unused = service.ensureModelsForPairInteractive("en", "fr")
		service.installer.getInstalledByKey.assert_not_called()

	def test_chromeAiLeavesTheDownloadToChrome(self) -> None:
		service = ModelManagerService()
		service.installer = Mock()
		self.useSecureScreen()
		self.assertTrue(service.ensureModelForPairInteractive("en", "fr"))
		service.installer.isPackageInstalled.assert_not_called()


if __name__ == "__main__":
	unittest.main()
