/**
 * run_parity.js — Python ↔ JS 엔진 일치 검증 (Phase 4 수용 기준 4번)
 *
 * 실행:  node tests/run_parity.js
 * 기준값: tests/fixtures/parity.json (python scripts/build_parity.py 가 생성)
 * 설정:   web/data/weights_cfg.json, web/data/grid_cfg.json (scripts/export_config.py 가 생성)
 *
 * 하나라도 불일치하면 종료 코드 1을 반환한다 (CI에서 실패 처리).
 */
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const SinkholeEngine = require(path.join(root, 'web', 'js', 'sim.js'));

const readJSON = (p) => JSON.parse(fs.readFileSync(path.join(root, p), 'utf8'));
const weightsCfg = readJSON('web/data/weights_cfg.json');
const gridCfg = readJSON('web/data/grid_cfg.json');
const parity = readJSON('tests/fixtures/parity.json');

const results = SinkholeEngine.validateParity(parity.cases, gridCfg, weightsCfg);
let failed = 0;
for (const r of results) {
  if (!r.ok) {
    failed++;
    console.log(`❌ ${r.case} @${r.elapsed_h}h  py=${r.py_score} js=${r.js_score} ` +
                `stage py=${r.py_stage} js=${r.js_stage} anomaly py=${r.py_anomaly} js=${r.js_anomaly}`);
  }
}
console.log(`\nParity: ${results.length - failed}/${results.length} 통과`);
process.exit(failed === 0 ? 0 : 1);
