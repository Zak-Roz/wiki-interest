"""Offline tests. Run:  python -m pytest tests -q
Fixtures seed a temporary cache so no network is touched."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
from wikiinterest import analyze, cli  # noqa: E402


@pytest.fixture(scope="session")
def cache(tmp_path_factory):
    d = tmp_path_factory.mktemp("cache")
    os.environ["WIKI_CACHE_DIR"] = str(d)
    fixtures.seed_all()
    return d


# ------------------------------------------------------------- analyze unit

def test_spike_detection_and_despiking():
    start, end = dt.date(2025, 1, 1), dt.date(2025, 6, 30)
    s = fixtures.gen_daily(start, end, 300, 0.0, noise=0.05,
                           spikes=[(dt.date(2025, 3, 10), 10.0, 2.0)])
    sp = analyze.detect_spikes(s)
    assert sp["spike_events"] == 1
    assert sp["top_spikes"][0]["peak"] in ("2025-03-10", "2025-03-11")
    assert 3 < sp["spike_share_pct"] < 20
    assert sp["despiked"]["2025-03-10"] < 700  # replaced by local baseline


def test_yoy_matches_generator_growth():
    start, end = dt.date(2024, 9, 1), dt.date(2026, 8, 31)
    s = fixtures.gen_daily(start, end, 500, 0.30, 0.3, 1, noise=0.0)
    r = analyze.analyze_series(s, None, None, {"lang": "xx", "title": "T", "had_data": True})
    assert 27 <= r["yoy_pct"] <= 33
    assert 27 <= r["trend_annualised_pct"] <= 33  # seasonality must not bias the trend
    assert r["trend_r2"] > 0.95
    assert r["peak_month"] == "Jan"


def test_trust_verdicts():
    start, end = dt.date(2024, 9, 1), dt.date(2026, 8, 31)
    tiny = fixtures.gen_daily(start, end, 5, 0.5, noise=0.3)
    r = analyze.analyze_series(tiny, None, None, {"lang": "xx", "title": "T", "had_data": True})
    assert r["trust"]["verdict"] == "low"
    assert any(c["check"] == "volume" and c["status"] == "fail" for c in r["trust"]["checks"])

    fresh = fixtures.gen_daily(start, end, 400, 0.0, noise=0.05, created=dt.date(2025, 6, 1))
    r = analyze.analyze_series(fresh, None, None,
                               {"lang": "xx", "title": "T", "had_data": True, "created": "2025-06-01"})
    assert any(c["check"] == "article_age" and c["status"] == "fail" for c in r["trust"]["checks"])

    spiky = fixtures.gen_daily(start, end, 200, 0.0, noise=0.05,
                               spikes=[(dt.date(2026, 5, 1), 60.0, 6.0)])
    r = analyze.analyze_series(spiky, None, None, {"lang": "xx", "title": "T", "had_data": True})
    gr = [c for c in r["trust"]["checks"] if c["check"] == "growth_robust"]
    assert gr and gr[0]["status"] in ("warn", "fail")


def test_bot_share_uses_all_agents():
    start, end = dt.date(2025, 1, 1), dt.date(2025, 12, 31)
    u = fixtures.gen_daily(start, end, 100, 0, noise=0)
    a = {k: v * 2 for k, v in u.items()}
    r = analyze.analyze_series(u, a, None, {"lang": "xx", "title": "T", "had_data": True})
    assert r["bot_share_pct"] == 50.0


# ---------------------------------------------------------- pipeline (CLI)

def test_run_two_languages(cache, tmp_path, capsys):
    out = tmp_path / "fasting"
    rc = cli.main(["run", "--topic", "intermittent fasting", "--langs", "pl,cs",
                   "--report-lang", "uk", "--offline", "--out", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "Q3030870" in text and "Post przerywany" in text and "Přerušovaný půst" in text
    assert "| pl |" in text and "| cs |" in text
    p = json.loads((out / "results.json").read_text())
    assert {r["lang"] for r in p["results"]} == {"pl", "cs"}
    cs = next(r for r in p["results"] if r["lang"] == "cs")
    assert cs["spikes"]["spike_events"] >= 2
    assert cs["yoy_despiked_pct"] < cs["yoy_pct"]
    for f in ("overview.png", "indexed.png", "daily_pl.png", "series.csv", "report.pdf"):
        assert (out / f).exists()
    from pypdf import PdfReader
    assert len(PdfReader(str(out / "report.pdf")).pages) == 1
    assert p["cache"]["requests"] == 0


def test_report_with_narrative(cache, tmp_path):
    out = tmp_path / "astro"
    assert cli.main(["run", "--topic", "астрономія", "--topic-lang", "uk", "--langs", "uk",
                     "--offline", "--out", str(out)]) == 0
    nar = tmp_path / "narrative.json"
    nar.write_text(json.dumps({"title": "Астрономія в укр. Wikipedia",
                               "recommendation": "Тестова рекомендація.",
                               "trust": ["uk: усе гаразд"], "caveats": ["Тест"]}, ensure_ascii=False))
    pdf = tmp_path / "final.pdf"
    assert cli.main(["report", "--results", str(out / "results.json"), "--narrative", str(nar),
                     "--lang", "uk", "--out", str(pdf)]) == 0
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    assert len(reader.pages) == 1
    assert "Тестова" in reader.pages[0].extract_text()


def test_search_fallback_is_flagged(cache, tmp_path, capsys):
    out = tmp_path / "english"
    assert cli.main(["run", "--topic", "English language", "--langs", "uk,sk", "--offline",
                     "--no-report", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "sk: Angličtina (search)" in text and "verify" in text


def test_override_and_redirects(cache, tmp_path, capsys):
    out = tmp_path / "f2"
    assert cli.main(["run", "--topic", "intermittent fasting", "--langs", "pl", "--article",
                     "pl:Post okresowy", "--include-redirects", "--offline", "--no-report",
                     "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Post przerywany (explicit) +2 redirects summed" in text


def test_unknown_topic_exits_nonzero(cache, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--topic", "Zorbulon protocol", "--langs", "pl", "--offline",
                  "--out", str(tmp_path / "z")])
    assert "no article found" in str(e.value)


def test_partial_month_refused(cache, tmp_path):
    this_month = dt.date.today().strftime("%Y-%m")
    with pytest.raises(SystemExit):
        cli.main(["run", "--topic", "x", "--langs", "pl", "--from", "2024-01", "--to", this_month,
                  "--offline", "--out", str(tmp_path / "p")])
