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

function automaticCurveFromPayload(payload) {
  const fc = payload?.flow_calibration || payload?.automatic_flow_calibration || payload || {};
  const outer = fc.result || payload?.result || null;
  const curve = outer?.result || outer;
  if (curve?.model || curve?.fit_quality || curve?.zero_flow) return { fc, outer: outer || fc, curve };
  return { fc, outer: outer || fc, curve: null };
}

function numberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function rangeText(values, digits, suffix) {
  const nums = values.map(numberOrNull).filter(v => v !== null);
  if (!nums.length) return "--";
  return `${Math.min(...nums).toFixed(digits)}–${Math.max(...nums).toFixed(digits)}${suffix}`;
}

function renderAutomaticSummaryCards(curve, points) {
  const el = document.getElementById("automaticFlowSummaryCards");
  if (!el) return;
  const q = curve?.fit_quality || {};
  const targetActual = q.target_vs_actual || {};
  const repeatability = q.repeatability || {};
  const validVoltageRange = curve?.valid_voltage_range_v || rangeText(points.map(p => p.mean_voltage_v), 4, " V");
  const validFlowRange = curve?.valid_flow_range_lpm || rangeText(points.map(p => p.mean_actual_flow_lpm), 4, " L/min");
  const zeroFlowVoltage = curve?.zero_flow?.voltage_v;
  const cards = [
    { k: "Usable", v: curve ? (curve.usable ? "yes" : "no") : "--" },
    { k: "Model type", v: curve?.model?.type || "--" },
    { k: "Valid voltage range", v: typeof validVoltageRange === "string" ? validVoltageRange : `${fmt(validVoltageRange?.[0], 4, " V")}–${fmt(validVoltageRange?.[1], 4, " V")}` },
    { k: "Valid flow range", v: typeof validFlowRange === "string" ? validFlowRange : `${fmt(validFlowRange?.[0], 4, " L/min")}–${fmt(validFlowRange?.[1], 4, " L/min")}` },
    { k: "Zero-flow voltage", v: fmt(zeroFlowVoltage, 4, " V") },
    { k: "Accepted points", v: String(q.accepted_point_count ?? points.length ?? "--") },
    { k: "Accepted trials", v: String(q.accepted_trial_count ?? "--") },
    { k: "Rejected trials", v: String(q.rejected_trial_count ?? curve?.rejected_trials?.length ?? "--") },
    { k: "Target mean error", v: fmt(targetActual.mean_delta_lpm, 4, " L/min") },
    { k: "Target std error", v: fmt(targetActual.std_delta_lpm, 4, " L/min") },
    { k: "Target max error", v: fmt(targetActual.max_abs_delta_lpm, 4, " L/min") },
    { k: "Mean repeatability", v: fmt(repeatability.mean_std_actual_flow_lpm, 4, " L/min") },
  ];
  el.innerHTML = cards.map(card => `<div class="summary-card"><div class="k">${card.k}</div><div class="v">${card.v}</div></div>`).join("");
}

function renderAutomaticRangeNote(curve, points) {
  const el = document.getElementById("automaticFlowRangeNote");
  if (!el) return;
  if (!curve) { el.textContent = "No automatic calibration result loaded yet."; return; }
  const requested = points.map(p => p.target_flow_lpm).map(numberOrNull).filter(v => v !== null);
  const actual = points.map(p => p.mean_actual_flow_lpm).map(numberOrNull).filter(v => v !== null);
  const usable = curve.usable ? "Calibration is usable" : "Calibration is not usable";
  const requestedRange = requested.length ? `${Math.min(...requested).toFixed(3)}–${Math.max(...requested).toFixed(3)} L/min requested targets` : "requested range unknown";
  const actualRange = actual.length ? `${Math.min(...actual).toFixed(3)}–${Math.max(...actual).toFixed(3)} L/min accepted actual range` : "no accepted range";
  const rejected = curve.rejected_trials?.length || 0;
  el.textContent = `${usable}; ${actualRange} from ${requestedRange}. ${rejected ? `${rejected} trial(s) were rejected; review reasons below.` : "No rejected trials reported."}`;
}

function renderAcceptedPoints(points) {
  const el = document.getElementById("flowAcceptedPoints");
  if (!el) return;
  el.innerHTML = "";
  if (!points.length) {
    const li = document.createElement("li");
    li.textContent = "No accepted model points yet.";
    el.appendChild(li);
    return;
  }
  for (const p of points) {
    const li = document.createElement("li");
    li.textContent = `target ${fmt(p.target_flow_lpm, 4, " L/min")} | actual ${fmt(p.mean_actual_flow_lpm, 4, " L/min")} | voltage ${fmt(p.mean_voltage_v, 4, " V")} | trials ${p.trial_count ?? "--"} | actual std ${fmt(p.std_actual_flow_lpm, 4, " L/min")} | voltage std ${fmt(p.std_voltage_v, 4, " V")}`;
    el.appendChild(li);
  }
}

