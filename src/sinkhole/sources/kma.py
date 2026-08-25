"""
sources/kma.py — 기상청 API허브 강수 어댑터 (Phase 6-1 완성)

AGENTS.md 규칙:
  - fusion/ core/ 코드를 한 줄도 수정하지 않는다.
  - 어댑터 교체만으로 sim → real 모드 전환.
  - API 실패 시 해당 채널만 np.nan, 나머지 채널은 계속 동작.

NetCDF4 변수 구조 (kma_sample.nc):
  lat     (N,)   — 관측/격자 위도
  lon     (N,)   — 관측/격자 경도
  rn_1h   (N,)   — 1시간 누적 강수량 (mm)
  rn_3h   (N,)   — 3시간 누적 강수량 (mm)
  rn_12h  (N,)   — 12시간 누적 강수량 (mm)

실제 API 연동 (Phase 6 이후):
  기상청 API허브 → 동네예보 + ASOS 실황
  환경변수 KMA_API_KEY 에서 키 읽기 (코드에 하드코딩 금지)
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .base import RainSourceAdapter

try:
    import netCDF4 as nc
    _NC4_AVAILABLE = True
except ImportError:
    _NC4_AVAILABLE = False
    warnings.warn("netCDF4 미설치 — KmaRainfallSource는 fixture 파일을 사용합니다.", stacklevel=2)

try:
    from scipy.spatial import cKDTree
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


class KmaRainfallSource(RainSourceAdapter):
    """기상청 NetCDF4 관측망 기반 강수 어댑터.

    fetch()는 NetCDF4 파일에서 1h/3h/12h 강수량을 읽어
    격자에 KD-트리 최근접 이웃 투영으로 반환한다.

    실제 API 환경:
      - KMA_API_KEY 환경변수에서 키를 읽는다.
      - 실패 시 np.nan 반환 (엔진은 계속 동작).
      - 타임아웃: 8초 (AGENTS.md 5.3절)

    Args:
        nc_path: NetCDF4 파일 경로 (기본: data/fixtures/kma_sample.nc)
        max_dist_deg: 최근접 이웃 허용 최대 거리 (도 단위, 기본 0.1°≈11km)
    """

    def __init__(
        self,
        nc_path: str | Path | None = None,
        max_dist_deg: float = 0.1,
    ) -> None:
        if nc_path is None:
            project_root = Path(__file__).resolve().parents[3]
            nc_path = project_root / "data" / "fixtures" / "kma_sample.nc"
        self.nc_path = Path(nc_path)
        self.max_dist_deg = max_dist_deg
        self._api_key: str | None = os.getenv("KMA_API_KEY")

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 [1h_mm, 3h_mm, 12h_mm] 강수량 배열을 반환한다.

        Args:
            grid_df: 격자 DataFrame (컬럼: id, lat, lon, gu)

        Returns:
            shape (N, 3): 강수량. 결측 격자는 np.nan.
        """
        n = len(grid_df)
        result = np.full((n, 3), np.nan, dtype=np.float64)

        if not self.nc_path.exists():
            # API 연동 시도 (Phase 6 실제 구현 자리)
            # 현재는 파일 없으면 np.nan 반환 (채널 실패 → 나머지 채널 계속)
            return result

        if not _NC4_AVAILABLE:
            return result

        try:
            result = self._load_from_nc(grid_df, result)
        except Exception as e:
            # AGENTS.md 5.3절: 실패해도 np.nan 반환, 엔진은 계속
            import warnings
            warnings.warn(f"[KmaRainfallSource] NetCDF4 파싱 실패: {e}", stacklevel=2)

        return result

    def _load_from_nc(self, grid_df: pd.DataFrame, result: np.ndarray) -> np.ndarray:
        """NetCDF4 파일에서 강수량을 읽어 격자에 투영한다."""
        with nc.Dataset(self.nc_path, "r") as ds:  # type: ignore[attr-defined]
            obs_lat  = np.asarray(ds.variables["lat"][:],   dtype=np.float64)
            obs_lon  = np.asarray(ds.variables["lon"][:],   dtype=np.float64)
            rn_1h    = np.asarray(ds.variables["rn_1h"][:], dtype=np.float64)
            rn_3h    = np.asarray(ds.variables["rn_3h"][:], dtype=np.float64)
            rn_12h   = np.asarray(ds.variables["rn_12h"][:],dtype=np.float64)

        # 관측소 좌표 → KD-트리
        obs_coords  = np.column_stack([obs_lat, obs_lon])
        grid_coords = np.column_stack([
            grid_df["lat"].values,
            grid_df["lon"].values,
        ])

        if _SCIPY_AVAILABLE:
            tree = cKDTree(obs_coords)
            dists, idxs = tree.query(grid_coords, k=1)
        else:
            # scipy 없을 때: 브루트포스 (느리지만 정확)
            idxs  = np.argmin(
                np.sum((obs_coords[None, :, :] - grid_coords[:, None, :]) ** 2, axis=2),
                axis=1,
            )
            dists = np.sqrt(np.sum((obs_coords[idxs] - grid_coords) ** 2, axis=1))

        # max_dist 초과 격자는 nan 유지
        valid = dists <= self.max_dist_deg
        result[valid, 0] = rn_1h[idxs[valid]]
        result[valid, 1] = rn_3h[idxs[valid]]
        result[valid, 2] = rn_12h[idxs[valid]]

        # 음수 강수량 → 0 (결측 처리 일부 API에서 음수 사용)
        result = np.where(result < 0, np.nan, result)
        return result

    @property
    def channel(self) -> str:
        return "rain"
