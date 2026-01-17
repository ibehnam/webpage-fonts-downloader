# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python package that downloads and converts fonts from webpages. Installable via `uv tool install`.

## Development Commands

```bash
# Install in editable mode
uv tool install --editable .

# Run the installed command
webpage-fonts-downloader <url> [options]

# Test on a simple site
webpage-fonts-downloader https://fonts.google.com/specimen/Roboto --list-only

# Test on bot-protected site (The Economist)
webpage-fonts-downloader "https://www.economist.com/..." --serif --ttf -v

# Alternative: Run directly as a script without installing
./download_fonts.py <url> [options]
```

## Architecture

### Package Structure

- **pyproject.toml**: Package metadata, dependencies, and build configuration
  - Uses `hatchling` as the build backend
  - Always use Python `>=3.13` in the `requires-python` field
  - Entry point: `webpage-fonts-downloader` command → `download_fonts:main`
- **download_fonts.py**: Single-file module containing all functionality

### Core Pipeline

1. **HTML Fetching** (`fetch_page`): Uses `curl_cffi.requests.Session(impersonate="chrome")` to mimic Chrome TLS fingerprint and bypass bot protection (e.g., Cloudflare, The Economist)

2. **CSS Discovery** (`extract_css_urls`, `extract_inline_styles`): Parses HTML with BeautifulSoup to find both `<link>` stylesheets and inline `<style>` blocks

3. **@font-face Parsing** (`parse_css_for_fonts`):
   - Primary: `cssutils.parseString()` to extract `@font-face` rules
   - Fallback: `parse_css_with_regex()` for malformed CSS
   - Follows `@import` rules recursively

4. **Font Classification** (`classify_font`): Regex pattern matching against `SERIF_PATTERNS`, `SANS_PATTERNS`, `MONO_PATTERNS` to categorize fonts into `FontCategory` enum

5. **Font Downloading** (`download_font`):
   - Prefers WOFF2 > WOFF > TTF > OTF formats (via `format_priority` dict)
   - Generates unique filenames with index suffix to avoid overwrites

6. **Format Conversion** (`convert_woff2_to_ttf`): Uses `fontTools.ttLib.TTFont` to convert WOFF2 to TTF, removes original WOFF2 file after successful conversion

### Data Models

- **`FontFace` (Pydantic)**: Represents a parsed `@font-face` rule with `family`, `url`, `weight`, `style`, `format`, `category`
- **`DownloadResult` (Pydantic)**: Wraps download outcome with `font`, `success`, `path`, `error`

### Key Implementation Details

- **URL extraction**: `extract_font_url()` parses `url()` and `format()` from CSS `src` property, skips `data:` URIs
- **Site name extraction**: `extract_site_name()` derives output directory from domain (e.g., `www.economist.com` → `economist`)
- **Deduplication**: `deduplicate_fonts()` removes duplicate URLs before downloading
- **Filtering**: `filter_fonts()` applies category filters based on CLI flags

## Modifying Font Classification

Add patterns to the module-level `SERIF_PATTERNS`, `SANS_PATTERNS`, or `MONO_PATTERNS` lists:

```python
SERIF_PATTERNS: list[str] = [
    r"serif",
    r"new-font-name.*serif",  # Add new pattern here
]
```

## Adding New CLI Options

1. Add argument to `create_arg_parser()`
2. Access via `args.<name>` in `main()`
3. Pass to relevant functions as keyword-only parameters

## Testing Bot Protection

The Economist requires Chrome TLS fingerprinting to work. If a site blocks requests:

1. Verify `curl_requests.Session(impersonate="chrome")` is used
2. Check if site requires cookies/auth (currently unsupported)
3. Consider adding delay/retry logic if rate-limited

## Dependencies Rationale

- `curl_cffi`: TLS fingerprinting to bypass Cloudflare/bot protection
- `beautifulsoup4`: HTML parsing for `<link>` and `<style>` tags
- `cssutils`: Robust CSS `@font-face` rule extraction
- `fonttools[woff]` + `brotli`: WOFF2 decompression and TTF conversion
- `pydantic`: Type-safe data models with validation
