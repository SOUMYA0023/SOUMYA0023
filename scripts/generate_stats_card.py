#!/usr/bin/env python3
"""
generate_stats_card.py
======================
Generates  assets/stats-card.svg  — a live GitHub stats card.

Data fetched at runtime (REST API, no PAT required)
----------------------------------------------------
  /users/{user}                     → public_repos, followers, following
  /users/{user}/repos?type=owner    → star count, fork count (paginated)
  /repos/{user}/{name}/languages    → language bytes per repo (aggregated)

No GraphQL / contribution-graph calls — those require a PAT.
All numeric values in the rendered SVG trace back to an API call here.

Usage
-----
  python scripts/generate_stats_card.py

Environment
-----------
  GITHUB_TOKEN   — default GITHUB_TOKEN injected by Actions
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests

# ── Identity ──────────────────────────────────────────────────────────────────
GITHUB_USER = "SOUMYA0023"
GITHUB_API  = "https://api.github.com"
TOKEN       = os.environ.get("GITHUB_TOKEN", "")
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "..", "assets")

# ── Card dimensions ───────────────────────────────────────────────────────────
CARD_W, CARD_H = 495, 500
TITLE_H        = 30
PAD            = 16

# ── Colours ───────────────────────────────────────────────────────────────────
BG         = "#0d0d0d"
GREEN_PRI  = "#39FF14"
GREEN_SEC  = "#2ecc40"
GREEN_LBL  = "#57d855"
TITLEBAR   = "#1a1a1a"
SEP_CLR    = "#1f1f1f"
GRAY       = "#888888"

FONT = "'Courier New', Courier, monospace"

# Language → colour map (GitHub language colours)
LANG_COLOURS: dict[str, str] = {
    "Python":           "#3572A5",
    "TypeScript":       "#2b7489",
    "JavaScript":       "#f1e05a",
    "HTML":             "#e34c26",
    "CSS":              "#563d7c",
    "Shell":            "#89e051",
    "Jupyter Notebook": "#DA5B0B",
    "C":                "#555555",
    "C++":              "#f34b7d",
    "Rust":             "#dea584",
    "Go":               "#00ADD8",
    "Java":             "#b07219",
    "Dockerfile":       "#384d54",
    "Vue":              "#41b883",
    "Kotlin":           "#A97BFF",
    "Swift":            "#F05138",
}
LANG_OTHER = "#6e7681"

# ── Inline icon paths (24×24 viewBox, scaled via transform) ──────────────────
ICON_STAR   = ("M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.62L12 2 "
               "9.19 8.62 2 9.24l5.46 4.73L5.82 21z")
ICON_FORK   = ("M6 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0 6a4 4 0 0 0-1 "
               "7.87V18a3 3 0 0 0 6 0v-1.13A4 4 0 0 0 10 9.17V8h-4zm"
               "6-6a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0 9a2 2 0 1 0 0 4 2 "
               "2 0 0 0 0-4z")
ICON_REPO   = ("M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5V5h"
               "1V3.5A2.5 2.5 0 0 0 12.5 1h-9A2.5 2.5 0 0 0 1 3.5v9A2"
               ".5 2.5 0 0 0 3.5 15H5v-1H3.5A1.5 1.5 0 0 1 2 12.5v-9z"
               "M8 8a1 1 0 0 1 1-1h6a1 1 0 0 1 0 2H9a1 1 0 0 1-1-1zm1"
               " 3a1 1 0 0 0 0 2h6a1 1 0 0 0 0-2H9zm-1-7a1 1 0 0 1 1-"
               "1h6a1 1 0 0 1 0 2H9a1 1 0 0 1-1-1z")
ICON_PERSON = ("M10 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-6 8a6 6 0 0 1 "
               "12 0H4z")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent":           f"profile-card-generator ({GITHUB_USER})",
    })
    if TOKEN:
        s.headers["Authorization"] = f"Bearer {TOKEN}"
    return s


def fetch_user(s: requests.Session) -> dict:
    r = s.get(f"{GITHUB_API}/users/{GITHUB_USER}", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_all_repos(s: requests.Session) -> list[dict]:
    """Paginate through ALL public repos owned by the user (not forks)."""
    repos, page = [], 1
    while True:
        r = s.get(
            f"{GITHUB_API}/users/{GITHUB_USER}/repos",
            params={"per_page": 100, "page": page, "type": "owner"},
            timeout=20,
        )
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_language_bytes(s: requests.Session, repos: list[dict]) -> dict[str, int]:
    """
    Aggregate language byte counts across all non-fork repos.
    Each repo's /languages response is summed into a single dict.
    """
    totals: dict[str, int] = defaultdict(int)
    for repo in repos:
        if repo.get("fork"):
            continue
        name = repo["name"]
        try:
            r = s.get(f"{GITHUB_API}/repos/{GITHUB_USER}/{name}/languages", timeout=10)
            if r.status_code == 200:
                for lang, count in r.json().items():
                    totals[lang] += count
        except Exception as exc:
            print(f"  [warn] language fetch failed for {name}: {exc}")
    return dict(totals)


def xml(s: object) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def fmt_n(n: int) -> str:
    """Human-readable number: 12345 → 12.3k, 1234567 → 1.2M."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def icon_svg(path: str, cx: float, y: float, size: float = 18,
             colour: str = GREEN_SEC) -> str:
    """Render a 24×24 path icon centred at *cx*, top-aligned at *y*."""
    half  = size / 2
    scale = size / 24
    tx    = cx - half
    return (f'<g transform="translate({tx:.1f},{y:.1f}) scale({scale:.4f})">'
            f'<path d="{path}" fill="{colour}"/>'
            f'</g>')


