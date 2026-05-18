let charts = {};

function fmt(value, digits, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits) + suffix;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setMessage(type, text) {
  const el = document.getElementById("globalMessage");
  if (!el) {
    if (type === "error") console.error(text);
    return;
  }
  el.className = `message ${type}`;
  el.textContent = text;
}

async function parseResponse(response) {
  const raw = await response.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch { data = { raw }; }
  if (!response.ok) {
    const err = data?.error || data?.message || `${response.status} ${response.statusText}`;
    throw new Error(err);
  }
  if (data && data.ok === false) throw new Error(data.error || "Request failed");
  return data;
}

async function apiGet(path) {
  try {
    const response = await fetch(path);
    return await parseResponse(response);
  } catch (err) {
    setMessage("error", `GET ${path} failed: ${err.message}`);
    throw err;
  }
}

async function apiPost(path, payload = {}) {
  try {
    console.log("POST", path, payload);
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    return await parseResponse(response);
  } catch (err) {
    setMessage("error", `POST ${path} failed: ${err.message}`);
    throw err;
  }
}

async function postJson(path, payload = {}) {
  const result = await apiPost(path, payload);
  setMessage("success", `OK: ${path}`);
  await updateStatus();
  return result;
}

async function jog(direction, amountType, amount) {
  const payload = { direction, amount_type: amountType, amount: Number(amount) };
  console.log("Jog clicked", payload);
  if (!["toward_empty", "toward_full"].includes(direction)) {
    setMessage("error", `Virheellinen suunta: ${direction}`);
    return;
  }
  if (!["ml", "steps"].includes(amountType) || !Number.isFinite(Number(amount)) || Number(amount) <= 0) {
    setMessage("error", "Jog-parametrit virheelliset.");
    return;
  }
  return postJson("/api/jog", payload);
}

