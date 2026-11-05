"""Gera os cards do perfil a partir da API GraphQL do GitHub.

Roda no GitHub Actions, sem depender de servico externo. O texto vira path
porque SVG dentro de <img> nao carrega webfont.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

USER = os.environ.get("PROFILE_USER", "gabrielgws")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "cards")
TZ = ZoneInfo("America/Sao_Paulo")

INK, DEEP, C700, C600, C500, C400 = "#083344", "#155E75", "#0E7490", "#0891B2", "#06B6D4", "#22D3EE"
C300, C200, G200, WHITE = "#67E8F9", "#A5F3FC", "#E5E7EB", "#FFFFFF"

FONT_PATH = Path(__file__).with_name("Outfit.woff2")
FONTS = {w: instantiateVariableFont(TTFont(FONT_PATH), {"wght": w}) for w in (400, 500, 600)}


def ptbr(n):
    return f"{n:,}".replace(",", ".")


def text_width(s, size, weight=400):
    f = FONTS[weight]
    cmap, hmtx = f.getBestCmap(), f["hmtx"]
    return sum(hmtx[cmap.get(ord(c), ".notdef")][0] for c in s) * size / f["head"].unitsPerEm


def text(s, x, y, size, fill, weight=400, anchor="start"):
    f = FONTS[weight]
    glyphs, cmap = f.getGlyphSet(), f.getBestCmap()
    scale = size / f["head"].unitsPerEm
    if anchor == "middle":
        x -= text_width(s, size, weight) / 2
    elif anchor == "end":
        x -= text_width(s, size, weight)
    parts = []
    for c in s:
        g = cmap.get(ord(c), ".notdef")
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        glyphs[g].draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
        parts.append(pen.getCommands())
        x += f["hmtx"][g][0] * scale
    return f'<path d="{"".join(parts)}" fill="{fill}"/>'


def panel(w, h):
    return (f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="14" fill="{INK}" '
            f'stroke="{C300}" stroke-opacity=".3"/>')


def save(name, w, h, title, body):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="{title}"><title>{title}</title>{body}</svg>', encoding="utf-8")


def graphql(query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        raise SystemExit(f"GraphQL: {data['errors']}")
    return data["data"]


COLLECTION = """totalCommitContributions totalPullRequestContributions totalIssueContributions
restrictedContributionsCount contributionCalendar { weeks { contributionDays { date contributionCount } } }"""


def fetch():
    head = graphql("""query($u:String!){user(login:$u){createdAt followers{totalCount}
        contributionsCollection{contributionYears}}}""", {"u": USER})["user"]
    years = head["contributionsCollection"]["contributionYears"]
    alias = " ".join(
        f'y{y}: contributionsCollection(from:"{y}-01-01T00:00:00Z", to:"{y}-12-31T23:59:59Z"){{{COLLECTION}}}'
        for y in years)
    colls = list(graphql(f"query($u:String!){{user(login:$u){{{alias}}}}}", {"u": USER})["user"].values())

    repos, cursor = [], None
    while True:
        page = graphql("""query($u:String!,$c:String){user(login:$u){repositories(first:100,after:$c,
            ownerAffiliations:OWNER,isFork:false){pageInfo{hasNextPage endCursor} nodes{stargazerCount
            languages(first:10,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}}}}}""",
                       {"u": USER, "c": cursor})["user"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return head, years, colls, repos


def mock():
    today = dt.datetime.now(TZ).date()
    days = [{"date": str(today - dt.timedelta(days=i)), "contributionCount": (i * 7) % 11 if i % 9 else 0}
            for i in range(420, -1, -1)]
    head = {"followers": {"totalCount": 12}}
    coll = {"totalCommitContributions": 1432, "totalPullRequestContributions": 38, "totalIssueContributions": 9,
            "restrictedContributionsCount": 210, "contributionCalendar": {"weeks": [{"contributionDays": days}]}}
    repos = [{"stargazerCount": 3, "languages": {"edges": [
        {"size": s, "node": {"name": n}} for n, s in
        [("PHP", 900), ("TypeScript", 700), ("JavaScript", 420), ("Blade", 180), ("Vue", 120), ("CSS", 90), ("HTML", 60)]]}}] * 3
    return head, [2026, 2025, 2024, 2023, 2022], [coll], repos


def summarize(head, years, colls, repos):
    today = dt.datetime.now(TZ).date()
    by_day = {}
    for c in colls:
        for week in c["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                day = dt.date.fromisoformat(d["date"])
                if day <= today:
                    by_day[day] = d["contributionCount"]
    days = sorted(by_day)

    longest = run = 0
    for d in days:
        run = run + 1 if by_day[d] else 0
        longest = max(longest, run)
    current, cursor = 0, today
    if not by_day.get(cursor):
        cursor -= dt.timedelta(days=1)  # hoje ainda pode ter contribuicao
    while by_day.get(cursor):
        current += 1
        cursor -= dt.timedelta(days=1)

    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    return {
        "commits": sum(c["totalCommitContributions"] for c in colls),
        "prs": sum(c["totalPullRequestContributions"] for c in colls),
        "issues": sum(c["totalIssueContributions"] for c in colls),
        "private": sum(c["restrictedContributionsCount"] for c in colls),
        "total": sum(by_day.values()),
        "repos": len(repos),
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": head["followers"]["totalCount"],
        "years": len(years),
        "current": current,
        "longest": longest,
        "langs": sorted(langs.items(), key=lambda kv: -kv[1]),
        "last31": [(today - dt.timedelta(days=i), by_day.get(today - dt.timedelta(days=i), 0)) for i in range(30, -1, -1)],
    }


def card_stats(s):
    w, h = 632, 320
    b = [panel(w, h), text("Números no GitHub", 32, 52, 26, WHITE, 600)]
    rows = [("Commits", s["commits"]), ("Contribuições privadas", s["private"]), ("Pull requests", s["prs"]),
            ("Issues", s["issues"]), ("Repositórios", s["repos"])]
    for i, (label, v) in enumerate(rows):
        y = 104 + i * 42
        b.append(text(label, 32, y, 20, G200))
        b.append(text(ptbr(v), w - 32, y, 22, WHITE, 600, "end"))
        if i < len(rows) - 1:
            b.append(f'<path d="M32 {y+15}H{w-32}" stroke="{C300}" stroke-opacity=".12"/>')
    save("stats.svg", w, h, f"Commits {s['commits']}, contribuições privadas {s['private']}, pull requests {s['prs']}, "
                            f"issues {s['issues']}, repositórios {s['repos']}", "".join(b))


def card_langs(s):
    w, h = 632, 320
    top = s["langs"][:6]
    total = sum(v for _, v in s["langs"]) or 1
    b = [panel(w, h), text("Linguagens", 32, 52, 26, WHITE, 600)]
    shades = [C400, C300, C200, C500, C600, C700]
    maxv = top[0][1] if top else 1
    for i, (name, v) in enumerate(top):
        y = 104 + i * 34
        pct = 100 * v / total
        b.append(text(name, 32, y, 19, G200))
        b.append(f'<rect x="196" y="{y-14}" width="316" height="14" rx="4" fill="{C300}" fill-opacity=".08"/>')
        b.append(f'<rect x="196" y="{y-14}" width="{max(6, 316 * v / maxv):.1f}" height="14" rx="4" fill="{shades[i]}"/>')
        b.append(text(f"{pct:.1f}%".replace(".", ","), w - 32, y, 18, WHITE, 500, "end"))
    alt = ", ".join(f"{n} {100 * v / total:.1f}%" for n, v in top) or "sem dados"
    save("langs.svg", w, h, f"Linguagens: {alt}", "".join(b))


def card_streak(s):
    w, h = 1280, 216
    b = [panel(w, h)]
    cols = [("Contribuições", s["total"], "no total"), ("Sequência atual", s["current"], "dias"),
            ("Maior sequência", s["longest"], "dias")]
    for i, (label, v, unit) in enumerate(cols):
        cx = 213 + i * 427
        big = i == 1
        b.append(text(label, cx, 62, 21, C200, 500, "middle"))
        b.append(text(ptbr(v), cx, 136, 64 if big else 54, WHITE, 600, "middle"))
        b.append(text(unit, cx, 174, 19, G200, 400, "middle"))
        if i:
            b.append(f'<path d="M{cx-213} 40V{h-40}" stroke="{C300}" stroke-opacity=".16"/>')
    save("streak.svg", w, h, f"{s['total']} contribuições, sequência atual de {s['current']} dias, "
                             f"maior sequência de {s['longest']} dias", "".join(b))


def card_activity(s):
    w, h = 1280, 340
    x0, x1, y0, y1 = 72, w - 40, 280, 92
    data = s["last31"]
    top = max(max(v for _, v in data), 1)
    pts = [(x0 + (x1 - x0) * i / 30, y0 - (y0 - y1) * v / top) for i, (_, v) in enumerate(data)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    b = [panel(w, h), text("Atividade nos últimos 31 dias", 32, 52, 26, WHITE, 600),
         f'<defs><linearGradient id="a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{C600}" '
         f'stop-opacity=".55"/><stop offset="1" stop-color="{C600}" stop-opacity="0"/></linearGradient></defs>']
    for t in (0, .5, 1):
        y = y0 - (y0 - y1) * t
        b.append(f'<path d="M{x0} {y}H{x1}" stroke="{C300}" stroke-opacity=".12"/>')
        b.append(text(ptbr(round(top * t)), x0 - 14, y + 6, 16, G200, 400, "end"))
    b.append(f'<polygon points="{x0},{y0} {line} {x1},{y0}" fill="url(#a)"/>')
    b.append(f'<polyline points="{line}" fill="none" stroke="{C400}" stroke-width="2.5" stroke-linejoin="round"/>')
    for x, y in pts:
        b.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{WHITE}"/>')
    for i in range(0, 31, 5):
        b.append(text(data[i][0].strftime("%d/%m"), pts[i][0], y0 + 30, 16, G200, 400, "middle"))
    total = sum(v for _, v in data)
    save("activity.svg", w, h, f"{total} contribuições nos últimos 31 dias", "".join(b))


def rank(v, limits):
    return "DCBAS"[sum(v >= t for t in limits)]


def card_trophies(s):
    w, h = 1280, 216
    items = [("Contribuições", s["total"], (200, 1000, 3000, 8000)), ("Pull requests", s["prs"], (10, 50, 100, 500)),
             ("Repositórios", s["repos"], (5, 20, 50, 100)), ("Sequência", s["longest"], (3, 7, 14, 30)),
             ("Anos ativo", s["years"], (1, 3, 5, 8))]
    b = [panel(w, h)]
    cell = (w - 40) / len(items)
    for i, (label, v, lim) in enumerate(items):
        cx = 20 + cell * i + cell / 2
        r = rank(v, lim)
        b.append(f'<circle cx="{cx:.1f}" cy="82" r="42" fill="{C300}" fill-opacity=".08" stroke="{C400}" stroke-width="2"/>')
        b.append(text(r, cx, 98, 44, WHITE, 600, "middle"))
        b.append(text(label, cx, 156, 19, C200, 500, "middle"))
        b.append(text(ptbr(v), cx, 184, 18, G200, 400, "middle"))
    save("trophies.svg", w, h, "Troféus: " + ", ".join(f"{l} {rank(v, t)}" for l, v, t in items), "".join(b))


def main():
    s = summarize(*(mock() if os.environ.get("MOCK") else fetch()))
    for card in (card_stats, card_langs, card_streak, card_activity, card_trophies):
        card(s)
    print({k: v for k, v in s.items() if k not in ("langs", "last31")})


main()
