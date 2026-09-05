# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Stand-ins for the NVDA modules Polyglot imports, so its code can be checked outside NVDA.

Only the behaviour Polyglot depends on is reproduced, and the configuration manager stub follows
NVDA's own rules: ``profiles`` is the active stack with the normal configuration first, and the
profile that was activated last is the one a changed setting is written to.
"""

import builtins
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock


class FakeProfile:
	"""One configuration profile, named as NVDA names it: None for the normal configuration."""

	def __init__(self, name: str | None, values: dict[str, Any] | None = None) -> None:
		self.name = name
		self.values: dict[str, Any] = values if values is not None else {}

	def get(self, key: str, default: Any = None) -> Any:
		return self.values.get(key, default)

	def pop(self, key: str, default: Any = None) -> Any:
		return self.values.pop(key, default)


class FakeConfigManager:
	"""The parts of NVDA's configuration manager that Polyglot's profile handling relies on."""

	def __init__(self) -> None:
		self.profiles: list[FakeProfile] = [FakeProfile(None)]
		self.savedProfiles: dict[str, FakeProfile] = {}
		self._dirtyProfiles: set[str] = set()
		#: Renames and deletions this stub carried out, so hooks can be checked against them.
		self.renamed: list[tuple[str, str]] = []
		self.deleted: list[str] = []
		#: How many times the configuration was written back to disk.
		self.saveCount = 0

	def save(self) -> None:
		self.saveCount += 1

	def addProfile(self, name: str, values: dict[str, Any] | None = None) -> FakeProfile:
		"""Save a profile without activating it."""
		profile = FakeProfile(name, values)
		self.savedProfiles[name] = profile
		return profile

	def activateProfile(self, name: str, values: dict[str, Any] | None = None) -> FakeProfile:
		"""Save a profile if needed and push it onto the active stack."""
		profile = self.savedProfiles.get(name) or self.addProfile(name, values)
		self.profiles.append(profile)
		return profile

	def listProfiles(self) -> list[str]:
		return list(self.savedProfiles)

	def getProfile(self, name: str) -> FakeProfile:
		return self.savedProfiles[name]

	def renameProfile(self, oldName: str, newName: str) -> None:
		profile = self.savedProfiles.pop(oldName)
		profile.name = newName
		self.savedProfiles[newName] = profile
		self.renamed.append((oldName, newName))

	def deleteProfile(self, name: str) -> None:
		del self.savedProfiles[name]
		self.deleted.append(name)


class FakeAction:
	"""The part of NVDA's extension point Action that Polyglot uses."""

	def __init__(self) -> None:
		self._handlers: list[Any] = []

	def register(self, handler: Any) -> None:
		self._handlers.append(handler)

	def unregister(self, handler: Any) -> None:
		if handler in self._handlers:
			self._handlers.remove(handler)

	def notify(self, **kwargs: Any) -> None:
		for handler in list(self._handlers):
			handler(**kwargs)


def installNvdaStubs(projectRoot: Path) -> ModuleType:
	"""Register the stand-in NVDA modules and make the add-on importable.

	Another check may have installed some of them already, so whichever stub the add-on imports is
	shared rather than replaced.

	:return: The stand-in ``config`` module, whose ``conf`` can be replaced per check.
	"""
	addonHandler = ModuleType("addonHandler")
	setattr(addonHandler, "initTranslation", Mock())
	_unused = sys.modules.setdefault("addonHandler", addonHandler)
	logHandler = ModuleType("logHandler")
	setattr(logHandler, "log", Mock())
	_unused = sys.modules.setdefault("logHandler", logHandler)
	extensionPoints = ModuleType("extensionPoints")
	setattr(extensionPoints, "Action", FakeAction)
	_unused = sys.modules.setdefault("extensionPoints", extensionPoints)
	config = ModuleType("config")
	setattr(config, "conf", FakeConfigManager())
	_unused = sys.modules.setdefault("config", config)
	globalVars = ModuleType("globalVars")
	appArgs = Mock()
	appArgs.configPath = str(projectRoot)
	appArgs.secure = False
	setattr(globalVars, "appArgs", appArgs)
	_unused = sys.modules.setdefault("globalVars", globalVars)
	nvdaState = ModuleType("NVDAState")
	writePaths = Mock()
	writePaths.addonsDir = str(projectRoot / "addons")
	setattr(nvdaState, "WritePaths", writePaths)
	_unused = sys.modules.setdefault("NVDAState", nvdaState)
	polyglotPackage = ModuleType("polyglot")
	setattr(polyglotPackage, "__path__", [str(projectRoot / "addon" / "globalPlugins" / "polyglot")])
	_unused = sys.modules.setdefault("polyglot", polyglotPackage)
	if not hasattr(builtins, "_"):
		# NVDA's addonHandler.initTranslation installs the translation lookup as a builtin.
		setattr(builtins, "_", lambda message: message)
	return sys.modules["config"]


def installGuiStubs() -> None:
	"""Register stand-ins for the NVDA and wxPython modules the user-facing services import.

	Only enough of each is provided for the modules to import: a check that reaches the real
	dialogs would be driving wxPython, which cannot run here. Whichever stub is already
	registered is kept, so this can be called alongside the other stub installation.
	"""
	for name in ("wx", "queueHandler", "nvwave", "tones", "ui"):
		_unused = sys.modules.setdefault(name, ModuleType(name))
	gui = sys.modules.setdefault("gui", ModuleType("gui"))
	guiMessage = sys.modules.setdefault("gui.message", ModuleType("gui.message"))
	guiHelper = sys.modules.setdefault("gui.guiHelper", ModuleType("gui.guiHelper"))
	setattr(gui, "message", guiMessage)
	setattr(gui, "guiHelper", guiHelper)
	setattr(gui, "mainFrame", Mock())
	setattr(gui, "messageBox", Mock())
	setattr(guiMessage, "MessageDialog", Mock())
	setattr(guiMessage, "ReturnCode", Mock())
	setattr(guiMessage, "DefaultButtonSet", Mock())
	setattr(guiHelper, "wxCallOnMain", Mock())
	wx = sys.modules["wx"]
	for name, value in (("OK", 4), ("ICON_ERROR", 512), ("ICON_INFORMATION", 2048)):
		setattr(wx, name, value)
	setattr(wx, "CallAfter", Mock())
	queueHandler = sys.modules["queueHandler"]
	setattr(queueHandler, "queueFunction", Mock())
	setattr(queueHandler, "eventQueue", Mock())