# ── SVG builder ───────────────────────────────────────────────────────────────

def build_svg(user: dict, repos: list[dict], lang_bytes: dict[str, int]) -> str:
    public_repos  = user.get("public_repos", 0)
    followers     = user.get("followers",    0)
    following     = user.get("following",    0)
    total_stars   = sum(r.get("stargazers_count", 0) for r in repos)
    total_forks   = sum(r.get("forks_count",      0) for r in repos)

    # Top 4 languages by byte volume
    top_langs   = sorted(lang_bytes.items(), key=lambda kv: kv[1], reverse=True)[:4]
    total_bytes = sum(v for _, v in top_langs) or 1

    parts: list[str] = []
    w = parts.append

    BAR_TOTAL_W = CARD_W - 2 * PAD     # full-width bar area

    # ── SVG root ─────────────────────────────────────────────────────────────
    w(f'<svg xmlns="http://www.w3.org/2000/svg" '
      f'width="{CARD_W}" height="{CARD_H}" '
      f'viewBox="0 0 {CARD_W} {CARD_H}" '
      f'role="img" aria-label="GitHub stats for {GITHUB_USER}">')

    # ── Styles ───────────────────────────────────────────────────────────────
    w(f'''<defs><style>
text         {{ font-family: {FONT}; }}
.wintitle    {{ font-size: 10px; fill: {GRAY}; }}
.sec-head    {{ font-size: 12px; font-weight: bold; fill: {GREEN_PRI}; }}
.stat-n      {{ font-size: 26px; font-weight: bold; fill: {GREEN_PRI}; }}
.stat-l      {{ font-size:  9px; fill: {GREEN_SEC}; }}
.lang-name   {{ font-size:  9px; font-weight: bold; fill: {GREEN_LBL}; }}
.lang-pct    {{ font-size:  9px; fill: {GREEN_SEC}; }}
.icon-n      {{ font-size: 14px; font-weight: bold; fill: {GREEN_PRI}; }}
.icon-l      {{ font-size:  9px; fill: {GREEN_SEC}; }}
.prompt-dim  {{ font-size:  9px; fill: {GREEN_SEC}; }}
.caption     {{ font-size:  8px; fill: {GREEN_SEC}; }}
</style></defs>''')

    # ── Background ────────────────────────────────────────────────────────────
    w(f'<rect width="{CARD_W}" height="{CARD_H}" fill="{BG}" rx="8"/>')

    # ── Title bar ─────────────────────────────────────────────────────────────
    w(f'<rect width="{CARD_W}" height="{TITLE_H}" fill="{TITLEBAR}" rx="8"/>')
    w(f'<rect y="{TITLE_H - 6}" width="{CARD_W}" height="6" fill="{TITLEBAR}"/>')
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        w(f'<circle cx="{16 + i * 18}" cy="15" r="5" fill="{c}"/>')
    w(f'<text x="{CARD_W // 2}" y="19" class="wintitle" text-anchor="middle">'
      f'soumya@github \u2014 stats</text>')

    y = float(TITLE_H + PAD)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: GitHub Statistics
    # ─────────────────────────────────────────────────────────────────────────
    w(f'<text x="{PAD}" y="{y:.1f}" class="sec-head">\u25c8  GitHub Statistics</text>')
    y += 8
    w(f'<line x1="{PAD}" y1="{y:.1f}" x2="{CARD_W - PAD}" y2="{y:.1f}" '
      f'stroke="{SEP_CLR}" stroke-width="1"/>')
    y += 22

    # 4 large stat boxes
    stats = [
        (fmt_n(public_repos), "Public Repos"),
        (fmt_n(followers),    "Followers"),
        (fmt_n(following),    "Following"),
        (fmt_n(total_stars),  "Total Stars"),
    ]
    cell_w = (CARD_W - 2 * PAD) // 4
    for i, (num, label) in enumerate(stats):
        cx = PAD + i * cell_w + cell_w // 2
        w(f'<text x="{cx}" y="{y + 8:.1f}" class="stat-n" text-anchor="middle">'
          f'{xml(num)}</text>')
        w(f'<text x="{cx}" y="{y + 28:.1f}" class="stat-l" text-anchor="middle">'
          f'{xml(label)}</text>')
    y += 52

    w(f'<line x1="{PAD}" y1="{y:.1f}" x2="{CARD_W - PAD}" y2="{y:.1f}" '
      f'stroke="{SEP_CLR}" stroke-width="1"/>')
    y += 20

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: Top Languages
    # ─────────────────────────────────────────────────────────────────────────
    w(f'<text x="{PAD}" y="{y:.1f}" class="sec-head">'
      f'\u25b8 Top Languages by Code Volume</text>')
    y += 18

    # Legend row
    leg_cell = BAR_TOTAL_W // max(len(top_langs), 1)
    leg_x    = PAD
    for lang, count in top_langs:
        colour = LANG_COLOURS.get(lang, LANG_OTHER)
        pct    = count / total_bytes * 100
        w(f'<rect x="{leg_x}" y="{y - 8:.1f}" width="9" height="9" '
          f'fill="{colour}" rx="2"/>')
        w(f'<text x="{leg_x + 13}" y="{y:.1f}" class="lang-name">'
          f'{xml(lang[:13])} '
          f'<tspan class="lang-pct">{pct:.1f}%</tspan>'
          f'</text>')
        leg_x += leg_cell
    y += 12

    # Composite stacked bar
    bar_h  = 12
    bar_x  = PAD
    for lang, count in top_langs:
        colour = LANG_COLOURS.get(lang, LANG_OTHER)
        seg_w  = max(int(count / total_bytes * BAR_TOTAL_W), 1)
        w(f'<rect x="{bar_x}" y="{y:.1f}" width="{seg_w}" height="{bar_h}" '
          f'fill="{colour}"/>')
        bar_x += seg_w
    y += bar_h + 12

    # Per-language bars with label + filled bar + percentage
    LABEL_COL = 95
    BAR_COL   = BAR_TOTAL_W - LABEL_COL - 46   # right 46 px reserved for pct

    for lang, count in top_langs:
        colour = LANG_COLOURS.get(lang, LANG_OTHER)
        pct    = count / total_bytes
        filled = max(int(pct * BAR_COL), 2)

        # Language name
        w(f'<text x="{PAD}" y="{y + 10:.1f}" class="lang-name">'
          f'{xml(lang[:16])}</text>')

        # Background bar
        bx = PAD + LABEL_COL
        w(f'<rect x="{bx}" y="{y + 2:.1f}" width="{BAR_COL}" height="9" '
          f'fill="#1a1a1a" rx="4"/>')
        # Filled portion
        w(f'<rect x="{bx}" y="{y + 2:.1f}" width="{filled}" height="9" '
          f'fill="{colour}" rx="4"/>')

        # Percentage label
        px = bx + BAR_COL + 6
        w(f'<text x="{px}" y="{y + 10:.1f}" class="lang-pct">'
          f'{pct * 100:.1f}%</text>')

        y += 18

    y += 8
    w(f'<line x1="{PAD}" y1="{y:.1f}" x2="{CARD_W - PAD}" y2="{y:.1f}" '
      f'stroke="{SEP_CLR}" stroke-width="1"/>')
    y += 18

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: Engagement icon row
    # Stars · Forks · Repos · Followers — all from REST API, no PAT needed.
    # ─────────────────────────────────────────────────────────────────────────
    icon_items = [
        (ICON_STAR,   fmt_n(total_stars),  "Stars"),
        (ICON_FORK,   fmt_n(total_forks),  "Forks"),
        (ICON_REPO,   fmt_n(public_repos), "Public Repos"),
        (ICON_PERSON, fmt_n(followers),    "Followers"),
    ]
    icon_cell_w = (CARD_W - 2 * PAD) // 4
    for i, (path, count, label) in enumerate(icon_items):
        cx = PAD + i * icon_cell_w + icon_cell_w // 2
        w(icon_svg(path, cx, y, size=20, colour=GREEN_SEC))
        w(f'<text x="{cx}" y="{y + 34:.1f}" class="icon-n" '
          f'text-anchor="middle">{xml(count)}</text>')
        w(f'<text x="{cx}" y="{y + 47:.1f}" class="icon-l" '
          f'text-anchor="middle">{xml(label)}</text>')

    y += 62
    w(f'<line x1="{PAD}" y1="{y:.1f}" x2="{CARD_W - PAD}" y2="{y:.1f}" '
      f'stroke="{SEP_CLR}" stroke-width="1"/>')
    y += 16

    # ─────────────────────────────────────────────────────────────────────────
    # Decorative terminal prompt footer (no live data, pure aesthetic)
    # ─────────────────────────────────────────────────────────────────────────
    w(f'<text x="{PAD}" y="{y:.1f}" class="prompt-dim">'
      f'{GITHUB_USER}@github:~$ <tspan fill="{GREEN_PRI}">echo &quot;Keep shipping.&quot;</tspan>'
      f'</text>')
    y += 14
    w(f'<text x="{PAD}" y="{y:.1f}" class="prompt-dim" fill="{GREEN_PRI}">Keep shipping.</text>')
    y += 14
    w(f'<text x="{PAD}" y="{y:.1f}" class="prompt-dim">'
      f'{GITHUB_USER}@github:~$ <tspan fill="{GREEN_PRI}">\u2588</tspan></text>')

    # ── Footer caption ────────────────────────────────────────────────────────
    w(f'<text x="{CARD_W // 2}" y="{CARD_H - 6}" class="caption" '
      f'text-anchor="middle">Auto-updated every 6 hours via GitHub Actions</text>')

    w('</svg>')
    return "\n".join(parts)


