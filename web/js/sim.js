/**
 * sim.js — 브라우저 내 시뮬레이션 엔진 (Phase 4)
 *
 * Python fusion/decay.py · fusion/scoring.py 를 JS로 이식.
 * 수용 기준 4번: 동일 입력·동일 시각에서 Python 결과와 점수 차이 0.01 미만.
 */

const SinkholeEngine = (() => {
  'use strict';

  function decayFactor(elapsedH, cfg) {
    const d = cfg.decay;
    const plateau  = d.plateau_hours;
    const tail     = d.tail_hours;
    const residual = d.residual_at_tail;
    const k = Math.log(residual) / (tail - plateau);
    if (elapsedH <= plateau) return 1.0;
    if (elapsedH <= tail)    return Math.exp(k * (elapsedH - plateau));
    return 0.0;
  }

  function applyDecay(score, elapsedH, cfg) {
    return score * decayFactor(elapsedH, cfg);
  }

  function computeR(r1, r3, r12, cfg) {
    const thresholds = cfg.realtime.rain.thresholds;
    let score = 0;
    for (const tier of thresholds) {
      const anyList = (tier.conditions || {}).any || [];
      let tierMet = false;
      for (const cond of anyList) {
        if (cond.all) {
          if (cond.all.every(sub => _checkRain(sub, r1, r3, r12))) { tierMet = true; break; }
        } else {
          if (_checkRain(cond, r1, r3, r12)) { tierMet = true; break; }
        }
      }
      if (tierMet) score = tier.score;
    }
    return score;
  }

  function _checkRain(cond, r1, r3, r12) {
    const val = cond.window_h === 1 ? r1 : cond.window_h === 3 ? r3 : r12;
    return val >= cond.mm;
  }

  function computeG(sigma, r, cfg) {
    const gc = cfg.realtime.groundwater;
    if (r < gc.min_rain_for_g) return 0;
    const drop = -sigma;
    if (drop >= 2.0) return gc.sigma2_score;
    if (drop >= 1.0) return gc.sigma1_score;
    return 0;
  }

  function computeT(deg, cfg) {
    return Math.min(Math.max(deg * cfg.realtime.traffic.max, 0), cfg.realtime.traffic.max);
  }

  function computeStage(b, r, g, cfg) {
    const bMin = cfg.stages.stage1.b_min;
    const rMin = cfg.stages.stage2.r_min;
    const gMin = cfg.stages.stage3.g_min;
    if (b >= bMin && r >= rMin && g >= gMin) return 3;
    if (b >= bMin && r >= rMin) return 2;
    return 1;
  }

  function computeAll(cell, elapsedH, cfg) {
    const factor = decayFactor(elapsedH, cfg);
    const r = cell.r_raw * factor;
    const g = cell.g_raw * factor;
    const t = cell.t_raw * factor;
    const score = Math.min(cell.b + r + g + t, 100);
    return { score, stage: computeStage(cell.b, r, g, cfg), r, g, t, b: cell.b };
  }

  function validateParity(cases, gridCfg, weightsCfg) {
    return cases.map(c => {
      const factor = decayFactor(c.elapsed_h, gridCfg);
      const r = c.r_raw * factor;
      const g = c.g_raw * factor;
      const t = c.t_raw * factor;
      const score = Math.min(c.b + r + g + t, 100);
      const stage = computeStage(c.b, r, g, weightsCfg);
      const scoreDiff = Math.abs(score - c.score);
      return {
        case: c.case, elapsed_h: c.elapsed_h,
        py_score: c.score, js_score: Math.round(score * 1e6) / 1e6,
        score_diff: Math.round(scoreDiff * 1e6) / 1e6,
        py_stage: c.stage, js_stage: stage,
        ok: scoreDiff < 0.01 && stage === c.stage,
      };
    });
  }

  return { decayFactor, applyDecay, computeR, computeG, computeT, computeStage, computeAll, validateParity };
})();
