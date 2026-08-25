"""
sources/base.py — 데이터 소스 어댑터 추상 클래스 (Phase 3)

AGENTS.md 7절:
  "모든 소스 어댑터는 sources/base.py의 추상 클래스를 상속하고 동일한 시그니처를 가진다."
  "각 채널은 원본 단위에서 이상도를 먼저 계산한 뒤 격자로 투영한다."

채널별 fetch() 반환 단위:
  RainSourceAdapter      → shape (N, 3): [1h_mm, 3h_mm, 12h_mm]
  GroundwaterSourceAdapter → shape (N,): σ 이상도 (양수=상승, 음수=하강)
  TrafficSourceAdapter    → shape (N,): 정체 저하율 0.0~1.0
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class RainSourceAdapter(ABC):
    """강수 데이터 소스 어댑터.

    fetch()는 1h/3h/12h 누적 강수량(mm)을 격자 배열로 반환한다.
    실시간 모드에서는 기상청 API 응답을 파싱해 채운다.
    시뮬 모드에서는 시나리오별 합성값을 생성한다.
    """

    @abstractmethod
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 강수량을 반환한다.

        Args:
            grid_df: 격자 정보 DataFrame (컬럼: id, lat, lon, gu)

        Returns:
            np.ndarray shape (N, 3): 각 행 = [1h_mm, 3h_mm, 12h_mm]
            결측 격자는 np.nan으로 채운다.
        """
        ...

    @property
    def channel(self) -> str:
        return "rain"


class GroundwaterSourceAdapter(ABC):
    """지하수위 데이터 소스 어댑터.

    fetch()는 격자별 σ 이상도를 반환한다.
    σ < 0: 수위 하강 (싱크홀 위험 증가)
    σ > 0: 수위 상승
    """

    @abstractmethod
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 지하수위 σ 이상도를 반환한다.

        Args:
            grid_df: 격자 정보 DataFrame

        Returns:
            np.ndarray shape (N,): σ 이상도. 결측은 np.nan.
        """
        ...

    @property
    def is_consecutive_valid(self) -> bool:
        """연속 관측 조건(2회 유지) 충족 여부.

        실시간 어댑터는 SQLite 이력으로 판정.
        시뮬 어댑터는 True를 반환한다 (연속 조건 항상 만족 가정).
        """
        return False

    @property
    def channel(self) -> str:
        return "groundwater"


class TrafficSourceAdapter(ABC):
    """교통 데이터 소스 어댑터.

    fetch()는 격자별 교통 정체 저하율(0.0~1.0)을 반환한다.
    Phase 3까지는 도로 등급·버스노선 수 기반 정적 프록시 사용.
    """

    @abstractmethod
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 교통 저하율을 반환한다.

        Args:
            grid_df: 격자 정보 DataFrame

        Returns:
            np.ndarray shape (N,): 저하율 0.0(정상)~1.0(극심 정체). 결측은 np.nan.
        """
        ...

    @property
    def channel(self) -> str:
        return "traffic"
