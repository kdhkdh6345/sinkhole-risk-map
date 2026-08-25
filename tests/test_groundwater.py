"""
tests/test_groundwater.py — 지하수위 어댑터 테스트 (Phase 6-2)
"""

import os

import numpy as np
import pandas as pd
import pytest

from sinkhole.sources.groundwater import SeoulGroundwaterSource, _idw_interpolate


def test_groundwater_fetch_shape():
    """fetch() 반환 형태가 (N,)인지 확인한다."""
    json_path = "data/fixtures/gw_sample.json"
    db_path   = "data/gw_history_test.db"

    if not os.path.exists(json_path):
        pytest.skip(f"fixture 없음: {json_path}")
    if not os.path.exists("data/grid.parquet"):
        pytest.skip("grid.parquet 없음")

    if os.path.exists(db_path):
        os.remove(db_path)

    real_grid = pd.read_parquet("data/grid.parquet")
    test_df   = real_grid.head(5).reset_index(drop=True)

    source = SeoulGroundwaterSource(json_path=json_path, db_path=db_path)
    result = source.fetch(test_df)

    assert result.shape == (5,), f"shape={result.shape}, 기대=(5,)"
    # nan 또는 float 값이어야 함
    assert np.all(np.isnan(result) | np.isfinite(result))

    if os.path.exists(db_path):
        os.remove(db_path)


def test_idw_interpolate_basic():
    """IDW 보간: 관측소와 같은 위치 → 관측값 그대로 반환."""
    obs_coords  = np.array([[37.5, 126.9]])
    obs_values  = np.array([-2.0])
    target      = np.array([[37.5, 126.9]])  # 동일 위치

    result = _idw_interpolate(obs_coords, obs_values, target, power=2, max_dist_deg=0.5)
    assert abs(result[0] - (-2.0)) < 1e-6, f"동일 위치 보간 실패: {result[0]}"


def test_idw_interpolate_out_of_range():
    """IDW 보간: 최대 반경 초과 → np.nan."""
    obs_coords  = np.array([[37.5, 126.9]])
    obs_values  = np.array([-2.0])
    target      = np.array([[37.5, 127.5]])  # 0.6° 거리

    result = _idw_interpolate(obs_coords, obs_values, target, power=2, max_dist_deg=0.1)
    assert np.isnan(result[0]), f"범위 초과 격자는 nan이어야 함: {result[0]}"


def test_idw_interpolate_weighting():
    """IDW 보간: 가까운 관측소에 더 높은 가중치가 부여된다."""
    obs_coords = np.array([
        [37.5, 126.90],  # 가까운 관측소 (value: -3.0)
        [37.5, 126.95],  # 먼 관측소   (value: 0.0)
    ])
    obs_values = np.array([-3.0, 0.0])
    target     = np.array([[37.5, 126.91]])  # 가까운 쪽 방향

    result = _idw_interpolate(obs_coords, obs_values, target, power=2, max_dist_deg=0.5)
    # 가까운 관측소(-3.0) 쪽으로 더 치우쳐야 함
    assert result[0] < -1.0, f"IDW 가중치 방향 오류: {result[0]:.4f}"


def test_consecutive_valid_default():
    """초기 상태에서 is_consecutive_valid는 False이다."""
    json_path = "data/fixtures/gw_sample.json"
    if not os.path.exists(json_path):
        pytest.skip(f"fixture 없음: {json_path}")

    source = SeoulGroundwaterSource(
        json_path=json_path,
        db_path="data/gw_history_test2.db",
    )
    assert source.is_consecutive_valid is False

    if os.path.exists("data/gw_history_test2.db"):
        os.remove("data/gw_history_test2.db")
