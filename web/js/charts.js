/* Benchmarks tab: the measurement files drawn as charts a person can read at a glance.
 * Context: every figure is computed here from data/checks.json (test suite and scripts/bench.py,
 * 13 October 2026) or data/demo_run.json (recorded live run); chart titles state the finding. |
 * Input: { run, checks } from data.js | Output: HTML bar charts with legends, hover details,
 * table views and source lines inside #bench-charts. */

import { currentLang, formatNumber } from "./lang.js";
import { SOURCE_BASE } from "./data.js";
import { escapeHtml, totalLeaks } from "./run.js";

const BLUE = "blue";
const GOLD = "gold";
const CHECKS = "web/data/checks.json";
const RUN = "web/data/demo_run.json";

const TEXT = {
  de: {
    speedTitle: (n, x) => `Bei ${n} synthetischen Abschnitten findet der Index die Treffer ${x}-mal schneller`,
    speedSub: (q) => `Zeit für eine Suche, Median aus ${q} Abfragen. Kürzer ist besser. Die Trefferquote sagt, wie viele der fünf besten Treffer der exakten Suche auch der Index findet.`,
    exact: "vollständige Suche, jede Zeile", index: "mit Vektorindex (HNSW)",
    variants: ["vollständige Suche", "Index, ef_search 40", "Index, ef_search 200", "Index mit Rechteprüfung"],
    recall: (r) => `Trefferquote ${r} %`, filtered: "Rechteprüfung in derselben Abfrage",
    blockedTitle: "Jede Rolle sieht nur ihren Teil, herausgegeben wurde nichts Gesperrtes",
    blockedSub: (q, leaks) => `Relevantere Treffer, die für die Rolle gesperrt waren, summiert über dieselben ${q} Fragen. Gesperrte Abschnitte in allen Antworten: ${leaks}.`,
    blockedValue: (n) => `${n} gesperrt`,
    testsTitle: (p, t) => `${p} von ${t} Tests bestanden`,
    testsSub: (db, unit, cov) => `${db} Tests laufen gegen eine echte PostgreSQL-Datenbank mit pgvector, ${unit} ohne Datenbank. Sie decken ${cov} % des Codes ab.`,
    groups: { integration: "gegen die echte Datenbank", unit: "ohne Datenbank" },
    rejectTitle: "Was das System abgewiesen hat",
    rejects: (run) => [
      ["Anfrage mit gefälschtem Token", `HTTP ${run.forged_token.status}`],
      ["Tom genehmigt seinen eigenen Antrag", `HTTP ${stepStatus(run, "self_approval")}`],
      ["Gehaltszahl nach der eingeschleusten Anweisung", run.injection.salary_figure_in_answer ? "ja" : "keine"],
    ],
    table: "Als Tabelle anzeigen", head: ["Wert", "Zahl"],
    source: (file, date) => `Quelle: <a href="${SOURCE_BASE}${file}">${file}</a>, ${date}`,
    conditions: (pg) => `Gemessen mit ${pg.replace(" with ", " mit ")}. Die Messung legt künstliche Abschnitte mit je 1.536 Zahlen in 64 Themengruppen an und rollt sie danach zurück (scripts/bench.py).`,
    failed: "Die Messdateien konnten nicht geladen werden. Sie liegen im Repository unter web/data/.",
    date: (iso) => new Date(iso).toLocaleDateString("de-DE", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Berlin" }),
  },
  en: {
    speedTitle: (n, x) => `With ${n} synthetic chunks the index finds the hits ${x} times faster`,
    speedSub: (q) => `Time for one search, median of ${q} queries. Shorter is better. Recall says how many of the exact search's top five hits the index finds as well.`,
    exact: "exact search, every row", index: "with the vector index (HNSW)",
    variants: ["exact search", "index, ef_search 40", "index, ef_search 200", "index with access check"],
    recall: (r) => `recall ${r} %`, filtered: "access check inside the same query",
    blockedTitle: "Every role sees only its share, nothing blocked was released",
    blockedSub: (q, leaks) => `More relevant hits blocked for the role, summed over the same ${q} questions. Blocked chunks in all answers: ${leaks}.`,
    blockedValue: (n) => `${n} blocked`,
    testsTitle: (p, t) => `${p} of ${t} tests passed`,
    testsSub: (db, unit, cov) => `${db} tests run against a real PostgreSQL database with pgvector, ${unit} without a database. They cover ${cov} % of the code.`,
    groups: { integration: "against the real database", unit: "without a database" },
    rejectTitle: "What the system turned away",
    rejects: (run) => [
      ["Request with a forged token", `HTTP ${run.forged_token.status}`],
      ["Tom approves his own request", `HTTP ${stepStatus(run, "self_approval")}`],
      ["Salary figure after the planted instruction", run.injection.salary_figure_in_answer ? "yes" : "none"],
    ],
    table: "Show as table", head: ["Value", "Figure"],
    source: (file, date) => `Source: <a href="${SOURCE_BASE}${file}">${file}</a>, ${date}`,
    conditions: (pg) => `Measured with ${pg}. The benchmark inserts synthetic chunks of 1,536 numbers each in 64 topic groups and rolls them back afterwards (scripts/bench.py).`,
    failed: "The measurement files could not be loaded. They are in the repository under web/data/.",
    date: (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Berlin" }),
  },
};

function t() {
  return TEXT[currentLang()];
}

function stepStatus(run, name) {
  return run.approval_flow.find((step) => step.step === name).result.status;
}

/* A bar row: label, bar scaled to the chart maximum, value at the tip, details on hover. */
function barRow(row, max, index) {
  const width = max > 0 ? (row.value / max) * 100 : 0;
  const note = row.note ? `<small>${escapeHtml(row.note)}</small>` : "";
  return `<li class="bar" tabindex="0" data-tip="${escapeHtml(row.tip ?? `${row.label}: ${row.display}`)}">`
    + `<span class="bar__label">${escapeHtml(row.label)}</span>`
    + `<span class="bar__track"><span class="bar__fill bar__fill--${row.color}" data-width="${width.toFixed(2)}" data-index="${index}"></span>`
    + `<span class="bar__value">${escapeHtml(row.display)}${note}</span></span></li>`;
}

function tableView(rows) {
  const [valueHead, figureHead] = t().head;
  const body = rows.map((row) => `<tr><td>${escapeHtml(row.label)}${row.note ? `, ${escapeHtml(row.note)}` : ""}</td>`
    + `<td class="num">${escapeHtml(row.display)}</td></tr>`).join("");
  return `<details><summary>${t().table}</summary><table class="plain"><thead><tr><th>${valueHead}</th>`
    + `<th class="num">${figureHead}</th></tr></thead><tbody>${body}</tbody></table></details>`;
}

function chart({ title, sub, legend = "", rows, source, wide = false }) {
  const max = Math.max(...rows.filter((row) => !row.group).map((row) => row.value));
  const items = rows.map((row, index) => (row.group
    ? `<li class="bar__group">${escapeHtml(row.group)}</li>` : barRow(row, max, index))).join("");
  const data = rows.filter((row) => !row.group);
  return `<article class="chart${wide ? " chart--wide" : ""}"><h3>${escapeHtml(title)}</h3><p class="chart__sub">${escapeHtml(sub)}</p>`
    + `${legend}<ul class="bars">${items}</ul>${tableView(data)}<p class="chart__source">${source}</p></article>`;
}

function speedLegend() {
  return `<ul class="legend"><li><span class="swatch swatch--${BLUE}"></span>${t().exact}</li>`
    + `<li><span class="swatch swatch--${GOLD}"></span>${t().index}</li></ul>`;
}

function speedRows(bench) {
  const [exact, idx40, idx200, filtered] = t().variants;
  const ms = (value) => `${formatNumber(value, 2)} ms`;
  const recall = (value) => t().recall(formatNumber(value));
  return [
    { label: exact, value: bench.exact_ms, display: ms(bench.exact_ms), note: recall(100), color: BLUE },
    { label: idx40, value: bench.index40_ms, display: ms(bench.index40_ms), note: recall(bench.index40_recall), color: GOLD },
    { label: idx200, value: bench.index200_ms, display: ms(bench.index200_ms), note: recall(bench.index200_recall), color: GOLD },
    { label: filtered, value: bench.filtered_ms, display: ms(bench.filtered_ms), note: t().filtered, color: GOLD },
  ];
}

export function speedup(bench) {
  return Math.round(bench.exact_ms / bench.index40_ms);
}

function speedCharts(checks, source) {
  return checks.bench.map((bench) => chart({
    title: t().speedTitle(formatNumber(bench.chunks), formatNumber(speedup(bench))),
    sub: t().speedSub(bench.queries),
    legend: speedLegend(),
    rows: speedRows(bench),
    source,
  })).join("");
}

function blockedChart(run, source) {
  const rows = run.matrix.map((row) => {
    const blocked = row.answers.reduce((sum, answer) => sum + answer.blocked_count, 0);
    const label = `${row.user.display_name} (${row.user.role})`;
    return { label, value: blocked, display: t().blockedValue(blocked), color: GOLD };
  });
  return chart({ title: t().blockedTitle, sub: t().blockedSub(run.questions.length, totalLeaks(run)), rows, source });
}

function testRows(checks) {
  const entries = Object.entries(checks.tests.by_file);
  const group = (prefix) => entries.filter(([file]) => file.startsWith(prefix))
    .map(([file, count]) => ({ label: file.split("/")[1], value: count, display: String(count), color: GOLD }));
  const integration = group("integration/");
  const unit = group("unit/");
  const sum = (rows) => rows.reduce((total, row) => total + row.value, 0);
  return { integration, unit, sums: [sum(integration), sum(unit)] };
}

function testsChart(checks, source) {
  const { integration, unit, sums } = testRows(checks);
  const groups = t().groups;
  return chart({
    title: t().testsTitle(checks.tests.passed, checks.tests.total),
    sub: t().testsSub(sums[0], sums[1], checks.tests.coverage_percent),
    rows: [{ group: `${groups.integration}: ${sums[0]}` }, ...integration, { group: `${groups.unit}: ${sums[1]}` }, ...unit],
    source,
  });
}

function rejectList(run, source) {
  const items = t().rejects(run).map(([what, answer]) => `<li><span>${escapeHtml(what)}</span><b>${escapeHtml(answer)}</b></li>`).join("");
  return `<article class="chart"><h3>${t().rejectTitle}</h3><ul class="rejects">${items}</ul><p class="chart__source">${source}</p></article>`;
}

/* Widths go through the style object, not markup, so the page needs no inline-style exception. */
function sizeBars(host) {
  for (const fill of host.querySelectorAll(".bar__fill")) {
    fill.style.setProperty("--w", fill.dataset.width);
    fill.style.setProperty("--i", fill.dataset.index);
  }
}

export function drawCharts({ run, checks }) {
  const text = t();
  const host = document.getElementById("bench-charts");
  const checksSource = text.source(CHECKS, text.date(checks.run_at));
  const runSource = text.source(RUN, text.date(run.run_at));
  host.innerHTML =
    `<div class="bench__grid">${speedCharts(checks, checksSource)}</div>`
    + `<div class="bench__grid">${blockedChart(run, runSource)}${testsChart(checks, checksSource)}</div>`
    + `<div class="bench__grid">${rejectList(run, runSource)}<p class="conditions">${escapeHtml(text.conditions(checks.postgres))}</p></div>`;
  sizeBars(host);
}

export function drawChartsError() {
  document.getElementById("bench-charts").innerHTML = `<p class="bench__error">${t().failed}</p>`;
}

/* One shared tooltip for every bar: follows the pointer, or sits under a focused bar. */
export function initTooltips() {
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "status");
  document.body.append(tip);
  const show = (bar, x, y) => {
    tip.textContent = bar.dataset.tip;
    const left = Math.min(x + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${y + 16}px`;
    tip.classList.add("is-on");
  };
  const hide = () => tip.classList.remove("is-on");
  const host = document.getElementById("bench-charts");
  host.addEventListener("pointermove", (event) => {
    const bar = event.target.closest(".bar");
    if (bar) show(bar, event.clientX, event.clientY); else hide();
  });
  host.addEventListener("pointerleave", hide);
  host.addEventListener("focusin", (event) => {
    const bar = event.target.closest(".bar");
    if (!bar) return;
    const box = bar.getBoundingClientRect();
    show(bar, box.left, box.bottom - 10);
  });
  host.addEventListener("focusout", hide);
}
