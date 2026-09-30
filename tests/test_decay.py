"""
tests/test_decay.py — 감쇠 함수 + AcceleratedClock 통합 테스트 (Phase 3)

수용 기준 3번 검증:
  AcceleratedClock으로 96시간을 가속 경과시켰을 때,
  특정 격자의 r 값이 다음을 만족한다:
    0~96h: 지속 감쇠
    48h 시점: 최초값의 약 0.1배
    96h 시점: 최초값의 0.01배
    96h 초과: 0

수용 기준 5번 검증:
  프로세스 종료 후 재시작해도 state.npz에서 감쇠 진행 상태가 복원된다.
"""

from __future__ import annotations

import math
import time
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── 단위 테스트: decay 함수 직접 검증 ──────────────────────────────────────

from sinkhole.fusion.decay import apply_decay, decay_factor


GRID_CFG = {
    "decay": {
        "plateau_hours": 0,
        "tail_hours": 96,
        "residual_at_tail": 0.01,
    }
}


def test_plateau_factor():
    """0h 에는 감쇠 계수 = 1.0 (오차 1e-9)."""
    elapsed = np.array([0.0])
    f = decay_factor(elapsed, GRID_CFG)
    assert abs(f[0] - 1.0) < 1e-9, f"0h: factor={f[0]:.6f}, 기대=1.0"


def test_decay_at_48h():
    """48h 시점에서 감쇠 계수 = sqrt(0.01) = 0.1."""
    elapsed = np.array([48.0])
    f = decay_factor(elapsed, GRID_CFG)
    expected = math.sqrt(0.01)  # ≈ 0.1
    assert abs(f[0] - expected) < 0.002, f"48h factor={f[0]:.4f}, 기대≈{expected:.4f}"


def test_decay_at_96h():
    """96h 시점에서 감쇠 계수 = residual = 0.01."""
    elapsed = np.array([96.0])
    f = decay_factor(elapsed, GRID_CFG)
    assert abs(f[0] - 0.01) < 0.001, f"96h factor={f[0]:.4f}, 기대=0.01"


def test_zero_after_tail():
    """96h 초과 시 감쇠 계수 = 0.0."""
    for t in [96.001, 100.0, 120.0, 1000.0]:
        elapsed = np.array([t])
        f = decay_factor(elapsed, GRID_CFG)
        assert f[0] == 0.0, f"t={t}h: factor={f[0]:.6f}, 기대=0.0"


def test_apply_decay_vector():
    """apply_decay의 벡터 계산 결과를 직접 계산 결과와 비교."""
    scores = np.array([100.0, 100.0, 100.0])
    elapsed = np.array([0.0, 48.0, 96.0])

    result = apply_decay(scores, elapsed, GRID_CFG)

    assert abs(result[0] - 100.0) < 0.01   # 0h: 100%
    assert abs(result[1] - 10.0) < 0.2     # 48h: 10.0
    assert abs(result[2] - 1.0) < 0.1      # 96h: 1.0


def test_decay_monotone():
    """0h 이후 감쇠는 단조감소해야 한다."""
    t_points = np.arange(0.0, 96.1, 0.5)
    f = decay_factor(t_points, GRID_CFG)
    diffs = np.diff(f)
    assert np.all(diffs <= 1e-12), f"단조감소 위반 발견: {diffs[diffs > 0]}"


# ── 통합 테스트: AcceleratedClock + GridRiskField ─────────────────────────

from sinkhole.core.clock import AcceleratedClock
from sinkhole.core.field import GridRiskField
from sinkhole.core.store import save_state, load_state
from sinkhole.sources.simulated import (
    SimulatedGroundwaterAdapter,
    SimulatedRainAdapter,
    SimulatedTrafficAdapter,
)


def _make_tiny_grid(n: int = 5) -> pd.DataFrame:
    """테스트용 소형 격자 DataFrame (강남구 N개)."""
    return pd.DataFrame({
        "id": list(range(n)),
        "lat": [37.57] * n,
        "lon": [126.98] * n,
        "gu": ["강남구"] * n,
    })


