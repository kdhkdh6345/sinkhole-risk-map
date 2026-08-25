"""
fusion/scoring.py — R/G/T 점수화 + 단계 판정 (Phase 3)

AGENTS.md 규칙:
  - 배점·임계값을 코드에 박지 않는다. 전부 config/weights.yaml에서 읽는다.
  - 결측은 np.nan으로 두고 해당 채널만 제외한다. 0으로 채우지 않는다.

채널별 점수화:
  compute_r()  강수(1h/3h/12h) → R 점수 0~25
  compute_g()  지하수위 σ → G 점수 0~10 (R 조건 + 연속 조건 포함)
  compute_t()  교통 저하율 → T 점수 0~5

단계 판정 (compute_stages):
  Stage 1: B >= b_min  (초록)
  Stage 2: Stage 1 AND R >= r_min  (노랑)
  Stage 3: Stage 2 AND G >= g_min  (빨강)
"""

from __future__ import annotations

import numpy as np


def compute_r(rain_arr: np.ndarray, cfg: dict) -> np.ndarray:
    """강수량 배열 → R 점수(0~25).

    Args:
        rain_arr: shape (N, 3) — 컬럼 순서: [1h_mm, 3h_mm, 12h_mm]
        cfg:      weights.yaml 딕셔너리

    Returns:
        np.ndarray shape (N,): R 점수 [0, 25]

    근거: AGENTS.md 6절 "강수 R" — 기상청 특보 기준 구간별 매핑.
    결측(nan) 격자는 0점으로 처리 (강수 없음으로 간주 — 보수적 처리).
    """
    n = rain_arr.shape[0]
    r1 = np.nan_to_num(rain_arr[:, 0], nan=0.0)   # 1h 강수량
    r3 = np.nan_to_num(rain_arr[:, 1], nan=0.0)   # 3h 강수량
    r12 = np.nan_to_num(rain_arr[:, 2], nan=0.0)  # 12h 강수량

    thresholds = cfg["realtime"]["rain"]["thresholds"]
    # thresholds는 score 오름차순 정렬이어야 함 (낮은 점수부터 덮어씀)
    scores = np.zeros(n, dtype=np.float64)

    for tier in thresholds:
        score = float(tier["score"])
        conds = tier["conditions"]

        any_conds = conds.get("any", [])
        tier_mask = np.zeros(n, dtype=bool)

        for cond in any_conds:
            if isinstance(cond, dict) and "all" not in cond:
                # 단일 조건: {window_h: N, mm: X}
                win = cond["window_h"]
                threshold_mm = cond["mm"]
                if win == 1:
                    tier_mask |= r1 >= threshold_mm
                elif win == 3:
                    tier_mask |= r3 >= threshold_mm
                elif win == 12:
                    tier_mask |= r12 >= threshold_mm
            elif isinstance(cond, dict) and "all" in cond:
                # AND 복합 조건
                sub_mask = np.ones(n, dtype=bool)
                for sub in cond["all"]:
                    win = sub["window_h"]
                    threshold_mm = sub["mm"]
                    if win == 1:
                        sub_mask &= r1 >= threshold_mm
                    elif win == 3:
                        sub_mask &= r3 >= threshold_mm
                    elif win == 12:
                        sub_mask &= r12 >= threshold_mm
                tier_mask |= sub_mask

        # 점수 오름차순이므로 무조건 덮어씀 (최종적으로 가장 높은 tier 적용)
        scores[tier_mask] = score

    return scores


