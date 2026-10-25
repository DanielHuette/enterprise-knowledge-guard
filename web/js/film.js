/* Präsentation tab: the project told in nine short scenes that play by themselves.
 * Context: the scenes are static HTML with CSS animations that start when a scene becomes
 * active; this module is the clock (play, pause, chapters, captions). Once the last scene has
 * played out it opens the project tab. With reduced motion the film starts paused, every scene
 * shows its final picture and the tab never switches by itself. | Input: clicks, keys,
 * visibility | Output: active scene, caption, chapter progress. */

import { currentLang } from "./lang.js";

const CHAPTERS = [
  { ms: 5000, de: ["Die Frage", "Zwei Menschen stellen dieselbe Frage."], en: ["The question", "Two people ask the same question."] },
  { ms: 5500, de: ["Zwei Antworten", "Die Antwort hängt an der Rolle, nicht am Sprachmodell."], en: ["Two answers", "The answer depends on the role, not on the language model."] },
  { ms: 6000, de: ["Die Datenbank", "Gesperrte Abschnitte verlassen die Datenbank nicht."], en: ["The database", "Blocked chunks never leave the database."] },
  { ms: 6000, de: ["Eine Abfrage", "Ähnlichkeit und Rechte werden in einer Abfrage geprüft."], en: ["One query", "Similarity and rights are checked in one query."] },
  { ms: 5000, de: ["Zwei Ebenen", "Fällt der Filter aus, halten die Zeilenrechte."], en: ["Two layers", "If the filter fails, row-level security still holds."] },
  { ms: 5500, de: ["Der Angriff", "Eine eingeschleuste Anweisung findet nichts zum Herausgeben."], en: ["The attack", "A planted instruction finds nothing to hand over."] },
  { ms: 5500, de: ["Der Agent", "Der Agent bekommt nur die Werkzeuge seiner Rolle."], en: ["The agent", "The agent only gets the tools of its role."] },
  { ms: 6500, de: ["Freigabe auf Zeit", "Eine Freigabe gilt für ein Dokument und läuft von selbst ab."], en: ["Time-limited access", "A grant covers one document and expires on its own."] },
  { ms: 8000, de: ["Gebaut und geprüft", "Gebaut mit diesen Fähigkeiten, geprüft gegen eine echte Datenbank."], en: ["Built and tested", "Built with these skills, tested against a real database."] },
];

const LABELS = { de: { play: "Abspielen", pause: "Pause" }, en: { play: "Play", pause: "Pause" } };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const state = { scene: 0, elapsed: 0, playing: false, userPaused: false, visible: false, frame: 0, last: 0 };

function el(id) {
  return document.getElementById(id);
}

function scenes() {
  return [...document.querySelectorAll("#stage .scene")];
}

function numberChildren() {
  const groups = "#stage .db__rows .row, #stage .db__out span, #stage .chips li, #stage .toolset li, #stage .grant li";
  const counters = new Map();
  for (const node of document.querySelectorAll(groups)) {
    const n = counters.get(node.parentElement) ?? 0;
    node.style.setProperty("--n", n);
    counters.set(node.parentElement, n + 1);
  }
}

function drawChapters() {
  const lang = currentLang();
  el("chapters").innerHTML = CHAPTERS.map((chapter, index) => `<li><button type="button" data-index="${index}"`
    + `${index === state.scene ? ' aria-current="step"' : ""}>${chapter[lang][0]}<span class="progress"></span></button></li>`).join("");
  el("film-caption").textContent = CHAPTERS[state.scene][lang][1];
  const button = el("film-play");
  button.setAttribute("aria-pressed", String(state.playing));
  button.querySelector(".film__play-label").textContent = LABELS[lang][state.playing ? "pause" : "play"];
}

function showScene(index) {
  state.scene = index;
  state.elapsed = 0;
  scenes().forEach((scene, position) => {
    scene.classList.remove("is-active");
    if (position === index) {
      void scene.offsetWidth;
      scene.classList.add("is-active");
    }
  });
  drawChapters();
}

function paintProgress() {
  const bar = el("chapters").querySelector(`[data-index="${state.scene}"] .progress`);
  if (bar) bar.style.transform = `scaleX(${Math.min(1, state.elapsed / CHAPTERS[state.scene].ms)})`;
}

// A film that has played to the end hands over to the project tab through the tab itself, so
// address, history and tab bar follow; it waits on its first scene for the next visit.
function openProject() {
  const tab = document.getElementById("tab-projekt");
  if (!tab || reducedMotion.matches) return false;
  tab.click();
  return true;
}

function frame(now) {
  state.elapsed += now - state.last;
  state.last = now;
  if (state.elapsed >= CHAPTERS[state.scene].ms) {
    const finished = state.scene === CHAPTERS.length - 1;
    showScene((state.scene + 1) % CHAPTERS.length);
    if (finished && openProject()) {
      paintProgress();
      return;
    }
  }
  paintProgress();
  state.frame = requestAnimationFrame(frame);
}

function setPlaying(playing) {
  state.playing = playing;
  el("stage").classList.toggle("is-paused", !playing);
  cancelAnimationFrame(state.frame);
  if (playing) {
    state.last = performance.now();
    state.frame = requestAnimationFrame(frame);
  }
  drawChapters();
  paintProgress();
}

export function setFilmVisible(visible) {
  state.visible = visible;
  const wanted = visible && !document.hidden && !state.userPaused && !reducedMotion.matches;
  if (wanted !== state.playing) setPlaying(wanted);
}

function bindControls() {
  el("film-play").addEventListener("click", () => {
    state.userPaused = state.playing;
    setPlaying(!state.playing);
  });
  el("chapters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-index]");
    if (!button) return;
    showScene(Number(button.dataset.index));
    paintProgress();
  });
  document.addEventListener("visibilitychange", () => setFilmVisible(state.visible));
}

export function initFilm() {
  numberChildren();
  bindControls();
  showScene(0);
  setPlaying(false);
}

export function redrawFilm() {
  drawChapters();
  paintProgress();
}
