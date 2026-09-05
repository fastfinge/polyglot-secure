# Polyglot-secure for NVDA

## About This Fork

This fork exists due to deep and insurmountable disagreements between myself and the original addon developer regarding how API Keys must be handled. This fork stores API Keys in the Windows Credential Manager. The original addon does not. As well, this addon removes the shared API keys shipped with the original addon. First, they belong to cary-rowen, and I have no right to use or distribute them. Second, when performing translations through a shared API key, in most cases, the owner of the key can see all text translated with the key.

I do not have the right to use or access the infrastructure of NVDACN, so the engines that route through it are gone as well: `Tencent Translate (Polyglot)`, `Volcengine (Polyglot)`, `VIVO Translate`, and `Google Translate (Polyglot)`. Every other engine is unchanged, so the add-ons are mostly drop-in replacements for one another, and I intend to keep Polyglot-secure mostly in sync with upstream.

If none of the above means anything to you: Polyglot is more convenient, Polyglot-secure is more secure. Take your pick based on that.

Inside NVDA the add-on still calls itself Polyglot: the settings panel, the Tools-menu entries, and the
names it stores credentials under are unchanged. That is deliberate, so that switching from Polyglot brings
your settings and your stored keys with you. The other side of it is that the two add-ons share one set of
settings and one set of stored keys, so do not run both at once: removing either one deletes the settings
and keys that both were using. Install one, or the other.

Polyglot-secure is a fast, extensible translation add-on for NVDA with support for multiple engines. It can translate selected text, clipboard text, and the last text spoken by NVDA, and can also automatically translate NVDA's speech output.

The add-on is built around a dynamic engine architecture. Translation engines declare their own capabilities and configuration schema, and the settings UI is generated from that schema at runtime. That keeps the core plugin small while making it straightforward to add new services.

## What It Does

- Translates selected text, clipboard text, and the last spoken NVDA utterance.
- Provides a translation command layer on `NVDA+Alt+Z`; press `H` in the layer to show command layer help.
- Supports live auto-translation of spoken NVDA content.
- Includes a smart speech filter to avoid translating roles, states, and formatting noise.
- Persists a translation cache to reduce repeated requests.
- Can copy manual translation results to the clipboard automatically.
- Lets you switch engines and languages without leaving the keyboard.
- Exposes a dedicated interactive translation dialog for longer or iterative translation work.
- Provides local English word definitions when NVDA is running in Chinese.

## Installation

The preferred installation path is the NVDA Add-on Store. You can also install manually:

