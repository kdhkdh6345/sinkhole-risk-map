"""
static_layers/liquefaction.py — 액상화 위험등급 레이어 스텁 (Phase 2)

현재 상태: 인터페이스만 구현, 0점 반환.
실제 구현: 국토교통부 액상화 위험지도 연동 후 채울 예정.

데이터 정규화 계획 (AGENTS.md 6절):
  - 상(High)   → 1.0 × max_score = 10점
  - 중(Medium) → 0.6 × max_score = 6점
  - 하(Low)    → 0.2 × max_score = 2점
"""

from __future__ import annotations

import numpy as np
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"

# 등급 → 가중치 (weights.yaml과 일치해야 함)
GRADE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.2}


def compute_liquefaction_scores(grid_count: int) -> np.ndarray:
    """액상화 위험등급 기반 점수를 반환한다.

    Args:
        grid_count: 격자 수 N

    Returns:
        np.ndarray (길이 N): 현재는 전부 0.0 (스텁)
    """
    # TODO: 국토교통부 액상화 위험지도 데이터 연동 후 구현
    #       1. 격자별 액상화 등급(상/중/하) 부여
    #       2. GRADE_WEIGHT 매핑 × max_score
    with open(WEIGHTS_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # max_score = cfg["static"]["liquefaction"]["max"]  # 나중에 사용
    return np.zeros(grid_count, dtype=np.float64)
