"""
fusion/anomaly.py — 상태공간 모델 기반 지하수위 이상탐지 (Phase 7-2)

BUILD_PLAN.md 7-2절:
  "1σ 넘으면 이상' 규칙을 상태공간 모델 기반 예측 → 잔차 판정으로 교체.
   다음 시점 지하수위를 예측하고, 실측과의 잔차가 크면 이상으로 판정.
   규칙기반 대비 오탐률 비교를 기록."

모델: 단순 칼만 필터 (1D)
  상태: [level, velocity]  (수위 + 변화율)
  관측: level
  예측: x_k+1 = F * x_k
  갱신: Kalman gain 기반

기존 규칙기반(1σ 임계값)은 is_anomaly_rule()로 남겨두어
두 방식을 동일 입력으로 비교 가능하게 한다.
"""

from __future__ import annotations

import numpy as np


class KalmanGroundwaterDetector:
    """1D 칼만 필터 기반 지하수위 이상탐지기.

    관측값의 예측 잔차가 threshold_sigma σ 를 넘으면 이상으로 판정.
    같은 입력에 대해 규칙기반과 칼만 방식을 모두 제공하여 오탐률 비교 가능.

    Args:
        process_noise:    Q — 상태 전이 불확실성 (크면 모델이 변화에 민감)
        measure_noise:    R — 측정 잡음 (작으면 관측을 더 신뢰)
        threshold_sigma:  잔차 이상 판정 임계값 (기본 2.5σ)
    """

    def __init__(
        self,
        process_noise: float = 0.1,
        measure_noise: float = 0.5,
        threshold_sigma: float = 2.5,
    ) -> None:
        self.Q = process_noise
        self.R = measure_noise
        self.threshold = threshold_sigma

        # 상태 벡터 x = [level, velocity], 초기화 전
        self._x: np.ndarray | None = None
        self._P: np.ndarray | None = None  # 오차 공분산

        # 상태 전이 행렬 (dt=1 단위시간)
        self._F = np.array([[1.0, 1.0], [0.0, 1.0]])
        # 관측 행렬 (level만 관측)
        self._H = np.array([[1.0, 0.0]])
        # 프로세스 잡음 공분산
        self._Q = np.eye(2) * self.Q
        # 측정 잡음 공분산
        self._R_mat = np.array([[self.R]])

        self.residuals: list[float] = []
        self.predictions: list[float] = []

    def update(self, observation: float) -> tuple[float, float, bool]:
        """새 관측값으로 칼만 필터를 갱신하고 이상 여부를 반환한다.

        Args:
            observation: 지하수위 관측값 (m)

        Returns:
            (predicted, residual, is_anomaly):
              predicted:  칼만 예측값
              residual:   관측 - 예측 (정규화 전)
              is_anomaly: 잔차가 threshold_sigma σ 초과 여부
        """
        # 초기화 (첫 관측)
        if self._x is None:
            self._x = np.array([observation, 0.0])
            self._P = np.eye(2) * 1.0
            self.residuals.append(0.0)
            self.predictions.append(observation)
            return observation, 0.0, False

        # ── 예측 단계 ────────────────────────────────────────────────────
        x_pred = self._F @ self._x
        P_pred = self._F @ self._P @ self._F.T + self._Q

        # ── 갱신 단계 ────────────────────────────────────────────────────
        y = observation - (self._H @ x_pred)[0]          # 혁신(잔차)
        S = self._H @ P_pred @ self._H.T + self._R_mat   # 혁신 공분산
        K = P_pred @ self._H.T @ np.linalg.inv(S)        # 칼만 이득
        self._x = x_pred + (K @ [[y]]).flatten()
        self._P = (np.eye(2) - K @ self._H) @ P_pred

        predicted = float(x_pred[0])
        residual  = float(y)

        # 정규화 잔차
        innov_std = float(np.sqrt(S[0, 0]))
        normalized = abs(residual) / max(innov_std, 1e-6)
        is_anomaly = normalized > self.threshold

        self.residuals.append(residual)
        self.predictions.append(predicted)

        return predicted, residual, is_anomaly

    def reset(self) -> None:
        """필터 상태를 초기화한다 (새 관측소 처리 시)."""
        self._x = None
        self._P = None
        self.residuals.clear()
        self.predictions.clear()


# ── 규칙기반 (기존 방식, 비교 실험용) ────────────────────────────────────

def is_anomaly_rule(
    sigma: float,
    threshold: float = 1.0,
) -> bool:
    """규칙기반 이상탐지: |σ| > threshold이면 이상.

    기존 방식 (Phase 3 이전). 비교 실험용으로 보존.

    Args:
        sigma:     σ 이상도 (음수=수위 하락)
        threshold: 이상 판정 임계값 (기본 1.0σ)

    Returns:
        True이면 이상
    """
    return abs(sigma) > threshold


def compare_anomaly_methods(
    observations: list[float],
    history_mean: float,
    history_std: float,
    kalman_threshold: float = 2.5,
    rule_threshold: float = 1.0,
) -> dict:
    """칼만 필터 vs 규칙기반 이상탐지를 동일 입력으로 비교한다.

    Args:
        observations:    시계열 관측값 목록
        history_mean:    30일 이력 평균 (규칙기반 σ 계산용)
        history_std:     30일 이력 표준편차
        kalman_threshold: 칼만 이상 판정 임계 σ
        rule_threshold:   규칙기반 이상 판정 임계 σ

    Returns:
        dict: {kalman_anomalies, rule_anomalies, false_positive_rate_reduction, ...}
    """
    detector = KalmanGroundwaterDetector(threshold_sigma=kalman_threshold)

    kalman_flags = []
    rule_flags   = []

    for obs in observations:
        _, _, ka = detector.update(obs)
        kalman_flags.append(ka)

        sigma = (obs - history_mean) / max(history_std, 1e-6)
        rule_flags.append(is_anomaly_rule(sigma, rule_threshold))

    ka_arr   = np.array(kalman_flags)
    rule_arr = np.array(rule_flags)

    n_total   = len(observations)
    n_kalman  = int(ka_arr.sum())
    n_rule    = int(rule_arr.sum())
    # 규칙기반만 탐지하고 칼만이 탐지 안 한 것 → 잠재적 오탐
    fp_reduction = max(0, n_rule - n_kalman) / max(n_total, 1)

    return {
        "n_total":           n_total,
        "n_kalman_anomalies":n_kalman,
        "n_rule_anomalies":  n_rule,
        "kalman_rate":       round(n_kalman / n_total, 4),
        "rule_rate":         round(n_rule / n_total, 4),
        "fp_reduction_pct":  round(fp_reduction * 100, 2),
        "kalman_flags":      kalman_flags,
        "rule_flags":        rule_flags,
        "residuals":         detector.residuals,
        "predictions":       detector.predictions,
    }
