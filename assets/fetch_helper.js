// wiki-interest browser helper.
//
// Used when the agent's sandbox cannot reach Wikimedia (e.g. claude.ai chat with
// the default network allowlist). The user opens the generated HTML page in
// their own browser; this script makes exactly the public API calls the Python
// pipeline would make (Wikidata -> article titles -> pageviews), and saves them
// as one JSON bundle. `wiki.py run --import bundle.json` then rebuilds the same
// cache entries in Python, so the analysis is identical to an online run.
//
// Records are semantic ({kind, lang, title, ...}), not raw URLs: Python rebuilds
// each URL with its own builders, so encoding differences between JavaScript and
// Python can never cause a cache miss.

const WD = 'https://www.wikidata.org/w/api.php';
const PV = 'https://wikimedia.org/api/rest_v1/metrics/pageviews';
const mw = (lang) => `https://${lang}.wikipedia.org/w/api.php`;
const q = (s) => encodeURIComponent(s);
const CORS = '&origin=*'; // MediaWiki/Wikidata need this for anonymous cross-origin reads

async function getJSON(fetchFn, url) {
  const r = await fetchFn(url);
  if (r.status === 404) return { status: 404, body: null };
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return { status: 200, body: await r.json() };
}

const pages = (b) => (b && b.query && b.query.pages) || [];
const isDisambiguation = (d) => {
  const s = (d || '').toLowerCase();
  return s.includes('disambiguation') || s.includes('topics referred to');
};

async function collect(cfg, fetchFn, log) {
  log = log || (() => {});
  const records = [];
  const rec = async (meta, url) => {
    const res = await getJSON(fetchFn, url);
    records.push(Object.assign({}, meta, { status: res.status, body: res.body }));
    return res.body;
  };
  const langs = cfg.langs;
  const ov = Object.assign({}, cfg.overrides || {});
  let links = {};
  let label = null;
  const topic = cfg.topic.trim();

  // 1. Wikidata item -> sitelinks (skipped when every language has an explicit title)
  if (!langs.every((l) => l in ov)) {
    let qid = null;
    const mLT = topic.match(/^([a-z]{2,3}(?:-[a-z]+)?):(.+)$/);
    if (/^Q\d+$/.test(topic)) {
      qid = topic;
    } else if (mLT) {
      log(`Wikidata item for ${topic}`);
      const b = await rec({ kind: 'qid_for_title', lang: mLT[1], title: mLT[2] },
        `${mw(mLT[1])}?action=query&prop=pageprops&ppprop=wikibase_item&titles=${q(mLT[2])}&redirects=1&format=json&formatversion=2${CORS}`);
      const p = pages(b)[0];
      qid = (p && p.pageprops && p.pageprops.wikibase_item) || null;
      if (!qid && !(mLT[1] in ov)) ov[mLT[1]] = mLT[2];
    } else {
      log(`Wikidata search: "${topic}"`);
      const b = await rec({ kind: 'wd_search', text: topic, lang: cfg.topic_lang },
        `${WD}?action=wbsearchentities&search=${q(topic)}&language=${cfg.topic_lang}&uselang=en&type=item&limit=7&format=json${CORS}`);
      const cands = ((b && b.search) || []).filter((c) => !isDisambiguation(c.description));
      let best = null, bestCov = -1;
      for (const c of cands.slice(0, 4)) {
        const info = await sitelinks(c.id);
        const cov = langs.filter((l) => l in info.links).length;
        if (cov > bestCov) { best = info; bestCov = cov; }
        if (cov === langs.length) break;
      }
      if (best) { qid = best.qid; label = best.label; links = best.links; }
    }
    if (qid && !label) {
      const info = await sitelinks(qid);
      label = info.label; links = info.links;
    }
  } else {
    label = topic;
  }

  async function sitelinks(qid) {
    const sites = langs.map((l) => `${l}wiki`).join('|');
    const b = await rec({ kind: 'wd_entities', qid: qid, langs: langs },
      `${WD}?action=wbgetentities&ids=${qid}&props=sitelinks|labels|descriptions&sitefilter=${q(sites)}&languages=en&format=json${CORS}`);
    const ent = (b && b.entities && b.entities[qid]) || {};
    const out = {};
    for (const [k, v] of Object.entries(ent.sitelinks || {})) out[k.slice(0, -4)] = v.title;
    const lab = ent.labels && ent.labels.en ? ent.labels.en.value : '';
    return { qid: qid, label: lab, links: out };
  }

  // 2. Per language: title, then the four data calls the pipeline needs
  const found = {};
  for (const lang of langs) {
    let title = null;
    if (lang in ov) {
      const b = await rec({ kind: 'canonical', lang: lang, title: ov[lang] },
        `${mw(lang)}?action=query&titles=${q(ov[lang])}&redirects=1&format=json&formatversion=2${CORS}`);
      const p = pages(b)[0];
      title = !p || p.missing ? ov[lang] : p.title;
    } else if (links[lang]) {
      title = links[lang];
    } else {
      const query = label || topic;
      log(`${lang}: no Wikidata link, searching "${query}"`);
      const b = await rec({ kind: 'search', lang: lang, query: query },
        `${mw(lang)}?action=query&list=search&srsearch=${q(query)}&srlimit=5&srnamespace=0&format=json&formatversion=2${CORS}`);
      const hits = (b && b.query && b.query.search) || [];
      title = hits.length ? hits[0].title : null;
    }
    if (!title) { log(`${lang}: no article found`); continue; }
    found[lang] = title;
    log(`${lang}: ${title}`);
    const t = q(title.replace(/ /g, '_'));
    for (const agent of ['user', 'all-agents']) {
      await rec({ kind: 'article', lang: lang, title: title, agent: agent },
        `${PV}/per-article/${lang}.wikipedia/all-access/${agent}/${t}/daily/${cfg.start_ymd}/${cfg.end_ymd}`);
    }
    await rec({ kind: 'project', lang: lang, agent: 'user' },
      `${PV}/aggregate/${lang}.wikipedia/all-access/user/daily/${cfg.start_ymd}00/${cfg.end_ymd}00`);
    await rec({ kind: 'first_rev', lang: lang, title: title },
      `${mw(lang)}?action=query&prop=revisions&titles=${q(title)}&rvlimit=1&rvdir=newer&rvprop=timestamp&redirects=1&format=json&formatversion=2${CORS}`);
  }
  return {
    format: 'wiki-interest-bundle/1',
    created_at: new Date().toISOString(),
    config: cfg,
    articles: found,
    records: records,
  };
}

if (typeof module !== 'undefined') module.exports = { collect };
