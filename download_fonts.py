#!/usr/bin/env python3
"""
Download fonts used by a webpage.

Parses HTML for CSS stylesheets, extracts @font-face rules,
classifies fonts, and downloads them to a local directory.
"""

import argparse
import logging
import re
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin, urlparse

import cssutils
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from fontTools.ttLib import TTFont
from pydantic import BaseModel


# Suppress cssutils logging noise
cssutils.log.setLevel(logging.CRITICAL)


class FontCategory(str, Enum):
    SERIF = "serif"
    SANS_SERIF = "sans-serif"
    MONOSPACE = "monospace"
    DISPLAY = "display"
    UNKNOWN = "unknown"


class FontFace(BaseModel):
    """Represents a parsed @font-face rule."""

    family: str
    url: str
    weight: str = "400"
    style: str = "normal"
    format: str | None = None
    category: FontCategory = FontCategory.UNKNOWN


class DownloadResult(BaseModel):
    """Result of a font download attempt."""

    font: FontFace
    success: bool
    path: Path | None = None
    error: str | None = None


# Heuristics for classifying font families
SERIF_PATTERNS: list[str] = [
    r"serif",
    r"georgia",
    r"times",
    r"garamond",
    r"palatino",
    r"cambria",
    r"didot",
    r"bodoni",
    r"caslon",
    r"baskerville",
    r"minion",
    r"sabon",
    r"bembo",
    r"plantin",
    r"econ.*serif",
    r"economist.*serif",
]

SANS_PATTERNS: list[str] = [
    r"sans",
    r"arial",
    r"helvetica",
    r"verdana",
    r"tahoma",
    r"roboto",
    r"open\s*sans",
    r"lato",
    r"montserrat",
    r"proxima",
    r"futura",
    r"avenir",
    r"gotham",
    r"gill",
    r"franklin",
    r"econ.*sans",
    r"economist.*sans",
]

MONO_PATTERNS: list[str] = [
    r"mono",
    r"courier",
    r"consolas",
    r"menlo",
    r"fira\s*code",
    r"source\s*code",
    r"jetbrains",
]


def classify_font(*, family: str) -> FontCategory:
    """Classify a font family into a category using heuristics."""
    family_lower = family.lower()
    for pattern in MONO_PATTERNS:
        if re.search(pattern, family_lower):
            return FontCategory.MONOSPACE
    for pattern in SANS_PATTERNS:
        if re.search(pattern, family_lower):
            return FontCategory.SANS_SERIF
    for pattern in SERIF_PATTERNS:
        if re.search(pattern, family_lower):
            return FontCategory.SERIF
    return FontCategory.UNKNOWN


def extract_font_url(*, src_value: str, base_url: str) -> tuple[str, str | None] | None:
    """Extract the font URL and format from a src property value."""
    # Match url(...) with optional format(...)
    url_match = re.search(r'url\(["\']?([^"\')\s]+)["\']?\)', src_value)
    if not url_match:
        return None
    raw_url = url_match.group(1)
    # Skip data URIs
    if raw_url.startswith("data:"):
        return None
    absolute_url = urljoin(base_url, raw_url)
    # Extract format if present
    format_match = re.search(r'format\(["\']?([^"\')\s]+)["\']?\)', src_value)
    font_format = format_match.group(1) if format_match else None
    return (absolute_url, font_format)


