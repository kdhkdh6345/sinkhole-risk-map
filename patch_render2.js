const fs = require('fs');
let code = fs.readFileSync('web/js/render.js', 'utf8');

// Replace old toggleHistory with toggleLayers
code = code.replace(
  "window.toggleHistory = () => {\n  const radio = document.querySelector('input[name=\"history_mode\"]:checked');\n  historyMode = radio ? radio.value : 'off';\n  updateDeckGLLayer();\n};",
  `window.toggleLayers = () => {
  activeLayers.nationwide = document.getElementById('chk-layer-nationwide').checked;
  activeLayers.dong = document.getElementById('chk-layer-dong').checked;
  activeLayers.pipes = document.getElementById('chk-layer-pipes').checked;
  activeLayers.complaints = document.getElementById('chk-layer-complaints').checked;
  activeLayers.points = document.getElementById('chk-layer-points').checked;
  
  // Backward compatibility for existing historyMode usages in grid layer
  historyMode = activeLayers.points ? 'points' : 'off';
  
  updateDeckGLLayer();
};`
);

// We need to inject the layers into the layers array inside updateDeckGLLayer()
const layerPushHook = "  DECK.setProps({ layers: layers });";
const newLayersLogic = `
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
      pickable: true
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
      pickable: true
    }));
  }

  DECK.setProps({ layers: layers });
`;
code = code.replace(layerPushHook, newLayersLogic);

// We also need to fix the tooltip logic
const tooltipHook = "  if (layer && layer.id === 'dong-geojson-layer') {";
const tooltipLogic = `  if (layer && layer.id === 'pipes-layer') {
    return { html: \`<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">📍 \${object.properties.name} (\${object.properties.type})</div>\` };
  }
  if (layer && layer.id === 'complaints-layer') {
    return { html: \`<div style="padding: 10px; background: rgba(0,0,0,0.8); color: white; border-radius: 4px;">⚠️ 민원 접수: \${object.type}<br>긴급도: \${object.urgency}단계</div>\` };
  }
  if (layer && layer.id === 'dong-geojson-layer') {`;
code = code.replace(tooltipHook, tooltipLogic);

// Wait, I should also update `if (historyMode !== 'dong')` for grid rendering
code = code.replace(
  "  if (historyMode !== 'dong') {\n    layers.push(layer);\n  }",
  "  if (true) {\n    layers.push(layer);\n  }"
);
code = code.replace(
  "  if (historyMode === 'dong' && DONG_GEOJSON) {",
  "  if (activeLayers.dong && DONG_GEOJSON) {"
);

fs.writeFileSync('web/js/render.js', code);
