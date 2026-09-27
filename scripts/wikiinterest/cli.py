"""Command line for the wiki-interest skill.

`run` does the whole pipeline in one call (resolve -> fetch -> analyze -> charts ->
draft PDF) and prints a compact summary; everything else is written to files so
that a small model never has to hold raw data in its context.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import os

from . import analyze, charts, fetch, helper, report, resolve
from .client import ApiError, Client, NetworkBlocked, OfflineMiss

EXIT_BLOCKED = 4
CHAT_OUTPUTS = Path("/mnt/user-data/outputs")  # claude.ai / Cowork: files here can be handed to the user


# ------------------------------------------------------------- network help

def required_hosts(langs: List[str]) -> List[tuple]:
    """(host, probe url, what it is needed for, required?)"""
    rows = [("wikimedia.org",
             f"{fetch.PV_BASE}/per-article/en.wikipedia/all-access/user/Main_Page/daily/20250101/20250101",
             "pageview numbers", True),
            ("www.wikidata.org", f"{resolve.WD_API}?action=query&meta=siteinfo&format=json",
             "matching the topic across languages", False)]
    for l in langs:
        rows.append((f"{l}.wikipedia.org", f"https://{l}.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json",
                     "article lookup and checks", False))
    return rows


def network_table(client: Client, langs: List[str]) -> tuple:
    lines, blocked = [], []
    for host, url, purpose, req in required_hosts(langs):
        status, detail = client.probe(url)
        if status != "ok":
            blocked.append(host)
        mark = {"ok": "ok     ", "blocked": "BLOCKED", "error": "ERROR  "}[status]
        lines.append(f"  {mark} {host:<22} {purpose}{' (required)' if req else ''} - {detail}")
    return lines, blocked


def settings_help(hosts: List[str]) -> List[str]:
    return [
        "Option A - allow the domains once (recommended), then start a NEW chat and repeat the request:",
        "  domains: " + ", ".join(hosts),
        "  - Free / Pro / Max: Settings > Capabilities > Code execution and file creation >",
        "    Allow network egress, add the domains (https://claude.ai/settings/capabilities)",
        "  - Team / Enterprise: an organization owner adds them in Organization settings >",
        "    Capabilities > network egress to package managers and specific domains",
        "    (https://claude.ai/admin-settings/capabilities)",
        "  - Claude Code / your own machine: nothing to do, the network is normally open.",
    ]


def helper_path(out_dir: Optional[Path]) -> Path:
    if CHAT_OUTPUTS.is_dir() and os.access(CHAT_OUTPUTS, os.W_OK):
        return CHAT_OUTPUTS / "wiki-fetch-data.html"
    return (out_dir or Path("wiki-interest-out")) / "wiki-fetch-data.html"


def blocked_exit(client: Client, err: NetworkBlocked, cfg: dict, out_dir: Optional[Path],
                 report_lang: str) -> int:
    lines, blocked = network_table(client, cfg["langs"])
    hosts = blocked or [err.host]
    page = helper.write_helper(cfg, helper_path(out_dir), report_lang)
    out = ["NETWORK BLOCKED - this environment cannot reach Wikipedia's servers. No data was retrieved.",
           *lines, "",
           "For the agent: tell the user this in their language and offer options A and B.",
           "Do NOT substitute other data sources, web search results or estimates for the numbers.",
           "", *settings_help(hosts), "",
           "Option B - no settings change: the user downloads the public data in their own browser.",
           f"  helper page written: {page}",
           "  1. give this file to the user (in claude.ai: present/share it as a file)",
           "  2. they open it in a browser, click the button, and upload the downloaded wiki-data.json here",
           "  3. then run: python scripts/wiki.py run --import <path of uploaded wiki-data.json> "
           f"--report-lang {report_lang} --out <dir>",
           "     (topic, languages, articles and window are taken from the file)"]
    print("\n".join(out))
    return EXIT_BLOCKED



# ----------------------------------------------------------------- helpers

def slugify(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", s.strip().lower(), flags=re.UNICODE)
    return re.sub(r"-+", "-", s).strip("-")[:60] or "topic"


def month_bounds(start_ym: str, end_ym: str):
    y, m = int(start_ym[:4]), int(start_ym[5:7])
    start = dt.date(y, m, 1)
    y2, m2 = int(end_ym[:4]), int(end_ym[5:7])
    nxt = dt.date(y2 + (m2 == 12), (m2 % 12) + 1, 1)
    return start, nxt - dt.timedelta(days=1)


def default_window(months: int):
    today = dt.date.today()
    last_full = (today.replace(day=1) - dt.timedelta(days=1))  # last day of previous month
    end_ym = last_full.strftime("%Y-%m")
    y, m = last_full.year, last_full.month
    m -= months - 1
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}", end_ym


def parse_overrides(items: Optional[List[str]]) -> Dict[str, str]:
    out = {}
    for it in items or []:
        m = resolve.LANG_TITLE_RE.match(it.strip())
        if not m:
            sys.exit(f"--article must look like lang:Title, got {it!r}")
        out[m.group(1)] = m.group(2).replace("_", " ")
    return out


def fmt(v, pct=False):
    if v is None:
        return "n/a"
    if pct:
        return f"{v:+.0f}%"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"


# ---------------------------------------------------------------- commands

def cmd_run(a: argparse.Namespace) -> int:
    notes: List[str] = []
    imported = None
    if a.import_file:
        bundle = helper.load_bundle(Path(a.import_file))
        bc = bundle["config"]
        if a.langs and [l.strip() for l in a.langs.split(",")] != bc["langs"]:
            sys.exit(f"--import: the data file was made for --langs {','.join(bc['langs'])}; "
                     "generate a new helper page for other languages")
        a.topic, a.topic_lang, a.langs = bc["topic"], bc["topic_lang"], ",".join(bc["langs"])
        a.frm, a.to = bc["start"][:7], bc["end"][:7]
        a.article = [f"{l}:{t}" for l, t in bc.get("overrides", {}).items()]
        imported = helper.import_bundle(bundle)
        a.offline = True
        notes.append(f"data imported from {a.import_file} ({imported} API responses fetched in the "
                     f"user's browser on {bundle.get('created_at', '?')[:10]})")
    if not a.topic or not a.langs:
        sys.exit("--topic and --langs are required (or --import <wiki-data.json>)")
    client = Client(offline=a.offline)
    langs = [l.strip() for l in a.langs.split(",") if l.strip()]
    if not langs:
        sys.exit("--langs is required, e.g. --langs pl,cs")
    if a.frm and a.to:
        start_ym, end_ym = a.frm, a.to
    else:
        start_ym, end_ym = default_window(a.months)
    start, end = month_bounds(start_ym, end_ym)
    if start < fetch.DATA_START:
        start = fetch.DATA_START
        print(f"note: Pageviews data starts 2015-07-01; window clipped", file=sys.stderr)
    if end >= dt.date.today():
        sys.exit("--to must be a completed month (partial months distort monthly growth)")
    overrides = parse_overrides(a.article)
    cfg = helper.build_config(a.topic, a.topic_lang, langs, overrides, start, end)
    out_hint = Path(a.out) if a.out else None

    try:
        res = resolve.resolve_topic(client, a.topic, langs, topic_lang=a.topic_lang,
                                    overrides=dict(overrides))
    except NetworkBlocked as e:
        return blocked_exit(client, e, cfg, out_hint, a.report_lang)
    except OfflineMiss as e:
        sys.exit(f"offline: {e}" + (" - the imported file does not cover this request; "
                                    "generate a new helper page" if imported is not None else ""))
    except ApiError as e:
        sys.exit(f"resolve failed: {e}")
    notes += res.get("notes", [])

    out_dir = Path(a.out) if a.out else Path("wiki-interest-out") / slugify(res["label"] or a.topic)
    out_dir.mkdir(parents=True, exist_ok=True)

    results, dailies, skipped = [], {}, []
    for lang in langs:
        art = res["articles"].get(lang) or {}
        title = art.get("title")
        if not title:
            skipped.append(f"{lang}: {art.get('note', 'no article')}")
            continue
        try:
            user, had = fetch.article_daily(client, lang, title, start, end, agent="user")
            user_main = dict(user)
            alls, _ = fetch.article_daily(client, lang, title, start, end, agent="all-agents")
            proj = fetch.project_daily(client, lang, start, end, agent="user")
        except NetworkBlocked as e:
            return blocked_exit(client, e, cfg, out_hint, a.report_lang)
        except OfflineMiss as e:
            sys.exit(f"offline: {e}" + (" - the imported file does not cover this request; "
                                        "generate a new helper page" if imported is not None else ""))
        except ApiError as e:
            skipped.append(f"{lang}: {e}")
            continue
        # Optional extras: without them the analysis still stands, with a note.
        titles = [title]
        if a.include_redirects:
            try:
                for rt in fetch.redirects_to(client, lang, title):
                    s_, _ = fetch.article_daily(client, lang, rt, start, end, agent="user")
                    for k in user:
                        user[k] += s_.get(k, 0)
                    titles.append(rt)
            except (NetworkBlocked, OfflineMiss):
                user, titles = dict(user_main), [title]
                notes.append(f"{lang}: redirects not summed (not available in this environment/data file)")
        try:
            created = fetch.first_revision_date(client, lang, title)
        except (NetworkBlocked, OfflineMiss):
            created = None
            notes.append(f"{lang}: article creation date unavailable - article_age check skipped")
        meta = {"lang": lang, "title": title, "had_data": had, "created": created,
                "via": art.get("via"), "redirects_summed": titles[1:],
                "user_main_daily": user_main}  # bot share compares like with like
        r = analyze.analyze_series(user, alls, proj, meta)
        r["resolve_note"] = art.get("note", "")
        r["redirects_summed"] = titles[1:]
        results.append(r)
        dailies[lang] = user

    if not results:
        sys.exit("no data for any language: " + "; ".join(skipped))

    comparison = analyze.compare(results, a.rank_by)
    rl = a.report_lang
    files = {}
    files["overview_png"] = str(charts.overview_chart(results, out_dir / "overview.png", rl, res["label"] or a.topic))
    files["indexed_png"] = str(charts.indexed_chart(results, out_dir / "indexed.png", rl))
    for r in results:
        files[f"daily_{r['lang']}_png"] = str(charts.daily_chart(r, dailies[r["lang"]], out_dir / f"daily_{r['lang']}.png", rl))

    # CSV of every daily point: the raw material for anyone who wants to re-check.
    csv_path = out_dir / "series.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "lang", "article", "user_views", "despiked_views"])
        for r in results:
            d = dailies[r["lang"]]
            for day in sorted(d):
                w.writerow([day, r["lang"], r["title"], d[day], analyze.detect_spikes(d)["despiked"][day]])
    files["series_csv"] = str(csv_path)

    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "topic": {"query": a.topic, "qid": res["qid"], "label": res["label"],
                  "description": res["description"], "candidates": res["candidates"]},
        "window": {"from": start_ym, "to": end_ym, "start": start.isoformat(), "end": end.isoformat()},
        "languages": langs, "skipped": skipped, "articles": res["articles"], "notes": notes,
        "results": results, "comparison": comparison, "files": files,
        "cache": client.stats,
    }
    results_path = out_dir / "results.json"
    files["results_json"] = str(results_path)
    if not a.no_report:
        pdf = out_dir / "report.pdf"
        report.build_pdf(results, comparison, Path(files["overview_png"]), pdf, rl,
                         topic=res["label"] or a.topic)
        files["report_pdf"] = str(pdf)
    payload["files"] = files
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))

    if a.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0
    print(summary_text(payload))
    return 0


def summary_text(p: dict) -> str:
    res = p["results"]
    t = p["topic"]
    lines = [f"# wiki-interest: {t['label'] or t['query']} ({t['qid'] or 'no Wikidata item'})"
             f" — {', '.join(p['languages'])} — {p['window']['from']}..{p['window']['to']}"]
    if t.get("description"):
        lines.append(f"Concept: {t['description']}")
    red = {r["lang"]: r.get("redirects_summed") or [] for r in res}
    lines.append("Resolved: " + " | ".join(
        f"{l}: {a.get('title') or '—'} ({a.get('via')})"
        + (f" +{len(red[l])} redirects summed" if red.get(l) else "")
        + (f" ⚠ {a['note']}" if a.get("note") else "")
        for l, a in p["articles"].items()))
    created = [f"{r['lang']} {r['created']}" for r in res if r.get("created")]
    if created:
        lines.append("Article created: " + ", ".join(created))
    if p["skipped"]:
        lines.append("Skipped: " + "; ".join(p["skipped"]))
    for n in p.get("notes", []):
        lines.append(f"Note: {n}")
    lines.append("")
    lines.append("| lang | views/day | YoY | YoY w/o spikes | last 3m vs yr ago (w/o spikes) | trend/yr (R²) | per 1M edition | share YoY | edition YoY | spikes % | bots % | confidence |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        lines.append("| " + " | ".join([
            r["lang"], fmt(r["avg_daily_views"]), fmt(r["yoy_pct"], True), fmt(r["yoy_despiked_pct"], True),
            fmt(r["recent_3m_vs_year_ago_pct"], True),
            f"{fmt(r['trend_annualised_pct'], True)} ({r['trend_r2'] if r['trend_r2'] is not None else 'n/a'})",
            fmt(r["share_per_million_last12"]), fmt(r["share_yoy_pct"], True), fmt(r["project_yoy_pct"], True),
            fmt(r["spikes"]["spike_share_pct"]), fmt(r["bot_share_pct"]), r["trust"]["verdict"]]) + " |")
    lines.append("")
    c = p["comparison"]
    lines.append(f"Ranking ({c['rank_by']}: {c['formula']}): " + "; ".join(
        f"{w['rank']}. {w['lang']}" + (f" (score {w['balanced_score']})" if "balanced_score" in w else "")
        for w in c["table"]))
    lines.append("")
    lines.append("Trust notes:")
    for r in res:
        iss = r["trust"]["issues"]
        lines.append(f"- {r['lang']} — {r['trust']['verdict']} ({r['trust']['score']}/100): " +
                     ("; ".join(f"[{i['status']}] {i['detail']}" for i in iss) if iss else "all checks passed"))
    sp = [(r["lang"], s) for r in res for s in r["spikes"]["top_spikes"][:3]]
    if sp:
        lines.append("Top spike events (peak day, peak views, x local baseline, length): " + "; ".join(
            f"{l} {s['peak']} ({s['views']:,}, {s['x_baseline']}x, {s['days']}d)" for l, s in sp))
    seas = [f"{r['lang']} peak {r['peak_month']} / trough {r['trough_month']} (index {r['seasonality_index']})"
            for r in res if r.get("peak_month")]
    if seas:
        lines.append("Seasonality: " + "; ".join(seas))
    lines.append("")
    lines.append("Files: " + ", ".join(f"{k}={v}" for k, v in p["files"].items()))
    st = p["cache"]
    lines.append(f"Cache: {st['hits']} hits, {st['misses']} misses, {st['requests']} API requests")
    lines.append("Next: read the table + trust notes, write narrative.json (title, recommendation, caveats) "
                 "and run `report` to finalise the PDF.")
    return "\n".join(lines)


def cmd_report(a: argparse.Namespace) -> int:
    p = json.loads(Path(a.results).read_text())
    narrative = json.loads(Path(a.narrative).read_text()) if a.narrative else {}
    if a.recommendation:
        narrative["recommendation"] = a.recommendation
    if a.title:
        narrative["title"] = a.title
    out = Path(a.out) if a.out else Path(p["files"]["results_json"]).parent / "report.pdf"
    chart = Path(p["files"]["overview_png"])
    report.build_pdf(p["results"], p["comparison"], chart, out, a.lang,
                     topic=p["topic"]["label"] or p["topic"]["query"], narrative=narrative)
    print(f"PDF written: {out}")
    return 0


def cmd_resolve(a: argparse.Namespace) -> int:
    client = Client(offline=a.offline)
    langs = [l.strip() for l in a.langs.split(",") if l.strip()]
    res = resolve.resolve_topic(client, a.topic, langs, topic_lang=a.topic_lang,
                                overrides=parse_overrides(a.article))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_top(a: argparse.Namespace) -> int:
    client = Client(offline=a.offline)
    y, m = int(a.month[:4]), int(a.month[5:7])
    rows = fetch.top_articles(client, a.lang, y, m, a.limit)
    print(f"Top {len(rows)} articles on {a.lang}.wikipedia, {a.month} (all agents, all access):")
    for r in rows:
        print(f"{r['rank']:>4}. {r['article']} — {r['views']:,}")
    return 0


def cmd_fetch(a: argparse.Namespace) -> int:
    client = Client(offline=a.offline)
    start, end = month_bounds(a.frm, a.to)
    m = resolve.LANG_TITLE_RE.match(a.article)
    if not m:
        sys.exit("--article must look like lang:Title")
    lang, title = m.group(1), m.group(2).replace("_", " ")
    series, had = fetch.article_daily(client, lang, title, start, end, agent=a.agent)
    w = csv.writer(sys.stdout)
    w.writerow(["date", "views"])
    for d in sorted(series):
        w.writerow([d, series[d]])
    if not had:
        print("warning: API returned no data for this title/window", file=sys.stderr)
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    langs = [l.strip() for l in (a.langs or "en").split(",") if l.strip()]
    lines, blocked = network_table(Client(), langs)
    print("Network check for wiki-interest:")
    print("\n".join(lines))
    if not blocked:
        print("All hosts reachable - `run` will work here.")
        return 0
    print("")
    print("\n".join(settings_help(blocked)))
    print("Option B - no settings change: `python scripts/wiki.py helper --topic ... --langs ...` "
          "writes a page the user opens in their browser to download the data.")
    return EXIT_BLOCKED


def cmd_helper(a: argparse.Namespace) -> int:
    langs = [l.strip() for l in a.langs.split(",") if l.strip()]
    start_ym, end_ym = (a.frm, a.to) if a.frm and a.to else default_window(a.months)
    start, end = month_bounds(start_ym, end_ym)
    cfg = helper.build_config(a.topic, a.topic_lang, langs, parse_overrides(a.article), start, end)
    path = Path(a.out) if a.out else helper_path(None)
    helper.write_helper(cfg, path, a.report_lang)
    print(f"helper page written: {path}")
    print("Give it to the user; they open it, click the button, upload wiki-data.json; then run:")
    print(f"  python scripts/wiki.py run --import <uploaded wiki-data.json> --report-lang {a.report_lang} --out <dir>")
    return 0


# ------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="wiki.py", description="Wikipedia interest analysis")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--offline", action="store_true", help="use only cached responses")

    r = sub.add_parser("run", help="full pipeline: resolve, fetch, analyze, charts, draft PDF")
    r.add_argument("--topic", help='topic text, "Q123" or "lang:Title"')
    r.add_argument("--langs", help="comma-separated language codes, e.g. pl,cs")
    r.add_argument("--import", dest="import_file",
                   help="wiki-data.json downloaded with the helper page (no network needed)")
    r.add_argument("--topic-lang", default="en", help="language the --topic text is written in")
    r.add_argument("--article", action="append", help="override: lang:Title (repeatable)")
    r.add_argument("--from", dest="frm", help="YYYY-MM first month (with --to)")
    r.add_argument("--to", help="YYYY-MM last completed month")
    r.add_argument("--months", type=int, default=24, help="window length if --from/--to not given")
    r.add_argument("--include-redirects", action="store_true", help="add views of redirect titles")
    r.add_argument("--rank-by", default="balanced", choices=["balanced", "growth", "volume", "share"])
    r.add_argument("--report-lang", default="en", help="labels language for charts/PDF (en, uk, pl)")
    r.add_argument("--out", help="output directory")
    r.add_argument("--no-report", action="store_true")
    r.add_argument("--json", action="store_true", help="print full results JSON instead of summary")
    common(r)
    r.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="rebuild the PDF from results.json with your narrative")
    p.add_argument("--results", required=True)
    p.add_argument("--narrative", help="JSON: {title, recommendation, trust:[..], caveats:[..]}")
    p.add_argument("--recommendation")
    p.add_argument("--title")
    p.add_argument("--lang", default="en")
    p.add_argument("--out")
    p.set_defaults(func=cmd_report)

    s = sub.add_parser("resolve", help="show which article each language maps to")
    s.add_argument("--topic", required=True)
    s.add_argument("--langs", required=True)
    s.add_argument("--topic-lang", default="en")
    s.add_argument("--article", action="append")
    common(s)
    s.set_defaults(func=cmd_resolve)

    t = sub.add_parser("top", help="most viewed articles of an edition for a month")
    t.add_argument("--lang", required=True)
    t.add_argument("--month", required=True, help="YYYY-MM")
    t.add_argument("--limit", type=int, default=40)
    common(t)
    t.set_defaults(func=cmd_top)

    c = sub.add_parser("check", help="test whether this environment can reach Wikimedia")
    c.add_argument("--langs", default="en")
    c.set_defaults(func=cmd_check)

    h = sub.add_parser("helper", help="write the browser page for environments without network")
    h.add_argument("--topic", required=True)
    h.add_argument("--langs", required=True)
    h.add_argument("--topic-lang", default="en")
    h.add_argument("--article", action="append")
    h.add_argument("--from", dest="frm")
    h.add_argument("--to")
    h.add_argument("--months", type=int, default=24)
    h.add_argument("--report-lang", default="en", help="language of the page (en, uk, pl)")
    h.add_argument("--out", help="path of the HTML file")
    h.set_defaults(func=cmd_helper)

    f = sub.add_parser("fetch", help="raw daily series for one article as CSV")
    f.add_argument("--article", required=True, help="lang:Title")
    f.add_argument("--from", dest="frm", required=True)
    f.add_argument("--to", required=True)
    f.add_argument("--agent", default="user", choices=["user", "all-agents", "spider", "automated"])
    common(f)
    f.set_defaults(func=cmd_fetch)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except BrokenPipeError:
        return 0
    except NetworkBlocked as e:
        print(f"NETWORK BLOCKED: {e}. Run `python scripts/wiki.py check` for what to change, "
              "or use the helper page (`wiki.py helper`). Do not substitute other data.")
        return EXIT_BLOCKED
    except ApiError as e:
        print(f"API error: {e}", file=sys.stderr)
        return 2
    except OfflineMiss as e:
        print(f"offline miss: {e}", file=sys.stderr)
        return 3
