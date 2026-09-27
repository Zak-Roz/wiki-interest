# wiki-interest — Wikipedia pageviews as a demand signal for B2C products

An [Agent Skill](https://agentskills.io/specification) that lets an AI agent
answer questions like *"Is interest in astronomy growing in Ukrainian
Wikipedia, and how much can we trust that?"* or *"Compare interest in
intermittent fasting in Polish vs Czech Wikipedia over two years"* with real
numbers, charts and a one-page PDF - and do it reliably on a small model
(Claude Haiku 4.5 class), because all the data work lives in bundled code.

```
wiki-interest/
├── SKILL.md                 # agent instructions (what to run, how to read, how to answer)
├── requirements.txt         # requests, numpy, matplotlib, reportlab
├── scripts/
│   ├── wiki.py              # entry point:  python scripts/wiki.py run|report|resolve|top|fetch
│   └── wikiinterest/        # client (cache/retries) · resolve (Wikidata) · fetch · analyze · charts · report · i18n · cli
├── references/              # metrics.md (definitions, trust checks) · pitfalls.md · api.md
├── assets/fonts/            # DejaVu Sans (Cyrillic-capable PDF fonts, free licence)
├── tests/                   # offline pytest suite + synthetic API fixtures
└── evals/                   # test prompts from the brief + OpenRouter harness for small-model runs
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export WIKI_USER_AGENT="my-app/1.0 (me@example.com)"    # Wikimedia asks every client to identify itself
python scripts/wiki.py run --topic "intermittent fasting" --langs pl,cs --report-lang uk --out out/fasting
```

Python 3.10+. No API keys: the Pageviews API and Wikidata are public.
Responses are cached under `~/.cache/wiki-interest` (`WIKI_CACHE_DIR` to change).

## Using it in claude.ai chat (restricted sandbox)

Claude Code runs commands on your machine, so the Wikimedia APIs are reachable.
claude.ai chat runs them in a cloud sandbox whose network allowlist by default
contains only package managers, GitHub and Anthropic. The skill detects this in
under a second and offers two ways forward (never substitute data):

- **Allow the domains once** - `wikimedia.org`, `www.wikidata.org` and the
  `<lang>.wikipedia.org` editions you use. Personal plans: Settings > Capabilities
  (network egress). Team/Enterprise: an organization owner, Organization settings >
  Capabilities > "package managers and specific domains". Start a new chat afterwards.
- **No settings change** - `run` writes `wiki-fetch-data.html`. The user opens it
  in their browser, clicks one button, and uploads the resulting `wiki-data.json`;
  `run --import wiki-data.json` then produces exactly the same analysis. The page
  replicates the pipeline's own API calls (tested in `tests/test_network.py`,
  which runs the page's JavaScript in Node and checks the imported results
  equal a direct run number for number).

`python scripts/wiki.py check --langs pl,cs` reports which hosts are reachable.

## How the pipeline works

1. **Resolve** — topic text (any language) → Wikidata item → article title per
   language edition via sitelinks. This is what makes cross-language comparisons
   compare the *same concept*. If an edition has no sitelink the tool falls back
   to full-text search and flags the result for verification.
2. **Fetch** — daily human views (`agent=user`) for the article, all-agent views
   (bot ratio), whole-edition views (normalisation), creation date, optionally
   redirects. ~4 requests per language, all cached.
3. **Analyze** — YoY and YoY-without-spikes, momentum, seasonality-free trend,
   spike events, bot share, share of the edition, and nine explicit trust
   checks that produce a high/medium/low verdict with reasons. See
   `references/metrics.md`.
4. **Charts + PDF** — overview (monthly views + share of edition), indexed
   comparison, daily chart with spikes marked, and a one-page A4 PDF whose text
   the agent replaces with its own narrative (`report --narrative`).

The agent's job is reduced to: map the request to parameters, run one command,
explain the printed table and trust notes in the user's language, and (if a
report is wanted) write ~100 words of narrative. It never writes API code or
computes statistics.

## Testing

