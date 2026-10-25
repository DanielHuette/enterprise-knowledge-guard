/* Runs before the first paint so the right language and tab show without a flash.
 * Context: loaded synchronously in <head>; everything else is an ES module that runs later. |
 * Input: ?lang=, stored choice, browser language, location.hash | Output: <html lang>,
 * class "js" and data-tab on <html>. */
(function () {
  "use strict";
  var root = document.documentElement;
  var tabs = ["projekt", "organigramm", "benchmarks", "praesentation"];
  var hash = location.hash.slice(1);
  var stored = null;
  try { stored = localStorage.getItem("lang"); } catch (error) { stored = null; }
  var wanted = new URLSearchParams(location.search).get("lang") || stored
    || (navigator.language || "de").slice(0, 2);
  root.lang = wanted === "en" ? "en" : "de";
  root.classList.add("js");
  root.dataset.tab = tabs.indexOf(hash) >= 0 ? hash : "projekt";
})();
