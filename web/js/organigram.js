/* Organigramm tab: a question lights up station after station, and the search station shows
 * what the database releases for two real users of the recorded live run.
 * Context: the stations are static HTML; this module adds the moving highlight and the
 * per-role release list. | Input: data/demo_run.json via data.js, role buttons |
 * Output: .is-live on the current station, list of released and blocked hits. */

import { currentLang } from "./lang.js";
import { escapeHtml } from "./run.js";

const STEP_MS = 1100;
const REST_MS = 1800;

const TEXT = {
  de: {
    blocked: "gesperrt, Titel bleibt verborgen",
    note: (blocked, released) => (blocked
      ? `${blocked} relevantere Treffer bleiben in der Datenbank. ${released} freigegebene Abschnitte gehen weiter.`
      : `Nichts gesperrt. Die ${released} relevantesten Abschnitte gehen weiter.`),
  },
  en: {
    blocked: "blocked, title stays hidden",
    note: (blocked, released) => (blocked
      ? `${blocked} more relevant hits stay in the database. ${released} released chunks move on.`
      : `Nothing blocked. The ${released} most relevant chunks move on.`),
  },
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let timer = 0;
let running = false;
let answers = new Map();
let user = "tom.schaefer";

function stations() {
  return [...document.querySelectorAll("#org .station")];
}

function tick(index) {
  const list = stations();
  list.forEach((station, position) => station.classList.toggle("is-live", position === index));
  const last = index === list.length - 1;
  timer = window.setTimeout(() => tick(last ? 0 : index + 1), last ? REST_MS : STEP_MS);
}

export function setOrganigramActive(active) {
  const shouldRun = active && !reducedMotion.matches && !document.hidden;
  if (shouldRun === running) return;
  running = shouldRun;
  window.clearTimeout(timer);
  if (running) tick(0);
  else stations().forEach((station) => station.classList.remove("is-live"));
}

function hitItem(icon, text, index, blocked) {
  return `<li class="${blocked ? "is-blocked" : ""}" data-index="${index}"><svg aria-hidden="true"><use href="#${icon}"/></svg><span>${text}</span></li>`;
}

export function drawGate() {
  const answer = answers.get(user);
  if (!answer) return;
  const text = TEXT[currentLang()];
  const blocked = Array.from({ length: answer.blocked_count }, (_, i) => hitItem("i-lock", text.blocked, i, true));
  const released = answer.sources.map((source, i) => hitItem("i-check", escapeHtml(source.title), answer.blocked_count + i, false));
  const list = document.getElementById("gate-hits");
  list.innerHTML = [...blocked, ...released].join("");
  for (const item of list.children) item.style.setProperty("--i", item.dataset.index);
  document.getElementById("gate-note").textContent = text.note(answer.blocked_count, answer.sources.length);
  for (const button of document.querySelectorAll(".gate__roles button")) {
    button.setAttribute("aria-pressed", String(button.dataset.user === user));
  }
}

export function initOrganigram(run) {
  answers = new Map(run.matrix.map((row) => [row.user.username, row.answers[0]]));
  for (const button of document.querySelectorAll(".gate__roles button")) {
    button.addEventListener("click", () => {
      user = button.dataset.user;
      drawGate();
    });
  }
  drawGate();
}
