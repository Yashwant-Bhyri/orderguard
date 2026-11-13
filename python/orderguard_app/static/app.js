"use strict";
/* app.js: the shell. Router, theme, environment block, command palette, keyboard shortcuts, auth prompt and boot.
   Loaded last: ui.js (components), pages.js and pages2.js (page logic) come first. */
(function () {
const { h, $, show, usd } = OG;
const VIEWS = ["overview", "screen", "order", "graph", "scenario", "arena", "ledger", "results"];
const TITLES = { overview: "Overview", screen: "Screen text", order: "Check order", graph: "Triggers", scenario: "Scenarios", arena: "Swarm arena", ledger: "Ledger", results: "Results" };
const H1 = { scenario: "h-scn" };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
};

/* ---------- 1. router ---------- */
let current = null, moved = false;
function route() {
  const v = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  if (v === current) return;
  current = v;
  for (const id of VIEWS) $(id).hidden = id !== v;
  for (const a of document.querySelectorAll("#nav a")) { if (a.dataset.view === v) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }
  document.title = (v === "overview" ? "" : TITLES[v] + " - ") + "OrderGuard";
  closeMenu();
  if (moved) $(H1[v] || "h-" + v).focus({ preventScroll: true });
  moved = true;
  window.scrollTo(0, 0);
}
OG.go = function go(view) {
  if (location.hash.slice(1) !== view) history.pushState ? history.pushState(null, "", "#" + view) : (location.hash = view);
  route();
};
window.addEventListener("hashchange", route);
window.addEventListener("popstate", route);

/* ---------- 2. mobile menu ---------- */
function closeMenu() { $("sidebar").classList.remove("open"); $("scrim").hidden = true; $("menu-btn").setAttribute("aria-expanded", "false"); }
$("menu-btn").addEventListener("click", () => {
  const open = !$("sidebar").classList.contains("open");
  $("sidebar").classList.toggle("open", open); $("scrim").hidden = !open; $("menu-btn").setAttribute("aria-expanded", String(open));
  if (open) $("nav").querySelector("a").focus();
});
$("scrim").addEventListener("click", closeMenu);

/* ---------- 3. theme: system, light or dark; remembered in localStorage when explicit ---------- */
const MODES = ["system", "light", "dark"];
let mode = store.get("og_theme");
mode = mode === "light" || mode === "dark" ? mode : "system";
function applyTheme() {
  if (mode === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", mode);
  $("theme-btn").textContent = "Theme: " + mode;
  $("theme-btn").setAttribute("aria-label", "Theme: " + (mode === "system" ? "follow system" : mode) + ". Activate to change.");
}
$("theme-btn").addEventListener("click", () => { mode = MODES[(MODES.indexOf(mode) + 1) % 3]; store.set("og_theme", mode === "system" ? null : mode); applyTheme(); });
applyTheme();

/* ---------- 4. environment block (sidebar bottom) ---------- */
OG.setEnv = function setEnv(d) {
  if (!d) { $("env-mode").textContent = "offline"; $("env-recv").textContent = "unknown"; $("env-dot").className = "dot"; return; }
  const m = d.model, spent = m.spent_usd || 0, cap = m.budget_usd || 0;
  $("env-mode").replaceChildren(OG.pill(m.mode, m.mode === "replay" ? "off" : m.key_configured ? "allow" : "hold"));
  $("env-model").textContent = m.provider + " / " + m.model.split("/").pop();
  $("env-budget-t").textContent = OG.usdSmall(spent) + " of " + OG.usdSmall(cap);
  $("env-budget-f").style.setProperty("width", (cap ? Math.min(100, 100 * spent / cap) : 0) + "%");
  $("env-budget").setAttribute("aria-label", "Budget: " + OG.usdSmall(spent) + " spent of " + OG.usdSmall(cap));
  $("env-dot").className = "dot " + (d.receiver.configured ? "on" : "warn");
  $("env-recv").textContent = d.receiver.configured ? "connected" : "not connected";
};

/* ---------- 5. auth prompt ---------- */
OG.needToken = () => { $("auth-form").hidden = false; $("token").focus(); };
$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const t = $("token").value.trim();
  if (!OG.setErr("token", t ? "" : "Enter the access token.")) return;
  OG.token = t;
  try { sessionStorage.setItem("og_token", t); } catch (x) { /* ignore */ }
  $("token").value = "";
  if (await OG.pages.overview.load()) loadRest();
});

