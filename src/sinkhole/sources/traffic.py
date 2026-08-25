import os
import json
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .base import TrafficSourceAdapter

class SeoulTrafficSource(TrafficSourceAdapter):
    def __init__(self, json_path: str = "data/fixtures/traffic_sample.json"):
        self.json_path = json_path

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        n_grids = len(grid_df)
        result = np.zeros(n_grids, dtype=np.float32)
        
        try:
            if not os.path.exists(self.json_path):
                print(f"[Warning] Traffic API Mock file not found: {self.json_path}")
                return result
                
            with open(self.json_path, 'r') as f:
                payload = json.load(f)
                
            links = payload.get("links", [])
            if not links:
                return result
                
            link_coords = []
            link_congestion = []
            
            for l in links:
                lat = l['start_lat']
                lon = l['start_lon']
                speed = l['speed_kmh']
                
                # 정체 저하율 (Congestion Ratio) 
                # 기준속도 60km/h 대비 얼마나 느려졌는지 계산. (0.0 ~ 1.0)
                # 속도가 0에 가까울수록 1.0(정체), 60 이상이면 0.0(원활)
                ratio = 1.0 - min(speed / 60.0, 1.0)
                ratio = max(ratio, 0.0)
                
                link_coords.append((lat, lon))
                link_congestion.append(ratio)
                
            if link_coords:
                tree = cKDTree(link_coords)
                grid_coords = np.column_stack((grid_df['lat'].values, grid_df['lon'].values))
                distances, indices = tree.query(grid_coords, k=1)
                
                link_congestion = np.array(link_congestion)
                result[:] = link_congestion[indices]
                
        except Exception as e:
            print(f"[Error] Traffic Source fetch failed: {e}")
            
        return result
