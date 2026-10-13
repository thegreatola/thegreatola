#!/usr/bin/env python3
"""Builds dark.svg and light.svg, the terminal card shown on the GitHub profile.

Reads the portrait from ascii.txt, pulls live numbers from the GitHub GraphQL
API, and writes both themes. Needs a token in GH_TOKEN that can see private
repos, otherwise the stats only count public work. update.sh supplies one from
the local GitHub CLI login, regenerates, commits and pushes:

    ./update.sh
"""
import datetime
import json
import os
import pathlib
import sys
import urllib.request
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).parent
LOGIN = "thegreatola"

# Layout, in px. CHAR_W is the advance we force on every glyph through
# textLength, so the card lines up the same in Consolas, Menlo or DejaVu.
FONT_SIZE = 16
CHAR_W = 9.6
LINE_H = 20
PAD_X = 18
TOP = 34
ART_COLS = 44
GAP = 3  # blank columns between the portrait and the readout
INFO_COLS = 54

THEMES = {
    "dark": {
        "bg": "#0d1117", "text": "#c9d1d9", "key": "#ff7a4d", "dim": "#3d4654",
        "art": "#aab4c0", "add": "#3fb950", "del": "#f85149",
    },
    "light": {
        "bg": "#fbfaf7", "text": "#1a1712", "key": "#d8431a", "dim": "#cfc9bd",
        "art": "#4a443a", "add": "#1a7f37", "del": "#cf222e",
    },
}


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GH_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        body = json.load(res)
    if body.get("errors"):
        sys.exit(f"GitHub API error: {body['errors']}")
    return body["data"]


