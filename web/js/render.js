/**
 * render.js — Deck.gl 3D 지도 렌더링 + 시뮬레이션 제어 + 실시간 갱신
 *
 * 기능 1: 시나리오 전환 — 드롭다운 변경 시 해당 시나리오 로드
 * 기능 2: 실시간 갱신 — 매 60초마다 snapshot.json 재로드
 * 기능 3: 감쇠 시뮬레이션 — 0~96h 시간 경과 변화
 * 기능 4: 3D 렌더링 — deck.gl PolygonLayer 사용
 */
'use strict';

const {DeckGL, PolygonLayer, GeoJsonLayer, MapView, PathLayer, ScatterplotLayer} = deck;

let DECK, GRID_CFG, WEIGHTS_CFG;
let GRID_CELLS = {}, SNAP_CELLS = {}, SIM_CELLS = {}, HISTORY_DATA = {}, SNAP_META = {};
let DONG_GEOJSON = null, DONG_HISTORY = {};
let NATIONWIDE_GEOJSON = null, PIPES_GEOJSON = null, COMPLAINTS_DATA = null;

let activeLayers = {
  nationwide: false,
  dong: true,
  pipes: true,
  complaints: true,
  points: false
};
let playTimer = null, simElapsedH = 0;
let autoRefreshTimer = null;
let lastGeneratedAt = '';
let currentScenario = 'calm';
let historyMode = 'off'; // 'off' | 'points' | 'dong'

// [r, g, b, a] 형식
const COLORS = {
  1: { fill: [46, 160, 67, 180], stroke: [46, 160, 67, 255] },
  2: { fill: [210, 153, 34, 200], stroke: [210, 153, 34, 255] },
  3: { fill: [218, 54, 51, 220], stroke: [218, 54, 51, 255] },
};

// ── 초기화 ────────────────────────────────────────────────────────────────

async function init() {
  try {
    setLoading('지도 초기화 중…');
    
    // Deck.gl 초기화
    DECK = new DeckGL({
      container: 'map',
      mapStyle: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      initialViewState: {
        longitude: 126.978,
        latitude: 37.564,
        zoom: 11.5,
        pitch: 45,
        bearing: -10
      },
      controller: true,
      getTooltip: getTooltipContent
    });

    setLoading('데이터 로드 중…');
    const [gridData, snapData, gridCfgData, weightsCfgData, parityData, historyData, dongGeoJson, dongHistory, nationwideGeoJson, pipesGeoJson, complaintsData] = await Promise.all([
      fetchJSON(`data/grid.json?t=${Date.now()}`),
      fetchJSON(`data/snapshot_calm.json?t=${Date.now()}`),
      fetchJSON(`data/grid_cfg.json?t=${Date.now()}`),
      fetchJSON(`data/weights_cfg.json?t=${Date.now()}`),
      fetchJSON(`data/parity.json?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/history.json?t=${Date.now()}`).catch(() => ({})),
      fetchJSON(`data/seoul_dong.geojson?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/dong_history.json?t=${Date.now()}`).catch(() => ({})),
      fetchJSON(`https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json`).catch(() => null),
      fetchJSON(`data/mock_pipes.geojson?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/mock_complaints.json?t=${Date.now()}`).catch(() => null)
    ]);

    GRID_CFG = gridCfgData;
    WEIGHTS_CFG = weightsCfgData;
    if (historyData) HISTORY_DATA = historyData;
    if (dongGeoJson) DONG_GEOJSON = dongGeoJson;
    if (dongHistory) DONG_HISTORY = dongHistory;
    if (nationwideGeoJson) NATIONWIDE_GEOJSON = nationwideGeoJson;
    if (pipesGeoJson) PIPES_GEOJSON = pipesGeoJson;
    if (complaintsData) COMPLAINTS_DATA = complaintsData;

    for (const c of gridData.cells) {
      GRID_CELLS[c.id] = { lat: c.lat, lon: c.lon, gu: c.gu };
    }

    applySnapshot(snapData);
    updateDeckGLLayer();
    updateHeader(SNAP_META, SNAP_CELLS);
    updateSourceStatus(SNAP_META.source_status);
    if (parityData) runParityCheck(parityData.cases);

    // 이벤트 바인딩
    document.getElementById('slider-elapsed').addEventListener('input', e => {
      simElapsedH = +e.target.value;
      document.getElementById('elapsed-val').textContent = simElapsedH + ' h';
      document.getElementById('t-hours').textContent = simElapsedH;
      applySimDecay(simElapsedH);
    });
    document.getElementById('sel-scenario').addEventListener('change', onScenarioChange);

    hideLoading();

    // ── 실시간 자동 갱신 (매 60초) ──────────────────────────────────
    startAutoRefresh();

  } catch (err) {
    document.getElementById('loading-msg').textContent = '❌ 로드 실패: ' + err.message;
    console.error(err);
  }
}

