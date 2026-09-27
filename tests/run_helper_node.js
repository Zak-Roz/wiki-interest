// Test driver: run assets/fetch_helper.js in Node with a fetch() that serves
// responses from a wiki-interest cache directory (the Python fixtures).
// Usage: node tests/run_helper_node.js <cache_dir> <config.json> <out_bundle.json>
const fs = require('fs'), path = require('path');
const { collect } = require(path.join(__dirname, '..', 'assets', 'fetch_helper.js'));
const [cacheDir, cfgPath, outPath] = process.argv.slice(2);
const byUrl = new Map();
for (const f of fs.readdirSync(cacheDir)) {
  const rec = JSON.parse(fs.readFileSync(path.join(cacheDir, f), 'utf8'));
  byUrl.set(decodeURIComponent(rec.url), rec);
}
const requested = [];
const fakeFetch = async (url) => {
  if (!url.endsWith('&origin=*') && !url.startsWith('https://wikimedia.org/'))
    throw new Error('MediaWiki/Wikidata call without origin=* (CORS would fail): ' + url);
  const key = decodeURIComponent(url.replace('&origin=*', ''));
  requested.push(key);
  const rec = byUrl.get(key);
  if (!rec) throw new Error('helper requested a URL the pipeline never uses: ' + key);
  return { status: rec.status, ok: rec.status === 200, json: async () => rec.body };
};
(async () => {
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  const bundle = await collect(cfg, fakeFetch, () => {});
  fs.writeFileSync(outPath, JSON.stringify(bundle));
  console.log(JSON.stringify({ records: bundle.records.length, requests: requested.length, articles: bundle.articles }));
})().catch((e) => { console.error(e.message); process.exit(1); });
