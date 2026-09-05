# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Tools menu integration for the native model manager dialog."""

from __future__ import annotations

from typing import Any

import addonHandler
import gui
import wx

from ..common.secureScreen import isSecureScreen, secureScreenDownloadMessage
from .dialog import ModelManagerDialog

addonHandler.initTranslation()


_dialog: ModelManagerDialog | None = None


def openModelManagerDialog() -> None:
	"""Open the model manager dialog or focus the existing instance."""
	global _dialog
	if isSecureScreen():
		# The menu item is not there on a secure screen, so this is only reached by another
		# caller; the dialog installs models, which must not happen as the system account.
		gui.messageBox(
			secureScreenDownloadMessage(),
			_("Polyglot ChromeAI Model Manager"),
			wx.OK | wx.ICON_INFORMATION,
		)
		return
	if _dialog is not None:
		try:
			if _dialog.IsShown():
				_dialog.Raise()
				_dialog.SetFocus()
				return
		except RuntimeError:
			_dialog = None
	gui.mainFrame.prePopup()
	try:
		_dialog = ModelManagerDialog(gui.mainFrame)
		_dialog.Show()
	finally:
		gui.mainFrame.postPopup()


def clearDialogReference(dialog: ModelManagerDialog) -> None:
	"""Clear the stored dialog reference when a dialog is destroyed."""
	global _dialog
	if _dialog is dialog:
		_dialog = None


def closeModelManagerDialog() -> None:
	"""Close the model manager dialog during add-on shutdown."""
	global _dialog
	if _dialog is None:
		return
	try:
		_dialog.Destroy()
	except RuntimeError:
		pass
	finally:
		_dialog = None


def bindToolsMenu(handler: Any) -> wx.MenuItem | None:
	"""Create the Tools menu item for opening the model manager.

	:return: The new menu item, or None on a secure screen, where models cannot be installed.
	"""
	if isSecureScreen():
		return None
	item = gui.mainFrame.sysTrayIcon.toolsMenu.Append(
		wx.ID_ANY,
		_("Polyglot ChromeAI model manager"),
		_("Manage Polyglot ChromeAI offline translation models"),
	)
	gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, handler.onOpenModelManager, item)
	return item


def unbindToolsMenu(item: wx.MenuItem | None) -> None:
	"""Remove the Tools menu item if it was added."""
	if item is None:
		return
	try:
		gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, source=item)
	except RuntimeError:
		pass
	try:
		gui.mainFrame.sysTrayIcon.toolsMenu.Remove(item.Id)
	except RuntimeError:
		pass
