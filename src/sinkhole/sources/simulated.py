"""
sources/simulated.py — 시뮬레이션 어댑터 (Phase 3)

세 시나리오를 지원한다:
  calm       — 평시. 대부분 Stage 1.
  heavy_rain — 특정 자치구에 호우경보급 강수 집중.
  extreme    — 극한호우 + 지하수위 2σ 급락 → Stage 3 발생.

AGENTS.md 규칙:
  - 실제 API를 절대 호출하지 않는다 (2절 6항).
  - 계산 엔진(fusion/, core/)과 같은 인터페이스를 사용한다.
  - 어댑터 교체만으로 실시간 모드로 전환 가능 (Phase 6).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import GroundwaterSourceAdapter, RainSourceAdapter, TrafficSourceAdapter

# 시나리오별 강수 집중 자치구 (기저점수가 높은 곳 위주로 배치하여 UI에서 식별 가능하도록 수정)
_HEAVY_RAIN_DISTRICTS = {"영등포구", "도봉구", "구로구", "성동구"}
_EXTREME_DISTRICTS = {"종로구", "용산구", "성북구", "중구", "마포구"}
_HISTORICAL_2022_DISTRICTS = {"동작구", "서초구", "강남구", "영등포구", "구로구", "관악구"}

# 교통 부하 높은 자치구 (정적 프록시 — 도로 등급·버스노선 밀도 기반)
_HIGH_TRAFFIC_DISTRICTS = {
    "강남구", "서초구", "송파구", "영등포구", "마포구",
    "종로구", "중구", "용산구", "성동구",
}
_MED_TRAFFIC_DISTRICTS = {
    "강서구", "은평구", "노원구", "도봉구", "구로구",
    "관악구", "광진구", "동작구",
}


class SimulatedRainAdapter(RainSourceAdapter):
    """시나리오 기반 합성 강수 어댑터.

    fetch()는 실제 기상청 어댑터와 동일한 (N, 3) 배열을 반환한다.
    [1h_mm, 3h_mm, 12h_mm] 단위로 반환하며,
    scoring.py.compute_r()를 통해 R 점수로 변환된다.
    """

    def __init__(self, scenario: str) -> None:
        """
        Args:
            scenario: "calm" | "heavy_rain" | "extreme" | "historical_flood_2022"
        """
        if scenario not in ("calm", "heavy_rain", "extreme", "historical_flood_2022"):
            raise ValueError(f"알 수 없는 시나리오: {scenario}")
        self._scenario = scenario

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 [1h_mm, 3h_mm, 12h_mm] 합성 강수량을 반환한다.

        Args:
            grid_df: 격자 DataFrame (id, lat, lon, gu)

        Returns:
            shape (N, 3): 합성 강수량 배열
        """
        n = len(grid_df)
        rain = np.zeros((n, 3), dtype=np.float64)  # [1h, 3h, 12h]

        if self._scenario == "calm":
            # 평시: 전 격자 무강수
            pass  # rain은 이미 0

        elif self._scenario == "heavy_rain":
            # 호우경보 (3h >= 90mm → R = 20)
            for i, gu in enumerate(grid_df["gu"]):
                if gu in _HEAVY_RAIN_DISTRICTS:
                    rain[i] = [0.0, 92.0, 0.0]  # 3h=92mm → 호우경보 R=20
                else:
                    rain[i] = [0.0, 42.0, 0.0]  # 3h=42mm → 사전주의 R=10

        elif self._scenario == "extreme":
            # 극한호우 (1h >= 72mm → R = 25)
            for i, gu in enumerate(grid_df["gu"]):
                if gu in _EXTREME_DISTRICTS:
                    rain[i] = [75.0, 95.0, 185.0]  # 극한호우 R=25
                else:
                    rain[i] = [0.0, 62.0, 115.0]   # 호우주의보 R=15
                    
        elif self._scenario == "historical_flood_2022":
            # 2022년 8월 8일 동작구 신대방 관측소(410) 및 강남 일대 강수량 기준
            # 1h: 141.5mm / 3h: 259.0mm / 12h: 380mm+ (R=25 확정 + 매우 위험)
            for i, gu in enumerate(grid_df["gu"]):
                if gu in _HISTORICAL_2022_DISTRICTS:
                    rain[i] = [141.5, 259.0, 381.5]
                else:
                    rain[i] = [50.0, 100.0, 150.0]

        return rain


class SimulatedGroundwaterAdapter(GroundwaterSourceAdapter):
    """시나리오 기반 합성 지하수위 어댑터.

    fetch()는 관측정 단위 σ 이상도를 격자로 투영한 배열을 반환한다.
    """

    def __init__(self, scenario: str) -> None:
        if scenario not in ("calm", "heavy_rain", "extreme", "historical_flood_2022"):
            raise ValueError(f"알 수 없는 시나리오: {scenario}")
        self._scenario = scenario

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 σ 이상도를 반환한다 (음수=급락).

        Returns:
            shape (N,): σ 이상도. 음수가 수위 급락 (위험 증가).
        """
        n = len(grid_df)
        sigma = np.zeros(n, dtype=np.float64)

        if self._scenario == "calm":
            # 지하수위 정상 → 이상 없음
            pass

        elif self._scenario == "heavy_rain":
            # 강남4구 일대 소폭 급락 → G = 5 (1σ 하강)
            for i, gu in enumerate(grid_df["gu"]):
                if gu in _HEAVY_RAIN_DISTRICTS:
                    sigma[i] = -1.2  # 1.2σ 급락

        elif self._scenario == "extreme":
            # 2σ 이상 급락 → G = 10 (단, R >= 15 조건 별도 체크)
            for i, gu in enumerate(grid_df["gu"]):
                if gu in _EXTREME_DISTRICTS:
                    sigma[i] = -2.1  # 2.1σ 급락
                    
        elif self._scenario == "historical_flood_2022":
            # 토립자 유실로 인한 수위 폭락 (3σ 이상)
            for i, gu in enumerate(grid_df["gu"]):
                if gu in _HISTORICAL_2022_DISTRICTS:
                    sigma[i] = -3.5  # 3.5σ 폭락

        return sigma

    @property
    def is_consecutive_valid(self) -> bool:
        """시뮬레이션에서는 연속 관측 조건을 항상 만족한 것으로 본다."""
        return True


class SimulatedTrafficAdapter(TrafficSourceAdapter):
    """정적 프록시 기반 교통 어댑터.

    도로 등급·버스노선 밀도를 자치구별로 코딩한 정적 프록시.
    시나리오와 무관하게 동일한 값을 반환한다 (Phase 3 설계).
    TOPIS 실시간 연동은 Phase 7 이후 선택 사항 (AGENTS.md 6절).
    """

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 교통 저하율(0.0~1.0)을 반환한다.

        도심부 주요 자치구: 0.7~1.0 (T 점수 3.5~5.0)
        중간 자치구:         0.4~0.6
        외곽 자치구:         0.1~0.3

        Returns:
            shape (N,): 교통 저하율
        """
        n = len(grid_df)
        deg = np.full(n, 0.2, dtype=np.float64)  # 기본: 외곽 수준

        for i, gu in enumerate(grid_df["gu"]):
            if gu in _HIGH_TRAFFIC_DISTRICTS:
                deg[i] = 0.85  # T ≈ 4.25
            elif gu in _MED_TRAFFIC_DISTRICTS:
                deg[i] = 0.50  # T ≈ 2.50

        return deg