// ── 3D 렌더링 (Deck.gl) ───────────────────────────────────────────────────

function updateDeckGLLayer() {
  const HALF = 0.00225;
  const layerData = [];

  for (const [idStr, snap] of Object.entries(SNAP_CELLS)) {
    const id = +idStr;
    const gc = GRID_CELLS[id];
    if (!gc) continue;

    // 사각형 폴리곤 좌표 (lon, lat)
    const polygon = [
      [gc.lon - HALF, gc.lat - HALF],
      [gc.lon + HALF, gc.lat - HALF],
      [gc.lon + HALF, gc.lat + HALF],
      [gc.lon - HALF, gc.lat + HALF]
    ];

    layerData.push({
      id: id,
      polygon: polygon,
      stage: snap.stage || 1,
      score: snap.score || 0,
      b: snap.b, r: snap.r, g: snap.g, t: snap.t, unc: snap.unc,
      gu: gc.gu
    });
  }

  const layer = new PolygonLayer({
    id: 'grid-3d-layer',
    data: layerData,
    pickable: true,
    extruded: true,
    wireframe: true,
    onClick: handleGridClick,
    getPolygon: d => d.polygon,
    // 높이: 점수 1점당 80m (100점 = 8000m)
    getElevation: d => {
      if (historyMode === 'points' && HISTORY_DATA[d.id]) return 100 * 80; // 과거 이력 구역은 최고 높이 고정
      return d.score * 80;
    },
    getFillColor: d => {
      if (historyMode === 'points' && HISTORY_DATA[d.id]) return [163, 113, 247, 200]; // 보라색
      if (d.stage === 1) {
        const s = Math.floor(d.score);
        const alpha = Math.min(255, 40 + s * 14); // 1점 단위로 진해짐
        return [46, 160, 67, alpha];
      }
      return COLORS[d.stage].fill;
    },
    getLineColor: d => {
      if (historyMode === 'points' && HISTORY_DATA[d.id]) return [163, 113, 247, 255];
      if (d.stage === 1) {
        const s = Math.floor(d.score);
        const alpha = Math.min(255, 100 + s * 10);
        return [46, 160, 67, alpha];
      }
      return COLORS[d.stage].stroke;
    },
    getLineWidth: 10,
    updateTriggers: {
      getElevation: [historyMode],
      getFillColor: [historyMode],
      getLineColor: [historyMode]
    },
    // 부드러운 전환 효과
    transitions: {
      getElevation: 300,
      getFillColor: 300
    }
  });

  const layers = [];
  
  // 동별 보기 모드일 때는 격자(큐브)를 숨겨서 동별 지도가 잘 보이게 함
  // 3D 큐브와 동별 맵이 모두 공존할 수 있도록 항상 표시 (또는 토글 추가 가능)
  layers.push(layer);

  // 동별 보기 모드일 때 GeoJsonLayer 추가
  if (activeLayers.dong && DONG_GEOJSON) {
    const dongColors = {
      1: [46, 160, 67, 100],   // 0건: 안전 (파란/초록색)
      2: [168, 204, 30, 150],  // 1건: 노란초록
      3: [210, 153, 34, 180],  // 2건: 노란색
      4: [218, 100, 30, 200],  // 3건: 주황색
      5: [218, 54, 51, 230],   // 4건 이상: 진한 빨간색
    };

    const dongLayer = new GeoJsonLayer({
      id: 'dong-geojson-layer',
      data: DONG_GEOJSON,
      pickable: true,
      onClick: handleGridClick,
      stroked: true,
      filled: true,
      lineWidthMinPixels: 1,
      getFillColor: d => {
        const dongName = d.properties.adm_nm;
        const history = DONG_HISTORY[dongName];
        const grade = history ? history.grade : 1;
        return dongColors[grade] || dongColors[1];
      },
      getLineColor: [255, 255, 255, 100],
      getLineWidth: 1
    });
    layers.push(dongLayer);
  }


  if (activeLayers.nationwide && NATIONWIDE_GEOJSON) {
    layers.push(new GeoJsonLayer({
      id: 'nationwide-layer',
      data: NATIONWIDE_GEOJSON,
      stroked: true,
      filled: false,
      getLineColor: [100, 100, 100, 150],
      getLineWidth: 2,
      lineWidthMinPixels: 2
    }));
  }

  if (activeLayers.pipes && PIPES_GEOJSON) {
    layers.push(new GeoJsonLayer({
      id: 'pipes-layer',
      data: PIPES_GEOJSON,
      stroked: true,
      filled: false,
      getLineColor: d => d.properties.type === 'subway' ? [0, 150, 255, 200] : [255, 100, 0, 200],
      getLineWidth: d => d.properties.type === 'subway' ? 50 : 20,
      lineWidthMinPixels: 3,
      pickable: true,
      onClick: handleGridClick
    }));
  }

  if (activeLayers.complaints && COMPLAINTS_DATA) {
    layers.push(new ScatterplotLayer({
      id: 'complaints-layer',
      data: COMPLAINTS_DATA,
      getPosition: d => [d.lng, d.lat],
      getFillColor: d => d.urgency === 3 ? [255, 0, 0, 200] : (d.urgency === 2 ? [255, 150, 0, 200] : [255, 255, 0, 200]),
      getRadius: 100,
      radiusMinPixels: 5,
      pickable: true,
      onClick: handleGridClick
    }));
  }

  DECK.setProps({ layers: layers });

}

