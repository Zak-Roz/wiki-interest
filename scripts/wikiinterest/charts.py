"""Charts. Deliberately few and consistent so a report reader learns them once:

- overview.png : monthly human views per language + views per 1M edition views
- indexed.png  : same series indexed to the first 3 months = 100 (growth shape)
- daily_<lang>.png : daily views with detected spikes marked (for explaining spikes)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .i18n import labels  # noqa: E402

PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b",
           "#17becf", "#e377c2"]


def _months_to_dates(months: List[str]) -> List[dt.date]:
    return [dt.date(int(m[:4]), int(m[5:7]), 1) for m in months]


def _style(ax):
    ax.grid(True, alpha=0.3)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.tick_params(axis="x", labelrotation=0, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)


def _series_label(r: dict) -> str:
    t = r["title"] if len(r["title"]) <= 28 else r["title"][:26] + "…"
    return f"{r['lang']}: {t}"


def overview_chart(results: List[dict], out: Path, lang: str = "en", topic: str = "") -> Path:
    L = labels(lang)
    has_share = any(r.get("monthly_share_per_million") for r in results)
    fig, axes = plt.subplots(2 if has_share else 1, 1, figsize=(8, 5.6 if has_share else 3.2),
                             sharex=True)
    axes = list(axes) if has_share else [axes]
    ax = axes[0]
    for i, r in enumerate(results):
        months = list(r["monthly_views"])
        ax.plot(_months_to_dates(months), list(r["monthly_views"].values()),
                marker="o", ms=3, lw=1.6, color=PALETTE[i % len(PALETTE)], label=_series_label(r))
    vals = [v for r in results for v in r["monthly_views"].values() if v > 0]
    if vals and max(vals) / max(min(vals), 1) > 40:
        ax.set_yscale("log")
    ax.set_title(L["monthly_views"], fontsize=10, loc="left")
    _style(ax)
    if has_share:
        ax2 = axes[1]
        for i, r in enumerate(results):
            sh = r.get("monthly_share_per_million") or {}
            if not sh:
                continue
            months = list(sh)
            ax2.plot(_months_to_dates(months), [v or 0 for v in sh.values()],
                     marker="o", ms=3, lw=1.6, color=PALETTE[i % len(PALETTE)])
        ax2.set_title(L["share_title"], fontsize=10, loc="left")
        _style(ax2)
    handles, labels_ = axes[0].get_legend_handles_labels()
    ncol = min(3, max(1, len(results)))
    fig.legend(handles, labels_, loc="lower center", ncol=ncol, fontsize=7.5, frameon=False)
    fig.tight_layout(rect=[0, 0.04 + 0.03 * ((len(results) - 1) // ncol), 1, 1])
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def indexed_chart(results: List[dict], out: Path, lang: str = "en") -> Path:
    L = labels(lang)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    for i, r in enumerate(results):
        months = list(r["monthly_views_despiked"])
        vals = list(r["monthly_views_despiked"].values())
        base = sum(vals[:3]) / max(len(vals[:3]), 1) or 1
        ax.plot(_months_to_dates(months), [100 * v / base for v in vals],
                lw=1.8, color=PALETTE[i % len(PALETTE)], label=_series_label(r))
    ax.axhline(100, color="grey", lw=0.8, ls="--")
    ax.set_title(L["index_title"], fontsize=10, loc="left")
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def daily_chart(r: dict, daily: dict, out: Path, lang: str = "en") -> Path:
    L = labels(lang)
    days = sorted(daily)
    xs = [dt.date.fromisoformat(d) for d in days]
    ys = [daily[d] for d in days]
    fig, ax = plt.subplots(figsize=(8, 3.0))
    ax.plot(xs, ys, lw=0.9, color=PALETTE[0])
    spikes = r["spikes"]["top_spikes"]
    if spikes:
        ax.scatter([dt.date.fromisoformat(s["peak"]) for s in spikes],
                   [s["views"] for s in spikes], color=PALETTE[1], zorder=3, s=22,
                   label=f"{L['spike']} (top {len(spikes)})")
        for s in spikes[:4]:
            ax.annotate(f"{s['peak']} ({s['x_baseline']}x)", (dt.date.fromisoformat(s["peak"]), s["views"]),
                        fontsize=7, xytext=(4, 2), textcoords="offset points")
        ax.legend(fontsize=8, frameon=False)
    ax.set_title(L["daily_title"].format(lang=r["lang"], title=r["title"]), fontsize=10, loc="left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out
