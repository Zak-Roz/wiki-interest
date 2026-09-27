"""No-network path: a one-page HTML helper the user opens in their own browser,
and the importer for the JSON bundle it downloads.

Why this exists: in some agent environments (claude.ai chat with the default
network allowlist, locked-down Team/Enterprise orgs) the sandbox cannot reach
Wikimedia at all. The data is public, so the user's own browser can fetch it;
the sandbox only needs the resulting file. Import rebuilds every cache entry
with the same URL builders the online pipeline uses, so `run --import` gives
exactly the analysis an online run would.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Dict, List

from . import fetch, resolve
from .client import cache_put

ASSETS = Path(__file__).resolve().parents[2] / "assets"
BUNDLE_FORMAT = "wiki-interest-bundle/1"

TEXT = {
    "en": {"title": "Wikipedia data for the wiki-interest analysis",
           "intro": "Your AI assistant cannot reach Wikipedia from its sandbox. This page downloads the public pageview data in your browser instead - nothing is sent anywhere else.",
           "what": "Topic: {topic} · languages: {langs} · {start} – {end}",
           "button": "Download data", "busy": "Downloading…",
           "done": "Done. Saved wiki-data.json - go back to the chat and upload this file.",
           "again": "If the download did not start, click here to save wiki-data.json",
           "fail": "Something failed: {err}. Check your internet connection and try again."},
    "uk": {"title": "Дані Wikipedia для аналізу wiki-interest",
           "intro": "AI-асистент не може звернутися до Wikipedia зі своєї пісочниці. Ця сторінка завантажить публічні дані про перегляди у вашому браузері — нікуди більше нічого не надсилається.",
           "what": "Тема: {topic} · мови: {langs} · {start} – {end}",
           "button": "Завантажити дані", "busy": "Завантажую…",
           "done": "Готово. Збережено wiki-data.json — поверніться в чат і завантажте цей файл.",
           "again": "Якщо завантаження не почалося, натисніть тут, щоб зберегти wiki-data.json",
           "fail": "Помилка: {err}. Перевірте з'єднання з інтернетом і спробуйте ще раз."},
    "pl": {"title": "Dane z Wikipedii do analizy wiki-interest",
           "intro": "Asystent AI nie może połączyć się z Wikipedią ze swojego środowiska. Ta strona pobierze publiczne dane o odsłonach w Twojej przeglądarce — nic nie jest wysyłane nigdzie indziej.",
           "what": "Temat: {topic} · języki: {langs} · {start} – {end}",
           "button": "Pobierz dane", "busy": "Pobieram…",
           "done": "Gotowe. Zapisano wiki-data.json — wróć do czatu i prześlij ten plik.",
           "again": "Jeśli pobieranie się nie rozpoczęło, kliknij tutaj, aby zapisać wiki-data.json",
           "fail": "Błąd: {err}. Sprawdź połączenie z internetem i spróbuj ponownie."},
}


def build_config(topic: str, topic_lang: str, langs: List[str], overrides: Dict[str, str],
                 start: dt.date, end: dt.date) -> dict:
    return {"topic": topic, "topic_lang": topic_lang, "langs": list(langs),
            "overrides": dict(overrides), "start": start.isoformat(), "end": end.isoformat(),
            "start_ymd": start.strftime("%Y%m%d"), "end_ymd": end.strftime("%Y%m%d")}


def write_helper(cfg: dict, path: Path, lang: str = "en") -> Path:
    T = dict(TEXT["en"])
    T.update(TEXT.get(lang, {}))
    js = (ASSETS / "fetch_helper.js").read_text(encoding="utf-8")
    what = T["what"].format(topic=cfg["topic"], langs=", ".join(cfg["langs"]),
                            start=cfg["start"], end=cfg["end"])
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    t_json = json.dumps(T, ensure_ascii=False).replace("</", "<\\/")
    page = f"""<!doctype html>
