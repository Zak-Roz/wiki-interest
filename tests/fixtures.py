"""Seed the response cache with synthetic-but-realistic API answers.

Why: the real Wikimedia API is not reachable in every CI/sandbox, and tests
must be deterministic. The fixtures go through the SAME url builders and cache
the pipeline uses, so `wiki.py run --offline` exercises every code path
(resolution, 404 handling, spikes, bots, normalisation, charts, PDF).

Usage:
    WIKI_CACHE_DIR=/tmp/wi-cache python tests/fixtures.py            # seed all
    WIKI_CACHE_DIR=/tmp/wi-cache python scripts/wiki.py run --offline ...
"""
from __future__ import annotations

import datetime as dt
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wikiinterest import fetch, resolve  # noqa: E402
from wikiinterest.cli import default_window, month_bounds  # noqa: E402
from wikiinterest.client import cache_put  # noqa: E402


def gen_daily(start: dt.date, end: dt.date, base: float, yoy: float, season_amp: float = 0.0,
              peak_month: int = 1, spikes=(), noise: float = 0.08, seed: int = 1,
              created: dt.date | None = None):
    """Daily series with compound growth, sinusoidal seasonality, weekly rhythm,
    lognormal noise and optional spikes (date, multiplier, decay_days)."""
    rng = random.Random(seed)
    out = {}
    n = (end - start).days + 1
    d = start
    for i in range(n):
        if created and d < created:
            out[d.isoformat()] = 0
            d += dt.timedelta(days=1)
            continue
        growth = (1 + yoy) ** (i / 365.0)
        phase = 2 * math.pi * ((d.timetuple().tm_yday - (peak_month - 1) * 30.4) / 365.0)
        season = 1 + season_amp * math.cos(phase)
        weekly = 0.93 if d.weekday() >= 5 else 1.02
        v = base * growth * season * weekly * math.exp(rng.gauss(0, noise))
        for sd, mult, decay in spikes:
            age = (d - sd).days
            if 0 <= age < 30:
                v *= 1 + (mult - 1) * math.exp(-age / decay)
        out[d.isoformat()] = int(round(v))
        d += dt.timedelta(days=1)
    return out


def items(project, article, series, agent):
    return {"items": [{"project": project, "article": article, "granularity": "daily",
                       "timestamp": k.replace("-", "") + "00", "access": "all-access",
                       "agent": agent, "views": v} for k, v in series.items() if v > 0]}


def seed_article(lang, title, start, end, user, bot_share=0.1, created="2015-01-01", redirects=()):
    proj = fetch.project_of(lang)
    cache_put(fetch.article_url(lang, title, start, end, "user"), 200, items(proj, title, user, "user"))
    alls = {k: int(v / (1 - bot_share)) for k, v in user.items()}
    cache_put(fetch.article_url(lang, title, start, end, "all-agents"), 200, items(proj, title, alls, "all-agents"))
    cache_put(fetch.first_revision_url(lang, title), 200,
              {"query": {"pages": [{"title": title, "revisions": [{"timestamp": created + "T10:00:00Z"}]}]}})
    cache_put(fetch.canonical_url(lang, title), 200, {"query": {"pages": [{"title": title}]}})
    cache_put(fetch.redirects_url(lang, title), 200,
              {"query": {"pages": [{"title": title, "redirects": [{"title": r} for r in redirects]}]}})
    for r in redirects:
        s = {k: int(v * 0.05) for k, v in user.items()}
        cache_put(fetch.article_url(lang, r, start, end, "user"), 200, items(proj, r, s, "user"))


def seed_project(lang, start, end, base, yoy, seed):
    s = gen_daily(start, end, base, yoy, 0.05, 11, noise=0.03, seed=seed)
    cache_put(fetch.project_url(lang, start, end, "user"), 200, items(fetch.project_of(lang), "-", s, "user"))


def seed_wikidata(query, qlang, qid, label, desc, sitelinks: dict, langs_requested: list[str],
                  extra_cands=(), also_lang_sets=()):
    """`langs_requested` (and each list in `also_lang_sets`) must match the
    --langs the test will pass, because the sitelinks URL carries a sitefilter."""
    cands = [{"id": qid, "label": label, "description": desc}] + list(extra_cands)
    cache_put(resolve.wd_search_url(query, qlang), 200, {"search": cands})
    ent = {"labels": {"en": {"value": label}}, "descriptions": {"en": {"value": desc}},
           "sitelinks": {f"{l}wiki": {"site": f"{l}wiki", "title": t} for l, t in sitelinks.items()}}
    for ls in [langs_requested, *also_lang_sets]:
        cache_put(resolve.wd_sitelinks_url(qid, ls), 200, {"entities": {qid: ent}})
        for c in extra_cands:  # candidates with no useful sitelinks
            cache_put(resolve.wd_sitelinks_url(c["id"], ls), 200,
                      {"entities": {c["id"]: {"labels": {"en": {"value": c["label"]}},
                                              "descriptions": {"en": {"value": c["description"]}},
                                              "sitelinks": {}}}})
    for l, t in sitelinks.items():
        cache_put(resolve.qid_url(l, t), 200,
                  {"query": {"pages": [{"title": t, "pageprops": {"wikibase_item": qid}}]}})


