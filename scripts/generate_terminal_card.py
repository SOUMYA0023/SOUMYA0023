#!/usr/bin/env python3
"""
generate_terminal_card.py
=========================
Generates  assets/terminal-card.svg  — a neofetch-style terminal profile card.

Layout
------
  Left panel  : ASCII-art rendering of the live GitHub avatar
  Right panel : system-info key/value list + "Highlights" project links

Every number shown in the card is fetched from the GitHub REST API at runtime.
The avatar is downloaded fresh each run, so avatar changes auto-propagate.

Usage
-----
  python scripts/generate_terminal_card.py

Environment
-----------
  GITHUB_TOKEN   — default GITHUB_TOKEN injected by Actions (read:user scope)
                   Works without a PAT for all data shown in this card.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from io import BytesIO

import requests
from PIL import Image

# ── Identity ──────────────────────────────────────────────────────────────────
GITHUB_USER    = "SOUMYA0023"
GITHUB_API     = "https://api.github.com"
TOKEN          = os.environ.get("GITHUB_TOKEN", "")
OUTPUT_DIR     = os.path.join(os.path.dirname(__file__), "..", "assets")

# ── Card dimensions ───────────────────────────────────────────────────────────
CARD_W, CARD_H = 495, 500
TITLE_H        = 30
PAD            = 14           # outer padding

# Vertical separator between ASCII panel (left) and info panel (right)
SPLIT_X        = 190

# ── ASCII art ─────────────────────────────────────────────────────────────────
ASCII_COLS      = 36          # characters per row
ASCII_ROWS      = 47          # number of rows  (portrait-ish, classic neofetch)
ASCII_FONT_SZ   = 7.5         # px  (Courier New)
ASCII_CHAR_W    = 4.5         # approximate glyph width at this size
ASCII_LINE_H    = 9.0         # line height

# Luminance→character mapping (dense=dark, sparse=light)
CHAR_RAMP = "@%#*+=-:·  "

# ── Info panel ────────────────────────────────────────────────────────────────
INFO_FONT_SZ   = 9.0
INFO_LINE_H    = 14
INFO_X         = SPLIT_X + 15          # left edge of info text
LABEL_W        = 72                    # fixed column width for labels
VALUE_X        = INFO_X + LABEL_W     # left edge of value text
VALUE_MAX_W    = CARD_W - PAD - VALUE_X  # px available for value
VALUE_MAX_CHARS = int(VALUE_MAX_W / (INFO_FONT_SZ * 0.601))  # ≈ 38 chars/line

# ── Colours ───────────────────────────────────────────────────────────────────
BG          = "#0d0d0d"
GREEN_PRI   = "#39FF14"    # primary text / values
GREEN_SEC   = "#2ecc40"    # dimmed / secondary
GREEN_LBL   = "#57d855"    # field labels
TITLEBAR    = "#1a1a1a"
SEP_CLR     = "#1f1f1f"
GRAY        = "#888888"
LINK_CLR    = "#58d0ff"

FONT = "'Courier New', Courier, monospace"

# ── Static info fields ────────────────────────────────────────────────────────
# Order is significant.  "Repos" is injected dynamically after index 8 (AI/ML).
STATIC_INFO: list[tuple[str, str]] = [
    ("Name",       "Soumya Kar"),
    ("Role",       "Full-Stack + AI Builder"),
    ("OS",         "CS Undergraduate"),
    ("Position",   "President, Intellects Technical Club"),
    ("CGPA",       "8.91"),
    ("Languages",  "Python, TypeScript, JavaScript"),
    ("Frameworks", "Next.js, React, FastAPI, LangGraph"),
    ("Tools",      "Supabase, PostgreSQL, Docker, GitHub Actions"),
    ("AI/ML",      "PyTorch, Gemini API, RAG pipelines"),
    # ← "Repos" inserted here at runtime
    ("Email",      "soumyasumankar23@gmail.com"),
    ("GitHub",     "github.com/SOUMYA0023"),
]

# ── Highlights (hardcoded — no PAT for GraphQL pinned-repos) ─────────────────
# NOTE: SVG <a href> links are not interactive when rendered via <img> on GitHub.
# These are styled visually as links; add them as markdown links in README too.
HIGHLIGHTS: list[tuple[str, str]] = [
    ("RepoLens AI",   f"https://github.com/{GITHUB_USER}/RepoLens-AI"),
    ("SmartReach-AI", f"https://github.com/{GITHUB_USER}/SmartReach-AI"),
    ("PneumoVision",  f"https://github.com/{GITHUB_USER}/PneumoVision"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept":              "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent":          f"profile-card-generator ({GITHUB_USER})",
    })
    if TOKEN:
        s.headers["Authorization"] = f"Bearer {TOKEN}"
    return s


def fetch_user(s: requests.Session) -> dict:
    r = s.get(f"{GITHUB_API}/users/{GITHUB_USER}", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_avatar(avatar_url: str) -> Image.Image:
    r = requests.get(avatar_url, timeout=15)
    r.raise_for_status()
    img = Image.open(BytesIO(r.content))
    # Handle RGBA by compositing on the card background colour
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (13, 13, 13))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert("RGB")


def image_to_ascii(img: Image.Image) -> list[str]:
    """
    Resize image to (ASCII_COLS × ASCII_ROWS) and map each pixel to a
    character from CHAR_RAMP via its greyscale luminance.
    The classic neofetch portrait look accepts the vertical stretch that
    arises when glyph height > glyph width.
    """
    small = img.resize((ASCII_COLS, ASCII_ROWS), Image.LANCZOS).convert("L")
    ramp_max = len(CHAR_RAMP) - 1
    rows: list[str] = []
    for y in range(ASCII_ROWS):
        row = "".join(CHAR_RAMP[int(small.getpixel((x, y)) / 255 * ramp_max)]
                      for x in range(ASCII_COLS))
        rows.append(row)
    return rows


def xml(s: str) -> str:
    """Minimal XML/SVG character escaping."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def wrap_value(value: str, max_chars: int) -> list[str]:
    """
    Split *value* into lines of at most *max_chars*.
    Prefers splitting at the last comma before the limit; falls back to a
    hard split at the character boundary.
    """
    if len(value) <= max_chars:
        return [value]
    split = value.rfind(",", 0, max_chars + 1)
    if split > 0:
        return [value[:split + 1].strip()] + wrap_value(value[split + 1:].strip(), max_chars)
    return [value[:max_chars]] + wrap_value(value[max_chars:], max_chars)