<html lang="{html.escape(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(T['title'])}</title>
<style>
 body{{font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;color:#1b1f24;background:#fff}}
 @media (prefers-color-scheme:dark){{body{{color:#e6e8eb;background:#16181b}} pre{{background:#22262b!important}}}}
 button{{font-size:17px;padding:12px 22px;border-radius:8px;border:0;background:#2563eb;color:#fff;cursor:pointer}}
 button:disabled{{opacity:.6;cursor:default}}
 pre{{background:#f3f5f7;padding:12px;border-radius:8px;white-space:pre-wrap;max-height:320px;overflow:auto;font-size:13px}}
 .muted{{opacity:.75;font-size:14px}} .ok{{color:#15803d;font-weight:600}} .err{{color:#b91c1c;font-weight:600}}
</style></head><body>
<h1 style="font-size:22px">{html.escape(T['title'])}</h1>
<p>{html.escape(T['intro'])}</p>
<p class="muted">{html.escape(what)}</p>
<p><button id="go">{html.escape(T['button'])}</button></p>
<p id="status"></p>
<pre id="log"></pre>
<script>
{js}
const CFG = {cfg_json};
const T = {t_json};
const logEl = document.getElementById('log');
const log = (s) => {{ logEl.textContent += s + '\\n'; logEl.scrollTop = logEl.scrollHeight; }};
function save(bundle) {{
  const blob = new Blob([JSON.stringify(bundle)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'wiki-data.json'; a.textContent = T.again;
  document.body.appendChild(a); a.click();
  return a;
}}
document.getElementById('go').onclick = async () => {{
  const btn = document.getElementById('go'), st = document.getElementById('status');
  btn.disabled = true; btn.textContent = T.busy; st.textContent = '';
  try {{
    const bundle = await collect(CFG, (u) => fetch(u), log);
    log('records: ' + bundle.records.length);
    save(bundle);
    st.className = 'ok'; st.textContent = T.done;
  }} catch (e) {{
    st.className = 'err'; st.textContent = T.fail.replace('{{err}}', e.message);
    btn.disabled = false; btn.textContent = T.button;
  }}
}};
</script></body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path


def load_bundle(path: Path) -> dict:
    try:
        b = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"--import: cannot read {path}: {e}")
    if not isinstance(b, dict) or b.get("format") != BUNDLE_FORMAT:
        raise SystemExit(f"--import: {path} is not a wiki-interest data file "
                         f"(expected format {BUNDLE_FORMAT}); regenerate it with the helper page")
    return b


def _url_for(r: dict, cfg: dict, start: dt.date, end: dt.date) -> str:
    k = r["kind"]
    if k == "wd_search":
        return resolve.wd_search_url(r["text"], r["lang"])
    if k == "wd_entities":
        return resolve.wd_sitelinks_url(r["qid"], r["langs"])
    if k == "qid_for_title":
        return resolve.qid_url(r["lang"], r["title"])
    if k == "canonical":
        return fetch.canonical_url(r["lang"], r["title"])
    if k == "search":
        return fetch.search_url(r["lang"], r["query"])
    if k == "article":
        return fetch.article_url(r["lang"], r["title"], start, end, r["agent"])
    if k == "project":
        return fetch.project_url(r["lang"], start, end, r.get("agent", "user"))
    if k == "first_rev":
        return fetch.first_revision_url(r["lang"], r["title"])
    raise ValueError(f"unknown record kind {k!r}")


def import_bundle(bundle: dict) -> int:
    """Write every record into the response cache; returns the number imported."""
    cfg = bundle["config"]
    start, end = dt.date.fromisoformat(cfg["start"]), dt.date.fromisoformat(cfg["end"])
    n = 0
    for r in bundle.get("records", []):
        try:
            url = _url_for(r, cfg, start, end)
        except (KeyError, ValueError):
            continue
        cache_put(url, int(r.get("status", 200)), r.get("body"))
        n += 1
    return n