def seed_all(months: int = 24):
    start_ym, end_ym = default_window(months)
    start, end = month_bounds(start_ym, end_ym)
    y = end.year

    # ---- 1. intermittent fasting: pl steady + January peaks, cs fast but spiky
    langs = ["pl", "cs"]
    seed_wikidata("intermittent fasting", "en", "Q3030870", "intermittent fasting",
                  "diet regimen that cycles between fasting and eating",
                  {"pl": "Post przerywany", "cs": "Přerušovaný půst", "en": "Intermittent fasting"},
                  langs, extra_cands=[{"id": "Q99999901", "label": "Intermittent Fasting (album)",
                                       "description": "2019 studio album"}],
                  also_lang_sets=[["pl"], ["cs"], ["pl", "cs", "sk"]])
    pl = gen_daily(start, end, 520, 0.22, 0.30, 1, noise=0.10, seed=11)
    cs = gen_daily(start, end, 210, 0.45, 0.20, 1, noise=0.12, seed=12,
                   spikes=[(dt.date(y - 1, 11, 14), 9.0, 3.0), (dt.date(y, 3, 2), 14.0, 2.5),
                           (dt.date(y, 6, 20), 6.0, 4.0)])
    seed_article("pl", "Post przerywany", start, end, pl, bot_share=0.12, created="2019-03-04",
                 redirects=["Intermittent fasting", "Post okresowy"])
    seed_article("cs", "Přerušovaný půst", start, end, cs, bot_share=0.18, created="2020-11-10")
    seed_project("pl", start, end, 8_500_000, -0.06, seed=21)
    seed_project("cs", start, end, 2_900_000, 0.01, seed=22)
    # follow-up override: user insists on a different Polish title (a redirect)
    cache_put(fetch.canonical_url("pl", "Post okresowy"), 200,
              {"query": {"redirects": [{"from": "Post okresowy", "to": "Post przerywany"}],
                         "pages": [{"title": "Post przerywany"}]}})

    # ---- 2. astronomy in Ukrainian: school-year seasonality, one eclipse spike,
    #         growth roughly equal to the whole edition (should trigger vs_edition warn)
    seed_wikidata("астрономія", "uk", "Q333", "astronomy",
                  "natural science that studies celestial objects and phenomena",
                  {"uk": "Астрономія", "en": "Astronomy"}, ["uk"])
    uk = gen_daily(start, end, 880, 0.11, 0.35, 10, noise=0.09, seed=31,
                   spikes=[(dt.date(y, 8, 12), 7.0, 2.0)])
    seed_article("uk", "Астрономія", start, end, uk, bot_share=0.09, created="2004-06-15")
    seed_project("uk", start, end, 3_800_000, 0.09, seed=32)

    # ---- 3. English language across 6 editions; sk has no sitelink -> search fallback;
    #         tr has heavy bot traffic; de shrinking; uk growing fast
    langs = ["uk", "pl", "cs", "de", "tr", "sk"]
    seed_wikidata("English language", "en", "Q1860", "English",
                  "West Germanic language",
                  {"uk": "Англійська мова", "pl": "Język angielski", "cs": "Angličtina",
                   "de": "Englische Sprache", "tr": "İngilizce", "en": "English language"}, langs,
                  also_lang_sets=[["uk", "sk"], ["uk", "pl", "cs", "de", "tr"], ["uk", "pl", "cs"]])
    cache_put(fetch.search_url("sk", "English"), 200,
              {"query": {"search": [{"title": "Angličtina", "snippet": "..."},
                                    {"title": "Anglický jazyk (rozlišovacia stránka)", "snippet": ""}]}})
    seed_article("uk", "Англійська мова", start, end, gen_daily(start, end, 1400, 0.38, 0.25, 9, seed=41), 0.10, "2005-02-01")
    seed_article("pl", "Język angielski", start, end, gen_daily(start, end, 3900, 0.01, 0.25, 9, seed=42), 0.11, "2003-05-20")
    seed_article("cs", "Angličtina", start, end, gen_daily(start, end, 720, 0.10, 0.25, 9, seed=43), 0.13, "2004-01-11")
    seed_article("de", "Englische Sprache", start, end, gen_daily(start, end, 5100, -0.07, 0.20, 9, seed=44), 0.12, "2002-09-09")
    seed_article("tr", "İngilizce", start, end, gen_daily(start, end, 2600, 0.24, 0.30, 9, seed=45), 0.42, "2004-11-30")
    seed_article("sk", "Angličtina", start, end, gen_daily(start, end, 60, 0.30, 0.25, 9, seed=46, noise=0.3), 0.15, "2006-03-03")
    seed_project("uk", start, end, 3_800_000, 0.09, seed=32)
    seed_project("pl", start, end, 8_500_000, -0.06, seed=21)
    seed_project("cs", start, end, 2_900_000, 0.01, seed=22)
    seed_project("de", start, end, 26_000_000, -0.05, seed=51)
    seed_project("tr", start, end, 3_100_000, 0.06, seed=52)
    seed_project("sk", start, end, 900_000, 0.02, seed=53)

    # ---- 4. a topic that does not exist anywhere: 404 path
    seed_wikidata("Zorbulon protocol", "en", "Q99999977", "Zorbulon protocol", "fictional", {}, ["pl"])
    cache_put(fetch.search_url("pl", "Zorbulon protocol"), 200, {"query": {"search": []}})
    return start, end


if __name__ == "__main__":
    print("cache dir:", os.environ.get("WIKI_CACHE_DIR", "~/.cache/wiki-interest"))
    s, e = seed_all()
    print(f"seeded fixtures for window {s}..{e}")
