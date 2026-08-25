"""
fusion/bayes.py — 다중센서 베이지안 융합 (Phase 7-1)

BUILD_PLAN.md 7-1절:
  "각 소스에 측정 분산을 부여해 통계적으로 결합.
   격자별 최적 추정치와 불확실성(신뢰구간)을 함께 산출.
   기존 단순 가중합 경로는 지우지 말고 옵션으로 남긴다."

융합 방식:
  단순 가중합: score = B + R + G + T  (기존 방식)
  베이지안:    각 측정값을 독립 관측으로 보고 사후 분산 최소화
               → 측정 분산이 작을수록 가중치가 높아짐

측정 분산 (variance) 부여 근거:
  B (기저점수):   분산 작음 (고해상도 정적 데이터) → var=4
  R (강수):       분산 중간 (기상청 500m 격자)     → var=9
  G (지하수위):   분산 큼   (IDW 보간 오차 큼)      → var=25
  T (교통):       분산 매우 큼 (정적 프록시)        → var=36

불확실성 산출:
  fused_var = 1 / Σ(1/var_i)   ← 베이지안 최소분산 결합
  unc = sqrt(fused_var)          ← 표준편차 = 1σ 불확실성
"""

from __future__ import annotations

import numpy as np


# ── 기본 측정 분산 (weights.yaml 미구현 시 사용) ──────────────────────────
DEFAULT_VARIANCES = {
    "b": 4.0,   # 정적 지반 데이터 — 신뢰도 높음
    "r": 9.0,   # 기상청 격자 강수 — 중간
    "g": 25.0,  # IDW 보간 지하수위 — 신뢰도 낮음
    "t": 36.0,  # 정적 프록시 교통 — 신뢰도 가장 낮음
}


def bayesian_fuse(
    b: np.ndarray,
    r: np.ndarray,
    g: np.ndarray,
    t: np.ndarray,
    variances: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """베이지안 최소분산 결합으로 총점과 불확실성을 계산한다.

    각 채널을 독립 관측으로 보고, 측정 분산의 역수를 가중치로 사용.
    결측(nan) 채널은 자동으로 제외한다.

    Args:
        b:         shape (N,) — 기저점수
        r:         shape (N,) — 감쇠 적용된 R (결측 가능)
        g:         shape (N,) — 감쇠 적용된 G (결측 가능)
        t:         shape (N,) — 감쇠 적용된 T (결측 가능)
        variances: 채널별 측정 분산 {'b':4, 'r':9, 'g':25, 't':36}

    Returns:
        (fused_score, unc):
          fused_score: shape (N,) — 융합 총점 [0, 100]
          unc:         shape (N,) — 1σ 불확실성 (표준편차)
                       데이터 희소 격자에서 더 큰 값이 나와야 함 (수용 기준 2번)
    """
    var = variances or DEFAULT_VARIANCES

    n = len(b)
    channels = [
        ("b", b,  var["b"]),
        ("r", r,  var["r"]),
        ("g", g,  var["g"]),
        ("t", t,  var["t"]),
    ]

    # 채널별 가중치: w_i = 1 / sigma_i^2
    # 결측 격자는 그 채널 가중치를 0으로
    weighted_sum = np.zeros(n, dtype=np.float64)
    total_weight = np.zeros(n, dtype=np.float64)

    for name, values, sigma2 in channels:
        vals   = np.asarray(values, dtype=np.float64)
        w_base = 1.0 / sigma2
        # nan 격자의 가중치 = 0
        valid  = ~np.isnan(vals)
        w      = np.where(valid, w_base, 0.0)
        v      = np.where(valid, vals,   0.0)

        weighted_sum += w * v
        total_weight += w

    # 총 가중치가 0인 격자 (모든 채널 결측) → 0
    safe_total = np.where(total_weight > 0, total_weight, 1.0)
    fused_score = np.where(total_weight > 0, weighted_sum / safe_total, 0.0)
    fused_score = np.clip(fused_score, 0.0, 100.0)

    # 불확실성: σ_fused = sqrt(1 / Σ(1/σ_i^2))
    # 활성 채널이 많을수록 불확실성 감소 (데이터 희소 격자에서 더 크게 나옴)
    fused_var = np.where(total_weight > 0, 1.0 / total_weight, np.nan)
    unc = np.sqrt(fused_var)

    return fused_score, unc


def simple_fuse(
    b: np.ndarray,
    r: np.ndarray,
    g: np.ndarray,
    t: np.ndarray,
) -> np.ndarray:
    """단순 가중합 융합 (기존 방식, 비교 실험용).

    nan 채널은 0으로 대체.

    Args:
        b, r, g, t: shape (N,) — 각 채널 점수

    Returns:
        shape (N,) — 총점 [0, 100]
    """
    score = (
        np.nan_to_num(b, nan=0.0)
        + np.nan_to_num(r, nan=0.0)
        + np.nan_to_num(g, nan=0.0)
        + np.nan_to_num(t, nan=0.0)
    )
    return np.clip(score, 0.0, 100.0)


def compare_fusion_methods(
    b: np.ndarray,
    r: np.ndarray,
    g: np.ndarray,
    t: np.ndarray,
    variances: dict | None = None,
) -> dict:
    """단순 가중합 vs 베이지안 융합 결과를 비교한다.

    docs/fusion_eval.md 비교표 생성에 사용.

    Returns:
        dict with keys: simple_score, bayes_score, unc,
                        mae, rmse, max_diff (베이지안 - 단순 차이)
    """
    simple = simple_fuse(b, r, g, t)
    bayes, unc = bayesian_fuse(b, r, g, t, variances)

    diff = bayes - simple
    mae  = float(np.nanmean(np.abs(diff)))
    rmse = float(np.sqrt(np.nanmean(diff ** 2)))
    max_diff = float(np.nanmax(np.abs(diff)))

    return {
        "simple_score": simple,
        "bayes_score":  bayes,
        "unc":          unc,
        "diff":         diff,
        "mae":          round(mae, 4),
        "rmse":         round(rmse, 4),
        "max_diff":     round(max_diff, 4),
    }
