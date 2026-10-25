/* Entry point: language, tabs, and the content of each tab once it is first opened.
 * Context: the project tab renders right away; organigram, benchmarks and film are imported
 * only when their tab is shown, so the first view on a phone stays light. |
 * Input: DOM, data files | Output: a working four-tab page. */

import { initLangSwitch, onLangChange, currentLang } from "./lang.js";
import { initTabs } from "./tabs.js";
import { loadData } from "./data.js";
import { drawRun, drawRunError } from "./run.js";

const TITLES = {
  de: { base: "Enterprise Knowledge Guard", projekt: "Firmenwissen mit Rechteprüfung in der Datenbank", organigramm: "Organigramm", benchmarks: "Benchmarks", praesentation: "Präsentation" },
  en: { base: "Enterprise Knowledge Guard", projekt: "Company knowledge with access checks in the database", organigramm: "Org chart", benchmarks: "Benchmarks", praesentation: "Presentation" },
};

const loaded = new Map();
const redraws = new Set();
let activeTab = "projekt";

function setTitle() {
  const names = TITLES[currentLang()];
  document.title = activeTab === "projekt" ? `${names.base} — ${names.projekt}` : `${names[activeTab]} — ${names.base}`;
}

async function loadOrganigram() {
  const [{ initOrganigram, drawGate, setOrganigramActive }, data] = await Promise.all([import("./organigram.js"), loadData()]);
  initOrganigram(data.run);
  redraws.add(drawGate);
  return setOrganigramActive;
}

async function loadBenchmarks() {
  const charts = await import("./charts.js");
  charts.initTooltips();
  try {
    const data = await loadData();
    const draw = () => charts.drawCharts(data);
    draw();
    redraws.add(draw);
  } catch {
    charts.drawChartsError();
  }
  return () => {};
}

async function loadFilm() {
  const { initFilm, setFilmVisible, redrawFilm } = await import("./film.js");
  initFilm();
  redraws.add(redrawFilm);
  return setFilmVisible;
}

const LOADERS = { organigramm: loadOrganigram, benchmarks: loadBenchmarks, praesentation: loadFilm };

async function showTab(id) {
  activeTab = id;
  setTitle();
  for (const [name, toggle] of loaded) (await toggle)(name === id);
  if (!loaded.has(id) && LOADERS[id]) {
    const toggle = LOADERS[id]();
    loaded.set(id, toggle);
    (await toggle)(activeTab === id);
  }
}

async function drawProject() {
  try {
    const data = await loadData();
    const draw = () => drawRun(data);
    draw();
    redraws.add(draw);
  } catch {
    drawRunError();
  }
}

initLangSwitch();
onLangChange(() => {
  setTitle();
  for (const redraw of redraws) redraw();
});
initTabs(showTab);
drawProject();
