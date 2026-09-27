---
name: wiki-interest
description: Measure and compare interest in a topic across Wikipedia language editions using Wikimedia pageview data, judge how trustworthy the trend is, produce charts and a shareable one-page PDF, and recommend which topics/languages a B2C product should invest in next. Use this whenever the user asks whether interest in a topic is growing, wants to compare a topic across languages or countries, asks which language edition or market to launch/localise next, mentions Wikipedia pageviews or "Wikipedia trends", or wants a short data-backed report on topic demand - even if they never say "Wikipedia". Also use it for follow-ups that change the topic, languages, time window or article choice of an earlier analysis.
---

# wiki-interest

Wikipedia pageviews are a free, public proxy for curiosity about a topic in a
language community. This skill turns them into decision-grade numbers with one
command, so you never have to write API code or do statistics by hand.

Everything numeric comes from `scripts/wiki.py`. Your job is to (1) translate
the request into parameters, (2) run the command, (3) explain the numbers and
their limits honestly in the user's language, (4) finish the PDF if asked.

## One-time setup

```bash
pip install -q -r requirements.txt      # requests, numpy, matplotlib, reportlab ("running pip as root" warning is harmless)
export WIKI_USER_AGENT="your-app/1.0 (contact@example.com)"   # Wikimedia asks for a contact
```
Run commands from the skill directory (paths below are relative to it). If that
directory is read-only, pass an absolute `--out` (e.g. `/tmp/wiki-interest/fasting`).
Responses are cached in `~/.cache/wiki-interest` (override with `WIKI_CACHE_DIR`),
so repeated and refined runs are instant and cost no API calls.

## Sandboxes without Wikipedia access (claude.ai chat, Cowork, locked-down orgs)

Claude Code runs on the user's machine, so the network is open. In claude.ai chat
the code runs in a cloud sandbox that by default reaches only package managers,
so the first `run` there may print **`NETWORK BLOCKED`** (exit code 4, under a second).
That is expected, not a bug. When you see it:

1. Tell the user, in their language, that no data could be retrieved because the
   sandbox cannot reach Wikipedia, and offer the two options the output prints:
   - **A (recommended, once):** allow the listed domains in Claude's settings
     (the output names the exact menu for personal and Team/Enterprise plans),
     then start a new chat and repeat the request.
   - **B (no settings change):** `run` has already written a helper page
     (`wiki-fetch-data.html`, path printed; in claude.ai it is in `/mnt/user-data/outputs/`).
     Share that file with the user. They open it in their browser, click the button,
     and upload the downloaded `wiki-data.json` back into the chat.
2. When the file arrives (look in `/mnt/user-data/uploads/`, the name may be
   `wiki-data (1).json`), run:
   ```bash
   python scripts/wiki.py run --import "/mnt/user-data/uploads/wiki-data.json" --report-lang uk --out /tmp/wiki/fasting
   ```
   Topic, languages, articles and window come from the file. The result is identical
   to an online run; continue with steps 3–5 below as usual.
3. **Never** fill the gap with web search, other datasets, memory or estimates, and do
   not switch to a different task. No data means no numbers.

`python scripts/wiki.py check --langs pl,cs` tests the connection without running anything.
`python scripts/wiki.py helper --topic … --langs … --report-lang uk` writes the helper page
directly (for example when the user already knows their sandbox is offline).

## Workflow

### 1. Turn the request into parameters

| User says | Parameter | Default / note |
|---|---|---|
| a topic ("intermittent fasting", "астрономія", "learning English") | `--topic "…"` + `--topic-lang xx` if the phrase is not English | Resolved to one Wikidata concept, then to the article in every language. For "learning English" use the concept the articles exist for: `--topic "English language"`. |
| languages / markets ("Polish and Czech", "our language editions") | `--langs pl,cs` | ISO codes of Wikipedia editions. Ask if the user says "our languages" and you don't know them. |
| period ("last two years", "since 2023") | `--months 24` or `--from 2023-01 --to 2026-08` | Default 24 months ending with the last completed month. `--to` must be a finished month. Data starts 2015-07. |
| the user's language | `--report-lang uk` | Chart/PDF labels: en, uk, pl (others fall back to en). Write your own text in the user's language regardless. |
| a specific article ("use the article X") | `--article pl:Post_przerywany` (repeatable) | Overrides resolution for that language. |
| "count the alternative titles too" | `--include-redirects` | Adds views of redirect titles (the API counts them separately). |
| a ranking criterion ("we care about growth" / "size") | `--rank-by growth\|volume\|share\|balanced` | Default balanced. Explain the formula printed with the ranking. |

If the request already contains topic + languages, run immediately with the
defaults and state the assumptions in your answer; ask only when a language
list or the topic itself is genuinely missing.

### 2. Run one command

```bash
python scripts/wiki.py run --topic "intermittent fasting" --langs pl,cs --report-lang uk --out out/fasting
python scripts/wiki.py run --topic "астрономія" --topic-lang uk --langs uk --report-lang uk --out out/astronomy
python scripts/wiki.py run --topic "English language" --langs uk,pl,cs,de,tr --rank-by balanced --out out/english
```

It resolves the topic, fetches human (agent=user) daily views for each
article plus the whole edition, analyses, draws charts, writes a draft PDF and
prints a compact summary. Files land in `--out` (default `wiki-interest-out/<topic>/`):
`results.json` (everything), `series.csv` (daily data), `overview.png`,
`indexed.png`, `daily_<lang>.png` (spikes marked), `report.pdf` (draft).

