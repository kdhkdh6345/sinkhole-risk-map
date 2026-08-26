import sys

with open('web/js/render.js', 'r') as f:
    code = f.read()

old_layers_def = """let activeLayers = {
  nationwide: false,
  dong: true,
  pipes: true,
  complaints: true,
  points: false
};"""
new_layers_def = """let activeLayers = {
  nationwide: false,
  grid: true,
  dong: true,
  pipes: true,
  complaints: true,
  points: false
};"""
code = code.replace(old_layers_def, new_layers_def)

old_toggle = """window.toggleLayers = () => {
  activeLayers.nationwide = document.getElementById('chk-layer-nationwide').checked;
  activeLayers.dong = document.getElementById('chk-layer-dong').checked;
  activeLayers.pipes = document.getElementById('chk-layer-pipes').checked;
  activeLayers.complaints = document.getElementById('chk-layer-complaints').checked;
  activeLayers.points = document.getElementById('chk-layer-points').checked;"""
new_toggle = """window.toggleLayers = () => {
  activeLayers.nationwide = document.getElementById('chk-layer-nationwide').checked;
  activeLayers.grid = document.getElementById('chk-layer-grid').checked;
  activeLayers.dong = document.getElementById('chk-layer-dong').checked;
  activeLayers.pipes = document.getElementById('chk-layer-pipes').checked;
  activeLayers.complaints = document.getElementById('chk-layer-complaints').checked;
  activeLayers.points = document.getElementById('chk-layer-points').checked;"""
code = code.replace(old_toggle, new_toggle)

old_grid_push = """  // 3D 큐브와 동별 맵이 모두 공존할 수 있도록 항상 표시 (또는 토글 추가 가능)
  layers.push(layer);"""
new_grid_push = """  if (activeLayers.grid) {
    layers.push(layer);
  }"""
code = code.replace(old_grid_push, new_grid_push)

with open('web/js/render.js', 'w') as f:
    f.write(code)

print("Grid patch applied.")
