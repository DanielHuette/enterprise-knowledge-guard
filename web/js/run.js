/* The recorded live run on the project tab.
 * Context: shows what scripts/demo_run.py recorded against the real API and what the test suite
 * and scripts/bench.py measured; nothing on it is typed in by hand. |
 * Input: data/demo_run.json, data/checks.json | Output: KPI tiles, user-by-question matrix,
 * approval steps, test and benchmark tables. */

import { currentLang, formatNumber } from "./lang.js";

const TEXT = {
  de: {
    users: "Nutzer mit fünf Rollen", leaks: "gesperrte Abschnitte herausgegeben", tests: "Tests bestanden",
    forged: "Antwort auf gefälschtes Token", blocked: "gesperrt", none: "keine Quelle", user: "Nutzer",
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
    failed: "Die Messdateien konnten nicht geladen werden. Sie liegen im Repository unter web/data/.",
  },
  en: {
    users: "users with five roles", leaks: "blocked chunks released", tests: "tests passed",
    forged: "response to a forged token", blocked: "blocked", none: "no source", user: "User",
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
    failed: "The measurement files could not be loaded. They are in the repository under web/data/.",
  },
};

const SECRET_TITLES = ["Salary Bands 2026", "Personnel File Case 4711", "Sales Strategy 2027",
  "Key Account Price List 2026", "Vector Search Research Report"];

function t(key) {
  return TEXT[currentLang()][key];
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function escapeDeep(value) {
  if (typeof value === "string") return escapeHtml(value);
  if (Array.isArray(value)) return value.map(escapeDeep);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, escapeDeep(inner)]));
  }
  return value;
}

function status(result) {
  const ok = result.status < 300;
  return `<span class="status ${ok ? "ok" : "no"}">HTTP ${result.status}</span>`;
}

export function totalLeaks(run) {
  return run.matrix.reduce((sum, row) => sum + row.leaks, 0);
}

function drawKpis(run, checks) {
  const tile = (value, label) => `<div class="kpi"><b>${value}</b><span>${label}</span></div>`;
  document.getElementById("run-kpis").innerHTML = [
    tile(run.matrix.length, t("users")),
    tile(totalLeaks(run), t("leaks")),
    tile(`${checks.tests.passed}/${checks.tests.total}`, t("tests")),
    tile(run.forged_token.status, t("forged")),
  ].join("");
}

function matrixCell(row, answer, label) {
  const top = answer.sources[0];
  const open = top && SECRET_TITLES.includes(top.title) && row.readable.includes(top.title);
  const blocked = answer.blocked_count ? `<em>${answer.blocked_count} ${t("blocked")}</em>` : "";
  return `<td class="cell${open ? " open" : ""}" data-label="${escapeHtml(label)}"><span><b>${escapeHtml(top ? top.title : t("none"))}</b>${blocked}</span></td>`;
}

function drawMatrix(run) {
  const labels = t("shortQ");
  const head = `<thead><tr><th>${t("user")}</th>${labels.map((q) => `<th>${escapeHtml(q)}</th>`).join("")}</tr></thead>`;
  const rows = run.matrix.map((row) => {
    const cells = row.answers.map((answer, index) => matrixCell(row, answer, labels[index])).join("");
    const user = row.user;
    return `<tr><td class="who">${escapeHtml(user.display_name)}<span>${escapeHtml(user.role)}</span></td>${cells}</tr>`;
  }).join("");
  document.getElementById("matrix").innerHTML = head + `<tbody>${rows}</tbody>`;
}

function drawFlow(run) {
  const texts = TEXT[currentLang()].flow;
  const items = run.approval_flow.map((step) => `<li>${texts[step.step](escapeDeep(step.result))}</li>`);
  items.push(`<li>${t("injection")(run.injection)}</li>`);
  document.getElementById("flow").innerHTML = items.join("");
}

function drawTests(checks) {
  const [fileHead, countHead] = t("testsHead");
  const rows = Object.entries(checks.tests.by_file)
    .map(([file, count]) => `<tr><td><code>${escapeHtml(file)}</code></td><td class="num">${count}</td></tr>`).join("");
  const total = `<tr><td><b>${t("coverage")(checks.tests.coverage_percent)}</b></td><td class="num"><b>${checks.tests.passed}</b></td></tr>`;
  document.getElementById("tests").innerHTML =
    `<table class="plain"><thead><tr><th>${fileHead}</th><th class="num">${countHead}</th></tr></thead><tbody>${rows}${total}</tbody></table>`;
}

function drawBench(checks) {
  const [variantHead, chunksHead, timeHead, recallHead] = t("benchHead");
  const names = t("variants");
  const rows = checks.bench.flatMap((bench) => [
    [names[0], bench.chunks, bench.exact_ms, 100],
    [names[1], bench.chunks, bench.index40_ms, bench.index40_recall],
    [names[2], bench.chunks, bench.index200_ms, bench.index200_recall],
    [names[3], bench.chunks, bench.filtered_ms, null],
  ]).map(([name, chunks, ms, recall]) => `<tr><td>${name}</td><td class="num">${formatNumber(chunks)}</td>`
    + `<td class="num">${formatNumber(ms, 2)} ms</td><td class="num">${recall === null ? "–" : `${formatNumber(recall)} %`}</td></tr>`).join("");
  document.getElementById("bench").innerHTML = `<table class="plain"><thead><tr><th>${variantHead}</th>`
    + `<th class="num">${chunksHead}</th><th class="num">${timeHead}</th><th class="num">${recallHead}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function drawRun(data) {
  drawKpis(data.run, data.checks);
  drawMatrix(data.run);
  drawFlow(data.run);
  drawTests(data.checks);
  drawBench(data.checks);
}

export function drawRunError() {
  document.getElementById("run-kpis").innerHTML = `<p class="bench__error">${t("failed")}</p>`;
}
