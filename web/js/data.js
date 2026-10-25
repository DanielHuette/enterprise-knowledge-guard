/* The two measurement files behind every number on the page.
 * Context: written by scripts/demo_run.py (recorded live run) and by the test suite plus
 * scripts/bench.py (checks); nothing here is typed in by hand. |
 * Input: data/demo_run.json, data/checks.json | Output: one cached promise of both. */

let pending = null;

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

export function loadData() {
  pending ??= Promise.all([fetchJson("data/demo_run.json"), fetchJson("data/checks.json")])
    .then(([run, checks]) => ({ run, checks }));
  return pending;
}

export const SOURCE_BASE = "https://github.com/DanielHuette/enterprise-knowledge-guard/blob/main/";
