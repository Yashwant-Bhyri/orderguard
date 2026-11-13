// DOM harness for the Swarm arena page. usage: node arena_dom.cjs <static dir> <jsdom dir> <api json file>
const fs = require("fs"), path = require("path");
const [root, jsdomDir, apiFile] = process.argv.slice(2);
const { JSDOM } = require(jsdomDir);
const api = JSON.parse(fs.readFileSync(apiFile, "utf8"));
const html = fs.readFileSync(path.join(root, "index.html"), "utf8").replace(/<script src="[^"]*"><\/script>/g, "");
const settle = () => new Promise(setImmediate);
const fail = (m) => { console.error("FAIL: " + m); process.exit(1); };

function boot(feeds, requireToken = false) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/#arena" });
  const w = dom.window, requests = [];
  const reply = (body, status = 200) => ({ ok: status === 200, status, json: async () => body });
  w.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {} });
  w.fetch = async (url, init) => {
    const u = new URL(url, w.location.href);
    requests.push(u);
    if (requireToken && init.headers.Authorization !== "Bearer test") return reply({}, 401);
    if (u.pathname === "/api/arena/feeds") return feeds ? reply(feeds) : reply({}, 503);
    if (u.pathname === "/api/arena/run") return reply(u.searchParams.has("feed") ? api.replay : api.run);
    if (u.pathname === "/api/arena/frontier") return reply(api.front);
    return reply({ model: { model: "fixture" }, receiver: {}, layers: [] });
  };
  w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
  for (const f of ["ui.js", "pages.js", "pages2.js", "arena.js", "app.js"]) w.eval(fs.readFileSync(path.join(root, f), "utf8"));
  return { w, requests, $: (s) => w.document.querySelector(s) };
}

async function main() {
  const { w, requests, $ } = boot(api.feeds);
  const submit = () => $("#ar-form").dispatchEvent(new w.Event("submit", { cancelable: true, bubbles: true }));
  const t = (s) => $(s) ? $(s).textContent : "";
  if (!$("#ar-out .empty")) fail("empty state missing");
  if (!/og-arena run --seed 7 --agents 1000/.test(t("#ar-cli"))) fail("cli line");
  await settle();
  const feed = api.feeds.feeds[0];
  const picker = $("#ar-feed");
  if (picker.options.length !== 2 || picker.options[1].value !== feed.name || picker.value !== "") fail("recorded feed options");
  if (!picker.options[1].textContent.includes(feed.ticks + " ticks, " + feed.source)) fail("recorded feed description");
  submit();
  await settle();
  for (const id of ["ar-tape", "ar-env", "ar-who", "ar-lat", "ar-lab"]) if (!$("#" + id)) fail("section " + id);
  const tiles = w.document.querySelectorAll("#ar-out .tiles .tile").length;
  if (tiles !== 5) fail("tiles " + tiles);
  const rows = w.document.querySelectorAll("table.tape tbody tr").length;
  if (rows < 1 || rows > 200) fail("tape rows " + rows);
  if (w.document.querySelectorAll("table.tape th").length !== 8) fail("ground truth must be hidden by default");
  $("#ar-reveal").checked = true; $("#ar-reveal").dispatchEvent(new w.Event("change"));
  if (w.document.querySelectorAll("table.tape th").length !== 9) fail("reveal column");
  if (w.document.querySelectorAll("svg.envc").length !== api.run.summary.envelopes.length) fail("envelope charts");
  if (!$("svg.who[role=img]") || !$("svg.lat[role=img]") || !$("svg.scat[role=img]")) fail("chart roles");
  if (!/Recommended envelope/.test(t("#ar-rec")) || !$("svg.scat .ring")) fail("recommendation");
  const caption = t("#ar-who .caption");
  if (!caption.includes("A per-agent share limits how much one agent can consume")) fail("per-agent share caption");
  if (!caption.includes("this run does not claim to detect collusion")) fail("collusion detection caption");
  const s = $("#ar-s-leak"); s.value = "0"; s.dispatchEvent(new w.Event("input"));
  if (!/Recommended envelope/.test(t("#ar-rec"))) fail("repick");
  if (w.document.querySelectorAll("[style]").length && [...w.document.querySelectorAll("[style]")].some((e) => !/^(left|top|width|--)/.test(e.getAttribute("style")))) fail("unexpected inline style");

  picker.value = feed.name;
  picker.dispatchEvent(new w.Event("change", { bubbles: true }));
  if (!t("#ar-cli").includes("og-arena replay --feed 'data/arena/feeds/" + feed.name + "'")) fail("recorded feed cli line");
  submit();
  await settle();
  for (const route of ["run", "frontier"]) {
    const called = requests.findLast((u) => u.pathname === "/api/arena/" + route);
    if (called.searchParams.get("feed") !== feed.name) fail("selected feed missing from " + route + " request");
  }
  if (!$("#ar-tape") || !t("#ar-out .msg").includes(feed.ticks + " steps")) fail("recorded run did not render");
  w.close();

  for (const [body, message] of [[{ feeds: [] }, "No recorded feeds on this server"], [null, "Recorded feeds could not be loaded"]]) {
    const fallback = boot(body);
    await settle();
    const picker = fallback.$("#ar-feed");
    if (picker.options.length !== 1 || picker.value !== "" || picker.disabled) fail("synthetic fallback");
    if (!fallback.$("#ar-feed-help").textContent.includes(message)) fail("missing feed status " + message);
    fallback.w.close();
  }

  const auth = boot(api.feeds, true);
  await settle();
  if (auth.$("#auth-form").hidden) fail("token prompt for recorded feeds");
  auth.$("#token").value = "test";
  auth.$("#auth-form").dispatchEvent(new auth.w.Event("submit", { cancelable: true, bubbles: true }));
  await settle();
  if (auth.$("#ar-feed").options[1]?.value !== feed.name) fail("recorded feeds missing after authentication");
  auth.w.close();
  console.log("ok rows=" + rows);
}

main().catch((error) => fail(error.stack));
