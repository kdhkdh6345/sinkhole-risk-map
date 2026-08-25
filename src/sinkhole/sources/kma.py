"""
sources/kma.py — 기상청 강수 데이터 어댑터 (Phase 6-1)
"""
import os
import numpy as np
import pandas as pd
import netCDF4 as nc
from scipy.spatial import cKDTree

from .base import RainSourceAdapter

class KmaRainfallSource(RainSourceAdapter):
    def __init__(self, nc_path: str = "data/fixtures/kma_sample.nc"):
        self.nc_path = nc_path

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        # 반환 배열: shape (N, 3) -> [1h_mm, 3h_mm, 12h_mm]
        n_grids = len(grid_df)
        result = np.full((n_grids, 3), np.nan, dtype=np.float32)
        
        try:
            if not os.path.exists(self.nc_path):
                print(f"[Warning] KMA API Mock file not found: {self.nc_path}")
                return result
                
            with nc.Dataset(self.nc_path, 'r') as ds:
                lat = ds.variables['lat'][:]
                lon = ds.variables['lon'][:]
                rn_1h = ds.variables['rn_1h'][:]
                rn_3h = ds.variables['rn_3h'][:]
                rn_12h = ds.variables['rn_12h'][:]
                
                # KDTree를 사용해 격자 포인트에 가장 가까운 NC 포인트 매핑
                nc_coords = np.column_stack((lat, lon))
                grid_coords = np.column_stack((grid_df['lat'].values, grid_df['lon'].values))
                
                tree = cKDTree(nc_coords)
                # k=1 로 가장 가까운 인덱스 탐색
                distances, indices = tree.query(grid_coords, k=1)
                
                # 매핑된 인덱스로 데이터 추출
                result[:, 0] = rn_1h[indices]
                result[:, 1] = rn_3h[indices]
                result[:, 2] = rn_12h[indices]
                
        except Exception as e:
            print(f"[Error] KMA Rainfall Source fetch failed: {e}")
            
        return result
