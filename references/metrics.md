# Metrics and trust checks (what `run` computes and why)

All metrics use **human traffic** (`agent=user`, `access=all-access`) at daily
granularity, aggregated to calendar months. Windows always start on the 1st
and end on the last day of a completed month, so monthly numbers are comparable.

## Per-language metrics

| Field (results.json) | Definition | Why it exists |
|---|---|---|
| `avg_daily_views` | total views / days in window | Size of the audience. Also gates the volume check. |
| `yoy_pct` | Σ last 12 months / Σ previous 12 months − 1 | Seasonally fair growth (same months compared). `null` if < 24 months. |
| `yoy_despiked_pct` | same on the despiked series | Growth that does not depend on news. **The figure to quote.** |
| `half_over_half_pct` | second half of window / first half − 1 | Fallback growth for short windows (not seasonally fair). |
| `recent_3m_vs_year_ago_pct` | last 3 months / same 3 months a year earlier − 1 (despiked) | Momentum: is growth accelerating or fading? |
| `trend_annualised_pct`, `trend_r2`, `trend_basis` | OLS on log(trailing-12-month sum); ≥18 months. Otherwise on raw months. | Seasonality-free compound rate. R² ≈ 1 means smooth growth; low R² means a step or a blip. |
| `seasonality_index`, `peak_month`, `trough_month` | (max − min) / mean of month-of-year averages (despiked, ≥24 months) | Tells you which months to compare and when demand is naturally high. |
| `spikes.spike_share_pct` | Σ(view − baseline) on spike days / total views | How much of the volume is event-driven. |
| `spikes.spike_events`, `spikes.top_spikes` | consecutive spike days grouped; top 5 by excess views | What to look up ("what happened on 2026-03-02?"). |
| `bot_share_pct` | 1 − user views / all-agent views (main article) | Data-quality flag; metrics already exclude bots. |
| `share_per_million_last12` | article views / edition views × 1e6, last 12 months | Size-independent comparison across languages. |
| `share_yoy_pct` | growth of that share | Is the topic gaining attention faster than everything else in that edition? |
| `project_yoy_pct` | YoY of the whole edition | Separates "topic growth" from "edition growth". |
| `coverage_pct` | days with > 0 views / days | Missing days may mean the page did not exist. |
| `created` | first revision date (MediaWiki) | Growth from zero after creation is an artifact. |
| `zero_tail_days` | zero-view days at the end | A dead tail usually means the article was moved/merged. |

### Spike detection

A day is a spike when its views exceed the rolling 28-day median by more than
4 robust standard deviations (MAD × 1.4826), are at least 2× that median and at
least 50 views. Spike days are replaced by the median to form the "despiked"
series. Consecutive spike days (≤ 3-day gaps) form one **event**. The thresholds
are deliberately conservative: better to miss a mild bump than to erase real growth.

## Trust checks

Each check yields `pass` / `warn` / `fail` and a sentence. Score starts at 100;
a *hard* failure (data, volume, tail, article_age - the series is unreadable)
costs 50, any other failure 30, a warning 10.
Verdict: **high** ≥ 90 (at most one warning), **medium** ≥ 60, else **low**.

| Check | warn | fail |
|---|---|---|
| data | – | API returned nothing for the title in the window |
| volume | < 100 views/day | < 20 views/day |
| window | < 24 months | – (12–23 months: no fair YoY; < 12: growth may be seasonal) |
| spikes | > 10 % of views from spikes | > 30 % |
| growth_robust | despiked YoY < half of raw YoY | raw growth > 5 % but despiked ≤ 0 |
| bots | > 15 % non-human | > 35 % |
| article_age | created < 180 days before window | created inside window |
| vs_edition | topic growth within ±5 pp of edition growth, or 5 pp slower | – |
| coverage | < 90 % of days have views | – |
| tail | – | ≥ 14 zero-view days at the end |

Low confidence does not mean "ignore"; it means "validate with another source
(search volume, app-store data, surveys) before spending money".

## Ranking (`comparison`)

`balanced` (default): for each language take its rank on three criteria -
despiked YoY, average daily views, share per million - average them, scale to
0–100 and multiply by a trust weight (high 1.0, medium 0.8, low 0.5).
`growth`, `volume`, `share` rank on one criterion × trust weight. The formula
is printed with the ranking so the reader can disagree with it; when the user
has their own criterion, re-rank from the table rather than trusting the score.