def _make_field(clock, n: int = 5) -> GridRiskField:
    """테스트용 GridRiskField 생성."""
    grid_df = _make_tiny_grid(n)
    baseline = np.full(n, 15.0)  # b_min(10) 초과 → Stage 1 가능
    return GridRiskField(grid_df=grid_df, baseline=baseline, clock=clock)


def test_accelerated_clock_decay_curve():
    """수용 기준 3번: AcceleratedClock으로 가상 시각을 이동시켜 감쇠 곡선 검증."""
    clock = AcceleratedClock(speed=1.0)
    field = _make_field(clock)

    # heavy_rain 시나리오로 업데이트 (종로구 → R=15 이상)
    rain_adapter = SimulatedRainAdapter("heavy_rain")
    gw_adapter = SimulatedGroundwaterAdapter("heavy_rain")
    traffic_adapter = SimulatedTrafficAdapter()

    # 이벤트 발생 (event_time = t_event)
    t_event = clock.now()
    field.update(rain_adapter, gw_adapter, traffic_adapter)

    # 이벤트 직후 R 점수 확인 (0h)
    snap_0h = field.snapshot()
    r0 = snap_0h["cells"][0]["r"]
    assert r0 > 0, f"heavy_rain에서 R 점수가 0: {r0}"

    # ── 48h 시점: r ≈ r0 × 0.1 ─────────────────────────────────────
    clock.set_virtual_time(t_event + 48 * 3600)
    snap_48h = field.snapshot()
    r_48h = snap_48h["cells"][0]["r"]
    ratio_48h = r_48h / r0
    assert abs(ratio_48h - 0.1) < 0.02, (
        f"48h: ratio={ratio_48h:.4f}, 기대≈0.1"
    )

    # ── 96h 시점: r ≈ r0 × 0.01 ──────────────────────────────────────
    clock.set_virtual_time(t_event + 96 * 3600)
    snap_96h = field.snapshot()
    r_96h = snap_96h["cells"][0]["r"]
    ratio_96h = r_96h / r0
    assert abs(ratio_96h - 0.01) < 0.005, (
        f"96h: ratio={ratio_96h:.4f}, 기대≈0.01"
    )

    # ── 100h 시점: r = 0 ───────────────────────────────────────────────
    clock.set_virtual_time(t_event + 100 * 3600)
    snap_100h = field.snapshot()
    r_100h = snap_100h["cells"][0]["r"]
    assert r_100h == 0.0, f"100h: r={r_100h:.4f}, 기대=0.0"


def test_state_restore_preserves_decay():
    """수용 기준 5번: state.npz 저장·복원 후 감쇠 상태가 유지된다."""
    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        clock = AcceleratedClock(speed=1.0)
        field = _make_field(clock)

        # heavy_rain으로 업데이트
        field.update(
            SimulatedRainAdapter("heavy_rain"),
            SimulatedGroundwaterAdapter("heavy_rain"),
            SimulatedTrafficAdapter(),
        )
        t_event = field._r_event_time[0]

        # 48h 후 상태로 설정
        t_after_48h = t_event + 48 * 3600
        clock.set_virtual_time(t_after_48h)
        snap_before = field.snapshot()
        r_before = snap_before["cells"][0]["r"]

        # 상태 저장
        save_state(field, tmp_path)

        # 새 인스턴스로 복원
        clock2 = AcceleratedClock(speed=1.0)
        field2 = _make_field(clock2)
        last_vt = load_state(field2, tmp_path)
        clock2.set_virtual_time(last_vt)

        snap_after = field2.snapshot()
        r_after = snap_after["cells"][0]["r"]

        assert abs(r_before - r_after) < 0.1, (
            f"복원 후 r 불일치: before={r_before:.4f}, after={r_after:.4f}"
        )

    finally:
        tmp_path.unlink(missing_ok=True)
