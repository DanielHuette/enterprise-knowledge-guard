/* Bottom tab bar: four deep-linkable views of one page.
 * Context: #projekt, #organigramm, #benchmarks and #praesentation open their tab directly, so a
 * link in a CV can land on any of them; older anchors inside the project tab still work. |
 * Input: location.hash, clicks, arrow keys, browser back/forward | Output: visible panel,
 * ARIA tab state, a callback per shown tab. */

export const TABS = ["projekt", "organigramm", "benchmarks", "praesentation"];
const DEFAULT_TAB = TABS[0];

let onShow = () => {};
let shown = null;

function tabElement(id) {
  return document.getElementById(`tab-${id}`);
}

function select(id) {
  const root = document.documentElement;
  root.dataset.tab = id;
  for (const name of TABS) {
    const active = name === id;
    const tab = tabElement(name);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(name).hidden = !active;
  }
  if (shown !== id) {
    shown = id;
    onShow(id);
  }
}

function route({ fromHistory }) {
  const target = decodeURIComponent(location.hash.slice(1));
  if (TABS.includes(target)) {
    select(target);
    window.scrollTo(0, 0);
    requestAnimationFrame(() => window.scrollTo(0, 0));
    return;
  }
  const anchor = target ? document.getElementById(target) : null;
  const panel = anchor?.closest(".panel");
  select(panel ? panel.id : DEFAULT_TAB);
  if (anchor && panel) anchor.scrollIntoView();
  else if (!fromHistory) window.scrollTo(0, 0);
}

function activate(id, focus) {
  if (location.hash !== `#${id}`) history.pushState(null, "", `#${id}`);
  select(id);
  window.scrollTo(0, 0);
  if (focus) tabElement(id).focus();
}

function onKey(event) {
  const index = TABS.indexOf(event.currentTarget.id.slice(4));
  const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 };
  if (!(event.key in moves)) return;
  event.preventDefault();
  activate(TABS[(moves[event.key] + TABS.length) % TABS.length], true);
}

export function initTabs(callback) {
  onShow = callback;
  history.scrollRestoration = "manual";
  for (const id of TABS) {
    const tab = tabElement(id);
    tab.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      activate(id, false);
    });
    tab.addEventListener("keydown", onKey);
  }
  window.addEventListener("hashchange", () => route({ fromHistory: false }));
  window.addEventListener("popstate", () => route({ fromHistory: true }));
  route({ fromHistory: true });
  // The browser's own jump to a fragment comes after this script and would hide the top bar.
  if (TABS.includes(location.hash.slice(1))) {
    window.addEventListener("load", () => requestAnimationFrame(() => window.scrollTo(0, 0)), { once: true });
  }
}
