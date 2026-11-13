"use strict";
/* Applies the remembered theme before first paint (loaded in <head>, blocking, so there is no flash). Storage may be blocked: every access is guarded. */
(function () {
  try {
    var t = localStorage.getItem("og_theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* storage blocked: follow the system */ }
})();