**Offline (deterministic, no network):**
```bash
pip install pytest
python -m pytest tests -q
```
`tests/fixtures.py` generates synthetic-but-realistic series (growth,
seasonality, weekly rhythm, news spikes with decaying tails, bots, edition
totals) and seeds the cache through the same URL builders the pipeline uses,
so every code path is exercised: resolution, search fallback, overrides,
redirect summing, 404s, partial-month refusal, spike detection, trust verdicts,
charts and a one-page PDF with Cyrillic text.

**Live smoke test (needs internet):**
```bash
python scripts/wiki.py resolve --topic "intermittent fasting" --langs pl,cs
python scripts/wiki.py run --topic "intermittent fasting" --langs pl,cs --months 24 --out out/live
```

**Small-model end-to-end (the brief's requirement):** `evals/run_agent.py` is a
~150-line tool-calling loop over the OpenRouter API (bash + read-file tools)
that gives the model `SKILL.md` and one of the prompts in `evals/evals.json`.
```bash
export OPENROUTER_API_KEY=...
python evals/run_agent.py --model anthropic/claude-haiku-4.5 --eval 1
python evals/run_agent.py --model anthropic/claude-haiku-4.5 --all --out evals/runs
```
It records the full transcript, every command the model ran, and the final
answer, so you can check the assertions in `evals/evals.json` (did it use the
despiked growth, did it name the articles, did it carry the trust notes, did
it produce a PDF). Free OpenRouter models (`:free` variants) also work but
often lack reliable tool calling; use them for cost estimates, not for judging
the skill.

## How the AI-assisted development was verified

The code and instructions were drafted with an AI assistant and then checked
in three ways: (1) unit tests with known ground truth — series generated with a
30 % annual growth must yield YoY ≈ 30 %, a 10× news day must be detected and
removed, a 5-views/day article must be marked low confidence; (2) visual
inspection of every chart and rasterised PDF; (3) reading the CLI output the
way the agent would, and rewriting `SKILL.md` wherever a small model could
misread a column (which is why the table header says "YoY w/o spikes" and the
summary ends with an explicit "Next:" line). Two bugs found this way: the
original monthly trend fit was biased by seasonality (fixed by fitting
trailing-12-month sums), and multi-week news waves leaked into "growth without
spikes" (fixed by a 3-month baseline and tail absorption).

## Roadmap — how to grow the skill

Each step is independent; do them in the order the users' questions demand.

1. **Topic clusters.** Let `--topic` accept several items and sum them per
   language (astronomy = Astronomy + Telescope + Solar System …), with a
   `--cluster` flag and per-article breakdown, so broad topics are not
   represented by one article. Wikidata "subclass of / part of" links can
   propose the cluster.
2. **Explain the spikes.** For each top spike event, query Wikipedia's
   revision history and the top-articles endpoint for that day to suggest a
   cause ("solar eclipse 2026-08-12"), still marked as a hypothesis.
3. **Comparable baselines.** Store per-edition benchmarks (median share of a
   "typical educational topic") so "252 per million" can be labelled above /
   below typical for that edition.
4. **Larger data volumes.** For hundreds of topics × languages: switch the
   client to async batches with a token bucket, store series in Parquet/SQLite
   instead of per-URL JSON, add a `batch` command that reads a CSV of
   (topic, langs) and writes one row of metrics per pair, and let the agent
   query the table instead of running one topic at a time. The Wikimedia
   pageview dumps (hourly TSV) become the source once monthly volume exceeds
   what the REST API is comfortable with.
5. **Country lens.** Use the per-country top-articles endpoint to check whether
   a language edition's interest comes from the country the founder targets.
6. **Forecast band.** A seasonal naive forecast (same month last year × trend)
   with a residual band gives founders a "what to expect next quarter" line
   and a way to check the skill's own accuracy month by month.
7. **Evaluation set.** Keep `evals/evals.json` growing with real user prompts
   and expected findings; run it against Haiku on every change to SKILL.md so
   instruction edits are measured, not guessed.