function renderEvents(data) { const el = document.getElementById("eventLog"); if (!el) return; el.innerHTML = ""; for (const ev of data.events || []) { const li = document.createElement("li"); li.textContent = ev; el.appendChild(li); } }
function renderFlowCalibrationPoints(data) { const el = document.getElementById("flowCalibrationList"); if (!el) return; el.innerHTML = ""; for (const p of data.flow_calibration_points || []) { const li = document.createElement("li"); li.textContent = `${p.gas.toUpperCase()} | expected ${fmt(p.expected_flow_lpm, 4, " L/min")} | measured ${fmt(p.measured_voltage_v, 4, " V")} | estimated ${fmt(p.estimated_flow_lpm, 4, " L/min")} | ${p.timestamp}`; el.appendChild(li); } }
function byGas(points) { return { air: points.filter(p => p.gas === "air"), co2: points.filter(p => p.gas === "co2") }; }
function linearFit(points) { if (points.length < 2) return null; const xs = points.map(p => Number(p.measured_voltage_v)); const ys = points.map(p => Number(p.expected_flow_lpm)); const n = xs.length; const sumX = xs.reduce((a, b) => a + b, 0); const sumY = ys.reduce((a, b) => a + b, 0); const sumXY = xs.reduce((a, x, i) => a + x * ys[i], 0); const sumX2 = xs.reduce((a, x) => a + x * x, 0); const denom = n * sumX2 - sumX * sumX; if (denom === 0) return null; const m = (n * sumXY - sumX * sumY) / denom; const b = (sumY - m * sumX) / n; const yMean = sumY / n; const ssRes = ys.reduce((a, y, i) => a + (y - (m * xs[i] + b)) ** 2, 0); const ssTot = ys.reduce((a, y) => a + (y - yMean) ** 2, 0); const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot; return { m, b, r2 }; }
function metrics(points) { if (!points.length) return null; const errs = points.map(p => Number(p.estimated_flow_lpm) - Number(p.expected_flow_lpm)); const abs = errs.map(Math.abs); const mae = abs.reduce((a, b) => a + b, 0) / abs.length; const rmse = Math.sqrt(errs.reduce((a, e) => a + e * e, 0) / errs.length); const maxAbs = Math.max(...abs); return { mae, rmse, maxAbs }; }
function qualityBadge(rmse) { if (rmse <= 0.01) return "Good"; if (rmse <= 0.03) return "Warning"; return "Poor"; }
function ensureChart(id, config) { if (charts[id]) { charts[id].data = config.data; charts[id].options = config.options; charts[id].update(); return charts[id]; } const ctx = document.getElementById(id); if (!ctx || typeof Chart === "undefined") return null; charts[id] = new Chart(ctx, config); return charts[id]; }
function renderSummary(points) { const el = document.getElementById("calibrationSummaryCards"); if (!el) return; const gases = byGas(points); const mAll = metrics(points); const mAir = metrics(gases.air) || { mae: NaN, rmse: NaN, maxAbs: NaN }; const mCo2 = metrics(gases.co2) || { mae: NaN, rmse: NaN, maxAbs: NaN }; const expectedVals = points.map(p => Number(p.expected_flow_lpm)); const range = expectedVals.length ? `${Math.min(...expectedVals).toFixed(3)}..${Math.max(...expectedVals).toFixed(3)} L/min` : "--"; const q = mAll ? qualityBadge(mAll.rmse) : "--"; el.innerHTML = [{ k: "Points (AIR/CO2)", v: `${gases.air.length} / ${gases.co2.length}` }, { k: "Coverage range", v: range }, { k: "RMSE (all)", v: fmt(mAll && mAll.rmse, 4, " L/min") + ` (${q})` }, { k: "MAE air | co2", v: `${fmt(mAir.mae, 4, "")}/${fmt(mCo2.mae, 4, "")}` },].map(card => `<div class="summary-card"><div class="k">${card.k}</div><div class="v">${card.v}</div></div>`).join(""); }
function renderCoverage(points) { const targetMin = 0.0, targetMax = 1.0; const elBar = document.getElementById("coverageBar"); const txt = document.getElementById("coverageText"); if (!elBar || !txt) return; if (!points.length) { elBar.style.width = "0%"; txt.textContent = "Ei pisteitä vielä."; return; } const vals = points.map(p => Number(p.expected_flow_lpm)); const span = Math.max(...vals) - Math.min(...vals); const full = Math.max(0.0001, targetMax - targetMin); const pct = Math.max(0, Math.min(100, (span / full) * 100)); elBar.style.width = `${pct}%`; txt.textContent = `Current coverage ${Math.min(...vals).toFixed(3)}..${Math.max(...vals).toFixed(3)} L/min (${pct.toFixed(1)}% of target ${targetMin.toFixed(1)}..${targetMax.toFixed(1)}).`; }
function renderRecommendation(points) { const el = document.getElementById("calibrationRecommendation"); if (!el) return; if (points.length < 4) { el.textContent = "Suositus: kerää vähintään 4 pistettä / kaasu (matalasta korkeaan virtaamaan)."; return; } const vals = [...new Set(points.map(p => Number(p.expected_flow_lpm).toFixed(3)).values())].map(Number).sort((a, b) => a - b); let worstGap = 0, mid = null; for (let i = 1; i < vals.length; i++) { const g = vals[i] - vals[i - 1]; if (g > worstGap) { worstGap = g; mid = (vals[i] + vals[i - 1]) / 2; } } el.textContent = mid !== null ? `Suositus: lisää seuraava piste noin ${mid.toFixed(3)} L/min (suurin aukko ${worstGap.toFixed(3)} L/min).` : "Suositus: lisää toistomittauksia nykyisiin virtauspisteisiin repeatabilityn parantamiseksi."; }
function renderCharts(points) { const gas = byGas(points); const fitAir = linearFit(gas.air); const fitCo2 = linearFit(gas.co2); const asXY = (arr, xk, yk) => arr.map(p => ({ x: Number(p[xk]), y: Number(p[yk]) })); const fitLine = (arr, fit) => { if (!fit || arr.length < 2) return []; const xs = arr.map(p => Number(p.measured_voltage_v)).sort((a, b) => a - b); const x1 = xs[0], x2 = xs[xs.length - 1]; return [{ x: x1, y: fit.m * x1 + fit.b }, { x: x2, y: fit.m * x2 + fit.b }]; };
ensureChart("curveChart", { type: "scatter", data: { datasets: [{ label: "AIR points", data: asXY(gas.air, "measured_voltage_v", "expected_flow_lpm"), backgroundColor: "#2563eb" }, { label: "CO2 points", data: asXY(gas.co2, "measured_voltage_v", "expected_flow_lpm"), backgroundColor: "#dc2626" }, { label: fitAir ? `AIR fit y=${fitAir.m.toFixed(3)}x+${fitAir.b.toFixed(3)} R²=${fitAir.r2.toFixed(3)}` : "AIR fit", data: fitLine(gas.air, fitAir), showLine: true, borderColor: "#2563eb", pointRadius: 0 }, { label: fitCo2 ? `CO2 fit y=${fitCo2.m.toFixed(3)}x+${fitCo2.b.toFixed(3)} R²=${fitCo2.r2.toFixed(3)}` : "CO2 fit", data: fitLine(gas.co2, fitCo2), showLine: true, borderColor: "#dc2626", pointRadius: 0 }, ] }, options: { parsing: false, scales: { x: { title: { display: true, text: "Measured voltage (V)" } }, y: { title: { display: true, text: "Expected flow (L/min)" } } } } }); }

