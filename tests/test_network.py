"""Network-restricted environments (claude.ai chat sandbox, locked-down orgs).
No real network is touched: requests.Session.get is replaced per test."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
from wikiinterest import cli, helper  # noqa: E402
from wikiinterest.client import Client, NetworkBlocked  # noqa: E402


class FakeResp:
    def __init__(self, status, headers=None, text=""):
        self.status_code, self.headers, self.text = status, headers or {}, text

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def empty_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(cli, "CHAT_OUTPUTS", tmp_path / "no-chat-outputs")  # not in claude.ai
    return tmp_path


def _counting(monkeypatch, behaviour):
    calls = []

    def fake_get(self, url, timeout=None):
        calls.append(url)
        return behaviour(url)
    monkeypatch.setattr(requests.Session, "get", fake_get)
    return calls


def test_proxy_403_is_blocked_without_retry(empty_cache, monkeypatch):
    calls = _counting(monkeypatch, lambda u: FakeResp(403, {"x-deny-reason": "host_not_allowed"},
                                                      "Host not in allowlist"))
    c = Client()
    with pytest.raises(NetworkBlocked) as e:
        c.get_json("https://wikimedia.org/api/rest_v1/x")
    assert e.value.host == "wikimedia.org" and "host_not_allowed" in e.value.reason
    assert len(calls) == 1
    with pytest.raises(NetworkBlocked):          # remembered: no second request
        c.get_json("https://wikimedia.org/api/rest_v1/y")
    assert len(calls) == 1


def test_connect_rejected_fails_fast(empty_cache, monkeypatch):
    def boom(u):
        raise requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")
    calls = _counting(monkeypatch, boom)
    t = time.time()
    with pytest.raises(NetworkBlocked):
        Client().get_json("https://www.wikidata.org/w/api.php?x=1")
    assert len(calls) == 1 and time.time() - t < 1.0   # previously: 4 attempts, ~12 s of sleeps


def test_real_404_from_wikimedia_is_not_blocked(empty_cache, monkeypatch):
    _counting(monkeypatch, lambda u: FakeResp(404, {}, "not found"))
    assert Client().get_json("https://wikimedia.org/api/rest_v1/z", ok404=True) is None


def test_run_blocked_prints_guidance_and_writes_helper(empty_cache, monkeypatch, capsys):
    _counting(monkeypatch, lambda u: FakeResp(403, {"x-deny-reason": "host_not_allowed"}, ""))
    out = empty_cache / "out"
    rc = cli.main(["run", "--topic", "intermittent fasting", "--langs", "pl,cs",
                   "--report-lang", "uk", "--out", str(out)])
    text = capsys.readouterr().out
    assert rc == cli.EXIT_BLOCKED
    assert "NETWORK BLOCKED" in text and "Do NOT substitute" in text
    for host in ("wikimedia.org", "www.wikidata.org", "pl.wikipedia.org", "cs.wikipedia.org"):
        assert host in text
    page = out / "wiki-fetch-data.html"
    assert page.exists() and "Завантажити дані" in page.read_text(encoding="utf-8")


def test_wikidata_blocked_but_titles_given(empty_cache, monkeypatch, capsys):
    """Only Wikidata blocked + every article given explicitly -> Wikidata is never needed."""
    monkeypatch.setenv("WIKI_CACHE_DIR", str(empty_cache / "fix"))
    fixtures.seed_all()
    calls = _counting(monkeypatch, lambda u: FakeResp(403, {"x-deny-reason": "host_not_allowed"}, ""))
    rc = cli.main(["run", "--topic", "post przerywany", "--langs", "pl,cs",
                   "--article", "pl:Post przerywany", "--article", "cs:Přerušovaný půst",
                   "--no-report", "--out", str(empty_cache / "o")])
    assert rc == 0 and not calls
    assert "(explicit)" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_helper_roundtrip(empty_cache, monkeypatch):
    """The helper page's JS must request exactly what the pipeline needs, and
    importing its bundle must reproduce a direct run number for number."""
    fix = empty_cache / "fix"
    monkeypatch.setenv("WIKI_CACHE_DIR", str(fix))
    fixtures.seed_all()
    s, e = cli.month_bounds(*cli.default_window(24))
    cfg = helper.build_config("intermittent fasting", "en", ["pl", "cs"], {}, s, e)
    cfg_p, bundle_p = empty_cache / "cfg.json", empty_cache / "bundle.json"
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False))
    p = subprocess.run(["node", str(ROOT / "tests" / "run_helper_node.js"), str(fix), str(cfg_p),
                        str(bundle_p)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert cli.main(["run", "--topic", "intermittent fasting", "--langs", "pl,cs", "--offline",
                     "--no-report", "--out", str(empty_cache / "direct")]) == 0
    monkeypatch.setenv("WIKI_CACHE_DIR", str(empty_cache / "fresh"))
    assert cli.main(["run", "--import", str(bundle_p), "--no-report",
                     "--out", str(empty_cache / "imported")]) == 0
    d = json.loads((empty_cache / "direct" / "results.json").read_text())
    i = json.loads((empty_cache / "imported" / "results.json").read_text())
    for a, b in zip(d["results"], i["results"]):
        for k in ("title", "avg_daily_views", "yoy_despiked_pct", "share_per_million_last12",
                  "bot_share_pct", "created", "trust"):
            assert a[k] == b[k], k
    assert i["cache"]["requests"] == 0


def test_import_rejects_other_languages(empty_cache, tmp_path):
    s, e = dt.date(2024, 9, 1), dt.date(2026, 8, 31)
    b = {"format": helper.BUNDLE_FORMAT, "config": helper.build_config("x", "en", ["pl"], {}, s, e),
         "records": []}
    f = tmp_path / "b.json"
    f.write_text(json.dumps(b))
    with pytest.raises(SystemExit) as ex:
        cli.main(["run", "--import", str(f), "--langs", "pl,cs", "--out", str(tmp_path / "o")])
    assert "made for --langs pl" in str(ex.value)
