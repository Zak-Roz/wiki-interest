"""Turn a topic ("intermittent fasting", "Q3030870", "uk:Астрономія") into the
concrete article title in every requested language edition.

Strategy, in order of trust:
1. explicit `lang:Title` overrides given by the agent/user           -> "explicit"
2. Wikidata item (QID or search) -> sitelinks (same concept, all langs) -> "wikidata"
3. full-text search on the target wiki (fuzzy, must be verified)      -> "search"

Cross-language comparisons are only meaningful if every language points at the
same concept, which is exactly what Wikidata sitelinks guarantee; that is why
search is the last resort and is flagged for verification.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import quote

from .client import Client, NetworkBlocked
from .fetch import canonical_title, search_titles, WEEK

WD_API = "https://www.wikidata.org/w/api.php"
QID_RE = re.compile(r"^Q\d+$")
LANG_TITLE_RE = re.compile(r"^([a-z]{2,3}(?:-[a-z]+)?):(.+)$")


def wd_search_url(text: str, lang: str, limit: int = 7) -> str:
    return (f"{WD_API}?action=wbsearchentities&search={quote(text)}&language={lang}"
            f"&uselang=en&type=item&limit={limit}&format=json")


def wd_sitelinks_url(qid: str, langs: List[str]) -> str:
    sites = "|".join(f"{l}wiki" for l in langs)
    return (f"{WD_API}?action=wbgetentities&ids={qid}&props=sitelinks|labels|descriptions"
            f"&sitefilter={quote(sites)}&languages=en&format=json")


def qid_url(lang: str, title: str) -> str:
    return (f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=pageprops"
            f"&ppprop=wikibase_item&titles={quote(title)}&redirects=1&format=json&formatversion=2")


def wd_search(client: Client, text: str, lang: str, limit: int = 7) -> List[dict]:
    url = wd_search_url(text, lang, limit)
    body = client.get_json(url, ttl=WEEK)
    return [{"id": r["id"], "label": r.get("label", ""),
             "description": r.get("description", "")} for r in body.get("search", [])]


def wd_sitelinks(client: Client, qid: str, langs: List[str]) -> dict:
    url = wd_sitelinks_url(qid, langs)
    body = client.get_json(url, ttl=WEEK)
    ent = body.get("entities", {}).get(qid, {})
    links = {k[:-4]: v["title"] for k, v in ent.get("sitelinks", {}).items()}
    return {"qid": qid, "label": ent.get("labels", {}).get("en", {}).get("value", ""),
            "description": ent.get("descriptions", {}).get("en", {}).get("value", ""),
            "sitelinks": links}


def qid_for_title(client: Client, lang: str, title: str) -> Optional[str]:
    url = qid_url(lang, title)
    body = client.get_json(url, ttl=WEEK)
    pages = body.get("query", {}).get("pages", [])
    if not pages:
        return None
    return pages[0].get("pageprops", {}).get("wikibase_item")


def _is_disambiguation(desc: str) -> bool:
    d = desc.lower()
    return "disambiguation" in d or "topics referred to" in d


def resolve_topic(
    client: Client, topic: str, langs: List[str], topic_lang: str = "en",
    overrides: Optional[Dict[str, str]] = None,
) -> dict:
    """Return {"topic":..., "qid":..., "label":..., "candidates":[...],
    "articles": {lang: {"title":..., "via":..., "note":...}}}."""
    overrides = overrides or {}
    out = {"topic": topic, "qid": None, "label": None, "description": None,
           "candidates": [], "articles": {}, "notes": []}
    try:
        qid, links = _wikidata_item(client, topic, langs, topic_lang, overrides, out)
    except NetworkBlocked as e:
        # Wikidata is only a matching aid: without it we can still use explicit
        # titles and per-wiki search, clearly flagged.
        qid, links = None, {}
        out["notes"].append(f"{e.host} unreachable ({e.reason}): topic matched by search, "
                            f"not by Wikidata - verify each article or pass --article")
    out["qid"] = qid
    _articles(client, topic, langs, overrides, links, out)
    return out


def _wikidata_item(client, topic, langs, topic_lang, overrides, out):
    if all(l in overrides for l in langs):  # nothing left to resolve
        out["label"] = topic
        return None, {}
    qid, links = None, {}
    if QID_RE.match(topic.strip()):
        qid = topic.strip()
    else:
        m = LANG_TITLE_RE.match(topic.strip())
        if m:  # topic given as "uk:Астрономія" -> look up its item
            qid = qid_for_title(client, m.group(1), m.group(2))
            if qid is None:
                overrides.setdefault(m.group(1), m.group(2))
        else:
            cands = wd_search(client, topic, topic_lang)
            cands = [c for c in cands if not _is_disambiguation(c["description"])]
            out["candidates"] = cands[:5]
            # Prefer the first candidate that actually has articles in the langs we need.
            best, best_cov = None, -1
            for c in cands[:4]:
                info = wd_sitelinks(client, c["id"], langs)
                cov = sum(1 for l in langs if l in info["sitelinks"])
                if cov > best_cov:
                    best, best_cov = info, cov
                if cov == len(langs):
                    break
            if best:
                qid = best["qid"]
                out.update(label=best["label"], description=best["description"])
                links = best["sitelinks"]
    if qid and not out["label"]:
        info = wd_sitelinks(client, qid, langs)
        out.update(label=info["label"], description=info["description"])
        links = info["sitelinks"]
    return qid, links


def _articles(client, topic, langs, overrides, links, out):
    for lang in langs:
        if lang in overrides:
            try:
                t = canonical_title(client, lang, overrides[lang])
            except NetworkBlocked as e:
                out["articles"][lang] = {"title": overrides[lang], "via": "explicit",
                                         "note": f"title not verified ({e.host} unreachable)"}
                continue
            if t is None:
                out["articles"][lang] = {"title": overrides[lang], "via": "explicit",
                                         "note": "page not found on this wiki - check the title"}
            else:
                out["articles"][lang] = {"title": t, "via": "explicit", "note": ""}
            continue
        if lang in links:
            out["articles"][lang] = {"title": links[lang], "via": "wikidata", "note": ""}
            continue
        # Fallback: search on the target wiki with the label or the raw topic.
        query = out["label"] or topic
        hits = search_titles(client, lang, query)
        if hits:
            out["articles"][lang] = {
                "title": hits[0]["title"], "via": "search",
                "note": f"no Wikidata sitelink; took top search hit for '{query}' - verify it is the same concept",
                "alternatives": [h["title"] for h in hits[1:4]]}
        else:
            out["articles"][lang] = {"title": None, "via": "none",
                                     "note": f"no article found for '{query}' in {lang}.wikipedia"}