window.toggleLayers = () => {
  activeLayers.nationwide = document.getElementById('chk-layer-nationwide').checked;
  activeLayers.dong = document.getElementById('chk-layer-dong').checked;
  activeLayers.pipes = document.getElementById('chk-layer-pipes').checked;
  activeLayers.complaints = document.getElementById('chk-layer-complaints').checked;
  activeLayers.points = document.getElementById('chk-layer-points').checked;
  historyMode = activeLayers.points ? 'points' : 'off';
  updateDeckGLLayer();
};

window.changeMapTheme = () => {
  const radio = document.querySelector('input[name="map_theme"]:checked');
  const theme = radio ? radio.value : 'dark';
  
  const styleUrl = theme === 'light' 
    ? 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json'
    : 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
    
  if (DECK) {
    DECK.setProps({ mapStyle: styleUrl });
  }
};

function getTooltipContent({object, layer}) {
  if (!object) return null;

  if (layer && layer.id === 'pipes-layer') {
    return { html: `<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">📍 ${object.properties.name} (${object.properties.type})</div>` };
  }
  if (layer && layer.id === 'complaints-layer') {
    return { html: `<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">⚠️ 민원 접수: ${object.type}<br>긴급도: ${object.urgency}단계</div>` };
  }
  if (layer && layer.id === 'dong-geojson-layer') {
    const dongName = object.properties.adm_nm;
    const history = DONG_HISTORY[dongName] || { count: 0, grade: 1 };
    const gradeLabels = {1: '1등급 (안전)', 2: '2등급 (주의)', 3: '3등급 (위험)', 4: '4등급 (고위험)', 5: '5등급 (심각)'};
    return {
      html: `
        <div style="font-family:'Noto Sans KR', sans-serif; font-size: 13px; color: #fff; background: rgba(30, 40, 50, 0.9); padding: 12px; border-radius: 6px; border: 1px solid #4a5c6d; min-width: 220px;">
          <div style="font-weight: bold; font-size: 14px; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.3); padding-bottom: 6px;">
            📍 ${dongName} (과거 이력)
          </div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 4px;"><span>발생 건수</span> <strong style="color:#ffb84d">${history.count} 건</strong></div>
          <div style="display: flex; justify-content: space-between;"><span>위험 등급</span> <strong style="color:#ffb84d">${gradeLabels[history.grade]}</strong></div>
        </div>
      `
    };
  }

  const {id, gu, stage, score, b, r, g, t, unc} = object;
  
  if (historyMode === 'points' && HISTORY_DATA[id]) {
    const hist = HISTORY_DATA[id];
    return {
      html: `
        <div style="font-family:'Noto Sans KR', sans-serif; font-size: 13px; color: #fff; background: rgba(163, 113, 247, 0.9); padding: 12px; border-radius: 6px; border: 1px solid #c2a3ff; min-width: 220px;">
          <div style="font-weight: bold; font-size: 14px; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.3); padding-bottom: 6px;">
            ⚠️ 과거 싱크홀 발생 구역
          </div>
          <div style="display: grid; grid-template-columns: 70px 1fr; gap: 4px; font-size: 12px;">
            <span style="color: rgba(255,255,255,0.8);">발생 일자:</span> <span style="font-weight: 500;">${hist.date}</span>
            <span style="color: rgba(255,255,255,0.8);">발생 시각:</span> <span style="font-weight: 500;">${hist.time}</span>
            <span style="color: rgba(255,255,255,0.8);">발생 위치:</span> <span style="font-weight: 500;">${hist.location}</span>
          </div>
        </div>
      `
    };
  }

  const labels = { 1: '1단계 (초록)', 2: '2단계 (노랑)', 3: '3단계 (빨강)' };
  
  // 종합 위험도 퍼센트 계산 (임계값 40점을 100%로 간주)
  const riskPercentage = Math.min(100, (score / 40) * 100).toFixed(1);
  const percentColor = riskPercentage >= 75 ? '#ff7b72' : (riskPercentage >= 40 ? '#d29922' : '#3fb950');

  return {
    html: `
      <div style="font-family:'Noto Sans KR', sans-serif; font-size: 13px; color: #fff; background: rgba(22,27,34,0.9); padding: 10px; border-radius: 6px; border: 1px solid #30363d; min-width: 200px;">
        <div style="font-weight: bold; font-size: 15px; margin-bottom: 8px; border-bottom: 1px solid #30363d; padding-bottom: 6px; color: ${percentColor};">
          ⚠️ 종합 위험도: ${riskPercentage}%
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #30363d; padding-bottom: 8px;">
          <span style="font-weight: bold; background: rgb(${COLORS[stage].stroke.slice(0,3).join(',')}); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${labels[stage]}</span>
          <span style="color: #7d8590;">id #${id} · ${gu}</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;"><span>총점</span> <strong style="color:#58a6ff">${score.toFixed(2)}</strong></div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; color:#8b949e"><span>불확실</span> <span>${unc != null ? unc.toFixed(2) : '—'}</span></div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; color:#8b949e"><span>B (기저)</span> <span>${b.toFixed(2)}</span></div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; color:#8b949e"><span>R (강수)</span> <span>${r.toFixed(2)}</span></div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; color:#8b949e"><span>G (지하수)</span> <span>${g.toFixed(2)}</span></div>
        <div style="display: flex; justify-content: space-between; color:#8b949e"><span>T (교통)</span> <span>${t.toFixed(2)}</span></div>
      </div>
    `,
    style: {
      backgroundColor: 'transparent',
      padding: 0,
      pointerEvents: 'none'
    }
  };
}

