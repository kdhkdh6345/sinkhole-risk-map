"""
static_layers/history.py — 과거 침하·공동 이력 레이어 스텁 (Phase 2)

현재 상태: 인터페이스만 구현, 0점 반환.
실제 구현: 서울시 싱크홀 발생 이력 DB 연동 후 채울 예정.

데이터 정규화 계획 (Phase 2+ 구현 시):
  - 반경 300m 내 과거 침하·공동 발생 건수 집계
  - 최근성 감쇠: weight = exp(-days_ago / 730)  # 2년 기준 절반
  - 가중 건수 합산 후 0~15점 min-max 정규화
"""

from __future__ import annotations

import numpy as np
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"


def compute_history_scores(grid_count: int) -> np.ndarray:
    """과거 침하·공동 이력 기반 점수를 반환한다.

    Args:
        grid_count: 격자 수 N

    Returns:
        np.ndarray (길이 N): 현재는 전부 0.0 (스텁)
    """
    # TODO: 서울시 지반침하 이력 데이터 연동 후 구현
    #       1. 격자별 반경 내 이력 건수 집계
    #       2. 최근성 감쇠 가중합
    #       3. 0~max_score min-max 정규화
    with open(WEIGHTS_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # max_score = cfg["static"]["history"]["max"]  # 나중에 사용
    return np.zeros(grid_count, dtype=np.float64)