function renderSoftpotCalibration(data) {
  setText("softpotCurrentTarget", data.current_target_ml === null || data.current_target_ml === undefined ? "--" : fmt(data.current_target_ml, 1, " ml"));
  const acceptedEl = document.getElementById("softpotAcceptedPoints");
  if (acceptedEl) {
    acceptedEl.innerHTML = "";
    for (const p of data.calibration_points || []) {
      const li = document.createElement("li");
      li.textContent = `${fmt(p.volume_ml, 2, " ml")} @ ${fmt(p.voltage_v, 4, " V")}`;
      acceptedEl.appendChild(li);
    }
  }
  const remainingEl = document.getElementById("softpotRemainingTargets");
  if (remainingEl) {
    remainingEl.innerHTML = "";
    const acceptedVolumes = new Set((data.calibration_points || []).map(p => Number(p.volume_ml)));
    for (const t of data.calibration_targets || []) {
      if (acceptedVolumes.has(Number(t))) continue;
      const li = document.createElement("li");
      li.textContent = `${fmt(t, 1, " ml")}`;
      remainingEl.appendChild(li);
    }
  }
}

async function updateStatus() {
  const data = await apiGet("/api/status");
  setText("softpotVoltage", fmt(data.softpot_voltage_v, 4, " V"));
  setText("softpotVolume", data.softpot_volume_ml === null ? "ei kalibroitu" : fmt(data.softpot_volume_ml, 2, " ml"));
  setText("flowVoltage", fmt(data.flow_voltage_v, 4, " V"));
  setText("flowLpm", fmt(data.flow_lpm, 4, " L/min"));
  setText("motorEnabled", data.motor_enabled === undefined ? "--" : (data.motor_enabled ? "päällä" : "pois"));
  setText("mode", data.mode || "--");
  setText("lastError", data.error || data.last_error || "--");
  renderEvents(data);
  renderFlowCalibrationPoints(data);
  renderSoftpotCalibration(data);
  const points = data.flow_calibration_points || [];
  renderSummary(points); renderCoverage(points); renderRecommendation(points); renderCharts(points);
  renderAutomaticFlowStatus(data);
}

function renderAutomaticFlowStatus(data){ const fc = data.flow_calibration || data.automatic_flow_calibration || data; const gas = fc.gas || '--'; const zeroCap = gas !== '--' ? (data.zero_flow_capture_by_gas?.[gas] || null) : null; setText('flowRunning', fc.running ? 'yes':'no'); setText('flowGas', fc.gas || '--'); setText('flowZeroStatus', zeroCap ? `yes (${fmt(zeroCap.voltage_v,4,' V')})` : 'no'); setText('flowCurrentTrial', fc.current_trial?.trial_id || fc.current_trial || '--'); setText('flowCurrentTarget', fc.current_trial?.target_flow_lpm ?? fc.current_target_flow_lpm ?? '--'); setText('flowCurrentRepeat', fc.current_trial?.repeat_index ?? '--'); setText('flowPhase', fc.phase || '--'); setText('flowCompletedCount', String(fc.completed_count ?? fc.completed_trials ?? '--')); setText('flowTotalCount', String(fc.total_count ?? fc.total_trials ?? '--')); setText('flowRunDir', fc.run_dir || '--'); setText('flowError', fc.error || '--'); setText('flowFailureReason', fc.last_failure_reason || '--'); if (fc.latest_sample){ setText('flowLatestVolume', fmt(fc.latest_sample.softpot_volume_ml,2,' ml')); setText('flowLatestVoltage', fmt(fc.latest_sample.flow_voltage_v,4,' V')); setText('flowLatestActualFlow', fmt(fc.latest_sample.actual_flow_lpm_window,4,' L/min')); } if (fc.result?.run_dir){ setText('flowSummaryPath', `${fc.result.run_dir}/summary.csv`); setText('flowCurvePath', `${fc.result.run_dir}/calibration_curve.json`); }
  setText('dashSelectedGas', gas); setText('dashZeroFlow', zeroCap ? 'yes' : 'no'); setText('dashLatestAutoCalibration', fc.result?.run_id || '--'); }

