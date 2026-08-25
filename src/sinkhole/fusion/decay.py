"""
fusion/decay.py — 감쇠 함수 (세 채널 공용, Phase 3)

AGENTS.md 규칙:
  "강수·지하수위·교통 세 채널이 동일한 감쇠 함수 하나를 공유한다.
   채널별로 별도 함수를 만들지 않는다."

감쇠 공식 (AGENTS.md 6절, config/grid.yaml 파라미터):
  plateau_hours = 24     # 0~24h: factor = 1.0 (감쇠 없음)
  tail_hours    = 72     # 24~72h: 지수감쇠
  residual      = 0.05   # 72h 시점 잔존 비율

  k = ln(residual) / (tail - plateau) = ln(0.05) / 48 ≈ -0.0624

  factor(t) =
    1.0                           if t <= plateau
    exp(k * (t - plateau))        if plateau < t <= tail
    0.0                           if t > tail

검증:
  t = 48h: exp(k * 24) = exp(ln(0.05)/2) = sqrt(0.05) ≈ 0.2236 (수용 기준 ~0.22)
  t = 72h: exp(k * 48) = 0.05                              (수용 기준 ~0.05)
"""

from __future__ import annotations

import math

import numpy as np


def decay_factor(elapsed_hours: np.ndarray, cfg: dict) -> np.ndarray:
    """경과 시간(시간 단위)에 따른 감쇠 계수 벡터를 반환한다.

    Args:
        elapsed_hours: shape (N,) — 이벤트 발생 후 경과 시간 (시간 단위, >=0)
        cfg: config/grid.yaml 딕셔너리 (decay 키 포함)

    Returns:
        np.ndarray shape (N,): 감쇠 계수 [0.0, 1.0]

    세 채널(강수·지하수위·교통) 모두 이 함수를 사용한다.
    채널별 별도 감쇠 함수를 만드는 것은 AGENTS.md 위반이다.
    """
    decay_cfg = cfg["decay"]
    plateau: float = decay_cfg["plateau_hours"]   # 24h
    tail: float = decay_cfg["tail_hours"]          # 72h
    residual: float = decay_cfg["residual_at_tail"]  # 0.05

    # 지수감쇠 계수 k 계산
    # k = ln(residual) / (tail - plateau)
    k: float = math.log(residual) / (tail - plateau)

    elapsed = np.asarray(elapsed_hours, dtype=np.float64)
    factor = np.ones_like(elapsed)

    # 24h < t <= 72h: 지수감쇠
    mask_decay = (elapsed > plateau) & (elapsed <= tail)
    factor[mask_decay] = np.exp(k * (elapsed[mask_decay] - plateau))

    # t > 72h: 완전 소멸
    factor[elapsed > tail] = 0.0

    return factor


def apply_decay(
    scores: np.ndarray,
    elapsed_hours: np.ndarray,
    cfg: dict,
) -> np.ndarray:
    """점수 배열에 감쇠를 적용해 반환한다.

    Args:
        scores:        shape (N,) — 이벤트 시점의 원시 점수
        elapsed_hours: shape (N,) — 이벤트 발생 후 경과 시간 (시간)
        cfg:           config/grid.yaml 딕셔너리

    Returns:
        np.ndarray shape (N,): 감쇠 적용된 점수
    """
    return scores * decay_factor(elapsed_hours, cfg)
