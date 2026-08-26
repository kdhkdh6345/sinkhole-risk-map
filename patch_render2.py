import sys
import re

with open('web/js/render.js', 'r') as f:
    code = f.read()

# Replace toggleHistory
old_toggle = """window.toggleHistory = () => {
  const radio = document.querySelector('input[name="history_mode"]:checked');
  historyMode = radio ? radio.value : 'off';
  updateDeckGLLayer();
};"""
new_toggle = """window.toggleLayers = () => {
  activeLayers.nationwide = document.getElementById('chk-layer-nationwide').checked;
  activeLayers.dong = document.getElementById('chk-layer-dong').checked;
  activeLayers.pipes = document.getElementById('chk-layer-pipes').checked;
  activeLayers.complaints = document.getElementById('chk-layer-complaints').checked;
  activeLayers.points = document.getElementById('chk-layer-points').checked;
  historyMode = activeLayers.points ? 'points' : 'off';
  updateDeckGLLayer();
};"""
code = code.replace(old_toggle, new_toggle)

# Inject layers
layer_push_hook = "  DECK.setProps({ layers: layers });"
new_layers = """
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
"""
code = code.replace(layer_push_hook, new_layers)

# Tooltip logic
tooltip_hook = "  if (layer && layer.id === 'dong-geojson-layer') {"
tooltip_logic = """  if (layer && layer.id === 'pipes-layer') {
    return { html: `<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">📍 ${object.properties.name} (${object.properties.type})</div>` };
  }
  if (layer && layer.id === 'complaints-layer') {
    return { html: `<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">⚠️ 민원 접수: ${object.type}<br>긴급도: ${object.urgency}단계</div>` };
  }
  if (layer && layer.id === 'dong-geojson-layer') {"""
code = code.replace(tooltip_hook, tooltip_logic)

# Grid push condition
code = code.replace(
    "  if (historyMode !== 'dong') {\n    layers.push(layer);\n  }",
    "  // 3D 큐브와 동별 맵이 모두 공존할 수 있도록 항상 표시 (또는 토글 추가 가능)\n  layers.push(layer);"
)

code = code.replace(
    "  if (historyMode === 'dong' && DONG_GEOJSON) {",
    "  if (activeLayers.dong && DONG_GEOJSON) {"
)

# Also update handleGridClick to handle pipes and complaints for the LLM
click_hook = "  if (info.layer.id === 'dong-geojson-layer') {"
click_logic = """  if (info.layer.id === 'pipes-layer') {
    selectedGridInfo = { type: 'pipe', name: info.object.properties.name, ptype: info.object.properties.type };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>${selectedGridInfo.name}</b> (노후도/안전 등급 분석)`;
  } else if (info.layer.id === 'complaints-layer') {
    selectedGridInfo = { type: 'complaint', name: info.object.type, urgency: info.object.urgency };
    document.getElementById('llm-target-info').innerHTML = `📍 <b>주민 민원</b>: ${selectedGridInfo.name} (긴급도 ${selectedGridInfo.urgency})`;
  } else if (info.layer.id === 'dong-geojson-layer') {"""
code = code.replace(click_hook, click_logic)

# Draft generation logic for new types
draft_hook = "  if (selectedGridInfo.type === 'dong') {"
draft_logic = """  if (selectedGridInfo.type === 'pipe') {
    draftText = `[안전안내문자]\n최근 ${selectedGridInfo.name} 주변 노후 인프라(관로/지하철)에서 지반 침하 위험이 분석되었습니다.\n해당 구간 통행 시 우회해 주시고 지반 이상 징후 발견 시 120으로 즉시 신고 바랍니다.`;
  } else if (selectedGridInfo.type === 'complaint') {
    draftText = `[긴급안내문자]\n인근 지역에 '${selectedGridInfo.name}' 민원이 다수 접수되어 지반 침하 및 포트홀 위험이 있습니다.\n사고 예방을 위해 해당 도로 진입을 자제해 주시기 바랍니다.`;
  } else if (selectedGridInfo.type === 'dong') {"""
code = code.replace(draft_hook, draft_logic)


with open('web/js/render.js', 'w') as f:
    f.write(code)
print("Patched render.js successfully!")