async function captureZeroFlow(){ const gas=document.getElementById('autoFlowGas')?.value||'air'; return postJson('/api/flow/zero-capture',{gas}); }
async function startAutomaticFlowCalibration() { const gas = document.getElementById("autoFlowGas")?.value; const flows = (document.getElementById("autoFlows")?.value || "").split(",").map(x => Number(x.trim())).filter(x => Number.isFinite(x) && x > 0); const repeats = Number(document.getElementById("autoRepeats")?.value || 1); const strokeStartMl = Number(document.getElementById("strokeStartMl")?.value || 100); const strokeEndMl = Number(document.getElementById("strokeEndMl")?.value || 0); const analysisMinMl = Number(document.getElementById("analysisMinMl")?.value || 10); const analysisMaxMl = Number(document.getElementById("analysisMaxMl")?.value || 90); if (!flows.length) { setMessage("error", "Please enter at least one valid flow rate."); return; } return postJson('/api/flow/start', {gas, flows_lpm: flows, repeats, stroke_start_ml: strokeStartMl, stroke_end_ml: strokeEndMl, analysis_min_ml: analysisMinMl, analysis_max_ml: analysisMaxMl}); }
async function startSingleDebugTrial() { const gas = document.getElementById("autoFlowGas")?.value; const flows = (document.getElementById("autoFlows")?.value || "").split(",").map(x => Number(x.trim())).filter(x => Number.isFinite(x) && x > 0); if (!flows.length) { setMessage("error", "Please enter at least one valid flow rate."); return; } const strokeStartMl = Number(document.getElementById("strokeStartMl")?.value || 100); const strokeEndMl = Number(document.getElementById("strokeEndMl")?.value || 0); const analysisMinMl = Number(document.getElementById("analysisMinMl")?.value || 10); const analysisMaxMl = Number(document.getElementById("analysisMaxMl")?.value || 90); return postJson('/api/flow/start', {gas, flows_lpm: [flows[0]], repeats: 1, stroke_start_ml: strokeStartMl, stroke_end_ml: strokeEndMl, analysis_min_ml: analysisMinMl, analysis_max_ml: analysisMaxMl}); }
async function stopAutomaticFlowCalibration(){ return postJson('/api/flow/stop', {}); }
async function captureFlowCalibrationPoint() { const gas = document.getElementById("flowCalGas")?.value; const expectedRaw = document.getElementById("flowCalExpected")?.value; if (!expectedRaw) { setMessage("error", "Anna expected flow (L/min)"); return; } return postJson("/api/flow-calibration/capture", { gas, expected_flow_lpm: Number(expectedRaw) }); }
async function resetFlowCalibrationPoints() { return postJson("/api/flow-calibration/reset", {}); }

function bindClick(id, handler) { const el = document.getElementById(id); if (!el) return; el.addEventListener("click", async () => { try { await handler(); } catch (e) { console.error(e); } }); }

window.addEventListener("load", () => {
  bindClick("btnSoftpotStart", () => postJson("/api/softpot/start", {}));
  bindClick("btnSoftpotAccept", () => postJson("/api/softpot/accept", {}));
  bindClick("btnSoftpotSave", () => postJson("/api/softpot/save", {}));
  bindClick("btnMotorEnable", () => postJson("/api/motor/enable", {}));
  bindClick("btnMotorDisable", () => postJson("/api/motor/disable", {}));
  bindClick("btnStop", () => postJson("/api/stop", {}));
  bindClick("btnFlowZero", captureZeroFlow);
  bindClick("btnFlowStart", startAutomaticFlowCalibration);
  bindClick("btnFlowStartOne", startSingleDebugTrial);
  bindClick("btnFlowStop", stopAutomaticFlowCalibration);
  bindClick("btnFlowCapturePoint", captureFlowCalibrationPoint);
  bindClick("btnFlowResetPoints", resetFlowCalibrationPoints);

  document.querySelectorAll("[data-jog-direction]").forEach((btn) => {
    btn.addEventListener("click", () => jog(btn.dataset.jogDirection, btn.dataset.jogAmountType, btn.dataset.jogAmount));
  });

  updateStatus();
  setInterval(updateStatus, 1000);
});