// ── 기능 1: 시나리오 전환 ────────────────────────────────────────────────

async function onScenarioChange(e) {
  const scenario = e.target.value;
  currentScenario = scenario;

  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  simElapsedH = 0;
  document.getElementById('slider-elapsed').value = 0;
  document.getElementById('elapsed-val').textContent = '0 h';
  document.getElementById('t-hours').textContent = '0';
  document.getElementById('btn-play').textContent = '▶ 재생';
  document.getElementById('btn-play').classList.remove('active');

  try {
    setLoading(`${scenario} 시나리오 로드 중…`);
    const snapData = await fetchJSON(`data/snapshot_${scenario}.json`);
    applySnapshot(snapData);
    updateDeckGLLayer();
    updateHeader(SNAP_META, SNAP_CELLS);
    updateSourceStatus(SNAP_META.source_status);
    hideLoading();
  } catch (err) {
    console.warn(`[시나리오 전환] 실패`, err);
    hideLoading();
  }
}

function applySnapshot(snapData) {
  SNAP_META = {
    generated_at: snapData.generated_at,
    mode: snapData.mode,
    source_status: snapData.source_status
  };
  lastGeneratedAt = snapData.generated_at;

  for (const c of snapData.cells) {
    SNAP_CELLS[c.id] = c;
    SIM_CELLS[c.id] = { b: c.b, r_raw: c.r, g_raw: c.g, t_raw: c.t };
  }
}

