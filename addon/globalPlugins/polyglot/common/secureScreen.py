# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Whether NVDA is on a secure screen, and what Polyglot must not do while it is.

A secure screen is one of the desktops Windows keeps apart from the signed-in session: the sign-in
screen, the lock screen, and the UAC prompt. NVDA runs there as the system account, so anything
downloaded there is written into the system account's profile rather than the user's: the user
cannot see it, cannot remove it through Polyglot's model managers, and cannot use it once signed
in. The offline model downloaders are therefore refused on a secure screen instead of run.
"""

from __future__ import annotations

import addonHandler
import globalVars

addonHandler.initTranslation()


def isSecureScreen() -> bool:
	"""Return whether NVDA is running on a secure screen."""
	return bool(getattr(globalVars.appArgs, "secure", False))


def secureScreenDownloadMessage() -> str:
	"""Return the reason a model download was refused, in the user's language."""
	return _(
		"Polyglot cannot download offline translation models on a secure screen, such as the "
		"sign-in screen or a UAC prompt. Use an engine that does not need downloaded models "
		"until you are back on your own desktop.",
	)


class SecureScreenError(RuntimeError):
	"""Raised when something that downloads or installs a model is reached on a secure screen."""

	def __init__(self, message: str | None = None) -> None:
		"""Initialize the error with a user-facing reason."""
		super().__init__(message or secureScreenDownloadMessage())
