"""
tests/test_scoring.py — R/G/T 점수화 + 단계 판정 테스트 (Phase 3)

수용 기준 4번 검증:
  G >= 10이어도 R < 15이면 3단계로 격상되지 않는다.

수용 기준 1·2번 검증:
  calm 시나리오: Stage 3 격자 0개
  extreme 시나리오: Stage 3 격자 1개 이상

수용 기준 6번 검증:
  snapshot.json이 AGENTS.md 5.2절 스키마와 정확히 일치한다.

수용 기준 7번 검증:
  격자 2,400개 기준 1회 계산이 1초 미만이다.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pytest

from sinkhole.core.clock import AcceleratedClock
from sinkhole.core.field import GridRiskField
from sinkhole.fusion.scoring import (
    compute_g,
    compute_r,
    compute_stages,
    compute_t,
)
from sinkhole.sources.simulated import (
    SimulatedGroundwaterAdapter,
    SimulatedRainAdapter,
    SimulatedTrafficAdapter,
)

# weights.yaml과 동기화된 테스트용 cfg
WEIGHTS_CFG = {
    "realtime": {
        "rain": {
            "thresholds": [
                {
                    "score": 10,
                    "conditions": {
                        "any": [
                            {"window_h": 1, "mm": 20},
                            {"window_h": 3, "mm": 40},
                        ]
                    },
                },
                {
                    "score": 15,
                    "conditions": {
                        "any": [
                            {"window_h": 3, "mm": 60},
                            {"window_h": 12, "mm": 110},
                        ]
                    },
                },
                {
                    "score": 20,
                    "conditions": {
                        "any": [
                            {"window_h": 3, "mm": 90},
                            {"window_h": 12, "mm": 180},
                        ]
                    },
                },
                {
                    "score": 25,
                    "conditions": {
                        "any": [
                            {"all": [{"window_h": 1, "mm": 50}, {"window_h": 3, "mm": 90}]},
                            {"window_h": 1, "mm": 72},
                        ]
                    },
                },
            ]
        },
        "groundwater": {
            "min_rain_for_g": 15,
            "sigma1_score": 5,
            "sigma2_score": 10,
        },
        "traffic": {"max": 5},
    },
    "stages": {
        "stage1": {"b_min": 10},
        "stage2": {"r_min": 15},
        "stage3": {"g_min": 10},
    },
}


# ── compute_r 단위 테스트 ───────────────────────────────────────────────────

def test_compute_r_zero():
    """강수 없음 → R = 0."""
    rain = np.zeros((5, 3))
    r = compute_r(rain, WEIGHTS_CFG)
    assert np.all(r == 0.0)


def test_compute_r_tier_precaution():
    """3h=42mm → R = 10 (사전주의 기준 40mm 초과)."""
    rain = np.array([[0.0, 42.0, 0.0]])
    r = compute_r(rain, WEIGHTS_CFG)
    assert r[0] == 10.0


def test_compute_r_tier_warning():
    """3h=92mm → R = 20 (호우경보 기준 90mm 초과)."""
    rain = np.array([[0.0, 92.0, 0.0]])
    r = compute_r(rain, WEIGHTS_CFG)
    assert r[0] == 20.0


def test_compute_r_tier_extreme():
    """1h=75mm → R = 25 (극한호우 기준 72mm 초과)."""
    rain = np.array([[75.0, 95.0, 185.0]])
    r = compute_r(rain, WEIGHTS_CFG)
    assert r[0] == 25.0


def test_compute_r_highest_tier_wins():
    """여러 기준 동시 만족 시 가장 높은 점수 적용."""
    # 3h=92mm(tier20), 1h=75mm(tier25) 동시
    rain = np.array([[75.0, 92.0, 185.0]])
    r = compute_r(rain, WEIGHTS_CFG)
    assert r[0] == 25.0


# ── compute_g 단위 테스트 ───────────────────────────────────────────────────

def test_compute_g_zero_when_r_low():
    """수용 기준 4번: R < 15이면 G >= 10이어도 G 점수 = 0."""
    sigma = np.array([-2.1])   # 2σ 급락
    r = np.array([14.9])       # R = 14.9 < 15
    g = compute_g(sigma, r, consecutive_valid=True, cfg=WEIGHTS_CFG)
    assert g[0] == 0.0, f"R < 15에서 G = {g[0]}, 기대 = 0"


def test_compute_g_sigma2_with_r():
    """R >= 15 AND 2σ 급락 AND 연속 유효 → G = 10."""
    sigma = np.array([-2.1])
    r = np.array([20.0])
    g = compute_g(sigma, r, consecutive_valid=True, cfg=WEIGHTS_CFG)
    assert g[0] == 10.0


def test_compute_g_sigma1_with_r():
    """R >= 15 AND 1σ 급락 AND 연속 유효 → G = 5."""
    sigma = np.array([-1.2])
    r = np.array([15.0])
    g = compute_g(sigma, r, consecutive_valid=True, cfg=WEIGHTS_CFG)
    assert g[0] == 5.0


def test_compute_g_no_consecutive():
    """연속 관측 불충족 → G = 0 (2회 연속 조건)."""
    sigma = np.array([-2.5])
    r = np.array([20.0])
    g = compute_g(sigma, r, consecutive_valid=False, cfg=WEIGHTS_CFG)
    assert g[0] == 0.0


# ── compute_stages 단위 테스트 ─────────────────────────────────────────────

def test_stage1_requires_b():
    """B < b_min이면 R/G 어떤 값이어도 Stage 1 (R/G 격상 없음)."""
    b = np.array([5.0])      # b_min=10 미만
    r = np.array([25.0])     # 극한호우
    g = np.array([10.0])     # 2σ 급락
    stages = compute_stages(b, r, g, WEIGHTS_CFG)
    assert stages[0] == 1, f"B < b_min에서 Stage = {stages[0]}, 기대 = 1"


def test_stage2_requires_b_and_r():
    """B >= b_min AND R >= r_min → Stage 2."""
    b = np.array([15.0])
    r = np.array([15.0])
    g = np.array([0.0])
    stages = compute_stages(b, r, g, WEIGHTS_CFG)
    assert stages[0] == 2


def test_stage3_requires_all():
    """B >= b_min AND R >= r_min AND G >= g_min → Stage 3."""
    b = np.array([15.0])
    r = np.array([15.0])
    g = np.array([10.0])
    stages = compute_stages(b, r, g, WEIGHTS_CFG)
    assert stages[0] == 3


def test_stage3_blocked_when_r_low():
    """수용 기준 4번: G >= g_min이어도 R < r_min이면 Stage 3 불가."""
    b = np.array([15.0])
    r = np.array([14.9])     # R < r_min
    g = np.array([10.0])     # G >= g_min
    stages = compute_stages(b, r, g, WEIGHTS_CFG)
    assert stages[0] < 3, (
        f"R < r_min에서 Stage = {stages[0]}, 기대 < 3 (수용 기준 4번)"
    )


# ── 시나리오 통합 테스트 ────────────────────────────────────────────────────

def _make_field_from_grid_parquet() -> GridRiskField | None:
    """실제 grid.parquet + baseline.npy를 사용하는 통합 테스트용 Field."""
    from pathlib import Path
    import yaml

    proj = Path(__file__).resolve().parents[1]
    parquet = proj / "data" / "grid.parquet"
    baseline_npy = proj / "data" / "baseline.npy"

    if not parquet.exists() or not baseline_npy.exists():
        return None  # Phase 1/2 미실행 환경에서는 스킵

    grid_df = pd.read_parquet(parquet)
    baseline = np.load(baseline_npy)
    clock = AcceleratedClock(speed=1.0)
    return GridRiskField(grid_df=grid_df, baseline=baseline, clock=clock)


@pytest.mark.parametrize("scenario,expected_stage3", [
    ("calm", 0),
    ("extreme", 1),  # 1 이상
])
def test_scenario_stage3_count(scenario: str, expected_stage3: int):
    """수용 기준 1·2번: calm=Stage3 없음, extreme=Stage3 1개 이상."""
    field = _make_field_from_grid_parquet()
    if field is None:
        pytest.skip("grid.parquet 또는 baseline.npy 없음 (build_grid/build_baseline 먼저 실행)")

    field.update(
        SimulatedRainAdapter(scenario),
        SimulatedGroundwaterAdapter(scenario),
        SimulatedTrafficAdapter(),
    )
    snap = field.snapshot(mode="sim")
    stage3_count = sum(1 for c in snap["cells"] if c["stage"] == 3)

    if expected_stage3 == 0:
        assert stage3_count == 0, f"{scenario}: Stage3 {stage3_count}개, 기대=0"
    else:
        assert stage3_count >= 1, f"{scenario}: Stage3 없음, 기대=1개 이상"


def test_snapshot_schema():
    """수용 기준 6번: snapshot.json이 AGENTS.md 5.2절 스키마와 일치한다."""
    field = _make_field_from_grid_parquet()
    if field is None:
        pytest.skip("grid.parquet 없음")

    field.update(
        SimulatedRainAdapter("heavy_rain"),
        SimulatedGroundwaterAdapter("heavy_rain"),
        SimulatedTrafficAdapter(),
    )
    snap = field.snapshot(mode="sim")

    # 최상위 키
    assert "generated_at" in snap
    assert "mode" in snap
    assert "source_status" in snap
    assert "cells" in snap

    # source_status 키
    for ch in ("rain", "groundwater", "traffic"):
        assert ch in snap["source_status"]

    # cells 스키마
    required_cell_keys = {"id", "stage", "score", "b", "r", "g", "t", "unc"}
    for cell in snap["cells"]:
        missing = required_cell_keys - set(cell.keys())
        assert not missing, f"셀 {cell['id']}: 필드 누락 {missing}"
        assert cell["stage"] in (1, 2, 3), f"stage={cell['stage']} 범위 밖"
        assert 0.0 <= cell["score"] <= 100.0
        assert cell["unc"] is None  # Phase 6 이전: null

    # JSON 직렬화 가능 여부 확인
    json_str = json.dumps(snap, ensure_ascii=False)
    assert len(json_str) > 0


def test_performance_under_1s():
    """수용 기준 7번: 격자 2400개 기준 1회 계산 1초 미만."""
    n = 2430
    grid_df = pd.DataFrame({
        "id": list(range(n)),
        "lat": np.random.uniform(37.4, 37.7, n),
        "lon": np.random.uniform(126.8, 127.2, n),
        "gu": np.random.choice(["강남구", "종로구", "마포구", "은평구"], n),
    })
    baseline = np.random.uniform(5, 20, n)
    clock = AcceleratedClock(speed=1.0)
    field = GridRiskField(grid_df=grid_df, baseline=baseline, clock=clock)

    field.update(
        SimulatedRainAdapter("extreme"),
        SimulatedGroundwaterAdapter("extreme"),
        SimulatedTrafficAdapter(),
    )

    t0 = time.perf_counter()
    _ = field.snapshot()
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"스냅샷 계산 {elapsed*1000:.0f}ms (기준: 1000ms)"
    print(f"\n  스냅샷 계산: {elapsed*1000:.1f}ms (격자 {n}개)")
