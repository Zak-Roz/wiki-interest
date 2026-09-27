# Pitfalls when reading Wikipedia pageviews as demand

Read this when a result looks too good, too bad, or the user asks "can we trust this?".

## Data-generation traps

- **Redirects are counted separately.** Views of "IF diet" (a redirect) are not
  added to "Intermittent fasting". If an article has popular alternative names,
  `--include-redirects` sums them (main article only for the bot ratio).
- **Article moves/merges** show up as a dead tail (zero views at the end) and a
  new article starting from zero. The `tail` and `article_age` checks catch the
  obvious cases; when both a fall and a rise appear in two titles, run both.
- **Articles created inside the window** always "grow". Check `created`.
- **Bots and scrapers**: `agent=user` already excludes classified bots, but
  unclassified automated traffic still slips through. A high `bots %` means the
  edition/article is being scraped; treat sudden plateaus with suspicion.
- **Data starts 2015-07-01** (the current pageview definition). Older "legacy"
  counts are not comparable and are not used.
- **Partial months** distort monthly growth; the tool refuses `--to` in the current month.
- **Time zone**: days are UTC.

## Interpretation traps

- **Absolute views across languages** mostly measure edition size. Use views per
  million edition views (`share_per_million`) for "how much of that community
  cares". A 300-views/day Czech article can be a bigger signal than a
  600-views/day Polish one.
- **Edition-wide trends**: many editions lost traffic after 2023 (AI answers,
  search changes). A topic falling 5 % in an edition falling 8 % is gaining share.
  The `vs_edition` check and `share YoY` make this visible.
- **Seasonality**: education topics peak in the school year, diets in January,
  travel in spring. Compare same months (YoY) and read `peak_month`.
- **News spikes** inflate every average. Quote `YoY w/o spikes`. Spikes are
  still information: a topic that spikes repeatedly has recurring media attention.
- **Google knowledge panels / AI overviews** answer simple queries without a
  click, which depresses pageviews for well-known topics more than for niche
  ones. This biases *levels* down for mainstream topics; trends within a topic
  are less affected.
- **Wikipedia readers ≠ buyers.** Interest in "astronomy" in uk.wikipedia is a
  proxy for curiosity in the Ukrainian-speaking population (including students
  doing homework), not for willingness to pay for a course. Use it to choose
  what to validate next, never as the only evidence.
- **One article ≠ the topic.** "Learning English" is spread over "English
  language", "English grammar", "IELTS", etc. Run several articles when the
  concept is broad, and say which one you used.
- **Language edition ≠ country.** Polish Wikipedia is read from Poland, but also
  by diaspora; Spanish/English/Arabic editions span many countries. When the
  user thinks in countries, say this explicitly (per-country data exists only
  for top articles, not per article).

## Statistical traps

- 24 months is the minimum for a seasonally fair YoY; with 12–23 months use
  `half_over_half_pct` and say it is not seasonally adjusted.
- Percent changes on < 100 views/day are noise. Report them with "roughly".
- R² of the trend fit is on 12-month sums; it says whether growth was steady,
  not whether it was large.