def parse_font_face_rule(*, rule: cssutils.css.CSSFontFaceRule, base_url: str) -> list[FontFace]:
    """Parse a @font-face rule and extract font information."""
    fonts: list[FontFace] = []
    family = None
    weight = "400"
    style = "normal"
    src_value = None
    for prop in rule.style:
        match prop.name:
            case "font-family":
                family = prop.value.strip("'\"")
            case "font-weight":
                weight = prop.value
            case "font-style":
                style = prop.value
            case "src":
                src_value = prop.value
    if not family or not src_value:
        return fonts
    # Handle multiple url() declarations in src (fallbacks)
    # We prefer woff2 > woff > ttf > otf > eot
    format_priority = {"woff2": 0, "woff": 1, "truetype": 2, "opentype": 3, "embedded-opentype": 4}
    candidates: list[tuple[str, str | None, int]] = []
    # Split by comma for multiple sources
    for src_part in src_value.split(","):
        result = extract_font_url(src_value=src_part.strip(), base_url=base_url)
        if result:
            url, fmt = result
            priority = format_priority.get(fmt or "", 5)
            # Also check file extension if no format specified
            if fmt is None:
                ext = Path(urlparse(url).path).suffix.lower()
                ext_to_fmt = {".woff2": 0, ".woff": 1, ".ttf": 2, ".otf": 3, ".eot": 4}
                priority = ext_to_fmt.get(ext, 5)
            candidates.append((url, fmt, priority))
    if not candidates:
        return fonts
    # Sort by priority and take the best
    candidates.sort(key=lambda x: x[2])
    best_url, best_format, _ = candidates[0]
    category = classify_font(family=family)
    fonts.append(
        FontFace(
            family=family,
            url=best_url,
            weight=weight,
            style=style,
            format=best_format,
            category=category,
        )
    )
    return fonts


def parse_css_for_fonts(*, css_text: str, base_url: str) -> list[FontFace]:
    """Parse CSS text and extract all @font-face declarations."""
    fonts: list[FontFace] = []
    try:
        sheet = cssutils.parseString(css_text)
        for rule in sheet:
            if isinstance(rule, cssutils.css.CSSFontFaceRule):
                fonts.extend(parse_font_face_rule(rule=rule, base_url=base_url))
    except Exception:
        # Fallback: use regex for malformed CSS
        fonts.extend(parse_css_with_regex(css_text=css_text, base_url=base_url))
    return fonts


