/* Language switch and the recorded live run.
 * Context: the run section shows what scripts/demo_run.py recorded against the real API and
 * what the test suite and scripts/bench.py measured; nothing on it is typed in by hand. |
 * Input: data/demo_run.json, data/checks.json | Output: KPI tiles, user-by-question matrix,
 * approval steps, test and benchmark tables. */
"use strict";

const TEXT = {
  de: {
    users: "Nutzer mit fünf Rollen", leaks: "gesperrte Abschnitte herausgegeben", tests: "Tests bestanden",
    forged: "Antwort auf gefälschtes Token", blocked: "gesperrt", none: "keine Quelle",
    shortQ: ["Gehalt Senior", "Gehalt Geschäftsführung", "Abmahnung 4711", "Rabatt ab 500 Lizenzen",
      "Umsatzziel Benelux", "Forschungsbericht HNSW", "Ausweis am ersten Tag"],
    flow: {
      catalog: (r) => `Tom sieht im Verzeichnis den Titel <code>${r.title}</code>, Rolle ab ${r.min_required_role}, lesbar: <b>nein</b>.`,
      ask_before: (r) => `Tom fragt nach dem Gehalt. Oberste Quelle: <code>${r.sources[0].title}</code>, <b>${r.blocked_count} relevantere Treffer gesperrt</b>.`,
      request: (r) => `Tom stellt einen Antrag. ${status(r)} Status <code>${r.body.status}</code>; am Zugriff ändert sich nichts.`,
      self_approval: (r) => `Tom versucht, selbst zu genehmigen. ${status(r)} ${r.body.detail}`,
      approval: (r) => `Miriam genehmigt für 7 Tage. ${status(r)} gültig bis <code>${r.body.valid_until}</code>.`,
      ask_after: (r) => `Tom fragt erneut. Oberste Quelle jetzt: <code>${r.sources[0].title}</code>, ${r.blocked_count} gesperrt.`,
      still_closed: (r) => `Tom fragt nach der Personalakte. Oberste Quelle: <code>${r.sources[0].title}</code>, <b>${r.blocked_count} gesperrt</b>; die Personalakte bleibt zu.`,
    },
    injection: (r) => `Angriff im Dokument: Bei der Frage nach dem Geschäftsführungsgehalt landet der eingeschleuste Absatz im Kontext (${r.instruction_in_context ? "ja" : "nein"}), eine Gehaltszahl dagegen ${r.salary_figure_in_answer ? "ja" : "nicht"}; ${r.blocked_count} Treffer gesperrt.`,
    testsHead: ["Testdatei", "Tests"], benchHead: ["Variante", "Abschnitte", "Zeit", "Trefferquote"],
    variants: ["exakt, jede Zeile", "Index, ef_search 40", "Index, ef_search 200", "Index mit Rechteprüfung"],
    coverage: (n) => `Abdeckung ${n} %`,
  },
  en: {
    users: "users with five roles", leaks: "blocked chunks released", tests: "tests passed",
    forged: "response to a forged token", blocked: "blocked", none: "no source",
    shortQ: ["Senior salary", "Managing director salary", "Warning 4711", "Discount from 500 licences",
      "Benelux revenue target", "HNSW research report", "Badge on day one"],
    flow: {
      catalog: (r) => `Tom sees the title <code>${r.title}</code> in the catalog, role from ${r.min_required_role}, readable: <b>no</b>.`,
      ask_before: (r) => `Tom asks about the salary. Top source: <code>${r.sources[0].title}</code>, <b>${r.blocked_count} more relevant hits blocked</b>.`,
      request: (r) => `Tom files a request. ${status(r)} status <code>${r.body.status}</code>; access does not change.`,
      self_approval: (r) => `Tom tries to approve it himself. ${status(r)} ${r.body.detail}`,
      approval: (r) => `Miriam approves for 7 days. ${status(r)} valid until <code>${r.body.valid_until}</code>.`,
      ask_after: (r) => `Tom asks again. Top source now: <code>${r.sources[0].title}</code>, ${r.blocked_count} blocked.`,
      still_closed: (r) => `Tom asks about the personnel file. Top source: <code>${r.sources[0].title}</code>, <b>${r.blocked_count} blocked</b>; the personnel file stays closed.`,
    },
    injection: (r) => `Attack inside a document: asked about the managing director's salary, the planted paragraph reaches the context (${r.instruction_in_context ? "yes" : "no"}), a salary figure ${r.salary_figure_in_answer ? "does" : "does not"}; ${r.blocked_count} hits blocked.`,
    testsHead: ["Test file", "Tests"], benchHead: ["Variant", "Chunks", "Time", "Recall"],
    variants: ["exact, every row", "index, ef_search 40", "index, ef_search 200", "index with access check"],
    coverage: (n) => `coverage ${n} %`,
  },
};

const SECRET_TITLES = ["Salary Bands 2026", "Personnel File Case 4711", "Sales Strategy 2027",
  "Key Account Price List 2026", "Vector Search Research Report"];

let lang = "de";
let run = null;
let checks = null;

