// frontend_smoke.js — executes the REAL TimePrep web/index.html script with a minimal DOM/fetch shim.
'use strict';
const fs = require("fs");
const htmlPath = process.argv[2];
const scenario = process.argv[3];
const html = fs.readFileSync(htmlPath, "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) { console.error("no script block"); process.exit(2); }
const pageScript = scriptMatch[1];
const elements = {};
const buttons = {};
function makeElement(tag, id) {
  const el = {
    tagName: String(tag).toUpperCase(), id: id || "", textContent: "", value: "", className: "",
    hidden: false, disabled: false, style: {}, checked: false, children: [], _listeners: {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, fn) { (this._listeners[t] || (this._listeners[t] = [])).push(fn); },
    dispatchEvent(ev) { (this._listeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
  };
  if (id) { elements[id] = el; }
  if (id === "runBtn" || id === "reconnectBtn" || id === "exportBtn") { buttons[id] = el; }
  return el;
}
const ids = ["inputPath","outputDir","ruleSelect","ruleCustom","status","log","previewCard","configCard",
             "pFile","pRows","pTimeCol","pRange","pVars","varBody","outputPath","runBtn","reconnectBtn",
             "exportBtn","trendVar","trendPlaceholder","trendChartWrap","trendCanvas","trendTooltip"];
ids.forEach(id => makeElement((id === "runBtn" || id === "reconnectBtn" || id === "exportBtn") ? "button" : (id === "trendVar" ? "select" : (id === "trendCanvas" ? "canvas" : "div")), id));
const documentShim = {
  getElementById(id) { return elements[id] || null; },
  createElement(tag) { return makeElement(tag); },
  querySelectorAll(sel) { if (sel === "button") return Object.values(buttons).filter(Boolean); return []; },
  addEventListener() {},
  documentElement: { outerHTML: "" }, body: { innerText: "" },
};
global.document = documentShim;
global.window = { addEventListener() {} };
Object.defineProperty(global, 'navigator', { value: { userAgent: 'node' }, configurable: true });
global.location = { origin: "http://127.0.0.1:8765", pathname: "/" };
const fetchCalls = [];
function makeFetch(stub) {
  return async (url) => { fetchCalls.push(url); const s = stub(url); if (s instanceof Error) throw s; return { ok: true, status: 200, async json() { return s; } }; };
}
function execute(stub) {
  global.fetch = makeFetch(stub);
  const fn = new Function("fetch", `
    const REF = {};
    ${pageScript.replace(/\bapiReady\b/g, "__apiReady").replace(/\bversionMismatch\b/g, "__versionMismatch")}
    REF.apiReady = () => __apiReady;
    REF.versionMismatch = () => __versionMismatch;
    return { ref: REF, connectService, reconnect, api, requireApi, showVersionMismatch, showServiceError, markServiceReady, applyMethods, fetchService };
  `);
  const ctx = fn(global.fetch);
  Object.defineProperty(ctx, "apiReady", { get() { return ctx.ref.apiReady(); }, configurable: true });
  Object.defineProperty(ctx, "versionMismatch", { get() { return ctx.ref.versionMismatch(); }, configurable: true });
  return ctx;
}
const HEALTH_OK = { app: "TimePrep", apiVersion: 2, pid: 1 };
const METHODS_OK = { apiVersion: 2, methods: [{ key: "median", label: "中位数", defaultParams: "" }], presetRules: ["", "1s"] };
(async () => {
  const result = {};
  try {
    const healthOk = (url) => url === "/api/health" ? HEALTH_OK : METHODS_OK;
    if (scenario === "healthy") {
      const exec = execute(healthOk);
      result.initial = await exec.connectService();
      result.state = { apiReady: exec.apiReady, versionMismatch: exec.versionMismatch };
      result.runDisabled = elements.runBtn.disabled;
      result.reconnectHidden = elements.reconnectBtn.hidden;
    } else if (scenario === "healthy_recovery") {
      const state = { mode: "normal" };
      const exec = execute((url) => {
        if (url === "/api/health") return HEALTH_OK;
        if (url === "/api/methods") return state.mode === "mismatch" ? { apiVersion: 3, methods: [], presetRules: [] } : METHODS_OK;
        return { error: "unknown" };
      });
      result.initial = await exec.connectService();
      result.initialState = { apiReady: exec.apiReady, versionMismatch: exec.versionMismatch };
      state.mode = "mismatch";
      await exec.reconnect();
      result.afterMismatch = { apiReady: exec.apiReady, versionMismatch: exec.versionMismatch };
      result.reconnectVisibleAfterMismatch = !elements.reconnectBtn.hidden;
      state.mode = "normal";
      await exec.reconnect();
      result.afterRecover = { apiReady: exec.apiReady, versionMismatch: exec.versionMismatch };
      result.runDisabled = elements.runBtn.disabled;
      result.reconnectHidden = elements.reconnectBtn.hidden;
    } else if (scenario === "mismatch") {
      const exec = execute((url) => url === "/api/health" ? { app: "TimePrep", apiVersion: 3, pid: 1 } : { apiVersion: 3, methods: [], presetRules: [] });
      await exec.connectService();
      result.state = { apiReady: exec.apiReady, versionMismatch: exec.versionMismatch };
      result.reconnectVisible = !elements.reconnectBtn.hidden;
      result.runDisabled = elements.runBtn.disabled;
    } else if (scenario === "error") {
      const exec = execute(() => new TypeError("fetch failed"));
      await exec.connectService();
      result.state = { apiReady: exec.apiReady, versionMismatch: exec.versionMismatch };
      result.reconnectVisible = !elements.reconnectBtn.hidden;
      result.runDisabled = elements.runBtn.disabled;
    } else if (scenario === "never_disable") {
      const exec = execute(() => ({ error: "unknown" }));
      await exec.connectService();
      result.runDisabled = elements.runBtn.disabled;
      result.hasDisableAll = /querySelectorAll\(['"]button['"]\)[\s\S]{0,80}button\.disabled\s*=\s*true\b/.test(pageScript);
      result.hasVersionMismatchTrue = /versionMismatch\s*=\s*true\b/.test(pageScript);
    }
  } catch (err) { result.error = String(err && err.stack || err); }
  console.log(JSON.stringify(result));
})().catch((err) => { console.error(JSON.stringify({ fatal: String(err && err.stack || err) })); process.exit(1); });
