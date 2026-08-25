/**
 * render.js — Leaflet 지도 렌더링 + 시뮬레이션 제어 (Phase 4)
 */
'use strict';

let MAP, GRID_CFG, WEIGHTS_CFG;
let GRID_CELLS = {}, SNAP_CELLS = {}, RECT_LAYERS = {}, SIM_CELLS = {}, SNAP_META = {};
let playTimer = null, simElapsedH = 0;

const COLORS = {
  1: { fill: 'rgba(46,160,67,.35)',  stroke: '#2ea043' },
  2: { fill: 'rgba(210,153,34,.45)', stroke: '#d29922' },
  3: { fill: 'rgba(218,54,51,.55)',  stroke: '#da3633' },
};

async function init() {
  try {
    setLoading('지도 초기화 중…');
    MAP = L.map('map', { center: [37.564, 126.978], zoom: 12, attributionControl: false });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 19 }).addTo(MAP);
    L.control.attribution({ position: 'bottomleft', prefix: false }).addAttribution('© OSM © CARTO').addTo(MAP);

    setLoading('데이터 로드 중…');
    const [gridData, snapData, gridCfgData, weightsCfgData, parityData] = await Promise.all([
      fetchJSON('data/grid.json'),
      fetchJSON('data/snapshot.json'),
      fetchJSON('data/grid_cfg.json'),
      fetchJSON('data/weights_cfg.json'),
      fetchJSON('data/parity.json').catch(() => null),
    ]);

    GRID_CFG = gridCfgData;
    WEIGHTS_CFG = weightsCfgData;

    for (const c of gridData.cells) GRID_CELLS[c.id] = { lat: c.lat, lon: c.lon, gu: c.gu };

    SNAP_META = { generated_at: snapData.generated_at, mode: snapData.mode, source_status: snapData.source_status };
    for (const c of snapData.cells) {
      SNAP_CELLS[c.id] = c;
      SIM_CELLS[c.id] = { b: c.b, r_raw: c.r, g_raw: c.g, t_raw: c.t };
    }

    setLoading('격자 렌더링 중…');
    await renderAllGrids(SNAP_CELLS);
    updateHeader(SNAP_META, SNAP_CELLS);
    updateSourceStatus(SNAP_META.source_status);
    if (parityData) runParityCheck(parityData.cases);

    document.getElementById('slider-elapsed').addEventListener('input', e => {
      simElapsedH = +e.target.value;
      document.getElementById('elapsed-val').textContent = simElapsedH + ' h';
      document.getElementById('t-hours').textContent = simElapsedH;
      applySimDecay(simElapsedH);
    });
    document.getElementById('sel-scenario').addEventListener('change', simReset);

    hideLoading();
  } catch (err) {
    document.getElementById('loading-msg').textContent = '❌ 로드 실패: ' + err.message;
    console.error(err);
  }
}

async function renderAllGrids(cellsById) {
  const HALF = 0.00225;
  const ids = Object.keys(cellsById).map(Number);
  for (let i = 0; i < ids.length; i += 300) {
    for (const id of ids.slice(i, i + 300)) {
      const gc = GRID_CELLS[id], snap = cellsById[id];
      if (!gc || !snap) continue;
      const bounds = [[gc.lat - HALF, gc.lon - HALF], [gc.lat + HALF, gc.lon + HALF]];
      const c = COLORS[snap.stage || 1];
      const rect = L.rectangle(bounds, { color: c.stroke, fillColor: c.fill, fillOpacity: 1, weight: 0.5, opacity: 0.8 }).addTo(MAP);
      rect.on('click', () => showPopup(id, gc, SNAP_CELLS[id]));
      RECT_LAYERS[id] = rect;
    }
    await new Promise(r => setTimeout(r, 0));
  }
}

function showPopup(id, gc, snap) {
  const stage = snap.stage || 1;
  const labels = { 1: '1단계 (초록)', 2: '2단계 (노랑)', 3: '3단계 (빨강)' };
  const pct = Math.min((snap.score / 100) * 100, 100).toFixed(0);
  const html = `
    <div class="popup-header">
      <span class="popup-stage-badge s${stage}">${labels[stage]}</span>
      <span class="popup-id">id #${id} · ${gc.gu}</span>
    </div>
    <div class="popup-score-bar">
      <div class="popup-score-fill" style="width:${pct}%;background:${COLORS[stage].stroke}"></div>
    </div>
    <div class="popup-breakdown">
      <div class="pb-item"><span class="pb-label">총점</span><span class="pb-value">${(snap.score||0).toFixed(2)}</span></div>
      <div class="pb-item"><span class="pb-label">불확실</span><span class="pb-value">${snap.unc != null ? snap.unc.toFixed(2) : '—'}</span></div>
      <div class="pb-item"><span class="pb-label">B (기저)</span><span class="pb-value">${(snap.b||0).toFixed(2)}</span></div>
      <div class="pb-item"><span class="pb-label">R (강수)</span><span class="pb-value">${(snap.r||0).toFixed(2)}</span></div>
      <div class="pb-item"><span class="pb-label">G (지하수)</span><span class="pb-value">${(snap.g||0).toFixed(2)}</span></div>
      <div class="pb-item"><span class="pb-label">T (교통)</span><span class="pb-value">${(snap.t||0).toFixed(2)}</span></div>
    </div>`;
  L.popup({ maxWidth: 260 }).setLatLng([gc.lat, gc.lon]).setContent(html).openOn(MAP);
}

