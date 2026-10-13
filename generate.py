#!/usr/bin/env python3
"""Builds dark.svg and light.svg, the terminal card shown on the GitHub profile,
and snake.svg, the contribution map with a snake crawling over it.

Reads the portrait point cloud from dots.json (made by portrait.py), pulls live
numbers from the GitHub GraphQL API, and writes both themes. Needs a token in GH_TOKEN that can see private
repos, otherwise the stats only count public work. update.sh supplies one from
the local GitHub CLI login, regenerates, commits and pushes:

    ./update.sh
"""
import datetime
import json
import os
import pathlib
import random
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
INFO_COLS = 54
PILL_FONT = 13
PILL_CHAR_W = 7.8
PILL_H = 22
PILL_ROW_H = 28

# Left column: the framed portrait with the stat tiles under it.
MAP_W = 422
MAP_TOP = 44
MAP_PAD = 14
INFO_X = PAD_X + MAP_W + 30
TILE_H = 62
DOT_GROUPS = 36

TOOLS = ["Claude", "OpenAI", "Grok", "Hermes", "Higgsfield", "Notion AI", "Cursor", "Bots"]
STACK = [
    ("Frontend", ["Next.js", "React", "TypeScript"]),
    ("Backend", ["Python", "Node.js", "Telegram Bot API", "Discord API"]),
    ("Database", ["PostgreSQL", "Supabase", "Sanity"]),
    ("Cloud & Security", ["Vercel", "Railway", "Docker", "Privy"]),
    ("Payment", ["Solana"]),
]