function renderRejectedTrials(curve) {
  const el = document.getElementById("flowRejectedTrials");
  if (!el) return;
  el.innerHTML = "";
  const rejected = curve?.rejected_trials || [];
  if (!rejected.length) {
    const li = document.createElement("li");
    li.textContent = "No rejected trials.";
    el.appendChild(li);
    return;
  }
  for (const trial of rejected) {
    const li = document.createElement("li");
    li.textContent = `${trial.trial_id || "trial"} | target ${fmt(trial.target_flow_lpm, 4, " L/min")} | status ${trial.status || "rejected"} | reason: ${trial.reason || "No reason recorded"}`;
    el.appendChild(li);
  }
}

function renderRecentTrials(fc, outer) {
  const el = document.getElementById("flowRecentTrials");
  if (!el) return;
  el.innerHTML = "";
  const trials = fc?.recent_trials || outer?.recent_trials || outer?.trial_statuses || fc?.trial_statuses || [];
  if (!trials.length) {
    const li = document.createElement("li");
    li.textContent = "No trial summaries yet.";
    el.appendChild(li);
    return;
  }
  for (const trial of trials.slice(-10).reverse()) {
    const li = document.createElement("li");
    li.textContent = `${trial.trial_id || "trial"} | target ${fmt(trial.target_flow_lpm, 4, " L/min")} | repeat ${trial.repeat_index ?? "--"} | status ${trial.status || "--"} | actual ${fmt(trial.actual_flow_lpm, 4, " L/min")} | voltage ${fmt(trial.mean_flow_voltage_v, 4, " V")} | ${trial.reason || "No reason recorded"}`;
    el.appendChild(li);
  }
}

function renderAutomaticCharts(curve, points) {
  const chartPoints = points.map(p => ({ x: numberOrNull(p.mean_voltage_v), y: numberOrNull(p.mean_actual_flow_lpm) })).filter(p => p.x !== null && p.y !== null).sort((a, b) => a.x - b.x);
  const linePoints = curve?.model?.type === "piecewise_linear" ? chartPoints : [];
  ensureChart("autoCurveChart", { type: "scatter", data: { datasets: [
    { label: "Accepted model points", data: chartPoints, backgroundColor: "#2563eb" },
    { label: "Piecewise linear curve", data: linePoints, showLine: true, borderColor: "#1a7f37", backgroundColor: "#1a7f37", pointRadius: 0 },
  ] }, options: { parsing: false, scales: { x: { title: { display: true, text: "Mean flow sensor voltage (V)" } }, y: { title: { display: true, text: "Mean actual flow (L/min)" } } } } });

  const targetPoints = points.map(p => ({ x: numberOrNull(p.target_flow_lpm), y: numberOrNull(p.mean_actual_flow_lpm) })).filter(p => p.x !== null && p.y !== null).sort((a, b) => a.x - b.x);
  const allVals = targetPoints.flatMap(p => [p.x, p.y]);
  const minVal = allVals.length ? Math.min(...allVals) : 0;
  const maxVal = allVals.length ? Math.max(...allVals) : 1;
  ensureChart("targetActualChart", { type: "scatter", data: { datasets: [
    { label: "Target vs actual", data: targetPoints, backgroundColor: "#dc2626" },
    { label: "Ideal y=x", data: [{ x: minVal, y: minVal }, { x: maxVal, y: maxVal }], showLine: true, borderColor: "#64748b", pointRadius: 0 },
  ] }, options: { parsing: false, scales: { x: { title: { display: true, text: "Target flow (L/min)" } }, y: { title: { display: true, text: "Mean actual flow (L/min)" } } } } });
}

function renderAutomaticFlowResults(payload) {
  const { fc, outer, curve } = automaticCurveFromPayload(payload);
  const points = curve?.model?.points || [];
  const q = curve?.fit_quality || {};
  setText("flowAcceptedCount", String(q.accepted_trial_count ?? "--"));
  setText("flowRejectedCount", String(q.rejected_trial_count ?? curve?.rejected_trials?.length ?? "--"));
  renderAutomaticSummaryCards(curve, points);
  renderAutomaticRangeNote(curve, points);
  renderAcceptedPoints(points);
  renderRejectedTrials(curve);
  renderRecentTrials(fc, outer);
  renderAutomaticCharts(curve, points);
}