/* ---------- 6. command palette and shortcuts ---------- */
const dlg = (id) => $(id);
function openDlg(id) { const d = dlg(id); if (d.showModal) { if (!d.open) d.showModal(); } else d.setAttribute("open", ""); }
function closeDlg(id) { const d = dlg(id); if (d.close) d.close(); else d.removeAttribute("open"); }
OG.runPreset = (p) => { if (!p) return; OG.go(p.page); p.run(); };
let items = [], sel = 0;
function allItems() {
  return [...VIEWS.map((v) => ({ group: "Go to", label: TITLES[v], run: () => OG.go(v) })), ...OG.presets.map((p) => ({ group: "Example", label: p.label, run: () => OG.runPreset(p) }))];
}
function drawPalette() {
  const q = $("pal-in").value.toLowerCase().split(/\s+/).filter(Boolean);
  items = allItems().filter((i) => q.every((t) => (i.label + " " + i.group).toLowerCase().includes(t)));
  sel = Math.min(sel, Math.max(0, items.length - 1));
  $("pal-list").replaceChildren(...(items.length ? items.map((it, i) => h("li", { id: "pal-" + i, role: "option", "aria-selected": String(i === sel), on: { click: () => choose(i), mousemove: () => { if (sel !== i) { sel = i; mark(); } } } },
    h("span", {}, it.label), h("span", { class: "g" }, it.group))) : [h("li", { role: "option", "aria-selected": "false" }, "Nothing matches. Try a page name or an example such as fake split.")]));
  $("pal-in").setAttribute("aria-activedescendant", items.length ? "pal-" + sel : "");
}
function mark() {
  [...$("pal-list").children].forEach((li, i) => li.setAttribute("aria-selected", String(i === sel)));
  $("pal-in").setAttribute("aria-activedescendant", "pal-" + sel);
  const li = $("pal-" + sel); if (li && li.scrollIntoView) li.scrollIntoView({ block: "nearest" });
}
function choose(i) { const it = items[i]; if (!it) return; closeDlg("palette"); it.run(); }
function openPalette() { $("pal-in").value = ""; sel = 0; drawPalette(); openDlg("palette"); $("pal-in").focus(); }
$("pal-in").addEventListener("input", () => { sel = 0; drawPalette(); });
$("pal-in").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); mark(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); mark(); }
  else if (e.key === "Enter") { e.preventDefault(); choose(sel); }
});
$("pal-btn").addEventListener("click", openPalette);
$("palette").addEventListener("click", (e) => { if (e.target === $("palette")) closeDlg("palette"); });
$("help").addEventListener("click", (e) => { if (e.target === $("help")) closeDlg("help"); });
$("help-close").addEventListener("click", () => closeDlg("help"));

const GO = { o: "overview", s: "screen", c: "order", t: "graph", n: "scenario", a: "arena", l: "ledger", r: "results" };
let gAt = 0;
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if ($("palette").open) closeDlg("palette"); else openPalette(); return; }
  if (e.key === "Escape") { closeMenu(); return; }
  if (e.metaKey || e.ctrlKey || e.altKey || $("palette").open || $("help").open) return;
  const t = e.target, tag = t && t.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
  if (e.key === "?") { e.preventDefault(); openDlg("help"); return; }
  if (gAt && Date.now() - gAt < 1200 && GO[e.key]) { e.preventDefault(); gAt = 0; OG.go(GO[e.key]); return; }
  gAt = e.key === "g" ? Date.now() : 0;
});

/* ---------- 7. boot ---------- */
function loadRest() { OG.pages.order.loadMandate(); OG.pages.scenario.load(); OG.pages.results.load(); }
for (const p of ["screen", "order", "graph", "scenario", "arena", "ledger"]) OG.pages[p].empty();
OG.pages.overview.start();
route();
OG.pages.overview.load().then((ok) => { if (ok) loadRest(); });
})();