# ── SVG builder ───────────────────────────────────────────────────────────────

def build_svg(ascii_lines: list[str], public_repos: int) -> str:
    parts: list[str] = []
    w = parts.append  # write helper

    # Merge Repos into info list at the right position
    info: list[tuple[str, str]] = (
        list(STATIC_INFO[:9])
        + [("Repos", str(public_repos))]
        + list(STATIC_INFO[9:])
    )

    # ── SVG root ─────────────────────────────────────────────────────────────
    w(f'<svg xmlns="http://www.w3.org/2000/svg" '
      f'xmlns:xlink="http://www.w3.org/1999/xlink" '
      f'width="{CARD_W}" height="{CARD_H}" '
      f'viewBox="0 0 {CARD_W} {CARD_H}" '
      f'role="img" '
      f'aria-label="Terminal profile card for {GITHUB_USER}">')

    # ── Embedded styles ───────────────────────────────────────────────────────
    w(f'''<defs><style>
text {{ font-family: {FONT}; }}
.ascii  {{ font-size: {ASCII_FONT_SZ}px; fill: {GREEN_PRI}; }}
.prompt {{ font-size: 8px; fill: {GREEN_SEC}; }}
.uname  {{ font-size: 13px; font-weight: bold; fill: {GREEN_PRI}; }}
.dash   {{ font-size: 9px;  fill: {GREEN_SEC}; }}
.lbl    {{ font-size: {INFO_FONT_SZ}px; font-weight: bold; fill: {GREEN_LBL}; }}
.val    {{ font-size: {INFO_FONT_SZ}px; fill: {GREEN_PRI}; }}
.sec    {{ font-size: {INFO_FONT_SZ}px; font-weight: bold; fill: {GREEN_SEC}; }}
.link   {{ font-size: {INFO_FONT_SZ}px; fill: {LINK_CLR}; }}
.wintitle {{ font-size: 10px; fill: {GRAY}; }}
.caption  {{ font-size: 8px;  fill: {GREEN_SEC}; }}
</style></defs>''')

    # ── Background ────────────────────────────────────────────────────────────
    w(f'<rect width="{CARD_W}" height="{CARD_H}" fill="{BG}" rx="8"/>')

    # ── Title bar ─────────────────────────────────────────────────────────────
    w(f'<rect width="{CARD_W}" height="{TITLE_H}" fill="{TITLEBAR}" rx="8"/>')
    w(f'<rect y="{TITLE_H - 6}" width="{CARD_W}" height="6" fill="{TITLEBAR}"/>')
    for i, colour in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        cx = 16 + i * 18
        w(f'<circle cx="{cx}" cy="15" r="5" fill="{colour}"/>')
    w(f'<text x="{CARD_W // 2}" y="19" class="wintitle" text-anchor="middle">'
      f'soumya@github \u2014 neofetch</text>')

    # ── Panel separator ───────────────────────────────────────────────────────
    w(f'<line x1="{SPLIT_X}" y1="{TITLE_H}" x2="{SPLIT_X}" y2="{CARD_H}" '
      f'stroke="{SEP_CLR}" stroke-width="1"/>')

    # ── Left panel: ASCII art ─────────────────────────────────────────────────
    content_top = TITLE_H + PAD          # y where content begins

    w(f'<text x="{PAD}" y="{content_top}" class="prompt">'
      f'$ neofetch --user {GITHUB_USER}</text>')

    ascii_y0 = content_top + int(ASCII_LINE_H) + 4
    for row_idx, row in enumerate(ascii_lines):
        y = ascii_y0 + row_idx * ASCII_LINE_H
        w(f'<text x="{PAD}" y="{y:.1f}" class="ascii">'
          f'<tspan xml:space="preserve">{xml(row)}</tspan></text>')

    # ── Right panel: system info ──────────────────────────────────────────────
    iy = float(content_top)

    # Username / hostname header
    w(f'<text x="{INFO_X}" y="{iy:.1f}" class="uname">{GITHUB_USER}@github</text>')
    iy += 13
    w(f'<text x="{INFO_X}" y="{iy:.1f}" class="dash">{"─" * 30}</text>')
    iy += INFO_LINE_H

    # Key / value rows
    for key, val in info:
        lines = wrap_value(val, VALUE_MAX_CHARS)

        # First line: label + first chunk of value
        w(f'<text x="{INFO_X}" y="{iy:.1f}" class="lbl">{xml(key)}:</text>')
        w(f'<text x="{VALUE_X}" y="{iy:.1f}" class="val">{xml(lines[0])}</text>')
        iy += INFO_LINE_H

        # Continuation lines (no label, indented to value column)
        for cont in lines[1:]:
            w(f'<text x="{VALUE_X}" y="{iy:.1f}" class="val">{xml(cont)}</text>')
            iy += INFO_LINE_H

    # Highlights section
    iy += 4
    w(f'<text x="{INFO_X}" y="{iy:.1f}" class="dash">{"─" * 30}</text>')
    iy += INFO_LINE_H
    w(f'<text x="{INFO_X}" y="{iy:.1f}" class="sec">Highlights:</text>')
    iy += INFO_LINE_H

    for name, url in HIGHLIGHTS:
        # <a href> is visual-only when SVG is rendered via <img>
        w(f'<a xlink:href="{xml(url)}" href="{xml(url)}">')
        w(f'<text x="{INFO_X + 8}" y="{iy:.1f}" class="link">\u25b8 {xml(name)}</text>')
        w('</a>')
        iy += INFO_LINE_H

    # ── Footer caption ────────────────────────────────────────────────────────
    w(f'<text x="{CARD_W // 2}" y="{CARD_H - 6}" class="caption" '
      f'text-anchor="middle">Auto-updated every 6 h via GitHub Actions</text>')

    w('</svg>')
    return "\n".join(parts)