# ── Entry point ───────────────────────────────────────────────────────────────

# ── XML validation ────────────────────────────────────────────────────────────

def validate_svg(svg_content: str) -> None:
    """Raise ValueError if *svg_content* is not well-formed XML."""
    try:
        ET.fromstring(svg_content)
    except ET.ParseError as exc:
        raise ValueError(f"Generated SVG is not well-formed XML: {exc}") from exc


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    try:
        s = _session()

        print(f"[stats-card] Fetching user data for @{GITHUB_USER} …")
        user = fetch_user(s)
        print(f"  → repos={user.get('public_repos')}, "
              f"followers={user.get('followers')}, "
              f"following={user.get('following')}")

        print("[stats-card] Fetching all public repos (paginated) …")
        repos = fetch_all_repos(s)
        print(f"  → {len(repos)} repos found")

        print("[stats-card] Aggregating language bytes …")
        lang_bytes = fetch_language_bytes(s, repos)
        print(f"  → {len(lang_bytes)} languages: "
              f"{list(lang_bytes.keys())[:6]}")

        print("[stats-card] Building SVG …")
        svg = build_svg(user, repos, lang_bytes)

        print("[stats-card] Validating SVG XML …")
        validate_svg(svg)   # fails loudly if builder produced malformed XML

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, "stats-card.svg")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"[stats-card] Done → {out_path}")

    except Exception as exc:  # noqa: BLE001
        print(f"\n[stats-card] FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
