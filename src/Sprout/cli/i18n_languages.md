# CLI i18n Languages

The Sprout CLI switches its user-facing menus and status text at runtime. The
language state is stored in `~/.sprout/settings.json` under `language`, with
`locale` kept in sync for web-compatible values.

## Supported Languages

| Code | Name |
|---|---|
| `zh` | 中文 |
| `en` | English |
| `ja` | 日本語 |
| `ko` | 한국어 |
| `ru` | Русский |
| `es` | Español |
| `pt` | Português |
| `zh-Hant` | 繁體中文 |

## Switching

Inside `uv run sprout`:

```text
/language            open the language selector
/language ja         switch directly to Japanese
/language zh-Hant    switch to Traditional Chinese
```

The selector lists every supported language in its native name. Dynamic
strings that are not yet in the translation catalog fall back to English.

## Adding a Language

1. Add the code to `supported_languages()` in `Sprout/cli/i18n.py`.
2. Add aliases to `_ALIASES` and a native name to `_LANGUAGE_NAMES`.
3. Register translations with `add_translations()` for the static CLI strings.
4. Keep dynamic strings language-neutral or move them to a keyed catalog.
