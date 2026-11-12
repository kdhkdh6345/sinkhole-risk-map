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
let GRID_CELLS = {}, SNAP_CELLS = {}, SIM_CELLS = {}, HISTORY_DATA = {}, SNAP_META = {}, HISTORY_META = null;
let DONG_GEOJSON = null, DONG_HISTORY = {};
let NATIONWIDE_GEOJSON = null, PIPES_GEOJSON = null, SEWER_GU = null, SUBWAY_OSM = null, COMPLAINTS_DATA = null, PIPE_PENALTIES = null, NEWS_ISSUES = null;

let activeLayers = {
  nationwide: false,
  grid: true,
  dong: true,
  pipes: true,
  subway: false,
  complaints: true,
  ai_anomaly: true,
  points: false,
  news: true
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
    const [gridData, snapData, gridCfgData, weightsCfgData, parityData, historyData, dongGeoJson, dongHistory, nationwideGeoJson, pipesGeoJson, complaintsData, pipePenalties, newsIssuesData, sewerGu, subwayOsm, jisHistory] = await Promise.all([
      fetchJSON(`data/grid.json?t=${Date.now()}`),
      fetchJSON(`data/snapshot_calm.json?t=${Date.now()}`),
      fetchJSON(`data/grid_cfg.json?t=${Date.now()}`),
      fetchJSON(`data/weights_cfg.json?t=${Date.now()}`),
      fetchJSON(`data/parity.json?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/history.json?t=${Date.now()}`).catch(() => ({})),
      fetchJSON(`data/seoul_dong.geojson?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/dong_history.json?t=${Date.now()}`).catch(() => ({})),
      fetchJSON(`https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json`).catch(() => null),
      fetchJSON(`data/seoul_subway.geojson?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/mock_complaints.json?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/pipe_penalties.json?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/news_issues.json?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/seoul_gu_sewer.geojson?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/snapshot_subway_osm.json?t=${Date.now()}`).catch(() => null),
      fetchJSON(`data/snapshot_sinkhole_history.json?t=${Date.now()}`).catch(() => null)
    ]);

    GRID_CFG = gridCfgData;
    WEIGHTS_CFG = weightsCfgData;
    updateStageLegend(WEIGHTS_CFG);
    // 과거 싱크홀: 국토교통부 지하안전정보(실제 사고)가 있으면 그것만 사용.
    // 없으면 기존 파일 중 보도 기반 실제 사고만 남기고, 가상 배치 항목은 쓰지 않는다.
    if (jisHistory && jisHistory.events && jisHistory.events.length) {
      HISTORY_DATA = jisHistory.by_grid || {};
      HISTORY_META = jisHistory.meta || null;
    } else if (historyData) {
      HISTORY_DATA = Object.fromEntries(Object.entries(historyData).filter(([, v]) => !String(v.location || '').includes('가상')));
    }
    if (dongGeoJson) DONG_GEOJSON = dongGeoJson;
    DONG_HISTORY = (jisHistory && jisHistory.by_dong) ? jisHistory.by_dong : {};  // 가상 이력 기반 집계는 쓰지 않음
    if (nationwideGeoJson) NATIONWIDE_GEOJSON = nationwideGeoJson;
    if (pipesGeoJson) PIPES_GEOJSON = pipesGeoJson;
    if (sewerGu) SEWER_GU = sewerGu;
    if (subwayOsm && subwayOsm.features && subwayOsm.features.length) SUBWAY_OSM = subwayOsm;
    if (complaintsData) COMPLAINTS_DATA = complaintsData;
    if (pipePenalties) PIPE_PENALTIES = pipePenalties;
    if (newsIssuesData) NEWS_ISSUES = newsIssuesData.issues;

    for (const c of gridData.cells) {
      GRID_CELLS[c.id] = { lat: c.lat, lon: c.lon, gu: c.gu };
    }

    // 뉴스 렌더링
    renderNewsFeed();

    applySnapshot(snapData);
    updateDeckGLLayer();
    updateHeader(SNAP_META, SNAP_CELLS);
    updateSourceStatus(SNAP_META.source_status, SNAP_META.source_detail);
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
    getElevation: d => d.score * 80,
    getFillColor: d => {
      if (d.stage === 1) {
        const s = Math.floor(d.score);
        const alpha = Math.min(255, 40 + s * 14);
        return [46, 160, 67, alpha];
      }
      return COLORS[d.stage].fill;
    },
    getLineColor: d => {
      if (d.stage === 1) {
        const s = Math.floor(d.score);
        const alpha = Math.min(255, 100 + s * 10);
        return [46, 160, 67, alpha];
      }
      return COLORS[d.stage].stroke;
    },
    getLineWidth: 10,
    transitions: {
      getElevation: 300,
      getFillColor: 300
    }
  });

  // ── 과거 싱크홀 발생 현황 (독립 레이어) ──────────────────────
  const historyLayerData = [];
  if (activeLayers.points) {
    for (const [idStr, info] of Object.entries(HISTORY_DATA)) {
      const id = +idStr;
      const gc = GRID_CELLS[id];
      if (!gc) continue;
      const polygon = [
        [gc.lon - HALF, gc.lat - HALF],
        [gc.lon + HALF, gc.lat - HALF],
        [gc.lon + HALF, gc.lat + HALF],
        [gc.lon - HALF, gc.lat + HALF]
      ];
      historyLayerData.push({ id, polygon, info });
    }
  }

  const historyLayer = new PolygonLayer({
    id: 'history-layer',
    data: historyLayerData,
    pickable: true,
    extruded: true,
    wireframe: true,
    onClick: handleGridClick,
    getPolygon: d => d.polygon,
    getElevation: 40 * 80,
    getFillColor: [163, 113, 247, 200],
    getLineColor: [163, 113, 247, 255],
    getLineWidth: 10,
    transitions: {
      getElevation: 300,
      getFillColor: 300
    }
  });

  const layers = [];
  
  // 3D 격자(큐브) 종합 위험도
  if (activeLayers.grid) {
    layers.push(layer);
  }

  // 과거 싱크홀 발생 현황 (독립)
  if (activeLayers.points && historyLayerData.length > 0) {
    layers.push(historyLayer);
  }

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

  // 하수관 노후율(구별, 실측 9개 구·추정 16개 구) + 실시간 하수관로 수위(툴팁)
  if (activeLayers.pipes && SEWER_GU) {
    layers.push(new GeoJsonLayer({
      id: 'sewer-gu-layer',
      data: SEWER_GU,
      stroked: true,
      filled: true,
      getFillColor: d => {
        const r = d.properties.ratio_30y;
        if (r == null) return [0, 0, 0, 0];
        const t = Math.max(0, Math.min(1, (r - 0.50) / 0.17));   // 노후율 50%~67%를 색 범위로
        const alpha = d.properties.data_type === 'measured' ? 120 : 60; // 추정값은 옅게
        return [255, Math.round(200 - 140 * t), Math.round(80 - 60 * t), alpha];
      },
      getLineColor: d => d.properties.data_type === 'measured' ? [255, 140, 40, 230] : [255, 200, 120, 140],
      getLineWidth: 40,
      lineWidthMinPixels: 1,
      pickable: true,
      onClick: handleGridClick
    }));
  }

  // 지하철 노선: OpenStreetMap 실제 노선 (수집본이 없으면 표시하지 않음)
  if (activeLayers.subway && SUBWAY_OSM) {
    layers.push(new GeoJsonLayer({
      id: 'subway-layer',
      data: SUBWAY_OSM,
      stroked: true,
      filled: false,
      getLineColor: d => {
        const hex = d.properties.color || '#0096FF';
        return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), 220];
      },
      getLineWidth: 80,
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

  // ── AI Prediction Residual Anomaly Layer (Phase 7-2) ──
  if (activeLayers.ai_anomaly && SNAP_CELLS && GRID_CELLS) {
    const anomalyData = Object.values(SNAP_CELLS).filter(c => c.ai_anomaly && GRID_CELLS[c.id]);
    if (anomalyData.length > 0) {
      layers.push(new ScatterplotLayer({
        id: 'ai-anomaly-layer',
        data: anomalyData,
        getPosition: d => [GRID_CELLS[d.id].lon, GRID_CELLS[d.id].lat],
        getFillColor: [255, 0, 0, 255],
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
        getRadius: 250,
        pickable: true,
        onClick: handleGridClick
      }));
    }
  }

  DECK.setProps({ layers: layers });

}

window.toggleLayers = () => {
  activeLayers.nationwide = document.getElementById('chk-layer-nationwide').checked;
  activeLayers.grid = document.getElementById('chk-layer-grid').checked;
  activeLayers.dong = document.getElementById('chk-layer-dong').checked;
  activeLayers.pipes = document.getElementById('chk-layer-pipes').checked;
  const subwayEl = document.getElementById('chk-layer-subway');
  if (subwayEl) activeLayers.subway = subwayEl.checked;
  activeLayers.complaints = document.getElementById('chk-layer-complaints').checked;
  
  const anomalyEl = document.getElementById('chk-layer-ai-anomaly');
  if (anomalyEl) activeLayers.ai_anomaly = anomalyEl.checked;
  
  activeLayers.points = document.getElementById('chk-layer-points').checked;
  const newsEl = document.getElementById('chk-layer-news');
  if (newsEl) activeLayers.news = newsEl.checked;
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

  if (layer && layer.id === 'sewer-gu-layer') {
    const p = object.properties;
    const lv = ((SNAP_META.sewer || {}).by_gu || {})[p.gu];
    const pct = v => v == null ? '-' : `${Math.round(v * 1000) / 10}%`;
    const kind = p.data_type === 'measured' ? '실측 (2023.12 기준)' : '추정';
    const live = lv
      ? `• 하수관 최고 수위: <b>${lv.max_m.toFixed(2)}m</b> (측정소 ${lv.n}곳 중)<br>• 위치: ${lv.max_addr}<br>• 측정: ${lv.time}`
      : '• 실시간 하수관 수위: 자료 없음';
    return { html: `<div style="font-family:'Noto Sans KR',sans-serif;font-size:13px;color:#fff;background:rgba(20,12,0,.95);padding:12px;border-radius:6px;border:1px solid #ff8c28;min-width:250px;">
      <div style="font-weight:bold;font-size:14px;margin-bottom:6px;color:#ffb84d;">🚰 ${p.gu} 하수관</div>
      • 30년 이상 노후관: <b>${pct(p.ratio_30y)}</b> · 50년 이상: ${pct(p.ratio_50y)}<br>
      <span style="opacity:.75">• 노후율 자료: ${kind}</span><br>
      <div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,140,40,.4)">${live}</div>
      <div style="opacity:.6;font-size:11px;margin-top:6px">출처: 서울 열린데이터광장 '서울시 하수관로 수위 현황'</div></div>` };
  }
  if (layer && (layer.id === 'subway-layer' || layer.id === 'pipe-layer')) {
    const p = object.properties;
    return { html: `<div style="padding: 10px; background: rgba(0,0,0,0.85); color: white; border-radius: 4px;">🚇 <b>${p.name}</b>${p.ref ? ` (${p.ref})` : ''}<div style="opacity:.6;font-size:11px;margin-top:4px">© OpenStreetMap contributors</div></div>` };
  }
  if (layer && layer.id === 'ai-anomaly-layer') {
    const { id, gu, score, gs } = object;
    const thr = ((WEIGHTS_CFG || {}).anomaly || {}).sigma_threshold ?? 2.5;
    const sigma = (gs ?? 0);
    return {
      html: `
        <div style="font-family:'Noto Sans KR', sans-serif; font-size: 13px; color: #fff; background: rgba(30, 0, 0, 0.95); padding: 12px; border-radius: 6px; border: 1px solid #ff4444; min-width: 250px; box-shadow: 0 4px 12px rgba(255,0,0,0.3);">
          <div style="font-weight: bold; font-size: 14px; margin-bottom: 8px; border-bottom: 1px solid rgba(255,0,0,0.4); padding-bottom: 6px; color: #ff7b72;">
            🚨 지하수위 이상탐지
          </div>
          <div style="margin-bottom: 8px;">
            <span style="color: #ffb84d;">📍 위치:</span> ${gu || '알 수 없음'} (ID: #${id})<br>
            <span style="color: #ffb84d;">⚠️ 종합 위험도:</span> ${score.toFixed(2)}점
          </div>
          <div style="background: rgba(0,0,0,0.5); padding: 6px; border-radius: 4px; font-size: 11px; color: #e6edf3; line-height: 1.4;">
            <b>[선정 기준]</b><br>
            • 지하수위 σ 이상도: <b>${sigma.toFixed(2)}σ</b><br>
            • 판정 기준: |σ| &gt; ${thr} (weights.yaml anomaly.sigma_threshold)<br>
            <span style="color: #ff7b72; display: inline-block; margin-top: 4px;">평상시 변동 범위를 크게 벗어난 지하수위 변화가 관측(또는 시뮬레이션)되었습니다. 현장 확인이 필요합니다.</span>
          </div>
        </div>
      `
    };
  }
  if (layer && layer.id === 'complaints-layer') {
    return { html: `<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">⚠️ 민원 접수: ${object.type}<br>긴급도: ${object.urgency}단계</div>` };
  }
  if (layer && layer.id === 'news-issues-layer') {
    return {
      html: `
        <div style="font-family:'Noto Sans KR', sans-serif; font-size: 13px; color: #fff; background: rgba(255, 60, 60, 0.9); padding: 12px; border-radius: 6px; border: 1px solid #ff7a7a; min-width: 220px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
          <div style="font-weight: bold; font-size: 14px; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.3); padding-bottom: 6px;">
            📰 실시간 뉴스 및 이슈
          </div>
          <div style="font-weight: 500; margin-bottom: 4px;">${object.title}</div>
          <div style="font-size: 12px; color: rgba(255,255,255,0.9); line-height: 1.4;">${object.description}</div>
          <div style="margin-top: 8px; font-size: 11px; color: rgba(255,255,255,0.6);">클릭하여 기사 보기</div>
        </div>
      `
    };
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

  if (object.stage === undefined || object.score === undefined) return null;
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
            ${hist.cause ? `<span style="color: rgba(255,255,255,0.8);">발생 원인:</span> <span style="font-weight: 500;">${hist.cause}</span>` : ''}
            ${hist.size ? `<span style="color: rgba(255,255,255,0.8);">규모:</span> <span style="font-weight: 500;">${hist.size}</span>` : ''}
            ${hist.count > 1 ? `<span style="color: rgba(255,255,255,0.8);">이 구역:</span> <span style="font-weight: 500;">총 ${hist.count}건 (최근 1건 표시)</span>` : ''}
          </div>
          <div style="opacity:.75;font-size:11px;margin-top:6px">${HISTORY_META ? '출처: 국토교통부 지하안전정보' : '출처: 언론 보도'}</div>
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

  const expEl = document.getElementById('sim-explanation');
  const expTextEl = document.getElementById('sim-exp-text');
  if (expEl && expTextEl) {
    expEl.style.display = 'block';
    if (scenario === 'calm') {
      expTextEl.innerHTML = LIVE_MODE_TEXT;
    } else if (scenario === 'heavy_rain') {
      expTextEl.innerHTML = '호우경보급 강수가 일부 자치구에 집중된 상황을 가정한 시뮬레이션으로, <b>시간 진행(재생)에 따른 지반 회복(감쇠) 과정</b>을 보여줍니다.';
    } else if (scenario === 'extreme') {
      expTextEl.innerHTML = '극한호우 및 지하수위 급락이 동시에 발생한 상황을 가정한 시뮬레이션입니다. <b>시간 진행(재생)에 따른 감쇠 과정</b>을 보여줍니다.';
    } else if (scenario === 'historical_flood_2022') {
      expTextEl.innerHTML = '2022년 8월 8일 동작구 및 강남 일대에 내린 기록적인 폭우 상황을 재현한 시뮬레이션입니다. <b>시간 진행(재생)에 따른 감쇠 과정</b>을 보여줍니다.';
    }
  }

  try {
    setLoading(`${scenario} 시나리오 로드 중…`);
    const snapData = await fetchJSON(`data/snapshot_${scenario}.json?t=${Date.now()}`);
    applySnapshot(snapData);
    updateDeckGLLayer();
    updateHeader(SNAP_META, SNAP_CELLS);
    updateSourceStatus(SNAP_META.source_status, SNAP_META.source_detail);
    hideLoading();
  } catch (err) {
    console.warn(`[시나리오 전환] 실패`, err);
    hideLoading();
  }
}

let ORIGINAL_RAW_CELLS = {};

function applySnapshot(snapData) {
  SNAP_META = {
    generated_at: snapData.generated_at,
    mode: snapData.mode,
    source_status: snapData.source_status,
    source_detail: snapData.source_detail || {},
    sewer: snapData.sewer || null
  };
  lastGeneratedAt = snapData.generated_at;

  for (const c of snapData.cells) {
    SNAP_CELLS[c.id] = c;
    ORIGINAL_RAW_CELLS[c.id] = { b: c.b, r: c.r, g: c.g, t: c.t, gs: c.gs ?? 0 };
    
    // 스냅샷 값을 그대로 시뮬레이션 초기값으로 사용한다.
    // (이전 버전의 브라우저 측 무작위 노이즈는 Python 결과와의 일치를 깨뜨려 제거함)
    SIM_CELLS[c.id] = {
      b: c.b,
      r_raw: c.r,
      g_raw: c.g,
      t_raw: c.t,
      gs_raw: c.gs ?? 0,
      ai_anomaly: c.ai_anomaly
    };
  }
}

// ── 기능 2: 스냅샷 자동 확인 (매 60초, 서버 갱신 주기는 workflow cron 참조) ──────────────────────────────────

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
      updateSourceStatus(SNAP_META.source_status, SNAP_META.source_detail);
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
    
    // 기저점수 B는 Python(build_baseline.py)이 계산한 값을 그대로 쓴다.
    // (이전 버전의 브라우저 전용 가산 — 과거 이력 +20, 관로 인접 +10 — 은
    //  Python 계산과 불일치하고 가상 데이터에 의존해 제거함)
    const adjustedSim = sim;
    const res = SinkholeEngine.computeAll(adjustedSim, elapsedH, GRID_CFG, WEIGHTS_CFG);
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
  
  // 초기화: 스냅샷 원래 값으로 되돌린다 (무작위 노이즈 없음 → 매번 같은 결과)
  for (const idStr of Object.keys(SIM_CELLS)) {
    const id = +idStr;
    const orig = ORIGINAL_RAW_CELLS[id];
    if (!orig) continue;
    SIM_CELLS[id] = { b: orig.b, r_raw: orig.r, g_raw: orig.g, t_raw: orig.t, gs_raw: orig.gs };
  }
  
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
  // 'real' 모드라도 채널이 실제 API(ok)가 아니면 '샘플 데이터'로 표시한다.
  const anyLive = Object.values(meta.source_status || {}).some(v => v === 'ok');
  const label = meta.mode === 'real' ? (anyLive ? '실시간' : '샘플 데이터') : '시뮬레이션';
  modeEl.textContent = label;
  modeEl.style.color = label === '실시간' ? '#2ea043' : '#58a6ff';
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

const LIVE_MODE_TEXT = '실시간 모드입니다. <b>강수는 기상청 AWS 실시간 관측</b>, <b>교통은 서울 실시간 도시데이터 도로소통</b>(주요 장소 주변, 30분 주기), <b>지하수위는 국가지하수측정망 시간자료</b>(서울 주변 관측정, 30분 주기)를 사용합니다. 연동에 실패한 채널은 샘플 데이터로 대체되며, 아래 데이터 소스 표시에서 실제 상태를 확인할 수 있습니다 (마우스를 올리면 상세 출처 표시).';

const SOURCE_STATUS_LABEL = {
  ok: '실시간',
  fixture: '샘플 데이터',
  sim: '시뮬레이션',
  no_data: '데이터 없음',
  unknown: '확인 중',
};

function updateSourceStatus(status, detail) {
  for (const [key, short] of [['rain','rain'],['groundwater','gw'],['traffic','tr']]) {
    const st = (status || {})[key] || 'unknown';
    document.getElementById('dot-' + short).className = 'src-dot ' + (st === 'ok' ? 'ok' : st.startsWith('error') ? 'err' : 'unknown');
    const el = document.getElementById('st-' + short);
    el.textContent = SOURCE_STATUS_LABEL[st] || st;
    el.title = ((detail || {})[key]) || '';   // 상세 출처 (예: AWS 매분자료, 관측소 N곳)
  }
}

// 범례의 단계 기준값을 weights.yaml에서 읽어 표시한다 (화면 문구와 계산 기준 불일치 방지).
function updateStageLegend(cfg) {
  const st = (cfg || {}).stages || {};
  const set = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  if (st.stage1) set('cond-s1', `B≥${st.stage1.b_min}`);
  if (st.stage2) set('cond-s2', `+R≥${st.stage2.r_min}`);
  if (st.stage3) set('cond-s3', `+G≥${st.stage3.g_min}`);
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
  
  if (info.layer.id === 'sewer-gu-layer') {
    const p = info.object.properties;
    selectedGridInfo = { type: 'pipe', name: p.gu, ptype: 'sewer' };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>${p.gu}</b> (노후 하수관·실시간 수위)`;
  } else if (info.layer.id === 'subway-layer' || info.layer.id === 'pipe-layer') {
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
  } else if (info.layer.id === 'ai-anomaly-layer') {
    const { id, gu, score, stage } = info.object;
    selectedGridInfo = { type: 'ai', id, gu, score, stage };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>${gu || '특정 지역'}</b> (AI 예측 이상탐지 발생!)`;
  } else if (info.layer.id === 'history-layer') {
    const histInfo = info.object.info;
    selectedGridInfo = { type: 'history', location: histInfo.location, date: histInfo.date };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>과거 싱크홀 발생 지역</b>: ${histInfo.location}`;
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
최근 ${selectedGridInfo.name} 일대 노후 하수관 및 하수관로 수위 상황을 고려할 때 지반 침하에 주의가 필요합니다.
해당 구간 통행 시 우회해 주시고 지반 이상 징후 발견 시 120으로 즉시 신고 바랍니다.`;
  } else if (selectedGridInfo.type === 'ai') {
    draftText = `[긴급재난문자]
AI 예측 시스템 분석 결과, ${selectedGridInfo.gu || '해당 지역'}에서 지하수위의 비정상적 변동 등 심각한 싱크홀 징후가 감지되었습니다.
주민 여러분께서는 신속히 안전한 곳으로 대피하시고, 지하차도 및 이면도로 진입을 전면 통제합니다.`;
  } else if (selectedGridInfo.type === 'complaint') {
    draftText = `[긴급안내문자]
인근 지역에 '${selectedGridInfo.name}' 민원이 다수 접수되어 지반 침하 및 포트홀 위험이 있습니다.
사고 예방을 위해 해당 도로 진입을 자제해 주시기 바랍니다.`;
  } else if (selectedGridInfo.type === 'history') {
    draftText = `[안전안내문자]
과거 싱크홀 발생 이력이 있는 집중 관리 구간(${selectedGridInfo.location}) 입니다.
현재 지하수위 등 이상 징후가 감지되고 있으니, 가급적 우회하시기 바랍니다.`;
  } else if (selectedGridInfo.type === 'dong') {
    if (selectedGridInfo.count >= 3) {
      draftText = `[안전안내문자]\n최근 ${selectedGridInfo.name} 일대에 지반 침하 이력이 다수 보고되었습니다.\n인근 차량 우회 및 보행자 안전에 유의하시고, 도로 갈라짐 발견 시 120으로 즉시 신고 바랍니다.`;
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
      
      // 타이핑 완료 후 수정 가능하도록 변경
      outputEl.contentEditable = "true";
      outputEl.style.outline = "none";
      outputEl.style.borderColor = "#a371f7";
      outputEl.style.cursor = "text";
      outputEl.title = "클릭하여 문안을 수정할 수 있습니다.";
      
      // 사용자 안내 문구 추가
      if (!document.getElementById('edit-hint')) {
        const hint = document.createElement('div');
        hint.id = 'edit-hint';
        hint.style.fontSize = '0.7rem';
        hint.style.color = '#8b949e';
        hint.style.marginTop = '-5px';
        hint.style.marginBottom = '10px';
        hint.style.textAlign = 'right';
        hint.innerText = '* 텍스트를 클릭하여 내용을 직접 수정할 수 있습니다.';
        outputEl.parentNode.insertBefore(hint, outputEl.nextSibling);
      }
    }
  }, 30);
}

function approveLlmDraft() {
  // 사용자가 수정한 텍스트 가져오기
  const outputEl = document.getElementById('llm-output');
  const finalMessage = outputEl.innerText || outputEl.textContent;

  // 브라우저 기본 alert 대신 커스텀 토스트 알림 띄우기
  const toast = document.getElementById('custom-toast');
  if (toast) {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(-50%) translateY(0)';
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(-50%) translateY(-50px)';
    }, 3000);
  }
  
  closeLlmPanel();
  
  // 가상 핸드폰 화면에 텍스트 넣기
  const phonePopup = document.getElementById('phone-popup');
  const phoneText = document.getElementById('phone-message-text');
  const alertBox = document.getElementById('phone-alert-box');
  const phoneTime = document.getElementById('phone-time');
  
  if (phonePopup && phoneText) {
    phoneText.textContent = finalMessage;
    
    // 현재 시간 표시
    const now = new Date();
    phoneTime.textContent = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');
    
    // UI 표시 및 애니메이션
    phonePopup.style.display = 'flex';
    setTimeout(() => {
      alertBox.style.opacity = '1';
      alertBox.style.transform = 'translateY(20px)';
    }, 100);
  }
}

// ── 뉴스 피드 렌더링 ──────────────────────────────────────────────────
function renderNewsFeed() {
  const container = document.getElementById('news-feed-list');
  if (!container) return;

  if (!NEWS_ISSUES || NEWS_ISSUES.length === 0) {
    container.innerHTML = `<div style="text-align: center; color: #8b949e; padding: 10px;">관련 뉴스가 없습니다.</div>`;
    return;
  }

  let html = '';
  NEWS_ISSUES.forEach(item => {
    html += `
      <div style="background: #0d1117; padding: 10px; border-radius: 6px; border: 1px solid #30363d;">
        <a href="${item.link}" target="_blank" style="color: #58a6ff; font-weight: bold; text-decoration: none; display: block; margin-bottom: 4px;">${item.title}</a>
        <div style="color: #8b949e; font-size: 0.75rem; line-height: 1.4;">${item.description}</div>
      </div>
    `;
  });
  container.innerHTML = html;
}
