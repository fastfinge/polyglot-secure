### Polyglot-secure 0.0.1

This is the first release of Polyglot-secure, a fork of Polyglot. It stores every API key, token, and
password in the Windows Credential Locker instead of `nvda.ini`, and it ships no shared credentials and no
routes through infrastructure the fork has no right to use.

- Removed the shared API key that upstream shipped for `Google Translate (Polyglot)`, along with that
  engine: it existed only to reach an NVDACN-hosted mirror with that key. `Google Translate (key-free)` is
  unaffected and still offers its optional mirror toggle.
- Removed the engines that authenticate against NVDACN: `Tencent Translate (Polyglot)`,
  `Volcengine (Polyglot)`, and `VIVO Translate`.
- The ChromeAI model manager no longer ships or defaults to the NVDACN-hosted model catalog. Chrome
  downloads its own models, as it always could; to pre-install models, supply your own catalog URL in the
  model manager's advanced panel or in the `POLYGLOT_MODEL_CATALOG_URL` environment variable.
- `Ollama 1` and `Ollama 2` now default to `http://localhost:11434/api/generate` rather than a shared
  third-party Ollama server. Existing saved URLs are untouched.
- Added the `Argos Translate (Offline)` engine, which translates inside NVDA with models you download through the new `Polyglot Argos model manager` in NVDA's Tools menu. Nothing is sent to a translation service. The manager installs, updates, and removes one model per language direction, and Polyglot offers to download a missing model the first time you translate a direction. Directions with no direct model are translated through English. The engine needs the 64-bit NVDA of 2026.1 or later; on earlier releases it reports itself as unavailable.
- Added the `LibreTranslate` engine, which translates through a LibreTranslate server you name. It runs the same models as the offline Argos engine, but on the server rather than inside NVDA, so it suits a computer too slow to translate locally, works on 32-bit NVDA where the Argos engine is unavailable, and uses a server you already have. The server address and an optional API key are configured in the settings panel, and the address defaults to `http://localhost:5000`, a server on this computer, so nothing is sent anywhere until you change it.
- Added the `Lara Translate` engine, which translates through Lara, the context-aware translation service from Translated. It is a paid service, free for the first 10,000 characters a month, and it needs an access key ID and access key secret from your Lara account. `Auto-detect` is available and Lara reports back the language it detected. The access key secret is never sent: Lara has it sign a statement of what is being asked for, answers with a short-lived token, and Polyglot reuses that token until it is nearly finished with, so a translation normally costs one request. Polyglot also asks Lara not to keep the text it is sent. Lara publishes SDKs rather than an API, so Polyglot speaks what those SDKs speak, read from Translated's own MIT-licensed Python SDK.
- Added the `Naver Papago (key-free)` engine, which translates through the Papago endpoint behind Naver's search-bar translator. It needs no account and no API key, and it is the best of the key-free engines for Korean in either direction. `Auto-detect` is available and Naver reports back the language it detected. Naver's endpoint answers only requests carrying a short-lived key that its search page hands out, so Polyglot fetches that key, reuses it while it lasts, and fetches another when Naver stops accepting it.
- The Argos models that are tokenized with BPE rather than SentencePiece now install and translate. Fifteen of the directions the package index offers are built this way, Spanish to English among them, and each of them used to be rejected as "does not hold a model Polyglot can use" after its full download. They are now tokenized the way the models behind them were trained, and the 1.5 MB that needs is downloaded only when you install one of those models.
- API keys, tokens, and passwords now follow NVDA's configuration profile rules: each profile can hold its own key, a profile without one uses the key from the profile below it, and the profile activated last wins. Keys are saved to the profile NVDA is editing, and clearing a field returns that profile to the inherited key.
- Renaming a configuration profile now moves its stored keys with it, and deleting a profile removes them.
- Upgrading from Polyglot 1.2.0 or earlier now migrates the keys saved in every configuration profile, not only in the profiles that happen to be active.
- Uninstalling Polyglot now removes its settings from every NVDA configuration profile, every API key, token, and password it stored in the Windows Credential Locker, and its translation cache. Updating the add-on keeps all three.
- The translation cache is now written a few seconds after it changes rather than on every translation. With auto-translation on, Polyglot used to rewrite the whole cache file for every phrase NVDA spoke; it now gathers those changes and writes them once, and writes whatever is still pending when NVDA exits.
- The translation cache now discards the entries you have used least recently rather than the ones stored longest ago, so a phrase you keep meeting stays cached.
- The translation cache is now replaced in a single step and is safe to use from several translations at once, so an interrupted write or two results arriving together can no longer damage it.
- The offline model downloaders no longer run on secure screens. NVDA is the system account on the sign-in screen, the lock screen, and UAC prompts, so anything downloaded there is written into that account's profile, out of reach of the models you installed and of the model managers that could remove them. Argos now says it cannot translate on those screens instead of offering a download, and ChromeAI leaves any model download to Chrome, as it does when you decline Polyglot's own installer.

### 1.2.1

- Improved the Simplified Chinese and Ukrainian localizations and aligned the English and Simplified Chinese documentation.
- Removed unused internal code and obsolete comments.

### 1.2.0

- Added the key-free `DeepL Web` engine with automatic source detection, regional language options, and support for requests up to 1,500 characters.
- Migrated key-free Microsoft Translator to the current Edge `translatetext` endpoint and removed the retired authentication-token flow.
- Refreshed OpenRouter presets with current translation-specialised Tencent and Gemini Flash Lite models, automatic fallback for retired presets, and prompt options matched to model capabilities.
- Reused HTTP connections across translation requests to reduce latency for repeated translations.
- Removed the unavailable Lingva Translate engine.
- Fixed long labels overflowing the Chrome AI and Common Settings panels.

### 1.1.1

- Fixed repeated current-character review failing after version 1.1.0 by preserving NVDA's
  `speech.spellTextInfo` keyword-argument contract.

### 1.1.0

- Relicensed Polyglot and its first-party dictionary resources under GPL-3.0-or-later, with cary-rowen
  copyright attribution and preserved third-party MIT and Apache-2.0 notices.
- Standardized copyright headers, NVDA naming, and docstrings, and removed sensitive content from diagnostic
  logs.
- Applied repository-wide Ruff formatting and excluded vendored dependencies and template build files from
  first-party linting.

### 1.0.0

- Added offline English-to-Chinese definitions to NVDA's repeated current-word review command in Chinese,
  including conservative lookup for common spelling and inflection variants, candidate announcements for
  ambiguous words, and clear feedback for possible abbreviations and words absent from the local dictionary.
- Manual selection, clipboard, and last-spoken translation now use matching local word definitions for
  supported English-Chinese requests. Translation-command and text-review lookup can be controlled separately
  from Common Settings.

### 0.9.7

- Improved smart speech filtering to better preserve user content while avoiding auto-translation of NVDA speech metadata.
- Simplified internal code by removing unused abstractions and redundant wrappers.
- Added Vietnamese localization.

### 0.9.5

- Improved ChromeAI model checks for faster translation responses.
- Improved ChromeAI cold-start performance.
- Hardened ChromeAI's managed Chrome handling for better stability and safety.
