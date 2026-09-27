"""Turn daily view series into a small set of decision-grade numbers plus an
explicit list of trust checks.

Design principle: every number that ends up in a report must be traceable to a
formula described in references/metrics.md, and every "be careful" must be an
explicit check with a status, not a vibe. That is what lets a small model write
an honest recommendation without doing statistics itself.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ----------------------------------------------------------------- helpers

def _pct(a: float, b: float) -> Optional[float]:
    """Percent change from b to a; None when b is 0."""
    if b <= 0:
        return None
    return round((a / b - 1.0) * 100.0, 1)


def monthly_sums(daily: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = defaultdict(int)
    for day, v in daily.items():
        out[day[:7]] += v
    return dict(sorted(out.items()))


def detect_spikes(daily: Dict[str, int], window: int = 91, z_thresh: float = 4.0,
                  min_views: int = 50) -> dict:
    """Robust spike detection.

    Baseline = centred rolling median over ~3 months (a month-long news wave
    cannot drag a 3-month median up, a 4-week one could). A day starts a spike
    when it is > z_thresh robust standard deviations (MAD) above the baseline,
    at least double it, and not tiny in absolute terms. Days that follow a
    spike stay in the event while they remain clearly elevated (> 1.5x
    baseline and z > 2), so the decaying tail of a news wave is removed too and
    does not leak into "growth without spikes"."""
    days = sorted(daily)
    x = np.array([daily[d] for d in days], dtype=float)
    n = len(x)
    baseline = np.zeros(n)
    z = np.zeros(n)
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        seg = x[lo:hi]
        med = float(np.median(seg))
        mad = float(np.median(np.abs(seg - med))) * 1.4826 + 1e-9
        baseline[i] = med
        z[i] = (x[i] - med) / mad
    spike = np.zeros(n, dtype=bool)
    in_event = False
    for i in range(n):
        starts = z[i] > z_thresh and x[i] >= 2 * baseline[i] and x[i] >= min_views
        continues = in_event and z[i] > 2 and x[i] >= 1.5 * baseline[i]
        spike[i] = bool(starts or continues)
        in_event = spike[i]
    excess = float(np.sum((x - baseline)[spike])) if spike.any() else 0.0
    total = float(x.sum())
    despiked = x.copy()
    despiked[spike] = baseline[spike]
    # Group consecutive spike days (gap <= 2 days) into events: "3 events" is
    # what a reader needs, "18 spike days" is not.
    events = []
    cur = None
    for i in range(n):
        if spike[i]:
            if cur and i - cur["last_i"] <= 3:
                cur["last_i"] = i
                cur["days"] += 1
                cur["excess"] += x[i] - baseline[i]
                if x[i] > cur["views"]:
                    cur.update(views=int(x[i]), x_baseline=round(x[i] / max(baseline[i], 1), 1),
                               peak=days[i])
            else:
                cur = {"date": days[i], "peak": days[i], "views": int(x[i]),
                       "x_baseline": round(x[i] / max(baseline[i], 1), 1), "days": 1,
                       "excess": x[i] - baseline[i], "last_i": i}
                events.append(cur)
    for e in events:
        e["excess_views"] = int(e.pop("excess"))
        e.pop("last_i")
    top = sorted(events, key=lambda e: -e["excess_views"])[:5]
    return {
        "spike_days": int(spike.sum()),
        "spike_events": len(events),
        "spike_share_pct": round(100.0 * excess / total, 1) if total else 0.0,
        "top_spikes": top,
        "despiked": {days[i]: int(round(despiked[i])) for i in range(n)},
    }


def log_trend(monthly: Dict[str, int]) -> dict:
    """Compound growth rate of the series.

    A plain line through monthly points is biased by seasonality (a January
    peak near the start or end of the window tilts the line). With >= 18 months
    we therefore fit log(trailing-12-month sum), which removes the seasonal
    cycle entirely; R² then reads as "how steady the growth is" (1 = smooth,
    low = a step change or a one-off). With shorter windows we fall back to
    the raw monthly fit and the caller flags the window as short."""
    vals = np.array(list(monthly.values()), dtype=float)
    if len(vals) < 4 or vals.sum() == 0:
        return {"trend_monthly_pct": None, "trend_annualised_pct": None, "trend_r2": None,
                "trend_basis": None}
    if len(vals) >= 18:
        series = np.convolve(vals, np.ones(12), mode="valid")  # trailing 12-month sums
        basis = "trailing-12-month sums"
    else:
        series = vals
        basis = "monthly (seasonality not removed)"
    y = np.log(series + 1.0)
    t = np.arange(len(series))
    slope, intercept = np.polyfit(t, y, 1)
    pred = slope * t + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-9
    g = math.exp(slope) - 1.0
    return {"trend_monthly_pct": round(g * 100, 2),
            "trend_annualised_pct": round(((1 + g) ** 12 - 1) * 100, 1),
            "trend_r2": round(max(0.0, 1 - ss_res / ss_tot), 2),
            "trend_basis": basis}


def seasonality(monthly: Dict[str, int]) -> dict:
    """Month-of-year profile; only meaningful with >= 24 months."""
    if len(monthly) < 24:
        return {"seasonality_index": None, "peak_month": None, "trough_month": None}
    by_m: Dict[int, List[float]] = defaultdict(list)
    for ym, v in monthly.items():
        by_m[int(ym[5:7])].append(v)
    prof = {m: float(np.mean(v)) for m, v in by_m.items()}
    mean = float(np.mean(list(prof.values()))) or 1e-9
    peak = max(prof, key=prof.get)
    trough = min(prof, key=prof.get)
    return {"seasonality_index": round((prof[peak] - prof[trough]) / mean, 2),
            "peak_month": MONTH_NAMES[peak - 1], "trough_month": MONTH_NAMES[trough - 1]}


# --------------------------------------------------------------- per series

def analyze_series(
    user_daily: Dict[str, int], all_daily: Optional[Dict[str, int]],
    project_daily: Optional[Dict[str, int]], meta: dict,
) -> dict:
    """meta: {"lang","title","had_data","created","window_start","window_end","via"}."""
    days = sorted(user_daily)
    x = np.array([user_daily[d] for d in days], dtype=float)
    n_days = len(days)
    total = float(x.sum())
    m = monthly_sums(user_daily)
    months = list(m)
    n_months = len(months)
    mv = list(m.values())

    sp = detect_spikes(user_daily)
    m_ds = monthly_sums(sp["despiked"])
    mv_ds = list(m_ds.values())

    def yoy(vals):
        return _pct(sum(vals[-12:]), sum(vals[-24:-12])) if len(vals) >= 24 else None

    def half(vals):
        h = len(vals) // 2
        return _pct(sum(vals[h:]), sum(vals[:h])) if len(vals) >= 4 else None

    def recent(vals):
        # last 3 full months vs same 3 months a year earlier (seasonally fair)
        if len(vals) >= 15:
            return _pct(sum(vals[-3:]), sum(vals[-15:-12]))
        return None

    res = {
        "lang": meta["lang"], "title": meta["title"], "resolved_via": meta.get("via"),
        "window": {"start": days[0], "end": days[-1], "days": n_days, "months": n_months},
        "total_views": int(total),
        "avg_daily_views": round(total / n_days, 1) if n_days else 0.0,
        "avg_monthly_views": int(round(total / n_months)) if n_months else 0,
        "last_month": {"month": months[-1], "views": mv[-1]} if months else None,
        "yoy_pct": yoy(mv),
        "yoy_despiked_pct": yoy(mv_ds),
        "half_over_half_pct": half(mv),
        "recent_3m_vs_year_ago_pct": recent(mv_ds),  # despiked: momentum, not news
        "spikes": {k: sp[k] for k in ("spike_days", "spike_events", "spike_share_pct", "top_spikes")},
        "coverage_pct": round(100.0 * float((x > 0).sum()) / n_days, 1) if n_days else 0.0,
        "first_nonzero_date": next((d for d in days if user_daily[d] > 0), None),
        "zero_tail_days": int(len(x) - (np.max(np.nonzero(x)[0]) + 1)) if x.any() else n_days,
        "created": meta.get("created"),
        "had_data": meta.get("had_data", True),
    }
    res.update(log_trend(m_ds))
    res.update(seasonality(m_ds))

    # Bots: share of all-agent views that are NOT human.
    if all_daily:
        all_total = float(sum(all_daily.values()))
        main_total = float(sum(meta.get("user_main_daily", user_daily).values()))
        res["bot_share_pct"] = round(100.0 * (1 - main_total / all_total), 1) if all_total else None
    else:
        res["bot_share_pct"] = None

    # Normalise by the whole language edition: views per million project views.
    if project_daily:
        pm = monthly_sums(project_daily)
        pmv = [pm.get(k, 0) for k in months]
        share = [round(1e6 * a / b, 2) if b else None for a, b in zip(mv, pmv)]
        res["project_yoy_pct"] = yoy(pmv)
        l12 = sum(mv[-12:]) / max(sum(pmv[-12:]), 1) * 1e6 if n_months >= 12 else \
            sum(mv) / max(sum(pmv), 1) * 1e6
        res["share_per_million_last12"] = round(l12, 2)
        res["share_yoy_pct"] = (_pct(sum(mv[-12:]) / max(sum(pmv[-12:]), 1),
                                     sum(mv[-24:-12]) / max(sum(pmv[-24:-12]), 1))
                                if n_months >= 24 else None)
        res["monthly_share_per_million"] = dict(zip(months, share))
        res["project_monthly_views"] = dict(zip(months, pmv))
    else:
        res.update(project_yoy_pct=None, share_per_million_last12=None, share_yoy_pct=None,
                   monthly_share_per_million={}, project_monthly_views={})

    res["monthly_views"] = m
    res["monthly_views_despiked"] = m_ds
    res["trust"] = trust_checks(res)
    return res


# -------------------------------------------------------------- trust checks

def trust_checks(r: dict) -> dict:
    """Each check: {"check","status":pass|warn|fail,"detail"}. The verdict is a
    simple score so that two people (or two models) get the same answer."""
    checks: List[dict] = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    if not r["had_data"]:
        add("data", "fail", "API returned no data for this title in the window (typo, page did not exist, or zero views)")
    avg = r["avg_daily_views"]
    if avg >= 100:
        add("volume", "pass", f"{avg:.0f} views/day on average - enough for stable trends")
    elif avg >= 20:
        add("volume", "warn", f"only {avg:.0f} views/day - trends are noisy; treat % changes loosely")
    else:
        add("volume", "fail", f"only {avg:.1f} views/day - too little traffic to read a trend")

    mo = r["window"]["months"]
    if mo >= 24:
        add("window", "pass", f"{mo} months of data - year-over-year comparison is seasonally fair")
    elif mo >= 12:
        add("window", "warn", f"{mo} months of data - no full year-over-year comparison; seasonality unknown")
    else:
        add("window", "warn", f"only {mo} months - growth figures may be seasonal, not structural")

    ss = r["spikes"]["spike_share_pct"]
    if ss <= 10:
        add("spikes", "pass", f"{ss}% of views come from spike days")
    elif ss <= 30:
        add("spikes", "warn", f"{ss}% of views come from {r['spikes']['spike_events']} spike event(s) - check what caused them")
    else:
        add("spikes", "fail", f"{ss}% of views come from spike days - interest is event-driven, not steady")

    y, yd = r["yoy_pct"], r["yoy_despiked_pct"]
    if y is not None and yd is not None and y > 5:
        if yd <= 0:
            add("growth_robust", "fail", f"YoY +{y}% disappears without spikes ({yd:+}%)")
        elif yd < y / 2:
            add("growth_robust", "warn", f"YoY +{y}% shrinks to {yd:+}% without spikes")
        else:
            add("growth_robust", "pass", f"growth holds without spikes ({yd:+}% vs {y:+}% raw)")
    elif y is not None:
        add("growth_robust", "pass", f"no growth claimed (YoY {y:+}%), nothing to inflate")

    b = r["bot_share_pct"]
    if b is not None:
        if b <= 15:
            add("bots", "pass", f"{b}% of traffic is non-human - normal")
        elif b <= 35:
            add("bots", "warn", f"{b}% of traffic is non-human - human series used, but watch for scraping")
        else:
            add("bots", "fail", f"{b}% of traffic is non-human - human series used; total figures elsewhere are inflated")

    c = r.get("created")
    if c:
        if c > r["window"]["start"]:
            add("article_age", "fail", f"article was created on {c}, inside the window - growth from zero is an artifact")
        elif c > (dt.date.fromisoformat(r["window"]["start"]) - dt.timedelta(days=180)).isoformat():
            add("article_age", "warn", f"article created {c}, shortly before the window - early ramp-up may inflate growth")
        else:
            add("article_age", "pass", f"article exists since {c}")

    py = r.get("project_yoy_pct")
    g = yd if yd is not None else y  # compare the honest (despiked) growth with the edition
    if g is not None and py is not None:
        diff = g - py
        if g > 5 and abs(diff) < 5:
            add("vs_edition", "warn", f"topic YoY w/o spikes {g:+}% ~ whole edition {py:+}% - growth is edition-wide, not topic-specific")
        elif g > 5 and diff < -5:
            add("vs_edition", "warn", f"topic grows slower than the whole edition ({g:+}% vs {py:+}%) - losing share")
        else:
            add("vs_edition", "pass", f"topic YoY w/o spikes {g:+}% vs whole {r['lang']}.wikipedia {py:+}% ({diff:+.1f} pp)")

    cov = r["coverage_pct"]
    if cov < 90:
        add("coverage", "warn", f"views recorded on only {cov}% of days")
    if r["zero_tail_days"] >= 14 and r["had_data"]:
        add("tail", "fail", f"no views in the last {r['zero_tail_days']} days - page likely moved, merged or deleted")

    # "hard" failures make the series unreadable (no data, too small, dead,
    # born inside the window) and cost 50; other failures inflate a reading
    # but leave it usable and cost 30; warnings cost 10.
    HARD = {"data", "volume", "tail", "article_age"}
    score = 100
    for c in checks:
        if c["status"] == "fail":
            score -= 50 if c["check"] in HARD else 30
        elif c["status"] == "warn":
            score -= 10
    score = max(0, score)
    # high = at most one warning; medium = a few warnings or one soft failure; low = worse
    verdict = "high" if score >= 90 else "medium" if score >= 60 else "low"
    return {"verdict": verdict, "score": score, "checks": checks,
            "issues": [c for c in checks if c["status"] != "pass"]}


# ----------------------------------------------------------------- compare

def compare(results: List[dict], rank_by: str = "balanced") -> dict:
    """Cross-language ranking with a transparent formula.

    balanced = mean rank of (growth without spikes, human volume, share of the
    edition), each discounted by the trust verdict. Founders can re-rank on
    their own criteria from the table; this is only a sensible default."""
    rows = []
    for r in results:
        rows.append({
            "lang": r["lang"], "title": r["title"],
            "avg_daily_views": r["avg_daily_views"],
            "yoy_pct": r["yoy_pct"], "yoy_despiked_pct": r["yoy_despiked_pct"],
            "half_over_half_pct": r["half_over_half_pct"],
            "trend_annualised_pct": r["trend_annualised_pct"],
            "share_per_million_last12": r["share_per_million_last12"],
            "share_yoy_pct": r["share_yoy_pct"],
            "spike_share_pct": r["spikes"]["spike_share_pct"],
            "spike_events": r["spikes"]["spike_events"],
            "bot_share_pct": r["bot_share_pct"],
            "confidence": r["trust"]["verdict"],
        })
    weight = {"high": 1.0, "medium": 0.8, "low": 0.5}

    def growth_key(row):
        g = row["yoy_despiked_pct"]
        if g is None:
            g = row["half_over_half_pct"]
        return -1e9 if g is None else g

    keys = {
        "growth": lambda w: growth_key(w),
        "volume": lambda w: w["avg_daily_views"],
        "share": lambda w: w["share_per_million_last12"] or 0,
    }
    if rank_by in keys:
        ranked = sorted(rows, key=lambda w: -keys[rank_by](w) * weight[w["confidence"]])
        formula = f"{rank_by} x trust weight (high 1.0 / medium 0.8 / low 0.5)"
    else:
        n = len(rows)
        ranks = defaultdict(float)
        for k in ("growth", "volume", "share"):
            order = sorted(rows, key=lambda w: -keys[k](w))
            for i, w in enumerate(order):
                ranks[w["lang"]] += (n - i)
        for w in rows:
            w["balanced_score"] = round(ranks[w["lang"]] / (3 * n) * 100 * weight[w["confidence"]], 1)
        ranked = sorted(rows, key=lambda w: (-w["balanced_score"], -growth_key(w), -w["avg_daily_views"]))
        formula = ("mean rank of (yoy without spikes, avg daily views, share of edition) "
                   "x trust weight (high 1.0 / medium 0.8 / low 0.5)")
    for i, w in enumerate(ranked):
        w["rank"] = i + 1
    return {"rank_by": rank_by, "formula": formula, "table": ranked}