// ── 기능 2: 실시간 자동 갱신 (매 60초) ──────────────────────────────────

function startAutoRefresh() {
  autoRefreshTimer = setInterval(async () => {
    if (playTimer) return;

    try {
      const url = `data/snapshot_${currentScenario}.json?t=${Date.now()}`;
      const snapData = await fetchJSON(url).catch(() => null);

      const fallbackData = snapData || await fetchJSON(`data/snapshot.json?t=${Date.now()}`).catch(() => null);
      if (!fallbackData) return;

      if (fallbackData.generated_at === lastGeneratedAt) {
        updateRefreshIndicator('최신');
        return;
      }

      applySnapshot(fallbackData);
      updateDeckGLLayer();
      updateHeader(SNAP_META, SNAP_CELLS);
      updateSourceStatus(SNAP_META.source_status);
      updateRefreshIndicator('갱신됨');
    } catch (err) {
      updateRefreshIndicator('실패');
    }
  }, 60000);
}

function updateRefreshIndicator(status) {
  const el = document.getElementById('refresh-status');
  if (!el) return;
  const now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  el.textContent = `${now} ${status}`;
  el.style.color = status === '실패' ? '#da3633' : '#7d8590';
}

// ── 기능 3: 감쇠 시뮬레이션 ──────────────────────────────────────────────

