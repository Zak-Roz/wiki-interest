# Wikimedia endpoints used by this skill

You normally never call these yourself - `scripts/wiki.py` does. This page is
for debugging and for extending the scripts.

## Pageviews API (AQS, `https://wikimedia.org/api/rest_v1/metrics/pageviews`)

| Endpoint | Used for | Notes |
|---|---|---|
| `/per-article/{project}/{access}/{agent}/{article}/daily/{YYYYMMDD}/{YYYYMMDD}` | article series | `project` = `uk.wikipedia`; `article` = title with `_`, percent-encoded (`/` and `?` too). 404 when no data at all in the range. |
| `/aggregate/{project}/{access}/{agent}/daily/{YYYYMMDDHH}/{YYYYMMDDHH}` | whole-edition series (normalisation) | Hours are `00`. |
| `/top/{project}/all-access/{YYYY}/{MM}/all-days` | discovery (`top` command) | 1000 rows, includes Main page / Special: pages that the tool filters out. |

- `access`: `all-access | desktop | mobile-app | mobile-web`
- `agent`: `all-agents | user | spider | automated` (`automated` exists since 2020; before that it is inside `user`)
- Data from **2015-07-01**; yesterday's data is usually complete by mid-morning UTC.
- No key needed. Send a descriptive `User-Agent` with contact info (`WIKI_USER_AGENT`) - Wikimedia's policy.
- Documented limit is 100 req/s per endpoint group; the client sleeps 50 ms between calls and retries 429/5xx with backoff. A typical `run` is 4 calls per language (+1 per redirect).
- Official reference: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html

## Wikidata / MediaWiki action API

| Call | Used for |
|---|---|
| `wikidata.org/w/api.php?action=wbsearchentities&search=…&language=xx` | topic text → candidate items (disambiguation pages skipped) |
| `…action=wbgetentities&ids=Q…&props=sitelinks&sitefilter=plwiki\|cswiki` | item → article title per edition (guarantees the same concept) |
| `xx.wikipedia.org/w/api.php?action=query&prop=pageprops&ppprop=wikibase_item&titles=…` | `lang:Title` → item |
| `…action=query&titles=…&redirects=1` | canonical title for `--article` overrides |
| `…action=query&prop=revisions&rvdir=newer&rvlimit=1` | creation date (`article_age` check) |
| `…action=query&prop=redirects&rdnamespace=0` | redirect titles for `--include-redirects` |
| `…action=query&list=search&srsearch=…` | fallback when Wikidata has no sitelink (flagged `search`) |

## Cache

Every GET is cached as JSON under `WIKI_CACHE_DIR` (default `~/.cache/wiki-interest`),
keyed by the full URL. Ranges ending more than 2 days ago never expire;
recent ranges expire after 6 h; Wikidata/search lookups after 7 days; 404s are
cached too. `--offline` / `WIKI_OFFLINE=1` forbids network access (used by tests).