1. Download the latest `.nvda-addon` package from the [Releases page](https://github.com/fastfinge/polyglot-secure/releases).
2. Open the downloaded file.
3. Confirm installation in NVDA.
4. Restart NVDA when prompted.

### Uninstalling

Removing Polyglot-secure removes everything it keeps outside its own folder: its settings in every NVDA configuration profile, and every API key, token, and password it stored in the Windows Credential Locker. The clean-up runs the next time NVDA starts, when NVDA finishes removing the add-on.

Updating Polyglot-secure keeps your settings and your stored keys; only a removal deletes them.

## Quick Start

1. Open `NVDA menu -> Preferences -> Settings -> Polyglot`.
2. Choose a translation engine and make sure it is enabled.
3. Configure any required credentials for that engine.
4. Set source and target languages.
5. Optionally enable clipboard copy and the smart speech filter.
6. Press `NVDA+Alt+Z`, then use one of the command-layer keys below. Press `H` in the layer to show command layer help.

## Command Layer

Press `NVDA+Alt+Z` to enter the command layer. A short beep confirms that the layer is active. Press `H` in the layer to show command layer help. Most commands execute once and exit the layer. Language and engine switching commands stay inside the layer so you can continue cycling. Engine switching cycles through enabled engines only.

| Key | Action |
| --- | --- |
| `T` | Translate the current selection. |
| `Shift+T` | Translate the current selection in reverse. |
| `B` | Translate clipboard text. |
| `Shift+B` | Translate clipboard text in reverse. |
| `L` | Translate the last text spoken by NVDA. |
| `Shift+L` | Translate the last text spoken by NVDA in reverse. |
| `S` | Next source language. |
| `Shift+S` | Previous source language. |
| `G` | Next target language. |
| `Shift+G` | Previous target language. |
| `E` | Next enabled engine. |
| `Shift+E` | Previous enabled engine. |
| `W` | Swap source and target languages. |
| `A` | Announce the current engine and language pair. |
| `C` | Copy the last translation result. |
| `V` | Toggle auto-translation. |
| `I` | Open the interactive translation dialog. |
| `O` | Open Polyglot settings. |
| `X` | Clear the translation cache. |
| `H` | Show command-layer help. |

## Interactive Translation Dialog

The interactive dialog is designed for longer text and iterative translation work.

- Open it from the command layer with `I`.
- Select an enabled engine, source language, and target language without leaving the dialog.
- Disabled engines remain configurable in settings, but are not listed in this dialog.
- For LLM-style engines, adjust model and prompt template directly in the dialog.
- Press `Ctrl+Enter` in the source text box to translate.
- Copy the result or clear both panes without reopening the window.

## Local English Word Definitions for Chinese NVDA

When NVDA's interface language is Chinese, including Simplified and Traditional Chinese, Polyglot adds an
offline English-to-Chinese dictionary to the command that reports the word at the review cursor:

1. With the desktop keyboard layout, press `numpad 5` once to read the word at the review cursor.
2. Press it twice to hear the word spelled out.
3. Press it three times to hear the Chinese definition when the complete word is found locally.

Add-ons that call NVDA's `speech.spellTextInfo` receive the same behavior. If a line contains only one
English word, pressing the current-line command three times also reports its definition. Lookup strips one
layer of common leading or trailing sentence punctuation and recognizes common inflections, including
plural, tense, participial, comparative, and superlative forms. Exact entries take priority. When a
spelling can refer to several entries, Polyglot announces up to three candidates with their first senses.
If a two- or three-character uppercase word only matches a lowercase entry, Polyglot reports the possible
lowercase meaning and warns that it may instead be an abbreviation. Words that look valid but are not included are
reported as missing. Single characters, multiword lines, and unsupported text keep NVDA's original character
descriptions. Lookup is fully local and never sends the word to a translation service.

The Translate Selection, Translate Clipboard, and Translate Last Spoken commands also use the local dictionary
for complete English words in English/auto-detect → Simplified or Traditional Chinese requests, and for
English-word input in Chinese → English requests. Other content continues through the selected translation engine.

Translation commands and text review have separate local-dictionary options. Both are enabled by default;
disabling either restores that command's original behavior.

Current dictionary size:

- 122,370 English entries, including about 118,460 complete headwords that can be queried directly.
- 34,859 validated inflected forms.
- About 154,800 complete word forms when case and common spelling variants are included.
- The bundled dictionary is about 6.8 MB and requires no separate download.

## Settings Guide

### Common Settings

- `Copy manual translation results to clipboard`: Copies manual translation output after a successful request.
- `Prefer local English-Chinese dictionary for selected text, clipboard, and last spoken text`: Controls local
  lookup for those three translation commands.
- `Use the local English-Chinese dictionary in text review`: Controls local definitions for NVDA text review.
- `Enable smart speech filter (skips roles, states, location, and formatting information)`: When translating spoken NVDA output, skips non-content speech such as roles, states, location, and formatting details where possible.
- `Clear Cache`: Clears the persistent translation cache and shows the current item count in the button label.
- `Clear Stored API Keys`: Deletes every API key, token, and password Polyglot has stored for your Windows account, in every configuration profile, and shows how many are stored in the button label.

### API Key Storage

Polyglot-secure ships no credentials of its own. Every engine that needs an API key, token, or password
needs one of yours, so nothing you translate passes through a key that someone else can read the traffic of.

API keys, tokens, and passwords are never written to `nvda.ini`. They are kept in the Windows Credential Locker, where Windows encrypts them for the signed-in account. This means they do not appear in NVDA's log at debug level, are not copied into portable copies of NVDA, and are not readable by other add-ons through NVDA's configuration.

A credential can also come from an environment variable, which is useful for shared or managed machines where nothing should be stored at all. The variable name is `POLYGLOT_` followed by the engine ID and the setting name in upper case, for example `POLYGLOT_DEEPL_APIKEY`, `POLYGLOT_OPENROUTER_APIKEY`, or `POLYGLOT_TENCENT_SECRETKEY`. A variable describes the whole machine, so it applies to every configuration profile: when one is set, it takes precedence over anything stored, and the matching settings field is disabled and labelled with the variable name.

### API Keys and Configuration Profiles

Every API key belongs to one NVDA configuration profile, and Polyglot applies NVDA's own profile rules to keys even though they are not stored in `nvda.ini`:

- A key you enter is saved to the profile NVDA is currently writing to, which is the profile named in the title of NVDA's settings dialog.
- A profile that has no key of its own uses the key from the profile below it, ending at the normal configuration. So a key entered in the normal configuration is used everywhere until a profile is given its own.
- When several profiles are active at once, the most recently activated one supplies the key, exactly as it supplies every other setting.

While a configuration profile other than the normal configuration is being edited, an API key field shows only that profile's own key. Its label says `(set in this profile)` when the profile has a key of its own, and `(inherited from the normal configuration)` or `(inherited from the <profile> profile)` when the field is empty because the key comes from elsewhere. Clearing the field removes the profile's own key so that it inherits again; it does not blank the inherited key.

Renaming a configuration profile moves its keys with it, and deleting a profile deletes the keys stored for it.

Each credential is stored under a target name of the form `NVDA/Polyglot/<engine>/<setting>` for the normal configuration, for example `NVDA/Polyglot/deepl/apiKey`, and `NVDA/Polyglot/profiles:<profile>/<engine>/<setting>` for a named profile, for example `NVDA/Polyglot/profiles:Reading email/deepl/apiKey`. You can review or delete them from Windows itself: `Control Panel -> User Accounts -> Credential Manager -> Windows Credentials`, or by pressing `Clear Stored API Keys` in Polyglot's settings.

Upgrading from Polyglot 1.2.0 or earlier moves any keys already saved in `nvda.ini` into the Credential Locker and removes the plain-text copies the first time the add-on starts. Every saved profile is migrated, not only the active ones, so a key you set in a profile keeps working in that profile. Keys stored by Polyglot 1.2.1 belong to the normal configuration, so every profile inherits them until you give it a key of its own. If secure storage is unavailable, the plain-text copy is still removed and an error is written to the log; re-enter the key in Polyglot's settings.

### The Translation Cache

Polyglot remembers the translations it has already made, so repeating a request does not cost another one. The cache is kept in `translation_cache.json` in your NVDA configuration directory and holds up to 10,000 entries, the least recently used being dropped to make room. Entries are stored under a hash of the language pair and the source text, so the file records the translated text but not a readable copy of the original.

Be aware of what this means: with auto-translation on, the cache accumulates translations of much of what NVDA speaks, and it is a plain file that anything running under your Windows account can read. It is not encrypted. Encrypting it would not change much, because the key would have to be available to Polyglot and therefore to anything else running in NVDA. If that matters to you, press `Clear Cache` in Polyglot's settings, which empties the file straight away.

Uninstalling Polyglot deletes the cache. Updating it keeps the cache, so you do not start from nothing after every update.

### Shared Engine Settings

Most engines inherit a common set of settings:

- `Enable this engine`: controls whether the engine is available for translation requests, command-layer engine switching, and the interactive dialog. Disabled engines remain visible and configurable in settings.
- `Source language` and `Target language`
- `Proxy mode`: use system proxy settings or disable proxy usage
- `Request timeout`

If an engine reports detected source language, Polyglot also exposes:

- `Auto-swap if detected source matches target (source must be 'Auto-detect')`: uses the configured swap language when auto-detection identifies the current target language
- `Swap to language`: the alternative target used during auto-swap

### Auto-Translation Behavior

- Auto-translation acts on spoken NVDA content captured by the speech pipeline.
- The add-on suppresses its own spoken messages to avoid translation loops.
- If auto-translation fails three times in a row, it is turned off automatically.
- The smart speech filter mainly affects spoken-content translation, not standard manual text translation.

### LLM and Polyglot-Specific Options

Some engines expose additional controls:

- `Ollama 1` and `Ollama 2` provide two separate saved profiles for different local or remote Ollama setups.
  Both default to `http://localhost:11434/api/generate`, so point them at your own server if it runs elsewhere.
- `OpenRouter` exposes API URL, API key, model preset, custom model name, prompt template, and custom prompts.
  The default preset is a translation-specialized model, which responds faster and costs less than a
  general-purpose model. Such models reply with the translated text only, so only the prompt templates they
  can follow are offered; pick a general-purpose preset if you need the structured JSON template and its
  source-language detection.
- `Ollama` engines expose API URL, model name, optional API key, prompt template, and custom prompts.
- `LibreTranslate` exposes the address of the server to use and an optional API key. It defaults to
  `http://localhost:5000`, a server on this computer, so point it at your own server or a hosted one.
- `Lara Translate` exposes the access key ID and access key secret of a Lara account. Both halves are
  needed; the secret is stored as a credential and never leaves this computer.
- `Google Translate (key-free)` offers an optional mirror-server toggle. The mirror is run by NVDACN and
  is off unless you turn it on; it needs no credentials, and with it off the engine talks to Google directly.

## Chrome AI Offline Translation

Polyglot can use Chrome's built-in Translator API for offline translation. Translation is handled by an isolated local Chrome instance, so the text is not sent to a third-party translation service.

### Requirements

- Google Chrome must be installed.
- Chrome 138 or later is recommended.
- The first use of a language direction requires the local translation model to be prepared. Chrome downloads it.

### How To Use

Select `Chrome AI (Offline)` in Polyglot settings, then choose the source and target languages. Chrome AI requires an explicit source language; `Auto-detect` is not available for this engine, so Polyglot can check the required model before starting Chrome.

On first use, Chrome downloads the model for the language direction you asked for, and translation continues once it is ready.

### Network And Models

Translation runs locally. Chrome downloads the models it needs.

Upstream Polyglot also shipped a catalog of pre-built models hosted by NVDACN, so its model manager could
install them directly when Chrome's own download service was slow or blocked. Polyglot-secure ships no such
catalog, because that infrastructure is not mine to use. `Polyglot ChromeAI model manager` in NVDA's Tools
menu therefore lists nothing until you give it a catalog of your own: open `Advanced`, enter a catalog URL,
and press `Load catalog`. The URL can also be set for the whole machine with the `POLYGLOT_MODEL_CATALOG_URL`
environment variable. Without one, Chrome handles model downloads and the model manager has nothing to do.

### Privacy And Data

Polyglot uses a separate Chrome data directory for Chrome AI, so it does not affect your regular Chrome profile. Models, cache data, and runtime data are kept to avoid repeated downloads.

The default location is:

```text
%LOCALAPPDATA%\Polyglot\ChromeAI
```

If the `LOCALAPPDATA` environment variable is not available, Polyglot falls back to the `polyglot_chrome_ai` directory under the NVDA configuration directory.

When NVDA exits, Polyglot closes the Chrome instance it started.

### Limitations

- Supported languages and language pairs are determined by Chrome's Translator API.
- Chrome AI requires an explicit source language; `Auto-detect` is not available for this engine.
- First use requires Chrome to download the model, which may be affected by network conditions.
- If the Translator API is unavailable, update Chrome or make sure the related Chrome feature is enabled.
- On a secure screen, such as the sign-in screen, the lock screen, or a UAC prompt, Polyglot's model manager installs nothing: NVDA runs there as the system account, so a downloaded model would land in that account's profile rather than yours. Model downloads on those screens are left to Chrome, as they are when you decline Polyglot's own installer.

## Argos Translate Offline Translation

Polyglot can translate with [Argos Translate](https://www.argosopentech.com/) models. Translation runs inside NVDA on your own machine, so nothing is sent to a translation service; the only network use is downloading the runtime and the language models themselves.

### Requirements

- NVDA 2026.1 or later. Earlier releases of NVDA are 32-bit, and the translation libraries Argos needs are only published for 64-bit Python, so the engine reports itself as unavailable there.
- A one-time runtime download of about 20 MB (CTranslate2 and SentencePiece). Polyglot installs it the first time you install a model, and verifies the download against a size and SHA-256 hash pinned in the add-on.
- A further 1.5 MB for the fifteen or so directions whose models are tokenized with BPE rather than SentencePiece, Spanish to English among them. Polyglot fetches those extras only when you install such a model, and verifies them the same way.
- One model package per language direction, typically 80 to 190 MB.

### How To Use

Select `Argos Translate (Offline)` in Polyglot settings, then choose the source and target languages. Argos requires an explicit source language; `Auto-detect` is not available for this engine, so Polyglot can check the required models before translating.

Open `Polyglot Argos model manager` from NVDA's Tools menu to install models in advance. The list shows every language direction the package index offers, with its status, download size, and version. Check the directions you want, uncheck the ones you no longer need, and press `Apply changes`. `Update all` reinstalls the directions whose published version is newer than the installed one.

On first use, if the required model is not installed, Polyglot asks whether to download it, naming the packages and the total download size. Choose Yes to install them and continue the translation, or No to cancel it.

When no model translates a direction directly, Polyglot pivots through English: French to German uses the French-to-English and English-to-German models in turn. The prompt and the model manager account for both packages.

### Network And Models

Models are listed from the Argos package index at `https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json` and downloaded from the links that index publishes. The add-on ships a snapshot of the index, so the model manager and the settings language lists work before the index has ever been downloaded; press `Load package index` in the model manager's advanced panel to refresh it. The index URL can be changed in the same panel if you host your own mirror.

The runtime and its BPE extras are downloaded from PyPI. Every one of those downloads is checked against a size and SHA-256 hash pinned in the add-on, so an unexpected file is refused rather than installed.

### Privacy And Data

The runtime, the installed models, the downloaded index, and unfinished downloads are kept outside the add-on's own folder so they survive add-on updates.

The default location is:

```text
%LOCALAPPDATA%\Polyglot\Argos
```

If the `LOCALAPPDATA` environment variable is not available, Polyglot falls back to `AppData\Local` under your home directory.

Like the Chrome AI models, Argos models are not deleted when the add-on is uninstalled, because they are expensive to download again. To remove them, uncheck everything in the model manager and press `Apply changes` before uninstalling.

### Limitations

- Supported languages and language pairs are determined by the Argos package index.
- Argos requires an explicit source language; `Auto-detect` is not available for this engine.
- A loaded model keeps its files open. Press `Unload models` in the model manager before removing or updating a direction you have just used.
- The runtime libraries stay loaded until NVDA restarts, so removing the runtime itself only takes effect after a restart.
- Translation quality is below that of the online engines, and long passages take noticeably longer than a network round trip.
- Models cannot be downloaded or installed on a secure screen, such as the sign-in screen, the lock screen, or a UAC prompt: NVDA runs there as the system account, which reaches neither your models nor a profile you could remove them from. Argos reports that it cannot translate on those screens, so use an online engine there.

## LibreTranslate

[LibreTranslate](https://libretranslate.com/) is a free and open-source translation server that runs the
same Argos models as Polyglot's offline engine, but on a server rather than inside NVDA. It is worth
choosing when the Argos engine is not an option or not fast enough:

- The machine doing the translating is the server, so a computer too slow to translate locally is no
  longer the limit.
- It works on 32-bit NVDA, where the offline Argos engine reports itself as unavailable.
- If you already run a LibreTranslate server, or have access to one, Polyglot can simply use it.

### How To Use

Select `LibreTranslate` in Polyglot settings, then set:

- `Server address`: the address of the server, such as `http://localhost:5000` for one running on this
  computer, `https://libretranslate.example.org` for your own, or `https://libretranslate.com` for the
  project's hosted service. Either the server's own address or the full `/translate` endpoint is accepted.
- `API key (leave empty if the server does not require one)`: many self-hosted servers need no key. Hosted
  services, including `libretranslate.com`, do. The key is stored in the Windows Credential Locker like
  every other credential; see [API Key Storage](#api-key-storage).

`Auto-detect` is available as the source language, and the server reports back which language it detected.

### Network And Data

The address ships as `http://localhost:5000`, which is where a LibreTranslate server installed on this
computer listens. Nothing leaves the machine until you change it, and Polyglot never contacts a server you
have not named yourself.

Whatever you translate is sent to the server you configure. A server of your own, on your own machine or
network, keeps the text there. A hosted service is a third party, and what it does with the text is
governed by its own privacy policy.

### Limitations

- The language list offers every language LibreTranslate can be built with. A given server may have been
  built with fewer, and asking it for one it does not have is answered with an error naming what it does
  have.
- Text longer than 2,000 characters is sent in several requests, matching the character limit servers
  commonly set.
- Translation quality is that of the Argos models, which is below that of the commercial online engines.

## Naver Papago

[Naver](https://www.naver.com/) is Korea's largest search engine, and its search bar carries a translator
widget powered by Papago, Naver's own translation service. `Naver Papago (key-free)` talks to the endpoint
behind that widget, so it needs no account and no API key. It is the engine to reach for when Korean is one
end of the translation, in either direction.

### How To Use

Select `Naver Papago (key-free)` in Polyglot settings and choose the source and target languages. There is
nothing else to configure. `Auto-detect` is available as the source language, and Naver reports back which
language it detected, so the auto-swap setting works with this engine.

The languages offered are the ones the endpoint accepts: Korean, English, Japanese, Simplified and
Traditional Chinese, Vietnamese, Indonesian, Thai, German, Russian, Spanish, Italian, French, Portuguese,
Hindi, and Arabic.

### Network And Data

Whatever you translate is sent to Naver, and what Naver does with it is governed by its own privacy policy.

The endpoint will not answer without a short-lived key that Naver's search page hands to its translator
widget. Polyglot fetches that key from the search page, keeps it for as long as it lasts, and fetches
another when Naver stops accepting it, so a translation normally costs one request. No cookie is kept and
nothing identifies you beyond the request itself.

### Limitations

- This is the endpoint behind a Web page, not a documented API. Naver may change or withdraw it without
  notice, and it comes with no service guarantee. Naver sells the Papago API for work that needs one.
- Text longer than 5,000 characters is sent in several requests, which is where the endpoint stops
  answering. Requests are spaced out slightly, as Naver asks that the translator not be hammered.
- Errors come back in Korean and say little beyond that something went wrong. Polyglot passes on what
  Naver said rather than guessing at a cause.

## Lara Translate

[Lara](https://laratranslate.com/) is a translation service from Translated, the company behind MyMemory
and ModernMT. It is a translation-specialized model rather than a general-purpose one, so it answers about
as quickly as the other online engines while translating with the surrounding sentences in mind. It is a
paid service, with a free allowance of 10,000 characters a month.

### How To Use

Generate an access key in your Lara account, which gives you an access key ID and an access key secret.
Then select `Lara Translate` in Polyglot settings and set:

- `Access key ID`: the first half of the access key, which names it.
- `Access key secret`: the second half, which proves it is yours. It is stored in the Windows Credential
  Locker like every other credential; see [API Key Storage](#api-key-storage).

`Auto-detect` is available as the source language, and Lara reports back which language it detected, so
the auto-swap setting works with this engine.

### Network And Data

Whatever you translate is sent to Lara, and what Lara does with it is governed by Translated's privacy
policy. Polyglot asks Lara not to keep the text it is sent, which is what Translated's own SDKs call a
no-trace translation.

The access key secret itself is never sent. Lara authenticates a key by having it sign a statement of what
is being asked for, so the secret stays on this computer and only the signature travels. Lara answers that
with a token that lasts a short while, which Polyglot reuses until it is nearly finished with and then
replaces, so a translation normally costs one request.

### Limitations

- Lara publishes SDKs rather than an API, and says a REST API is available on request. Polyglot speaks
  what the SDKs speak, read from Translated's own MIT-licensed Python SDK. Translated may change it
  without notice, as it is not the interface they document.
- An active subscription is required beyond the free 10,000 characters a month.
- Text longer than 2,000 characters is sent in several requests. Lara documents no limit, so this is a
  cautious figure rather than a measured one; because Lara translates with the surrounding sentences in
  mind, longer requests would translate slightly better as well as cost fewer of them.
- Lara names a locale rather than a language. Polyglot's plain codes are sent as the widest-spoken locale
  of that language, so `English` reaches Lara as `en-US` and `Portuguese` as `pt-PT`; choose
  `English (British)` or `Portuguese (Brazilian)` where the difference matters.

## Engine Overview

The repository currently includes the following engines:

| Engine | Credentials | Notes |
| --- | --- | --- |
| `Argos Translate (Offline)` | None | Translates inside NVDA with downloaded Argos models; NVDA 2026.1 or later, explicit source language. |
| `Baidu Translate` | Baidu app ID and secret | Standard vendor API integration. |
| `Caiyun` | Caiyun token | Standard vendor API integration. |
| `Chrome AI (Offline)` | None | Uses Chrome's built-in Translator API with local models; select the source language explicitly. |
| `DeepL` | DeepL API key | Standard vendor API integration. |
| `DeepL Web (key-free)` | None | Uses DeepL's unofficial anonymous Web endpoint; limited to 1,500 characters per request. |
| `Google Translate (key-free)` | None | Talks to Google directly, with an optional toggle for an NVDACN-run mirror. |
| `Lara Translate` | Lara access key ID and secret | Context-aware paid service from Translated; free for 10,000 characters a month. |
| `LibreTranslate` | Server address, optional API key | Talks to a LibreTranslate server you name; defaults to one on this computer. |
| `Microsoft Translator (key-free)` | None | Uses the Edge `translatetext` endpoint. |
| `Naver Papago (key-free)` | None | Uses the endpoint behind Naver's search-bar translator; best of the key-free engines for Korean. |
| `Niutrans` | Niutrans API key | Standard vendor API integration. |
| `Ollama 1` | Ollama URL, model name, optional key | First saved Ollama profile. |
| `Ollama 2` | Ollama URL, model name, optional key | Second saved Ollama profile. |
| `OpenRouter` | OpenRouter API key | Supports model presets and editable prompt templates. |
| `Tencent Translate` | Tencent secret ID and secret key | Standard vendor API integration. |
| `Yandex Translate` | None | Public-style endpoint, no detected-language reporting. |

## Contributing

Contributions are welcome across code, documentation, localization, testing, and engine integrations.

- Issues: [GitHub Issues](https://github.com/fastfinge/polyglot-secure/issues)
- Releases: [GitHub Releases](https://github.com/fastfinge/polyglot-secure/releases)

When adding a new engine:

1. Create a module under `addon/globalPlugins/polyglot/services/engines/`.
2. Implement `TranslationEngine` or, for HTTP engines, extend `BaseHttpEngine`.
3. Return a config spec from `getConfigSpec()` if the engine needs settings.
4. Use supported control types from `views/factory.py`: `choice`, `text`, `password`, `checkbox`, and `spinctrl`.
5. Verify the engine appears correctly in the dynamic settings panel and, when enabled, command-layer switching and the interactive dialog.

## License

Copyright (C) 2025-2026 cary-rowen, and contributors to this fork.

Polyglot-secure is a fork of [Polyglot](https://github.com/cary-rowen/polyglot) by cary-rowen.

This project is licensed under the GNU General Public License version 3 or later
(`GPL-3.0-or-later`). See the repository's [COPYING.txt](https://github.com/fastfinge/polyglot-secure/blob/main/COPYING.txt).
