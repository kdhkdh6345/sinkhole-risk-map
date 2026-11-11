"""
build_parity.py — Python ↔ JS 일치 검증용 기준 케이스 생성 (Phase 4 수용 기준 4번)

실행:
    python scripts/build_parity.py           # 케이스 재생성 (설정 변경 후 반드시 실행)
    python scripts/build_parity.py --check   # 저장된 케이스가 현재 Python 엔진과 일치하는지 확인

산출물:
    tests/fixtures/parity.json   — node tests/run_parity.js 가 사용
    web/data/parity.json         — web/test_parity.html 이 사용

기대값(score/unc/stage/ai_anomaly)은 전부 Python 엔진 함수로 계산한다.
JS 엔진(web/js/sim.js)이 같은 입력에서 같은 값을 내는지는 run_parity.js가 검증한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sinkhole.fusion.bayes import bayesian_fuse  # noqa: E402
from sinkhole.fusion.decay import decay_factor  # noqa: E402
from sinkhole.fusion.scoring import compute_stages  # noqa: E402

OUT_PATHS = [
    PROJECT_ROOT / "tests" / "fixtures" / "parity.json",
    PROJECT_ROOT / "web" / "data" / "parity.json",
]

# 입력 케이스: (이름, b, r_raw, g_raw, t_raw, gs_raw)
INPUTS = [
    ("calm_grid",   15.0,  0.0,  0.0, 3.0,  0.0),
    ("stage2_grid", 15.0, 20.0,  0.0, 3.0, -0.5),
    ("stage3_grid", 15.0, 25.0, 10.0, 3.0, -3.2),
    ("low_b_rain",   6.0, 25.0, 10.0, 4.5, -3.0),
]
ELAPSED_H = [0.0, 1.0, 6.0, 24.0, 48.0, 72.0, 96.0, 100.0]


def _load_cfg() -> tuple[dict, dict]:
    with open(PROJECT_ROOT / "config" / "weights.yaml", encoding="utf-8") as f:
        weights = yaml.safe_load(f)
    with open(PROJECT_ROOT / "config" / "grid.yaml", encoding="utf-8") as f:
        grid = yaml.safe_load(f)
    return weights, grid


def build_cases() -> dict:
    """현재 설정과 Python 엔진으로 기준 케이스를 계산한다."""
    weights, grid = _load_cfg()
    variances = (weights.get("fusion") or {}).get("variances")
    thr = float((weights.get("anomaly") or {}).get("sigma_threshold", 2.5))

    cases = []
    for name, b, r_raw, g_raw, t_raw, gs_raw in INPUTS:
        for h in ELAPSED_H:
            f = float(decay_factor(np.array([h]), grid)[0])
            r, g, t = r_raw * f, g_raw * f, t_raw * f
            score, unc = bayesian_fuse(
                np.array([b]), np.array([r]), np.array([g]), np.array([t]), variances
            )
            stage = int(compute_stages(np.array([b]), np.array([r]), np.array([g]), weights)[0])
            cases.append({
                "case": name,
                "elapsed_h": h,
                "b": b, "r_raw": r_raw, "g_raw": g_raw, "t_raw": t_raw, "gs_raw": gs_raw,
                "decay_factor": round(f, 6),
                "score": round(float(score[0]), 6),
                "unc": round(float(unc[0]), 6),
                "stage": stage,
                "ai_anomaly": bool(abs(gs_raw * f) > thr),
            })

    return {
        "description": "Python-JS 일치 검증용 고정 케이스 (scripts/build_parity.py가 생성, 수작업 편집 금지)",
        "decay": grid["decay"],
        "stages": weights["stages"],
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="저장된 케이스와 현재 엔진 결과 비교")
    args = parser.parse_args()

    data = build_cases()

    if args.check:
        ok = True
        for p in OUT_PATHS:
            if not p.exists():
                print(f"❌ 없음: {p}")
                ok = False
                continue
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
            if saved != data:
                print(f"❌ 불일치: {p} — 설정이나 엔진이 바뀌었으면 build_parity.py를 다시 실행하세요.")
                ok = False
            else:
                print(f"✅ 일치: {p} ({len(data['cases'])}개 케이스)")
        return 0 if ok else 1

    for p in OUT_PATHS:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"저장: {p} ({len(data['cases'])}개 케이스)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