def fetch_stats():
    viewer = gql("""{ viewer { id login createdAt } }""")["viewer"]
    if viewer["login"] != LOGIN:
        sys.exit(f"token belongs to {viewer['login']}, expected {LOGIN}")

    repos, cursor = [], None
    while True:
        page = gql("""
            query($cursor: String) { viewer {
              repositories(first: 50, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  name owner { login } stargazerCount
                  languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                    edges { size node { name } }
                  }
                }
              }
            } }""", cursor=cursor)["viewer"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    languages = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            languages[name] = languages.get(name, 0) + edge["size"]
    # Markup and stylesheets drown out the languages the logic is written in.
    for markup in ("HTML", "CSS", "SCSS", "Jupyter Notebook"):
        languages.pop(markup, None)
    top_languages = [name for name, _ in sorted(languages.items(), key=lambda kv: -kv[1])[:3]]

    contributions = 0
    this_year = datetime.date.today().year
    for year in range(int(viewer["createdAt"][:4]), this_year + 1):
        contributions += gql("""
            query($from: DateTime!, $to: DateTime!) { viewer {
              contributionsCollection(from: $from, to: $to) {
                contributionCalendar { totalContributions }
              }
            } }""", **{"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["viewer"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]

    added = deleted = 0
    for repo in repos:
        cursor = None
        while True:
            ref = gql("""
                query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
                  repository(owner: $owner, name: $name) { defaultBranchRef { target {
                    ... on Commit { history(first: 100, after: $cursor, author: {id: $id}) {
                      pageInfo { hasNextPage endCursor }
                      nodes { additions deletions }
                    } }
                  } } }
                }""", owner=repo["owner"]["login"], name=repo["name"], id=viewer["id"],
                cursor=cursor)["repository"]["defaultBranchRef"]
            if not ref:  # empty repo
                break
            history = ref["target"]["history"]
            for commit in history["nodes"]:
                added += commit["additions"]
                deleted += commit["deletions"]
            if not history["pageInfo"]["hasNextPage"]:
                break
            cursor = history["pageInfo"]["endCursor"]

    return {
        "repos": len(repos),
        "stars": sum(repo["stargazerCount"] for repo in repos),
        "contributions": contributions,
        "added": added,
        "deleted": deleted,
        "languages": top_languages,
    }


# A readout line is a list of (text, css class) segments, INFO_COLS wide.

def row(key, value):
    dots = "." * (INFO_COLS - len(key) - len(value) - 2)
    return [(key, "key"), (f" {dots} ", "dim"), (value, "text")]


def pair(left_key, left_value, right_key, right_value):
    half = INFO_COLS // 2 - 2
    out = []
    for key, value in ((left_key, left_value), (right_key, right_value)):
        dots = "." * (half - len(key) - len(value) - 2)
        out += [(key, "key"), (f" {dots} ", "dim"), (value, "text")]
        if key is left_key:
            out.append((" |  ", "dim"))
    return out


def heading(title):
    return [("- ", "dim"), (title, "text"), (" " + "-" * (INFO_COLS - len(title) - 3), "dim")]


def readout(stats):
    loc = stats["added"] - stats["deleted"]
    loc_key = "Lines of Code"
    loc_tail = f"{loc:,} ( "
    plus, minus = f"{stats['added']:,}++", f"{stats['deleted']:,}--"
    loc_dots = "." * (INFO_COLS - len(loc_key) - len(loc_tail) - len(plus) - len(minus) - 6)
    return [
        [(f"{LOGIN}@github", "text"), (" " + "-" * (INFO_COLS - len(LOGIN) - 8), "dim")],
        row("OS", "Web3 growth operator + AI builder"),
        row("Uptime", "5+ years scaling protocols"),
        row("Host", "Working globally"),
        row("Editor", "Claude Code, Cursor"),
        row("Languages", ", ".join(stats["languages"])),
        [],
        heading("Builds"),
        row("gtmquant.com", "GTM engine for web3 campaigns"),
        row("usevano.io", "Market intelligence"),
        row("memecoins-trading-agent", "Autonomous trading agent"),
        row("content-creator-skills", "Content engine for LLMs"),
        [],
        heading("Track Record"),
        row("Impressions", "250M+ generated for clients"),
        pair("Projects", "200+", "Creators", "2K+"),
        row("Audience", "104K+ on X"),
        [],
        heading("Contact"),
        row("Web", "thegreatola.com"),
        row("X", "@thegreatola"),
        row("LinkedIn", "in/olamilekan-majekodunmi"),
        [],
        heading("GitHub Stats"),
        pair("Repos", f"{stats['repos']:,}", "Stars", f"{stats['stars']:,}"),
        row("Contributions", f"{stats['contributions']:,}"),
        [(loc_key, "key"), (f" {loc_dots} ", "dim"), (loc_tail, "text"),
         (plus, "add"), (", ", "text"), (minus, "del"), (" )", "text")],
        [(f"{LOGIN}@github", "key"), (":", "text"), ("~", "key"), ("$ ", "text")],
    ]


def render(theme, art, lines):
    c = THEMES[theme]
    info_x = PAD_X + (ART_COLS + GAP) * CHAR_W
    width = round(info_x + INFO_COLS * CHAR_W + PAD_X)
    rows = max(len(art), len(lines))
    height = TOP + rows * LINE_H + 2

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Consolas, Menlo, \'DejaVu Sans Mono\', '
        f'\'Liberation Mono\', monospace" font-size="{FONT_SIZE}px" role="img" '
        f'aria-label="{LOGIN}: web3 growth operator and AI builder">',
        "<style>",
        f".text{{fill:{c['text']}}}.key{{fill:{c['key']}}}.dim{{fill:{c['dim']}}}"
        f".art{{fill:{c['art']}}}.add{{fill:{c['add']}}}.del{{fill:{c['del']}}}",
        "text{white-space:pre}",
        ".l{opacity:0;animation:in .3s ease-out forwards}",
        ".cursor{animation:blink 1.1s steps(1) infinite}",
        "@keyframes in{to{opacity:1}}",
        "@keyframes blink{50%{opacity:0}}",
        "@media (prefers-reduced-motion:reduce){.l{opacity:1;animation:none}.cursor{animation:none}}",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="14" fill="{c["bg"]}"/>',
    ]

    # Portrait draws in first, top to bottom, then the readout types out.
    for i, line in enumerate(art):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        out.append(
            f'<text class="l art" x="{PAD_X + indent * CHAR_W:.1f}" y="{TOP + i * LINE_H}" '
            f'textLength="{len(body) * CHAR_W:.1f}" xml:space="preserve" '
            f'style="animation-delay:{i * 0.03:.2f}s">{escape(body)}</text>'
        )

    start = len(art) * 0.03
    cursor = None
    for i, segments in enumerate(lines):
        if not segments:
            continue
        chars = sum(len(text) for text, _ in segments)
        y = TOP + i * LINE_H
        delay = start + i * 0.07
        spans = "".join(f'<tspan class="{cls}">{escape(text)}</tspan>' for text, cls in segments)
        out.append(
            f'<text class="l" x="{info_x:.1f}" y="{y}" textLength="{chars * CHAR_W:.1f}" '
            f'xml:space="preserve" style="animation-delay:{delay:.2f}s">{spans}</text>'
        )
        cursor = (info_x + chars * CHAR_W, y, delay)

    x, y, delay = cursor
    out.append(
        f'<g class="l" style="animation-delay:{delay:.2f}s"><rect class="cursor key" '
        f'x="{x:.1f}" y="{y - 14}" width="{CHAR_W}" height="18"/></g>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    art = (ROOT / "ascii.txt").read_text().splitlines()
    lines = readout(fetch_stats())
    for theme in THEMES:
        (ROOT / f"{theme}.svg").write_text(render(theme, art, lines))


if __name__ == "__main__":
    main()
