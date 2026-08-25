#!/usr/bin/env python3
"""
싱크홀 위험도 계산 모듈

강수량 기반 싱크홀 발생 위험도를 0~100 점수로 산출.
(추후 실제 싱크홀 이력 데이터로 임계값 보정 가능)

위험도 산출 방식:
  1. 기본 점수: 1시간 강수량(RN1) → 점수 매핑
  2. 누적 가중치: 연속 강수 시간이 길수록 토양 포화 → 위험도 상승
  3. 최종: 클리핑 [0, 100]

사용 예:
  from sinkhole_risk import RiskCalculator
  rc = RiskCalculator()
  score = rc.score(rn1_mm=25.0, cumulative_mm=80.0)
"""

import numpy as np
import pandas as pd
from typing import Optional


class RiskCalculator:
    """강수량 → 싱크홀 위험도(0~100) 변환기"""

    # 1시간 강수량(mm) → 기본 위험 점수 (선형 보간 기반 구간)
    # (mm_threshold, base_score)
    RAIN_SCORE_TABLE = [
        (0,   0),
        (1,   5),    # 약한 비
        (5,  20),    # 보통 비
        (20, 50),    # 강한 비
        (40, 75),    # 매우 강한 비
        (70, 95),    # 폭우
        (100, 100),  # 극한 강수
    ]

    # 누적 강수량(mm) 가중 계수
    # 토양이 포화될수록 같은 강도에서 위험도 더 높아짐
    CUMULATIVE_WEIGHT = [
        (0,   1.0),
        (30,  1.1),
        (60,  1.2),
        (100, 1.35),
        (150, 1.5),
    ]

    def __init__(self):
        self._rain_mm   = [r[0] for r in self.RAIN_SCORE_TABLE]
        self._rain_sc   = [r[1] for r in self.RAIN_SCORE_TABLE]
        self._cum_mm    = [r[0] for r in self.CUMULATIVE_WEIGHT]
        self._cum_wt    = [r[1] for r in self.CUMULATIVE_WEIGHT]

    def _base_score(self, rn1: float) -> float:
        """1시간 강수량 → 기본 점수 (선형 보간)"""
        return float(np.interp(rn1, self._rain_mm, self._rain_sc))

    def _cum_weight(self, cumulative: float) -> float:
        """누적 강수량 → 가중 계수 (선형 보간)"""
        return float(np.interp(cumulative, self._cum_mm, self._cum_wt))

    def score(self, rn1_mm: float, cumulative_mm: float = 0.0) -> float:
        """
        Parameters
        ----------
        rn1_mm       : 현재 1시간 강수량 (mm)
        cumulative_mm: 과거 12시간 누적 강수량 (mm, 기본 0)

        Returns
        -------
        float: 위험도 점수 0~100
        """
        if np.isnan(rn1_mm) or rn1_mm <= 0:
            return 0.0
        base   = self._base_score(rn1_mm)
        weight = self._cum_weight(cumulative_mm)
        return float(np.clip(base * weight, 0, 100))

    def score_grid(self,
                   rn1_grid: np.ndarray,
                   cumulative_grid: Optional[np.ndarray] = None) -> np.ndarray:
        """
        격자 전체에 위험도 적용

        Parameters
        ----------
        rn1_grid        : shape (NY, NX) — 1시간 강수량
        cumulative_grid : shape (NY, NX) — 누적 강수량 (없으면 0)

        Returns
        -------
        np.ndarray shape (NY, NX) — 위험도 점수 [0, 100]
        """
        if cumulative_grid is None:
            cumulative_grid = np.zeros_like(rn1_grid)

        risk = np.zeros_like(rn1_grid, dtype=np.float32)
        mask = ~np.isnan(rn1_grid) & (rn1_grid > 0)

        base   = np.interp(rn1_grid[mask], self._rain_mm, self._rain_sc)
        weight = np.interp(cumulative_grid[mask], self._cum_mm, self._cum_wt)
        risk[mask] = np.clip(base * weight, 0, 100)

        return risk

    @staticmethod
    def label(score: float) -> str:
        """점수 → 위험 등급 텍스트"""
        if score >= 75:  return "🔴 위험"
        if score >= 50:  return "🟠 경고"
        if score >= 20:  return "🟡 주의"
        if score >  0:   return "🟢 관심"
        return "⚪ 안전"

    @staticmethod
    def color(score: float) -> str:
        """점수 → 지도 표시 색상 (Hex)"""
        if score >= 75:  return "#d73027"   # 빨강
        if score >= 50:  return "#fc8d59"   # 주황
        if score >= 20:  return "#fee08b"   # 노랑
        if score >  0:   return "#91cf60"   # 연두
        return "#d9d9d9"                     # 회색 (안전)

    @staticmethod
    def opacity(score: float) -> float:
        """점수 → 지도 투명도"""
        return float(np.clip(score / 100 * 0.75 + 0.05, 0.05, 0.80))


# ── 빠른 테스트 ───────────────────────────────────────────────
if __name__ == "__main__":
    rc = RiskCalculator()
    test_cases = [
        (0,   0,   "비 없음"),
        (3,   0,   "약한 비"),
        (10,  0,   "보통 비"),
        (10,  80,  "보통 비 + 누적"),
        (30,  0,   "강한 비"),
        (30,  100, "강한 비 + 누적"),
        (60,  0,   "폭우"),
        (80,  150, "폭우 + 포화"),
    ]
    print(f"{'RN1(mm)':>8} {'누적(mm)':>8} {'점수':>6}  등급         설명")
    print("-" * 55)
    for rn1, cum, desc in test_cases:
        s = rc.score(rn1, cum)
        print(f"{rn1:>8.1f} {cum:>8.1f} {s:>6.1f}  {rc.label(s):<12} {desc}")
