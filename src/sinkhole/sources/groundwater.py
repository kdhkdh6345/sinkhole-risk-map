"""
sources/groundwater.py — 지하수위 데이터 어댑터 (Phase 6-2)
"""
import os
import json
import time
import sqlite3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .base import GroundwaterSourceAdapter

class SeoulGroundwaterSource(GroundwaterSourceAdapter):
    def __init__(self, json_path: str = "data/fixtures/gw_sample.json", db_path: str = "data/gw_history.db"):
        self.json_path = json_path
        self.db_path = db_path
        self._init_db()
        self._seed_db_if_empty()
        self._is_consecutive_valid = False

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS gw_history (
                    station_id TEXT,
                    timestamp REAL,
                    level REAL
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_gw ON gw_history(station_id, timestamp)')

    def _seed_db_if_empty(self):
        # 30일 이력이 없으면 가짜 이력을 생성하여 DB에 넣는다 (평균 20.0m, std 1.0m)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM gw_history")
            if cur.fetchone()[0] == 0:
                now = time.time()
                data = []
                for st in ["GW_GANGNAM_01", "GW_SEOCHO_01", "GW_JONGNO_01"]:
                    for i in range(30):
                        ts = now - (30 - i) * 86400
                        lvl = np.random.normal(20.0, 1.0)
                        data.append((st, ts, lvl))
                cur.executemany("INSERT INTO gw_history VALUES (?, ?, ?)", data)
                conn.commit()

    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        n_grids = len(grid_df)
        result = np.full(n_grids, np.nan, dtype=np.float32)
        self._is_consecutive_valid = False
        
        try:
            if not os.path.exists(self.json_path):
                print(f"[Warning] GW API Mock file not found: {self.json_path}")
                return result
                
            with open(self.json_path, 'r') as f:
                payload = json.load(f)
                
            stations = payload.get("stations", [])
            if not stations:
                return result
                
            st_coords = []
            st_sigma = []
            
            now = time.time()
            
            with sqlite3.connect(self.db_path) as conn:
                for st in stations:
                    sid = st['station_id']
                    lvl = st['level_m']
                    
                    # 현재 값 삽입
                    conn.execute("INSERT INTO gw_history VALUES (?, ?, ?)", (sid, now, lvl))
                    
                    # 최근 30일 데이터 조회
                    df_hist = pd.read_sql_query(
                        "SELECT level FROM gw_history WHERE station_id = ? AND timestamp >= ? ORDER BY timestamp DESC", 
                        conn, params=(sid, now - 30 * 86400)
                    )
                    
                    if len(df_hist) >= 2:
                        mean_val = df_hist['level'].mean()
                        std_val = df_hist['level'].std()
                        if std_val == 0:
                            std_val = 1e-6
                            
                        # σ 계산 (현재 수위가 과거 대비 얼마나 높은지/낮은지)
                        # 수위 하강이 위험이므로, 낮아지면 σ < 0 이 되도록 (lvl - mean)/std
                        sigma = (lvl - mean_val) / std_val
                        
                        # 2회 연속 하강 조건 체크
                        # 가장 최근(방금 넣은 것)과 그 이전 것을 비교
                        last_2 = df_hist['level'].head(2).values
                        if len(last_2) == 2:
                            sigma_prev = (last_2[1] - mean_val) / std_val
                            # 만약 -1.0(1시그마) 이상 연속 하락했다면 유효로 판단
                            if sigma < -1.0 and sigma_prev < -1.0:
                                self._is_consecutive_valid = True
                        
                        st_coords.append((st['lat'], st['lon']))
                        st_sigma.append(sigma)
            
            if st_coords:
                # KDTree로 보간(Nearest Neighbor)
                tree = cKDTree(st_coords)
                grid_coords = np.column_stack((grid_df['lat'].values, grid_df['lon'].values))
                distances, indices = tree.query(grid_coords, k=1)
                
                # 격자에 σ 투영
                st_sigma = np.array(st_sigma)
                result[:] = st_sigma[indices]

        except Exception as e:
            print(f"[Error] Groundwater Source fetch failed: {e}")
            
        return result

    @property
    def is_consecutive_valid(self) -> bool:
        return self._is_consecutive_valid
