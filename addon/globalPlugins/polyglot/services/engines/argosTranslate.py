# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Translate offline with Argos Translate models.

Argos models run entirely on this computer: nothing is sent anywhere, and no account or key is
needed. The models themselves are downloaded once, from Polyglot's Argos model manager or from the
prompt shown the first time a language direction is used.
"""

from typing import Any
from collections.abc import Callable

import addonHandler
from logHandler import log

from ...argosManager.catalog import normalizeLanguageCode
from ...argosManager.service import getArgosService
from ...common import languages
from ...common.exceptions import EngineError, SilentTranslationCancel
from ...common.secureScreen import SecureScreenError
from ..engine import ChunkedTranslationMixin

addonHandler.initTranslation()


class ArgosTranslateEngine(ChunkedTranslationMixin):
	"""Translate text offline with Argos Translate models installed by Polyglot."""

	id = "argos"
	name = _("Argos Translate (Offline)")

	def __init__(self) -> None:
		"""Initialize the engine from the Argos package index."""
		super().__init__()
		self._supportedLangs: dict[str, str] | None = None

	@property
	def autoDetectCode(self) -> str | None:
		return None

	@property
	def enabledConfigLabel(self) -> str:
		"""Return the Argos-specific label for the common enable checkbox."""
		return _("Enable Argos Translate offline engine (NVDA 2026.1 or later)")

	@property
	def defaultSourceLanguage(self) -> str:
		return "en"

	@property
	def defaultTargetLanguage(self) -> str:
		return "es"

	def getSupportedLanguages(self) -> dict[str, str]:
		"""Return every language the Argos package index can translate, with its display name.

		The index is read from disk only, so opening Polyglot's settings never waits for the
		network. The model manager saves a fresh copy whenever it downloads one.
		"""
		if self._supportedLangs is None:
			try:
				codes = getArgosService().getCatalogSnapshot().getLanguageCodes()
			except Exception:
				log.error("Argos: the package index could not be read.", exc_info=True)
				codes = ["en"]
			self._supportedLangs = languages.getLanguageDictForCodes(codes)
		return self._supportedLangs

	def getConfigSpec(self) -> list[dict[str, Any]]:
		allLangs = self.getSupportedLanguages()
		return [
			self.getEnabledConfigSpec(),
			{
				"id": "langFrom",
				"label": _("Source language:"),
				"type": "choice",
				"choices": allLangs.copy(),
				"default": self.defaultSourceLanguage,
			},
			{
				"id": "langTo",
				"label": _("Target language:"),
				"type": "choice",
				"choices": allLangs.copy(),
				"default": self.defaultTargetLanguage,
			},
			{
				"id": "threads",
				"label": _("Processor threads (0 uses a sensible number):"),
				"type": "spinctrl",
				"default": 0,
				"min": 0,
				"max": 16,
			},
		]

	def getUiStates(self, allConfigs: dict[str, Any]) -> dict[str, Any]:
		"""Keep the source and target language lists from offering the same language twice."""
		states: dict[str, Any] = {}
		allLangs = self.getSupportedLanguages()
		selectedFrom = allConfigs.get("langFrom", self.defaultSourceLanguage)
		selectedTo = allConfigs.get("langTo", self.defaultTargetLanguage)
		fromChoices = allLangs.copy()
		toChoices = allLangs.copy()
		if selectedTo:
			_unused = fromChoices.pop(selectedTo, None)
		if selectedFrom:
			_unused = toChoices.pop(selectedFrom, None)
		states["langFrom"] = {"choices": fromChoices}
		states["langTo"] = {"choices": toChoices}
		return states

	@property
	def maxRequestLength(self) -> int:
		"""Return the text size translated at once, so long passages report progress."""
		return 5000

	@property
	def requestDelayRange(self) -> tuple[float, float]:
		"""Return no delay between chunks: the model is local, and nothing is being rate limited."""
		return (0, 0)

	def translate(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
		isCancelled: Callable[[], bool] | None = None,
	) -> dict[str, Any]:
		"""Make sure the needed models are installed, then translate in bounded chunks."""
		if not self.isEnabled(config):
			log.debug("Argos: the engine is disabled, refusing the translation request.")
			raise EngineError(
				_(
					"The Argos Translate offline engine is disabled. "
					"Enable it in the Polyglot settings panel before using it.",
				),
			)
		if isCancelled and isCancelled():
			return {}
		if normalizeLanguageCode(langFrom) == normalizeLanguageCode(langTo):
			return {"translation": text}
		self._ensureModelsReady(langFrom, langTo)
		if isCancelled and isCancelled():
			return {}
		return super().translate(text, langFrom, langTo, config, isCancelled)

	def _ensureModelsReady(self, langFrom: str, langTo: str) -> None:
		"""Prompt for any model this direction needs and is missing.

		:raises EngineError: If the model check failed, or NVDA is on a secure screen, where models
			cannot be downloaded.
		:raises SilentTranslationCancel: If the user chose not to download it.
		"""
		service = getArgosService()
		try:
			shouldContinue = service.ensureModelsForPairInteractive(langFrom, langTo)
		except SecureScreenError as error:
			# Already a finished sentence for the user, so it is reported as it stands.
			raise EngineError(str(error)) from error
		except Exception as error:
			log.error("Argos: the model check failed.", exc_info=True)
			raise EngineError(_("Argos Translate error: ") + str(error)) from error
		if not shouldContinue:
			raise SilentTranslationCancel()

	def _translateChunk(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		"""Translate one chunk with the installed models."""
		try:
			threads = int(config.get("threads", 0) or 0)
		except (TypeError, ValueError):
			threads = 0
		service = getArgosService()
		try:
			translation = service.translator.translate(text, langFrom, langTo, threads)
		except RuntimeError as error:
			raise EngineError(str(error)) from error
		except Exception as error:
			log.error("Argos: translation failed.", exc_info=True)
			raise EngineError(_("Argos Translate error: ") + str(error)) from error
		return {"translation": translation}

	def areLanguagesEquivalent(self, detectedLanguage: str, targetLanguage: str) -> bool:
		"""Compare languages by the codes the Argos index uses, so regional forms match."""
		return normalizeLanguageCode(detectedLanguage) == normalizeLanguageCode(targetLanguage)
