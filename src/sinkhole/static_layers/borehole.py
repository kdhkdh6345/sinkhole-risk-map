"""
static_layers/borehole.py — 시추공 지층/N값 레이어 스텁 (Phase 2)

현재 상태: 인터페이스만 구현, 0점 반환.
실제 구현: data/raw/국토교통부_지반정보_전기비저항탐사_20240820.csv 및
           GIMS 시추공 DB 연동 후 채울 예정.

데이터 정규화 계획 (Phase 2+ 구현 시):
  - N값(표준관입시험 타격횟수) 역수를 격자 평균
  - 매립층(fill) 여부 플래그 가산
  - 0~15점 min-max 정규화
"""

from __future__ import annotations

import numpy as np
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"


def compute_borehole_scores(grid_count: int) -> np.ndarray:
    """시추공 N값 기반 점수를 반환한다.

    Args:
        grid_count: 격자 수 N

    Returns:
        np.ndarray (길이 N): 현재는 전부 0.0 (스텁)
    """
    # TODO: GIMS 시추공 DB 연동 후 실제 계산 구현
    #       1. N값 역수 계산 (N값 클수록 지반 강함 → 위험도 낮음)
    #       2. 매립층 여부 가산
    #       3. 격자 단위로 IDW 보간
    #       4. 0~max_score min-max 정규화
    with open(WEIGHTS_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # max_score = cfg["static"]["borehole"]["max"]  # 나중에 사용
    return np.zeros(grid_count, dtype=np.float64)