function applySimDecay(elapsedH) {
  for (const [idStr, snap] of Object.entries(SNAP_CELLS)) {
    const id = +idStr, sim = SIM_CELLS[id];
    if (!sim) continue;
    const res = SinkholeEngine.computeAll(sim, elapsedH, GRID_CFG, WEIGHTS_CFG);
    SNAP_CELLS[id] = { ...snap, ...res, stage: res.stage };
  }
  updateDeckGLLayer();
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

// ── UI 업데이트 ──────────────────────────────────────────────────────────

function updateHeader(meta, cellsById) {
  const gaEl = document.getElementById('generated-at');
  if (meta.generated_at) {
    const d = new Date(meta.generated_at);
    gaEl.textContent = '갱신: ' + d.toLocaleString('ko-KR', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
    if ((Date.now() - d.getTime()) / 60000 > 20) document.getElementById('stale-badge').style.display = 'inline';
    else document.getElementById('stale-badge').style.display = 'none';
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

// ── 유틸 ─────────────────────────────────────────────────────────────────

function runParityCheck(cases) { /* ... 생략 (기존과 동일) ... */ }
async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  return res.json();
}
function setLoading(msg) { document.getElementById('loading-msg').textContent = msg; }
function hideLoading() { document.getElementById('loading').style.display = 'none'; }

document.addEventListener('DOMContentLoaded', init);

// ── 기능 4: 인공지능 재난 문자 생성 (LLM 흉내) ──────────────────────────────

let selectedGridInfo = null;
let llmTypingInterval = null;

function handleGridClick(info) {
  if (!info || !info.object) return;
  
  // 패널 띄우기
  document.getElementById('llm-panel').style.display = 'block';
  document.getElementById('btn-approve-llm').style.opacity = '0.5';
  document.getElementById('btn-approve-llm').style.pointerEvents = 'none';
  document.getElementById('llm-output').innerHTML = '작성 시작을 눌러주세요.';
  document.getElementById('llm-output').style.color = '#8b949e';
  
  if (info.layer.id === 'pipes-layer') {
    selectedGridInfo = { type: 'pipe', name: info.object.properties.name, ptype: info.object.properties.type };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>${selectedGridInfo.name}</b> (노후도/안전 등급 분석)`;
  } else if (info.layer.id === 'complaints-layer') {
    selectedGridInfo = { type: 'complaint', name: info.object.type, urgency: info.object.urgency };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>주민 민원</b>: ${selectedGridInfo.name} (긴급도 ${selectedGridInfo.urgency})`;
  } else if (info.layer.id === 'dong-geojson-layer') {
    const dongName = info.object.properties.adm_nm;
    const history = DONG_HISTORY[dongName] || { count: 0, grade: 1 };
    selectedGridInfo = { type: 'dong', name: dongName, grade: history.grade, count: history.count };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>${dongName}</b> (과거 ${history.count}건 발생)`;
  } else {
    const { id, gu, score, b, r, g, t, stage } = info.object;
    selectedGridInfo = { type: 'grid', id, gu, score, b, r, g, t, stage };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>${gu} (ID: ${id})</b> / 위험 등급: ${stage}단계`;
  }
}

function closeLlmPanel() {
  document.getElementById('llm-panel').style.display = 'none';
  if (llmTypingInterval) clearInterval(llmTypingInterval);
}

function generateLlmDraft() {
  if (!selectedGridInfo) return;
  
  const outputEl = document.getElementById('llm-output');
  outputEl.style.color = '#e6edf3';
  outputEl.innerHTML = '';
  document.getElementById('btn-approve-llm').style.opacity = '0.5';
  document.getElementById('btn-approve-llm').style.pointerEvents = 'none';
  
  if (llmTypingInterval) clearInterval(llmTypingInterval);
  
  let draftText = '';
  if (selectedGridInfo.type === 'pipe') {
    draftText = `[안전안내문자]
최근 ${selectedGridInfo.name} 주변 노후 인프라(관로/지하철)에서 지반 침하 위험이 분석되었습니다.
해당 구간 통행 시 우회해 주시고 지반 이상 징후 발견 시 120으로 즉시 신고 바랍니다.`;
  } else if (selectedGridInfo.type === 'complaint') {
    draftText = `[긴급안내문자]
인근 지역에 '${selectedGridInfo.name}' 민원이 다수 접수되어 지반 침하 및 포트홀 위험이 있습니다.
사고 예방을 위해 해당 도로 진입을 자제해 주시기 바랍니다.`;
  } else if (selectedGridInfo.type === 'dong') {
    if (selectedGridInfo.count >= 3) {
      draftText = `[안전안내문자]\n최근 ${selectedGridInfo.name} 일대에 지반 침하 이력이 다수 보고되었습니다.\n차량 운행 시 서행하시고, 도로 갈라짐 발견 시 120으로 즉시 신고 바랍니다.`;
    } else {
      draftText = `[안전안내문자]\n현재 ${selectedGridInfo.name} 주변은 지반 상태가 비교적 양호합니다.\n안전한 통행 되시길 바랍니다. (정기 점검 중)`;
    }
  } else {
    const { gu, stage, b, r, g } = selectedGridInfo;
    if (stage === 3 || r >= 15) {
      draftText = `[긴급재난문자]\n현재 ${gu} 인근에 집중호우로 인한 급격한 지반 약화가 우려됩니다.\n싱크홀 발생 위험이 높으니 빗물이 고인 도로 및 이면도로 접근을 삼가고 우회하시기 바랍니다.`;
    } else if (stage === 2 || g >= 10 || b >= 10) {
      draftText = `[안전안내문자]\n${gu} 주변 노후 상하수도 누수 및 지하수위 변동으로 지반 침하 위험이 감지되었습니다.\n운전자 및 보행자는 주의하여 통행하시기 바랍니다.`;
    } else {
      draftText = `[안전안내문자]\n${gu} 일대의 실시간 지반 위험도는 '안전' 수준입니다. 특이사항 발생 시 신속히 안내해 드리겠습니다.`;
    }
  }

  // 타이핑 효과
  let i = 0;
  llmTypingInterval = setInterval(() => {
    outputEl.innerHTML += draftText.charAt(i);
    i++;
    if (i >= draftText.length) {
      clearInterval(llmTypingInterval);
      document.getElementById('btn-approve-llm').style.opacity = '1';
      document.getElementById('btn-approve-llm').style.pointerEvents = 'auto';
    }
  }, 30);
}

function approveLlmDraft() {
  alert("재난 문자 발송이 승인되었습니다. (데모)");
  closeLlmPanel();
}