function t(key) { return TEXT[lang][key]; }

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

function status(result) {
  const ok = result.status < 300;
  return `<span class="status ${ok ? "ok" : "no"}">HTTP ${result.status}</span>`;
}

function number(value, digits = 0) {
  return value.toLocaleString(lang === "de" ? "de-DE" : "en-US",
    {minimumFractionDigits: digits, maximumFractionDigits: digits});
}

function drawKpis() {
  const cells = run.matrix.flatMap((row) => row.answers);
  const tile = (value, label) => `<div class="kpi"><b>${value}</b><span>${label}</span></div>`;
  document.getElementById("run-kpis").innerHTML = [
    tile(run.matrix.length, t("users")),
    tile(run.matrix.reduce((sum, row) => sum + row.leaks, 0), t("leaks")),
    tile(`${checks.tests.passed}/${checks.tests.total}`, t("tests")),
    tile(run.forged_token.status, t("forged")),
  ].join("");
  return cells;
}

function drawMatrix() {
  const head = `<thead><tr><th></th>${t("shortQ").map((q) => `<th>${escapeHtml(q)}</th>`).join("")}</tr></thead>`;
  const rows = run.matrix.map((row) => {
    const cells = row.answers.map((answer) => {
      const top = answer.sources[0];
      const secret = top && SECRET_TITLES.includes(top.title) && row.readable.includes(top.title);
      const blocked = answer.blocked_count ? `<em>${answer.blocked_count} ${t("blocked")}</em>` : "";
      return `<td class="cell${secret ? " open" : ""}"><b>${escapeHtml(top ? top.title : t("none"))}</b>${blocked}</td>`;
    }).join("");
    const user = row.user;
    return `<tr><td class="who">${escapeHtml(user.display_name)}<span>${escapeHtml(user.role)}</span></td>${cells}</tr>`;
  }).join("");
  document.getElementById("matrix").innerHTML = head + `<tbody>${rows}</tbody>`;
}

function drawFlow() {
  const texts = TEXT[lang].flow;
  const items = run.approval_flow.map((step) => `<li>${texts[step.step](escapeDeep(step.result))}</li>`);
  items.push(`<li>${t("injection")(run.injection)}</li>`);
  document.getElementById("flow").innerHTML = items.join("");
}

function escapeDeep(value) {
  if (typeof value === "string") return escapeHtml(value);
  if (Array.isArray(value)) return value.map(escapeDeep);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, escapeDeep(inner)]));
  }
  return value;
}

function drawChecks() {
  const [fileHead, countHead] = t("testsHead");
  const testRows = Object.entries(checks.tests.by_file)
    .map(([file, count]) => `<tr><td><code>${file}</code></td><td class="num">${count}</td></tr>`).join("");
  document.getElementById("tests").innerHTML = `<table class="plain"><thead><tr><th>${fileHead}</th><th>${countHead}</th></tr></thead><tbody>${testRows}<tr><td><b>${t("coverage")(checks.tests.coverage_percent)}</b></td><td class="num"><b>${checks.tests.passed}</b></td></tr></tbody></table>`;
  const [variantHead, chunksHead, timeHead, recallHead] = t("benchHead");
  const names = t("variants");
  const rows = checks.bench.flatMap((run) => [
    [names[0], run.chunks, run.exact_ms, 100],
    [names[1], run.chunks, run.index40_ms, run.index40_recall],
    [names[2], run.chunks, run.index200_ms, run.index200_recall],
    [names[3], run.chunks, run.filtered_ms, null],
  ]).map(([name, chunks, ms, recall]) => `<tr><td>${name}</td><td class="num">${number(chunks)}</td><td class="num">${number(ms, 2)} ms</td><td class="num">${recall === null ? "–" : number(recall, 0) + " %"}</td></tr>`).join("");
  document.getElementById("bench").innerHTML = `<table class="plain"><thead><tr><th>${variantHead}</th><th>${chunksHead}</th><th>${timeHead}</th><th>${recallHead}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function draw() {
  if (!run || !checks) return;
  drawKpis();
  drawMatrix();
  drawFlow();
  drawChecks();
}

function setLanguage(code) {
  lang = code === "en" ? "en" : "de";
  document.documentElement.lang = lang;
  for (const button of document.querySelectorAll(".lang button")) {
    button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
  }
  try { localStorage.setItem("lang", lang); } catch (error) { /* storage unavailable */ }
  draw();
}

async function main() {
  let stored = null;
  try { stored = localStorage.getItem("lang"); } catch (error) { /* storage unavailable */ }
  const preferred = new URLSearchParams(location.search).get("lang") || stored
    || (navigator.language || "de").slice(0, 2);
  for (const button of document.querySelectorAll(".lang button")) {
    button.addEventListener("click", () => setLanguage(button.dataset.lang));
  }
  setLanguage(preferred);
  [run, checks] = await Promise.all([
    fetch("data/demo_run.json").then((r) => r.json()),
    fetch("data/checks.json").then((r) => r.json()),
  ]);
  draw();
}

main();