THEMES = {
    "dark": {
        "bg": "#0d1117", "text": "#c9d1d9", "key": "#ff7a4d", "dim": "#3d4654",
        "art": "#8b96a3", "panel": "#131a23",
    },
    "light": {
        "bg": "#fbfaf7", "text": "#1a1712", "key": "#d8431a", "dim": "#cfc9bd",
        "art": "#7a7264", "panel": "#f4f1ea",
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
                }
              }
            } }""", cursor=cursor)["viewer"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

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
    }


def fetch_calendar():
    """The last year of contributions as (total, weeks); each week is a list of
    (weekday, count, level 0-4, date)."""
    calendar = gql("""{ viewer { contributionsCollection { contributionCalendar {
        totalContributions
        weeks { contributionDays { weekday contributionCount contributionLevel date } }
    } } } }""")["viewer"]["contributionsCollection"]["contributionCalendar"]
    levels = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
    weeks = [
        [(d["weekday"], d["contributionCount"], levels.index(d["contributionLevel"]), d["date"])
         for d in week["contributionDays"]]
        for week in calendar["weeks"]
    ]
    return calendar["totalContributions"], weeks


SNAKE_LEVELS = ["#ebe6dc", "#f6cdbd", "#f0a184", "#e76f47", "#d8431a"]
SNAKE_LOOP = 32  # seconds for one lap of the board
SNAKE_SEGMENTS = 6
REGROW = 0.34  # share of the lap a cell stays eaten before it grows back


def render_snake(total, weeks):
    """Contribution grid in the light card style. The snake sweeps the columns
    in a zigzag, each cell empties as the head reaches it and grows back later,
    and a lane under the grid brings the snake home so the lap repeats forever."""
    c = THEMES["light"]
    width = round(INFO_X + INFO_COLS * CHAR_W + PAD_X)
    pitch = (width - 2 * PAD_X) / len(weeks)
    cell = pitch - 4
    top = 58
    height = round(top + 8 * pitch + 14)

    def center(col, row):
        return PAD_X + col * pitch + pitch / 2, top + row * pitch + pitch / 2

    # Zigzag over every slot of the grid, then back along the lane below it.
    route = []
    for col in range(len(weeks)):
        rows = range(7) if col % 2 == 0 else range(6, -1, -1)
        route += [(col, row) for row in rows]
    points = [center(col, row) for col, row in route]
    points += [center(route[-1][0], 7), center(0, 7), points[0]]
    lengths = [0.0]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        lengths.append(lengths[-1] + abs(x2 - x1) + abs(y2 - y1))
    reach = {slot: lengths[i] / lengths[-1] * SNAKE_LOOP for i, slot in enumerate(route)}
    path = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Consolas, Menlo, \'DejaVu Sans Mono\', '
        f'\'Liberation Mono\', monospace" role="img" '
        f'aria-label="{total:,} contributions in the last year">',
        "<style>",
        f".label{{fill:{c['art']}}}.text{{fill:{c['text']}}}.key{{fill:{c['key']}}}",
        "".join(f".v{i}{{--c:{color}}}" for i, color in enumerate(SNAKE_LEVELS)),
        f".d{{fill:var(--c)}}.e{{animation:eat {SNAKE_LOOP}s linear infinite}}",
        f"@keyframes eat{{0%,{REGROW * 100:.0f}%{{fill:{SNAKE_LEVELS[0]}}}"
        f"{REGROW * 100 + 8:.0f}%,100%{{fill:var(--c)}}}}",
        "@media (prefers-reduced-motion:reduce){.e{animation:none}}",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="14" fill="{c["bg"]}"/>',
        f'<text class="label" x="{PAD_X}" y="24" font-size="11px" letter-spacing="2.5">CONTRIBUTION.MAP</text>',
        f'<text font-size="13px" text-anchor="end" x="{width - PAD_X}" y="24">'
        f'<tspan class="key" font-weight="bold">{total:,}</tspan>'
        f'<tspan class="label"> contributions in the last year</tspan></text>',
    ]

    month = None
    for col, week in enumerate(weeks):
        first = week[0][3]
        if first[5:7] != month and col < len(weeks) - 1:
            month = first[5:7]
            name = datetime.date.fromisoformat(first).strftime("%b")
            out.append(f'<text class="label" font-size="10.5px" x="{PAD_X + col * pitch + 2:.1f}" y="{top - 8}">{name}</text>')
        for weekday, count, level, _ in week:
            x, y = center(col, weekday)
            eaten = f' class="d v{level} e" style="animation-delay:{reach[(col, weekday)]:.2f}s"' if level else ' class="d v0"'
            out.append(f'<rect{eaten} x="{x - cell / 2:.1f}" y="{y - cell / 2:.1f}" '
                       f'width="{cell:.1f}" height="{cell:.1f}" rx="3"/>')

    out.append(f'<path id="route" d="{path}" fill="none"/>')
    lag = pitch / lengths[-1] * SNAKE_LOOP * 0.92
    for i in reversed(range(SNAKE_SEGMENTS)):
        size = cell * (1.12 - 0.09 * i)
        fill = c["text"] if i else c["key"]
        out.append(
            f'<rect x="{-size / 2:.1f}" y="{-size / 2:.1f}" width="{size:.1f}" height="{size:.1f}" '
            f'rx="{size * 0.3:.1f}" fill="{fill}" visibility="hidden">'
            f'<set attributeName="visibility" to="visible" begin="{i * lag:.2f}s"/>'
            f'<animateMotion dur="{SNAKE_LOOP}s" begin="{i * lag:.2f}s" repeatCount="indefinite">'
            f'<mpath href="#route"/></animateMotion></rect>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


# The readout is a list of blocks drawn top to bottom. A text block is a list
# of (text, css class) segments INFO_COLS wide; the others are tagged tuples.

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


GAP = ("gap",)


LABEL_COLS = 17  # width reserved for a stack group's label


def pill_rows(label, items):
    """Splits pills into as many rows as the readout width needs. Rows after
    the first carry an empty label so they stay indented under the pills."""
    room = (INFO_COLS - (LABEL_COLS if label else 0)) * CHAR_W
    rows, used = [[]], 0
    for item in items:
        width = len(item) * PILL_CHAR_W + 18 + 7
        if rows[-1] and used + width - 7 > room:
            rows.append([])
            used = 0
        rows[-1].append(item)
        used += width
    return [("pills", label if i == 0 else label and "", row) for i, row in enumerate(rows)]


def readout():
    return [
        [(f"{LOGIN}@github", "text"), (" " + "-" * (INFO_COLS - len(LOGIN) - 8), "dim")],
        row("Role", "AI Engineer + GTM Engineer"),
        row("Status", "Building usevano.io"),
        row("Uptime", "5+ years scaling protocols"),
        row("Host", "Working globally"),
        GAP,
        heading("Tools"),
        *pill_rows(None, TOOLS),
        GAP,
        heading("Stack"),
        *[block for label, items in STACK for block in pill_rows(label, items)],
        GAP,
        heading("Builds"),
        row("gtmquant.com", "GTM engine for any business"),
        row("usevano.io", "Personal trading assistant"),
        row("memecoins-trading-agent", "Autonomous trading agent"),
        row("content-creator-skills", "Content engine for LLMs"),
        GAP,
        heading("Track Record"),
        row("Revenue", "$10M+ generated"),
        row("Impressions", "250M+ driven"),
        row("Distributed", "$5M+ to communities"),
        pair("Communities", "50+", "Projects", "200+"),
        pair("Creators", "2K+", "Trading tools", "5+"),
        row("Audience", "120K+ across platforms"),
        GAP,
        heading("Contact"),
        row("Web", "thegreatola.com"),
        row("X", "@thegreatola"),
        row("LinkedIn", "in/olamilekan-majekodunmi"),
        GAP,
        [(f"{LOGIN}@github", "key"), (":", "text"), ("~", "key"), ("$ ", "text")],
    ]


def compact(n):
    for size, suffix in ((1_000_000, "M"), (1_000, "K")):
        if n >= size * 10:
            return f"{n / size:.0f}{suffix}"
        if n >= size:
            return f"{n / size:.1f}{suffix}"
    return str(n)


def render_readout(blocks, start):
    """Returns the svg lines, the y of the bottom, and where the cursor goes."""
    out, y, cursor = [], TOP, None
    for i, block in enumerate(blocks):
        delay = start + i * 0.06
        anim = f'style="animation-delay:{delay:.2f}s"'
        if block is GAP:
            y += LINE_H
        elif block[0] == "pills":
            _, label, items = block
            x = INFO_X
            out.append(f'<g class="l" {anim}>')
            if label:
                out.append(
                    f'<text class="key" x="{x:.1f}" y="{y + 2}" textLength="{len(label) * CHAR_W:.1f}" '
                    f'xml:space="preserve">{escape(label)}</text>'
                )
            if label is not None:
                x += LABEL_COLS * CHAR_W
            for item in items:
                width = len(item) * PILL_CHAR_W + 18
                out.append(
                    f'<rect class="pill" x="{x:.1f}" y="{y - 14}" width="{width:.1f}" '
                    f'height="{PILL_H}" rx="{PILL_H / 2}"/>'
                    f'<text class="text" font-size="{PILL_FONT}px" x="{x + 9:.1f}" y="{y + 1}" '
                    f'textLength="{len(item) * PILL_CHAR_W:.1f}" xml:space="preserve">{escape(item)}</text>'
                )
                x += width + 7
            out.append("</g>")
            y += PILL_ROW_H
        else:
            chars = sum(len(text) for text, _ in block)
            spans = "".join(f'<tspan class="{cls}">{escape(text)}</tspan>' for text, cls in block)
            out.append(
                f'<text class="l" x="{INFO_X:.1f}" y="{y}" textLength="{chars * CHAR_W:.1f}" '
                f'xml:space="preserve" {anim}>{spans}</text>'
            )
            cursor = (INFO_X + chars * CHAR_W, y, delay)
            y += LINE_H
    x, cy, delay = cursor
    out.append(
        f'<g class="l" style="animation-delay:{delay:.2f}s"><rect class="cursor key" '
        f'x="{x:.1f}" y="{cy - 14}" width="{CHAR_W}" height="18"/></g>'
    )
    return out, y - LINE_H + 8


def render_map(portrait, bottom):
    """The framed dot portrait. Dots are split into groups that drift in from
    scattered offsets, so the face assembles out of loose particles, on a loop."""
    x0, y0 = PAD_X, MAP_TOP
    height = bottom - y0
    scale = min((MAP_W - 2 * MAP_PAD) / portrait["width"], (height - 2 * MAP_PAD) / portrait["height"])
    off_x = x0 + (MAP_W - portrait["width"] * scale) / 2
    off_y = y0 + height - MAP_PAD - portrait["height"] * scale
    out = [
        f'<text class="label" x="{x0}" y="{y0 - 12}" font-size="11px" letter-spacing="2.5">VISUAL.MAP</text>',
        f'<rect class="frame" x="{x0}" y="{y0}" width="{MAP_W}" height="{height}" rx="6"/>',
    ]
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x0 + MAP_W, y0, -1, 1),
                           (x0, y0 + height, 1, -1), (x0 + MAP_W, y0 + height, -1, -1)):
        out.append(f'<path class="corner" d="M{cx + 16 * sx} {cy}H{cx}V{cy + 16 * sy}"/>')

    rng = random.Random(11)
    groups = [[] for _ in range(DOT_GROUPS)]
    for dot in portrait["dots"]:
        rng.choice(groups).append(dot)
    for i, dots in enumerate(groups):
        cls = "p accent" if i % 9 == 0 else "p"
        style = (f"--dx:{rng.uniform(-70, 70):.0f}px;--dy:{rng.uniform(-90, 90):.0f}px;"
                 f"--fx:{rng.uniform(-1.6, 1.6):.1f}px;--fy:{rng.uniform(-1.6, 1.6):.1f}px;"
                 f"animation-delay:{rng.uniform(0, 0.9):.2f}s")
        path = "".join(f"M{off_x + x * scale:.1f} {off_y + y * scale:.1f}h0" for x, y in dots)
        out.append(f'<path class="{cls}" style="{style}" d="{path}"/>')
    return out


def render_tiles(stats, top):
    tiles = [
        (f"{stats['repos']:,}", "repos"),
        (f"{stats['stars']:,}", "stars"),
        (f"{stats['contributions']:,}", "contributions"),
        (compact(stats["added"] - stats["deleted"]), "lines of code"),
    ]
    gap = 10
    width = (MAP_W - gap * (len(tiles) - 1)) / len(tiles)
    out = []
    for i, (value, label) in enumerate(tiles):
        x = PAD_X + i * (width + gap)
        out.append(
            f'<g class="l" style="animation-delay:{1.2 + i * 0.12:.2f}s">'
            f'<rect class="tile" x="{x:.1f}" y="{top}" width="{width:.1f}" height="{TILE_H}" rx="8"/>'
            f'<text class="text" font-size="19px" font-weight="bold" text-anchor="middle" '
            f'x="{x + width / 2:.1f}" y="{top + 28}">{value}</text>'
            f'<text class="label" font-size="10.5px" text-anchor="middle" '
            f'x="{x + width / 2:.1f}" y="{top + 46}">{label}</text></g>'
        )
    return out


def render(theme, portrait, stats):
    c = THEMES[theme]
    info, info_bottom = render_readout(readout(), 0.3)
    tiles_top = info_bottom - TILE_H
    width = round(INFO_X + INFO_COLS * CHAR_W + PAD_X)
    height = info_bottom + 16

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Consolas, Menlo, \'DejaVu Sans Mono\', '
        f'\'Liberation Mono\', monospace" font-size="{FONT_SIZE}px" role="img" '
        f'aria-label="{LOGIN}: AI agents, workflow automation and products">',
        "<style>",
        f".text{{fill:{c['text']}}}.key{{fill:{c['key']}}}.dim{{fill:{c['dim']}}}"
        f".label{{fill:{c['art']}}}",
        f".frame{{fill:{c['panel']};stroke:{c['dim']}}}"
        f".corner{{fill:none;stroke:{c['key']};stroke-width:2}}",
        f".pill,.tile{{fill:{c['panel']};stroke:{c['dim']}}}",
        f".p{{fill:none;stroke:{c['text']};stroke-width:1.8;stroke-linecap:round;"
        "animation:cycle 11s ease-in-out infinite both}",
        f".accent{{stroke:{c['key']}}}",
        "text{white-space:pre}",
        ".l{opacity:0;animation:in .3s ease-out forwards}",
        ".cursor{animation:blink 1.1s steps(1) infinite}",
        "@keyframes in{to{opacity:1}}",
        "@keyframes blink{50%{opacity:0}}",
        # One endless loop: particles gather into the face, hold with a slight
        # drift, break apart the opposite way, then gather again.
        "@keyframes cycle{0%{opacity:0;transform:translate(var(--dx),var(--dy))}"
        "14%{opacity:1;transform:translate(0,0)}"
        "45%{opacity:1;transform:translate(var(--fx),var(--fy))}"
        "76%{opacity:1;transform:translate(0,0)}"
        "100%{opacity:0;transform:translate(calc(var(--dx)*-1),calc(var(--dy)*-1))}}",
        "@media (prefers-reduced-motion:reduce){.l{opacity:1;animation:none}"
        ".cursor,.p{animation:none}}",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="14" fill="{c["bg"]}"/>',
    ]
    out += render_map(portrait, tiles_top - 12)
    out += render_tiles(stats, tiles_top)
    out += info
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    portrait = json.loads((ROOT / "dots.json").read_text())
    stats = fetch_stats()
    for theme in THEMES:
        (ROOT / f"{theme}.svg").write_text(render(theme, portrait, stats))
    (ROOT / "snake.svg").write_text(render_snake(*fetch_calendar()))


if __name__ == "__main__":
    main()
