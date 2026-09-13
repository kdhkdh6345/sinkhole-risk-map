import sys

with open('web/js/render.js', 'r') as f:
    code = f.read()

old_decay = """function applySimDecay(elapsedH) {
  for (const [idStr, snap] of Object.entries(SNAP_CELLS)) {
    const id = +idStr, sim = SIM_CELLS[id];
    if (!sim) continue;
    const res = SinkholeEngine.computeAll(sim, elapsedH, GRID_CFG, WEIGHTS_CFG);
    SNAP_CELLS[id] = { ...snap, ...res, stage: res.stage };
  }
  updateDeckGLLayer();
  updateCounters(SNAP_CELLS);
}"""

new_decay = """function applySimDecay(elapsedH) {
  for (const [idStr, snap] of Object.entries(SNAP_CELLS)) {
    const id = +idStr, sim = SIM_CELLS[id];
    if (!sim) continue;
    
    // 과거 사고 이력이 있으면 기저 위험도(b)에 페널티(+20)를 줌
    let adjustedSim = { ...sim };
    if (HISTORY_DATA[id]) {
      adjustedSim.b = Math.min(adjustedSim.b + 20, 100);
    }
    
    const res = SinkholeEngine.computeAll(adjustedSim, elapsedH, GRID_CFG, WEIGHTS_CFG);
    SNAP_CELLS[id] = { ...snap, ...res, stage: res.stage };
  }
  updateDeckGLLayer();
  updateCounters(SNAP_CELLS);
}"""

code = code.replace(old_decay, new_decay)

with open('web/js/render.js', 'w') as f:
    f.write(code)

print("History risk patched in render.js")