# ── XML validation ────────────────────────────────────────────────────────────

def validate_svg(svg_content: str) -> None:
    """
    Parse the generated SVG as XML and raise ValueError if it is malformed.
    This catches any SVG-builder bugs before the file is written to disk,
    preventing a broken image from being committed to the repo.
    """
    try:
        ET.fromstring(svg_content)
    except ET.ParseError as exc:
        raise ValueError(f"Generated SVG is not well-formed XML: {exc}") from exc


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    try:
        s = _session()

        print(f"[terminal-card] Fetching user data for @{GITHUB_USER} …")
        user_data    = fetch_user(s)
        public_repos = user_data.get("public_repos", 0)
        avatar_url   = user_data.get("avatar_url", "")
        if not avatar_url:
            raise RuntimeError("GitHub API returned no avatar_url — check token scopes.")
        print(f"  → public_repos={public_repos}")

        print("[terminal-card] Fetching avatar …")
        avatar = fetch_avatar(avatar_url)

        print(f"[terminal-card] Converting to ASCII art ({ASCII_COLS}×{ASCII_ROWS}) …")
        ascii_lines = image_to_ascii(avatar)

        print(f"[terminal-card] Rendering SVG ({CARD_W}×{CARD_H}) …")
        svg = build_svg(ascii_lines, public_repos)

        print("[terminal-card] Validating SVG XML …")
        validate_svg(svg)   # fails loudly if the builder produced malformed XML

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, "terminal-card.svg")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"[terminal-card] Done → {out_path}")

    except Exception as exc:  # noqa: BLE001
        print(f"\n[terminal-card] FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