async function updateStatus() {
  const data = await apiGet("/api/status");
  setText("softpotVoltage", fmt(data.softpot_voltage_v, 4, " V"));
  setText("softpotVolume", fmt(data.softpot_volume_ml, 2, " ml"));
  setText("flowVoltage", fmt(data.flow_voltage_v, 4, " V"));
  setText("flowLpm", fmt(data.flow_lpm, 4, " L/min"));
  setText("motorState", data.motor_enabled ? "ENABLED" : "disabled");
  setText("stepPosition", `${data.step_position} (${data.step_position_valid ? "valid" : "not homed"})`);
  setText("mode", data.mode || "--");
  setText("lastEvent", data.last_event || "--");
  setText("rawSoftpotVoltage", fmt(data.raw_softpot_voltage ?? data.softpot_voltage_v, 4, " V"));
  setText("rawSoftpotVolume", fmt(data.raw_softpot_volume_ml ?? data.softpot_volume_ml, 2, " ml"));
  setText("filteredSoftpotVolume", fmt(data.filtered_softpot_volume_ml ?? data.softpot_volume_ml, 2, " ml"));
  setText("softpotGlitchCount", String(data.softpot_glitch_count ?? 0));
  const rejected = data.last_rejected_softpot_sample; setText("lastRejectedSoftpot", rejected ? `${fmt(rejected.raw_volume_ml,2," ml")} reason=${rejected.reason}` : "--");
  renderEvents(data); renderSoftpotCalibration(data); renderFlowCalibrationPoints(data);
  const points = data.flow_calibration_points || [];
  renderSummary(points); renderCoverage(points); renderRecommendation(points); renderCharts(points);
  renderAutomaticFlowStatus(data);
  const fc = data.flow_calibration || data.automatic_flow_calibration || data;
  if (document.getElementById("automaticFlowSummaryCards") && !fc?.running && !automaticCurveFromPayload(data).curve) {
    try {
      const response = await fetch("/api/flow/latest-result");
      if (response.ok) renderAutomaticFlowResults(await parseResponse(response));
      else renderAutomaticFlowResults(data);
    } catch (err) {
      renderAutomaticFlowResults(data);
    }
  }
}

function renderAutomaticFlowStatus(data){ const fc = data.flow_calibration || data.automatic_flow_calibration || data; const gas = fc.gas || '--'; const zeroCap = gas !== '--' ? (data.zero_flow_capture_by_gas?.[gas] || null) : null; setText('flowRunning', fc.running ? 'yes':'no'); setText('flowGas', fc.gas || '--'); setText('flowZeroStatus', zeroCap ? `yes (${fmt(zeroCap.voltage_v,4,' V')})` : 'no'); setText('flowCurrentTrial', fc.current_trial?.trial_id || fc.current_trial || '--'); setText('flowCurrentTarget', fc.current_trial?.target_flow_lpm ?? fc.current_target_flow_lpm ?? '--'); setText('flowCurrentRepeat', fc.current_trial?.repeat_index ?? '--'); setText('flowPhase', fc.phase || '--'); setText('flowCompletedCount', String(fc.completed_count ?? fc.completed_trials ?? '--')); setText('flowTotalCount', String(fc.total_count ?? fc.total_trials ?? '--')); setText('flowRunDir', fc.run_dir || fc.result?.run_dir || fc.result?.source_run_dir || '--'); const unstableMsg = fc.softpot_signal_unstable ? ' | Softpot signal unstable / glitch rejected' : ''; setText('flowError', (fc.error || '--') + unstableMsg); setText('flowFailureReason', fc.last_failure_reason || '--'); if (fc.latest_sample){ setText('flowLatestVolume', fmt(fc.latest_sample.softpot_volume_ml,2,' ml')); setText('flowLatestVoltage', fmt(fc.latest_sample.flow_voltage_v,4,' V')); setText('flowLatestActualFlow', fmt(fc.latest_sample.actual_flow_lpm_window,4,' L/min')); } const outer = fc.result || data.result || {}; const curve = outer.result || outer; const runDir = outer.run_dir || curve.source_run_dir || fc.run_dir; if (runDir){ setText('flowSummaryPath', `${runDir}/summary.csv`); setText('flowCurvePath', `${runDir}/calibration_curve.json`); }
  setText('dashSelectedGas', gas); setText('dashZeroFlow', zeroCap ? 'yes' : 'no'); setText('dashLatestAutoCalibration', fc.result?.run_id || data.result?.run_id || '--'); renderAutomaticFlowResults(data); }

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