### 3. Read the summary

The table columns, in the order printed:

- **views/day** - average human views per day. Under ~100/day trends are noisy; under ~20 they are unreadable.
- **YoY** - last 12 months vs the 12 before (needs 24 months). Seasonally fair.
- **YoY w/o spikes** - same, after replacing spike days with the local baseline. **This is the growth figure to quote**; the raw YoY tells you how much news inflated it.
- **last 3m vs yr ago (w/o spikes)** - recent momentum; compare it with YoY to say "accelerating" or "cooling".
- **trend/yr (R²)** - compound growth from a fit on trailing-12-month sums. R² near 1 = steady growth; low R² = a step change or a one-off.
- **per 1M edition** - views per million views of the whole language edition. Use this to compare languages of different sizes: it is "how much of that community's attention the topic gets".
- **share YoY** - growth of that share. Positive = topic outgrows its edition.
- **edition YoY** - growth of the whole edition. If it matches the topic's growth, the topic is just riding the tide.
- **spikes %** - share of views that came from spike days. **Top spike events** lists peak dates; do not guess causes - say "spike on <date>, likely news/event; verify before relying on it" unless you actually know.
- **bots %** - non-human share of traffic (human series is already used for all metrics; this is a data-quality flag).
- **confidence** - high / medium / low from the trust checks (volume, window, spikes, growth robustness, bots, article age, vs-edition, coverage, dead tail). The **Trust notes** lines list every failed/warned check with its reason - carry these into the answer.

Lower-level definitions: `references/metrics.md`. Known traps: `references/pitfalls.md`.

### 4. Write the answer

Answer in the user's language, short, numbers first. Structure:

1. **What was measured** - articles used per language (name them; flag any marked `search` or ⚠ as "please confirm this is the right article"), window, human views only.
2. **Findings** - one line per language with views/day, YoY w/o spikes, per-1M share, confidence. Then the comparison in words (who is bigger, who grows faster, who is gaining share).
3. **How much to trust it** - the trust notes turned into plain language, plus the two universal caveats: pageviews measure curiosity, not willingness to pay; one article stands in for the whole topic.
4. **Recommendation / next checks** - what to explore next and why, tied to the user's criterion (growth, size, share). Suggest concrete follow-ups: add languages, extend the window, sum related articles, check what caused a spike.

Do not compute or "estimate" any number yourself; if it is not in the summary or `results.json`, say so. Keep percentages rounded as printed.

### 5. Finalise the PDF (when a report/PDF/shareable summary is wanted)

The draft PDF already has the table, chart and auto caveats. Replace its text
with yours: write `narrative.json` in the user's language and rebuild.

```json
{
  "title": "Інтервальне голодування: Польща vs Чехія, 2024-09 – 2026-08",
  "recommendation": "2–3 sentences: what to do next and why, tied to the numbers.",
  "trust": ["pl (висока довіра): усі перевірки пройдено.", "cs (середня): 11% переглядів від 3 сплесків; 18% трафіку - боти."],
  "caveats": ["Перегляди вимірюють цікавість, а не готовність платити.", "Одна стаття представляє всю тему."]
}
```
```bash
python scripts/wiki.py report --results out/fasting/results.json --narrative narrative.json --lang uk --out out/fasting/report.pdf
```
Then hand the user the PDF path (and `overview.png` if they want just the chart).
The PDF is always one page; long text is shrunk, so keep the recommendation to ~60 words.

## Follow-ups and corrections

- Change of languages, window, criterion or topic → re-run `run` with new parameters (cache makes it seconds). Keep `--out` per topic so earlier results survive.
- "That's the wrong article" → `--article xx:Correct_Title` for that language. `python scripts/wiki.py resolve --topic … --langs …` shows candidates and alternatives without fetching data.
- "Interest in X is spread over several articles" → run once per article (or per related topic) and compare the summaries; or `--include-redirects` for alternative names of the same article. Summing unrelated articles is not supported on purpose - say so and compare them side by side.
- "What is popular in this edition at all?" → `python scripts/wiki.py top --lang uk --month 2026-08` (discovery of candidate topics).
- Raw numbers wanted → point to `series.csv` or `python scripts/wiki.py fetch --article uk:Астрономія --from 2025-01 --to 2025-12`.

## When things go wrong

- `NETWORK BLOCKED` - see "Sandboxes without Wikipedia access" above. Relay options A and B; do not substitute data.
- `Note: … unavailable` lines - a helper host was blocked or missing from an imported file; the analysis stands, mention the skipped check.
- `--import: the data file was made for --langs …` - the user wants other languages than the file covers; generate a new helper page (`wiki.py helper`).
- `no data for any language` / `no article found` - the topic did not resolve; try the English concept name, a Wikidata Q-id, or `--article`.
- A language line says `(search)` - Wikidata had no article link; the tool took the best search hit. Name it explicitly and ask the user to confirm.
- `--to must be a completed month` - pick the previous month.
- `HTTP 429` - the API is throttling; wait a minute and re-run (cached parts are skipped).
- `offline miss` - `--offline` was set (or `WIKI_OFFLINE=1`) and data is not cached; drop the flag.

## Rules of thumb

- Quote growth without spikes; mention raw growth only to explain the gap.
- Never compare raw views across languages without the per-1M column; a small edition can have higher intensity of interest.
- A growing article in a growing edition is not a growing topic - check "edition YoY".
- Confidence "low" means: report the numbers, but recommend validating with another source before investing.
- Wikipedia interest ≠ market demand. Say it once, plainly, in every report.
