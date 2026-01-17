# Webpage Font Downloader

Download and convert fonts used by any webpage.

## Features

- 🔍 **Smart Discovery**: Parses HTML and CSS to find all `@font-face` declarations
- 🎯 **Category Filtering**: Download only serif, sans-serif, or monospace fonts
- 🔄 **Format Conversion**: Convert WOFF2 fonts to TTF for macOS compatibility
- 🛡️ **Bot Protection Bypass**: Uses Chrome TLS fingerprinting to access protected sites
- 📁 **Auto-naming**: Creates output directories named after the website

## Installation

Requires Python 3.13+ and [uv](https://github.com/astral-sh/uv).

### Install from GitHub

```bash
uv tool install git+https://github.com/ibehnam/webpage-fonts-downloader.git
```

The `download-fonts` command will be available globally.

### Install from Local Clone

```bash
# Clone the repository
git clone https://github.com/ibehnam/webpage-fonts-downloader.git
cd webpage-fonts-downloader

# Install the tool
uv tool install .

# Or install in editable mode for development
uv tool install --editable .
```

## Usage

```bash
# List fonts from a webpage
download-fonts https://example.com --list-only

# Download serif fonts to ./economist
download-fonts https://www.economist.com/... --serif

# Download and convert to TTF (macOS compatible)
download-fonts https://www.economist.com/... --serif --ttf

# Download all font types to custom directory
download-fonts https://example.com --all -o ./my-fonts

# Verbose mode for debugging
download-fonts https://example.com --verbose
```

### Alternative: Run as a script (without installation)

You can also run the script directly:

```bash
chmod +x download_fonts.py
./download_fonts.py https://example.com --list-only
```

## Options

- `--serif`: Download only serif fonts
- `--sans-serif`: Download only sans-serif fonts
- `--monospace`: Download only monospace fonts
- `--all`: Download all fonts (including unclassified)
- `--ttf`: Convert downloaded WOFF2 fonts to TTF format
- `--output, -o`: Specify output directory (default: `./<site-name>`)
- `--list-only`: List fonts without downloading
- `--verbose, -v`: Show detailed progress
- `--timeout`: HTTP timeout in seconds (default: 30)

## How It Works

1. Fetches the webpage HTML using Chrome TLS fingerprint impersonation
2. Extracts inline `<style>` blocks and external CSS stylesheet URLs
3. Parses CSS for `@font-face` rules using `cssutils`
4. Classifies fonts by category using heuristics
5. Downloads fonts (preferring WOFF2 > WOFF > TTF > OTF formats)
6. Optionally converts WOFF2 to TTF using `fonttools`

## Example: The Economist

```bash
download-fonts --serif --ttf \
  "https://www.economist.com/science-and-technology/2024/12/16/earth-is-warming-faster-scientists-are-closing-in-on-why"
```

Output:
```
Found 10 font(s):
  [serif]  EconomistSerifOsF (300 900, normal)
  [serif]  EconomistSerifOsF (300 900, italic)
  ...

Downloading to: ./economist
  OK: EconomistSerifOsF-300_900-normal-00.woff2
  ...

Converting to TTF...
  OK: EconomistSerifOsF-300_900-normal-00.ttf
  ...
```

## Dependencies

- `curl_cffi`: Browser TLS fingerprinting for bypassing bot protection
- `beautifulsoup4`: HTML parsing
- `cssutils`: CSS `@font-face` rule extraction
- `fonttools[woff]`: WOFF2 to TTF conversion
- `brotli`: WOFF2 decompression
- `pydantic`: Data validation

## License

MIT