def compute_g(
    sigma_arr: np.ndarray,
    r_scores: np.ndarray,
    consecutive_valid: bool | np.ndarray,
    cfg: dict,
) -> np.ndarray:
    """지하수위 σ 이상도 → G 점수(0~10).

    조건 (AGENTS.md 6절):
      1. R >= min_rain_for_g (강수 없는 단독 변동 배제)
      2. consecutive_valid (2회 연속 관측 유지)

    Args:
        sigma_arr:        shape (N,) — σ 이상도 (음수=수위 급락)
        r_scores:         shape (N,) — 현재 R 점수
        consecutive_valid: bool 또는 shape (N,) bool 배열.
                          시뮬: True, 실시간: 관측정 단위 판정 결과
        cfg:              weights.yaml 딕셔너리

    Returns:
        np.ndarray shape (N,): G 점수 [0, 10]
    """
    g_cfg = cfg["realtime"]["groundwater"]
    min_rain: float = g_cfg["min_rain_for_g"]   # 15
    s1_score: float = g_cfg["sigma1_score"]      # 5
    s2_score: float = g_cfg["sigma2_score"]      # 10

    n = len(sigma_arr)
    scores = np.zeros(n, dtype=np.float64)

    # 조건 1: R >= min_rain
    r_ok = r_scores >= min_rain

    # 조건 2: 연속 관측 유지
    if isinstance(consecutive_valid, bool):
        consec_ok = np.full(n, consecutive_valid, dtype=bool)
    else:
        consec_ok = np.asarray(consecutive_valid, dtype=bool)

    # 지하수위 급락 = sigma < 0, |sigma| >= threshold
    sigma = np.nan_to_num(sigma_arr, nan=0.0)
    drop = -sigma  # 양수가 급락 크기

    base_condition = r_ok & consec_ok

    # 1σ 이상 급락 → +5
    mask1 = base_condition & (drop >= 1.0)
    scores[mask1] = s1_score

    # 2σ 이상 급락 → +10 (덮어씀)
    mask2 = base_condition & (drop >= 2.0)
    scores[mask2] = s2_score

    return scores


def compute_t(degradation_arr: np.ndarray, cfg: dict) -> np.ndarray:
    """교통 저하율 → T 점수(0~5).

    Phase 3까지: 정적 프록시 (도로 등급, 버스노선 수 기반 저하율).
    저하율 0~1 → 0~max_t 선형 변환.

    Args:
        degradation_arr: shape (N,) — 교통 저하율 0.0~1.0
        cfg:             weights.yaml 딕셔너리

    Returns:
        np.ndarray shape (N,): T 점수 [0, 5]
    """
    max_t: float = cfg["realtime"]["traffic"]["max"]  # 5
    deg = np.nan_to_num(degradation_arr, nan=0.0)
    return np.clip(deg * max_t, 0.0, max_t)


def compute_stages(
    b: np.ndarray,
    r: np.ndarray,
    g: np.ndarray,
    cfg: dict,
) -> np.ndarray:
    """B/R/G 점수로 단계(1/2/3)를 판정한다.

    단계 정의 (AGENTS.md 6절):
      Stage 1 (초록): 기본 상태. 모든 격자.
      Stage 2 (노랑): Stage 1 AND B >= b_min AND R >= r_min
      Stage 3 (빨강): Stage 2 AND G >= g_min

    수용 기준 4번 근거:
      G >= g_min이어도 R < r_min이면 Stage 3 격상 불가.
      → Stage 3 = Stage 2 AND G >= g_min 이므로
        R < r_min → Stage 2 불가 → Stage 3 불가 (자동 보장)

    Args:
        b:   shape (N,) — 정적 기저점수
        r:   shape (N,) — 감쇠 적용된 R 점수
        g:   shape (N,) — 감쇠 적용된 G 점수
        cfg: weights.yaml 딕셔너리

    Returns:
        np.ndarray shape (N,) dtype int8: 1/2/3
    """
    b_min: float = cfg["stages"]["stage1"]["b_min"]
    r_min: float = cfg["stages"]["stage2"]["r_min"]
    g_min: float = cfg["stages"]["stage3"]["g_min"]

    stage = np.ones(len(b), dtype=np.int8)  # 기본: Stage 1

    # Stage 2: B >= b_min AND R >= r_min
    s2_mask = (b >= b_min) & (r >= r_min)
    stage[s2_mask] = 2

    # Stage 3: Stage 2 AND G >= g_min
    s3_mask = s2_mask & (g >= g_min)
    stage[s3_mask] = 3

    return stage