def parse_css_with_regex(*, css_text: str, base_url: str) -> list[FontFace]:
    """Fallback regex-based parser for @font-face rules."""
    fonts: list[FontFace] = []
    # Match @font-face blocks
    pattern = r"@font-face\s*\{([^}]+)\}"
    for match in re.finditer(pattern, css_text, re.IGNORECASE | re.DOTALL):
        block = match.group(1)
        # Extract properties
        family_match = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)['\"]?\s*;", block)
        src_match = re.search(r"src\s*:\s*([^;]+);", block, re.DOTALL)
        weight_match = re.search(r"font-weight\s*:\s*([^;]+);", block)
        style_match = re.search(r"font-style\s*:\s*([^;]+);", block)
        if not family_match or not src_match:
            continue
        family = family_match.group(1).strip()
        src_value = src_match.group(1).strip()
        weight = weight_match.group(1).strip() if weight_match else "400"
        style = style_match.group(1).strip() if style_match else "normal"
        result = extract_font_url(src_value=src_value, base_url=base_url)
        if result:
            url, fmt = result
            category = classify_font(family=family)
            fonts.append(
                FontFace(
                    family=family,
                    url=url,
                    weight=weight,
                    style=style,
                    format=fmt,
                    category=category,
                )
            )
    return fonts


def fetch_page(*, url: str, client: curl_requests.Session) -> str:
    """Fetch HTML content from a URL."""
    response = client.get(url, allow_redirects=True)
    response.raise_for_status()
    return response.text


def fetch_css(*, url: str, client: curl_requests.Session) -> str:
    """Fetch CSS content from a URL."""
    response = client.get(url, allow_redirects=True)
    response.raise_for_status()
    return response.text


def extract_css_urls(*, html: str, base_url: str) -> list[str]:
    """Extract CSS stylesheet URLs from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    # Find <link rel="stylesheet"> tags
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href")
        if href:
            urls.append(urljoin(base_url, href))
    # Find <link> with type="text/css"
    for link in soup.find_all("link", type="text/css"):
        href = link.get("href")
        if href and urljoin(base_url, href) not in urls:
            urls.append(urljoin(base_url, href))
    return urls


def extract_inline_styles(*, html: str) -> list[str]:
    """Extract inline <style> content from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    styles: list[str] = []
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            styles.append(style_tag.string)
    return styles


def download_font(
    *,
    font: FontFace,
    output_dir: Path,
    client: curl_requests.Session,
    index: int,
) -> DownloadResult:
    """Download a single font file."""
    try:
        response = client.get(font.url, allow_redirects=True)
        response.raise_for_status()
        # Determine filename
        parsed = urlparse(font.url)
        original_name = Path(parsed.path).name
        # Clean up filename - remove query params from name
        if "?" in original_name:
            original_name = original_name.split("?")[0]
        # Construct descriptive filename with index for uniqueness
        safe_family = re.sub(r"[^\w\-]", "_", font.family)
        safe_weight = re.sub(r"\s+", "_", font.weight)
        ext = Path(original_name).suffix or ".woff2"
        filename = f"{safe_family}-{safe_weight}-{font.style}-{index:02d}{ext}"
        output_path = output_dir / filename
        output_path.write_bytes(response.content)
        return DownloadResult(font=font, success=True, path=output_path)
    except Exception as e:
        return DownloadResult(font=font, success=False, error=str(e))


def convert_woff2_to_ttf(*, woff2_path: Path) -> Path | None:
    """Convert a woff2 font to ttf format. Returns the new path or None on failure."""
    try:
        ttf_path = woff2_path.with_suffix(".ttf")
        font = TTFont(woff2_path)
        font.flavor = None  # Remove woff2 compression
        font.save(ttf_path)
        font.close()
        return ttf_path
    except Exception:
        return None


def collect_fonts_from_page(
    *,
    url: str,
    client: curl_requests.Session,
    log: Callable[[str], None],
) -> list[FontFace]:
    """Collect all fonts referenced by a webpage."""
    all_fonts: list[FontFace] = []
    log(f"Fetching page: {url}")
    html = fetch_page(url=url, client=client)
    # Extract and parse inline styles
    inline_styles = extract_inline_styles(html=html)
    for i, style in enumerate(inline_styles):
        log(f"Parsing inline style block {i + 1}")
        fonts = parse_css_for_fonts(css_text=style, base_url=url)
        all_fonts.extend(fonts)
    # Extract and fetch external CSS
    css_urls = extract_css_urls(html=html, base_url=url)
    log(f"Found {len(css_urls)} external stylesheet(s)")
    for css_url in css_urls:
        try:
            log(f"Fetching CSS: {css_url}")
            css_text = fetch_css(url=css_url, client=client)
            fonts = parse_css_for_fonts(css_text=css_text, base_url=css_url)
            all_fonts.extend(fonts)
            # Also check for @import rules
            import_pattern = r'@import\s+url\(["\']?([^"\')\s]+)["\']?\)'
            for match in re.finditer(import_pattern, css_text):
                import_url = urljoin(css_url, match.group(1))
                log(f"Following @import: {import_url}")
                try:
                    import_css = fetch_css(url=import_url, client=client)
                    fonts = parse_css_for_fonts(css_text=import_css, base_url=import_url)
                    all_fonts.extend(fonts)
                except Exception as e:
                    log(f"  Failed to fetch @import: {e}")
        except Exception as e:
            log(f"  Failed to fetch CSS: {e}")
    return all_fonts


def deduplicate_fonts(*, fonts: list[FontFace]) -> list[FontFace]:
    """Remove duplicate fonts based on URL."""
    seen_urls: set[str] = set()
    unique: list[FontFace] = []
    for font in fonts:
        if font.url not in seen_urls:
            seen_urls.add(font.url)
            unique.append(font)
    return unique


def filter_fonts(
    *,
    fonts: list[FontFace],
    categories: set[FontCategory] | None,
) -> list[FontFace]:
    """Filter fonts by category."""
    if categories is None:
        return fonts
    return [f for f in fonts if f.category in categories]


def create_arg_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="Download fonts used by a webpage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://example.com
  %(prog)s https://example.com --serif --output ./fonts
  %(prog)s https://example.com --sans-serif --monospace
  %(prog)s https://example.com --all --list-only
        """,
    )
    parser.add_argument("url", help="URL of the webpage to analyze")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory for downloaded fonts (default: ./<domain-name>)",
    )
    parser.add_argument(
        "--serif",
        action="store_true",
        help="Download serif fonts",
    )
    parser.add_argument(
        "--sans-serif",
        action="store_true",
        help="Download sans-serif fonts",
    )
    parser.add_argument(
        "--monospace",
        action="store_true",
        help="Download monospace fonts",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all fonts (including unknown category)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List fonts without downloading",
    )
    parser.add_argument(
        "--ttf",
        action="store_true",
        help="Convert downloaded fonts to TTF format (macOS compatible)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        help="User-Agent header for requests",
    )
    return parser


def extract_site_name(*, url: str) -> str:
    """Extract a clean site name from URL for use as directory name."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    # Remove www. prefix
    if host.startswith("www."):
        host = host[4:]
    # Take the main domain name (before TLD)
    parts = host.split(".")
    if len(parts) >= 2:
        return parts[-2]  # e.g., "economist" from "www.economist.com"
    return host


def main() -> int:
    """Main entry point."""
    parser = create_arg_parser()
    args = parser.parse_args()
    # Set default output directory based on site name if not specified
    if args.output is None:
        site_name = extract_site_name(url=args.url)
        args.output = Path(f"./{site_name}")
    # Determine which categories to include
    categories: set[FontCategory] | None = None
    if args.all:
        categories = None  # All categories
    elif args.serif or args.sans_serif or args.monospace:
        categories = set()
        if args.serif:
            categories.add(FontCategory.SERIF)
        if args.sans_serif:
            categories.add(FontCategory.SANS_SERIF)
        if args.monospace:
            categories.add(FontCategory.MONOSPACE)
    else:
        # Default: download all if no filter specified
        categories = None
    # Setup logging
    def log(msg: str) -> None:
        if args.verbose:
            print(f"[*] {msg}", file=sys.stderr)
    # Track downloads for potential conversion
    downloaded_paths: list[Path] = []
    success_count = 0
    # Create HTTP client with browser TLS fingerprint impersonation
    with curl_requests.Session(impersonate="chrome", timeout=args.timeout) as client:
        # Collect fonts
        try:
            fonts = collect_fonts_from_page(url=args.url, client=client, log=log)
        except curl_requests.RequestsError as e:
            print(f"Error fetching page: {e}", file=sys.stderr)
            return 1
        # Deduplicate and filter
        fonts = deduplicate_fonts(fonts=fonts)
        fonts = filter_fonts(fonts=fonts, categories=categories)
        if not fonts:
            print("No fonts found matching the specified criteria.")
            return 0
        # Display found fonts
        print(f"\nFound {len(fonts)} font(s):\n")
        for font in fonts:
            cat_str = f"[{font.category.value}]".ljust(14)
            print(f"  {cat_str} {font.family} ({font.weight}, {font.style})")
            if args.verbose:
                print(f"               URL: {font.url}")
        if args.list_only:
            return 0
        # Create output directory
        args.output.mkdir(parents=True, exist_ok=True)
        print(f"\nDownloading to: {args.output.resolve()}\n")
        # Download fonts
        for i, font in enumerate(fonts):
            result = download_font(font=font, output_dir=args.output, client=client, index=i)
            if result.success and result.path is not None:
                print(f"  OK: {result.path.name}")
                success_count += 1
                downloaded_paths.append(result.path)
            else:
                print(f"  FAILED: {font.family} - {result.error}", file=sys.stderr)
        print(f"\nDownloaded {success_count}/{len(fonts)} font(s).")
    # Convert to TTF if requested (outside the session context)
    if args.ttf and downloaded_paths:
        print("\nConverting to TTF...")
        convert_count = 0
        for woff2_path in downloaded_paths:
            if woff2_path.suffix.lower() == ".woff2":
                ttf_path = convert_woff2_to_ttf(woff2_path=woff2_path)
                if ttf_path:
                    print(f"  OK: {ttf_path.name}")
                    woff2_path.unlink()  # Remove original woff2
                    convert_count += 1
                else:
                    print(f"  FAILED: {woff2_path.name}", file=sys.stderr)
            else:
                print(f"  SKIP: {woff2_path.name} (not woff2)")
        print(f"\nConverted {convert_count} font(s) to TTF.")
    return 0 if success_count == len(fonts) else 1


if __name__ == "__main__":
    sys.exit(main())
