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
    append(...children) { this.children.push(...children); },
    addEventListener(t, fn) { (this._listeners[t] || (this._listeners[t] = [])).push(fn); },
    dispatchEvent(ev) { (this._listeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
  };
  if (id) { elements[id] = el; }
  if (["runBtn", "reconnectBtn", "exportBtn", "trendZoomIn", "trendZoomOut", "trendResetRange"].includes(id)) { buttons[id] = el; }
  return el;
}
const ids = ["inputPath","outputDir","ruleSelect","ruleCustom","status","log","previewCard","configCard",
             "pFile","pRows","pRange","varBody","outputPath","runBtn","reconnectBtn",
             "exportBtn","trendVar","trendStart","trendEnd","trendMaxPoints","trendZoomIn",
             "trendZoomOut","trendResetRange","trendPlaceholder","trendChartWrap","trendCanvas","trendTooltip"];
ids.forEach(id => makeElement((["runBtn", "reconnectBtn", "exportBtn", "trendZoomIn", "trendZoomOut", "trendResetRange"].includes(id)) ? "button" : (id === "trendVar" ? "select" : (id === "trendCanvas" ? "canvas" : "div")), id));
elements.trendMaxPoints.value = "2000";
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
    return { ref: REF, connectService, reconnect, api, requireApi, showVersionMismatch, showServiceError, markServiceReady, applyMethods, fetchService, loadPreview, buildTable, calculateTrendRange, setTrendFullRange, formatTrendAxisTime };
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
    } else if (scenario === "preview_processable_rows") {
      const exec = execute((url) => {
        if (url === "/api/health") return HEALTH_OK;
        if (url === "/api/methods") return METHODS_OK;
        return {
          file: "industrial.csv", path: "C:/data/industrial.csv", rows: 4,
          timeColumn: "Time", timeRange: "2026-09-01 ~ 2026-09-01", droppedRows: 0,
          columns: [
            { name: "TIC101", processable: true },
            { name: "Mode", processable: false },
          ],
        };
      });
      await exec.connectService();
      elements.inputPath.value = "C:/data/industrial.csv";
      await exec.loadPreview();
      result.tableRows = elements.varBody.children.length;
      result.rowNames = elements.varBody.children.map((row) => row.children[1].textContent);
      result.status = elements.status.textContent;
    } else if (scenario === "trend_range") {
      const exec = execute((url) => url === "/api/health" ? HEALTH_OK : METHODS_OK);
      const fullStart = Date.parse("2026-09-01T00:00:00");
      const fullEnd = Date.parse("2026-09-05T00:00:00");
      const zoomIn = exec.calculateTrendRange(
        fullStart, fullEnd, fullStart, fullEnd, 0.5,
      );
      const zoomOut = exec.calculateTrendRange(
        zoomIn.start, zoomIn.end, fullStart, fullEnd, 2,
      );
      const leftBoundary = exec.calculateTrendRange(
        fullStart, fullStart + 24 * 60 * 60 * 1000, fullStart, fullEnd, 2,
      );
      exec.setTrendFullRange("2026-09-01 00:00:00", "2026-09-05 00:00:00");
      result.zoomInDuration = (zoomIn.end - zoomIn.start) / (fullEnd - fullStart);
      result.zoomInCenter = (zoomIn.start + zoomIn.end) / 2;
      result.zoomOutIsFull = zoomOut.start === fullStart && zoomOut.end === fullEnd;
      result.leftBoundary = {
        startIsFull: leftBoundary.start === fullStart,
        durationDays: (leftBoundary.end - leftBoundary.start) / (24 * 60 * 60 * 1000),
      };
      result.fullRange = [elements.trendStart.value, elements.trendEnd.value];
      result.crossDayLabel = exec.formatTrendAxisTime(Date.parse("2026-09-02T12:00:00"), true);
      result.sameDayLabel = exec.formatTrendAxisTime(Date.parse("2026-09-02T12:00:00"), false);
    }
  } catch (err) { result.error = String(err && err.stack || err); }
  console.log(JSON.stringify(result));
})().catch((err) => { console.error(JSON.stringify({ fatal: String(err && err.stack || err) })); process.exit(1); });