function updateHeader(meta, cellsById) {
  const gaEl = document.getElementById('generated-at');
  if (meta.generated_at) {
    const d = new Date(meta.generated_at);
    gaEl.textContent = '갱신: ' + d.toLocaleString('ko-KR', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
    if ((Date.now() - d.getTime()) / 60000 > 20) document.getElementById('stale-badge').style.display = 'inline';
  }
  const modeEl = document.getElementById('mode-badge');
  modeEl.textContent = meta.mode === 'real' ? '실시간' : '시뮬레이션';
  modeEl.style.color = meta.mode === 'real' ? '#2ea043' : '#58a6ff';
  updateCounters(cellsById);
}

function updateCounters(cellsById) {
  let s1 = 0, s2 = 0, s3 = 0;
  for (const c of Object.values(cellsById)) {
    if (c.stage === 3) s3++; else if (c.stage === 2) s2++; else s1++;
  }
  document.getElementById('cnt-s1').textContent = s1.toLocaleString();
  document.getElementById('cnt-s2').textContent = s2.toLocaleString();
  document.getElementById('cnt-s3').textContent = s3.toLocaleString();
  document.getElementById('chip-s3').style.boxShadow = s3 > 0 ? '0 0 8px rgba(218,54,51,.6)' : '';
}

function updateSourceStatus(status) {
  for (const [key, short] of [['rain','rain'],['groundwater','gw'],['traffic','tr']]) {
    const st = (status || {})[key] || 'unknown';
    document.getElementById('dot-' + short).className = 'src-dot ' + (st === 'ok' ? 'ok' : st.startsWith('error') ? 'err' : 'unknown');
    document.getElementById('st-' + short).textContent = st;
  }
}

function applySimDecay(elapsedH) {
  for (const [idStr, rect] of Object.entries(RECT_LAYERS)) {
    const id = +idStr, sim = SIM_CELLS[id];
    if (!sim) continue;
    const res = SinkholeEngine.computeAll(sim, elapsedH, GRID_CFG);
    const c = COLORS[res.stage];
    rect.setStyle({ color: c.stroke, fillColor: c.fill });
    SNAP_CELLS[id] = { ...SNAP_CELLS[id], ...res, stage: res.stage };
  }
  updateCounters(SNAP_CELLS);
}

function simToggle() {
  const btn = document.getElementById('btn-play');
  if (playTimer) {
    clearInterval(playTimer); playTimer = null;
    btn.textContent = '▶ 재생'; btn.classList.remove('active');
  } else {
    btn.textContent = '⏸ 일시정지'; btn.classList.add('active');
    playTimer = setInterval(() => {
      if (simElapsedH >= 96) { simToggle(); return; }
      simElapsedH++;
      document.getElementById('slider-elapsed').value = simElapsedH;
      document.getElementById('elapsed-val').textContent = simElapsedH + ' h';
      document.getElementById('t-hours').textContent = simElapsedH;
      applySimDecay(simElapsedH);
    }, 120);
  }
}

function simReset() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  simElapsedH = 0;
  document.getElementById('slider-elapsed').value = 0;
  document.getElementById('elapsed-val').textContent = '0 h';
  document.getElementById('t-hours').textContent = '0';
  document.getElementById('btn-play').textContent = '▶ 재생';
  document.getElementById('btn-play').classList.remove('active');
  applySimDecay(0);
}

function runParityCheck(cases) {
  if (!GRID_CFG || !WEIGHTS_CFG) return;
  const results = SinkholeEngine.validateParity(cases, GRID_CFG, WEIGHTS_CFG);
  const allOk = results.every(r => r.ok);
  const maxDiff = Math.max(...results.map(r => r.score_diff));
  console.group('[Python-JS 일치 검증] 수용 기준 4번');
  console.log(`${allOk ? '✅ 전부 일치' : '❌ 불일치'} | 최대 점수 차이: ${maxDiff.toFixed(6)} (기준: 0.01)`);
  console.table(results.map(r => ({ 케이스: r.case, '경과h': r.elapsed_h, Py점수: r.py_score, JS점수: r.js_score, 차이: r.score_diff, 통과: r.ok ? '✅' : '❌' })));
  console.groupEnd();
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  return res.json();
}
function setLoading(msg) { document.getElementById('loading-msg').textContent = msg; }
function hideLoading() { document.getElementById('loading').style.display = 'none'; }

document.addEventListener('DOMContentLoaded', init);
