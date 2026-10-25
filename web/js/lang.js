/* Page language shared by every module.
 * Context: boot.js picks the starting language before paint; this module switches it later and
 * tells the renderers, which draw their numbers in the matching locale. |
 * Input: clicks on the DE/EN buttons | Output: <html lang>, stored choice, change callbacks. */

const listeners = new Set();

export function currentLang() {
  return document.documentElement.lang === "en" ? "en" : "de";
}

export function locale() {
  return currentLang() === "en" ? "en-US" : "de-DE";
}

export function onLangChange(callback) {
  listeners.add(callback);
}

export function formatNumber(value, digits = 0) {
  return value.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function setLang(code) {
  const lang = code === "en" ? "en" : "de";
  document.documentElement.lang = lang;
  for (const button of document.querySelectorAll(".lang button")) {
    button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
  }
  try {
    localStorage.setItem("lang", lang);
  } catch {
    // Private mode or blocked storage: the choice simply is not remembered.
  }
  for (const callback of listeners) callback(lang);
}

export function initLangSwitch() {
  for (const button of document.querySelectorAll(".lang button")) {
    button.setAttribute("aria-pressed", String(button.dataset.lang === currentLang()));
    button.addEventListener("click", () => setLang(button.dataset.lang));
  }
}
