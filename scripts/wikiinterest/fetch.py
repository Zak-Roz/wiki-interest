"""Calls to the Wikimedia Pageviews API and a few MediaWiki action-API helpers.

Everything returns plain Python structures keyed by ISO dates so analyze.py
never needs to know where the numbers came from.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from .client import Client, FOREVER

PV_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
DATA_START = dt.date(2015, 7, 1)  # Pageviews API has no data before this
SIX_HOURS = 6 * 3600
WEEK = 7 * 24 * 3600


def project_of(lang: str) -> str:
    return f"{lang}.wikipedia"


def api_title(title: str) -> str:
    """Pageviews API wants underscores and percent-encoding ('/' and '?' too)."""
    return quote(title.replace(" ", "_"), safe="")


def _ttl_for(end: dt.date) -> Optional[float]:
    # Complete past ranges are immutable; recent ranges may still be backfilled.
    return FOREVER if end < dt.date.today() - dt.timedelta(days=2) else SIX_HOURS


def _ymd(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def article_url(lang: str, title: str, start: dt.date, end: dt.date,
                agent: str = "user", access: str = "all-access") -> str:
    return (f"{PV_BASE}/per-article/{project_of(lang)}/{access}/{agent}/"
            f"{api_title(title)}/daily/{_ymd(start)}/{_ymd(end)}")


def project_url(lang: str, start: dt.date, end: dt.date,
                agent: str = "user", access: str = "all-access") -> str:
    return (f"{PV_BASE}/aggregate/{project_of(lang)}/{access}/{agent}/daily/"
            f"{_ymd(start)}00/{_ymd(end)}00")


def top_url(lang: str, year: int, month: int) -> str:
    return f"{PV_BASE}/top/{project_of(lang)}/all-access/{year}/{month:02d}/all-days"


def article_daily(
    client: Client, lang: str, title: str, start: dt.date, end: dt.date,
    agent: str = "user", access: str = "all-access",
) -> Tuple[Dict[str, int], bool]:
    """Daily views for one article -> (series, had_data).
    Missing days (no views) are returned as 0.

    The API answers 404 when there is no data at all in the range (typo,
    article did not exist yet, or truly zero views); we return an all-zero
    series and let the caller flag it.
    """
    url = article_url(lang, title, start, end, agent, access)
    body = client.get_json(url, ttl=_ttl_for(end), ok404=True)
    series = {}
    d = start
    while d <= end:
        series[d.isoformat()] = 0
        d += dt.timedelta(days=1)
    if body:
        for item in body.get("items", []):
            ts = item["timestamp"]
            key = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
            if key in series:
                series[key] = int(item.get("views", 0))
    return series, bool(body and body.get("items"))


def project_daily(
    client: Client, lang: str, start: dt.date, end: dt.date,
    agent: str = "user", access: str = "all-access",
) -> Dict[str, int]:
    """Whole-project daily views, used to normalise for edition size/growth."""
    url = project_url(lang, start, end, agent, access)
    body = client.get_json(url, ttl=_ttl_for(end), ok404=True)
    series = {}
    d = start
    while d <= end:
        series[d.isoformat()] = 0
        d += dt.timedelta(days=1)
    if body:
        for item in body.get("items", []):
            ts = item["timestamp"]
            key = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
            if key in series:
                series[key] = int(item.get("views", 0))
    return series


def top_articles(client: Client, lang: str, year: int, month: int, limit: int = 50) -> List[dict]:
    """Most viewed articles of a project for a month (discovery helper)."""
    url = top_url(lang, year, month)
    body = client.get_json(url, ttl=FOREVER, ok404=True)
    if not body:
        return []
    out = []
    for item in body["items"][0].get("articles", []):
        t = item["article"]
        if t.startswith(("Special:", "Спеціальна:", "Specjalna:", "Speciální:", "Spezial:",
                         "Especial:", "Spécial:", "Wikipedia:", "Файл:", "File:", "Plik:",
                         "Soubor:", "Datei:", "Portal:", "Portál:", "Портал:", "Category:",
                         "Категорія:", "Kategoria:", "Kategorie:", "Talk:", "User:")) \
                or t in ("Main_Page", "Головна_сторінка", "Wikipedia:Strona_główna",
                         "Hlavní_strana", "Wikipedia:Hauptseite", "-"):
            continue
        out.append({"article": t.replace("_", " "), "views": item["views"], "rank": item["rank"]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- MediaWiki

def _mw(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def canonical_url(lang: str, title: str) -> str:
    return (f"{_mw(lang)}?action=query&titles={quote(title)}&redirects=1"
            f"&format=json&formatversion=2")


def first_revision_url(lang: str, title: str) -> str:
    return (f"{_mw(lang)}?action=query&prop=revisions&titles={quote(title)}"
            f"&rvlimit=1&rvdir=newer&rvprop=timestamp&redirects=1&format=json&formatversion=2")


def redirects_url(lang: str, title: str, limit: int = 30) -> str:
    return (f"{_mw(lang)}?action=query&prop=redirects&titles={quote(title)}"
            f"&rdlimit={limit}&rdnamespace=0&format=json&formatversion=2")


def search_url(lang: str, query: str, limit: int = 5) -> str:
    return (f"{_mw(lang)}?action=query&list=search&srsearch={quote(query)}"
            f"&srlimit={limit}&srnamespace=0&format=json&formatversion=2")


def canonical_title(client: Client, lang: str, title: str) -> Optional[str]:
    """Follow redirects / normalisation; None if the page does not exist."""
    url = canonical_url(lang, title)
    body = client.get_json(url, ttl=WEEK)
    pages = body.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    return pages[0]["title"]


def first_revision_date(client: Client, lang: str, title: str) -> Optional[str]:
    """ISO date of the article's first revision (creation), or None."""
    url = first_revision_url(lang, title)
    body = client.get_json(url, ttl=FOREVER)
    pages = body.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    revs = pages[0].get("revisions") or []
    return revs[0]["timestamp"][:10] if revs else None


def redirects_to(client: Client, lang: str, title: str, limit: int = 30) -> List[str]:
    """Titles that redirect to `title`. Views on redirects are NOT counted on the
    target by the Pageviews API, so summing them gives a fuller picture."""
    url = redirects_url(lang, title, limit)
    body = client.get_json(url, ttl=WEEK)
    pages = body.get("query", {}).get("pages", [])
    if not pages:
        return []
    return [r["title"] for r in pages[0].get("redirects", [])][:limit]


def search_titles(client: Client, lang: str, query: str, limit: int = 5) -> List[dict]:
    """Full-text search on one wiki: fallback when Wikidata has no sitelink."""
    url = search_url(lang, query, limit)
    body = client.get_json(url, ttl=WEEK)
    return [{"title": r["title"], "snippet": r.get("snippet", "")}
            for r in body.get("query", {}).get("search", [])]
