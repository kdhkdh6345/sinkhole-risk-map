"""
sources/groundwater.py — 서울시 지하수위 어댑터 (Phase 6-2 완성)

AGENTS.md 규칙:
  - fusion/ core/ 코드를 한 줄도 수정하지 않는다.
  - 관측정 단위로 30일 이력을 SQLite에 누적.
  - σ 계산 → IDW(역거리 가중) 보간으로 격자 투영.
  - 2회 연속 조건 구현.

데이터 흐름:
  JSON fixture/실제 API → SQLite(gw_history.db) → σ 계산 → IDW 투영 → (N,) 배열
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .base import GroundwaterSourceAdapter

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GW_JSON = _PROJECT_ROOT / "data" / "fixtures" / "gw_sample.json"
_GW_DB   = _PROJECT_ROOT / "data" / "gw_history.db"

# IDW 보간 파라미터
_IDW_POWER   = 2     # 거리 지수 (p=2: 표준 역제곱 거리)
_IDW_MAX_KM  = 20.0  # 투영 최대 반경 (km)
_HIST_DAYS   = 30    # σ 계산에 사용하는 이력 기간
_CONSEC_N    = 2     # 연속 조건 충족 횟수


class SeoulGroundwaterSource(GroundwaterSourceAdapter):
    """서울시 보조지하수 관측망 기반 지하수위 어댑터.

    Args:
        json_path: 관측 데이터 JSON 경로 (기본: data/fixtures/gw_sample.json)
        db_path:   SQLite 이력 DB 경로 (기본: data/gw_history.db)
    """

    def __init__(
        self,
        json_path: str | Path | None = None,
        db_path:   str | Path | None = None,
    ) -> None:
        self.json_path = Path(json_path) if json_path else _GW_JSON
        self.db_path   = Path(db_path)   if db_path   else _GW_DB
        self._is_consecutive_valid = False
        self._init_db()
        self._seed_db_if_empty()

    # ── DB 초기화 ─────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gw_history (
                    station_id TEXT NOT NULL,
                    timestamp  REAL NOT NULL,
                    level      REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gw ON gw_history(station_id, timestamp)"
            )

    def _seed_db_if_empty(self) -> None:
        """DB가 비어 있으면 30일 합성 이력을 생성한다 (σ 계산용 베이스라인)."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM gw_history")
            if cur.fetchone()[0] > 0:
                return

        if not self.json_path.exists():
            return

        with open(self.json_path, encoding="utf-8") as f:
            data = json.load(f)

        now = time.time()
        rows = []
        rng  = np.random.default_rng(42)

        for i, station in enumerate(data.get("stations", [])):
            sid = station.get("id") or station.get("station_id", str(i))
            mean_level = float(station.get("level") or station.get("level_m", 20.0))
            std_level  = float(station.get("std", 1.0))

            # 30일 × 24h × 6회(10분 간격) = 4320 레코드/관측정
            for day in range(30):
                for hour in range(24):
                    ts = now - (30 - day) * 86400 - hour * 3600
                    lv = mean_level + rng.normal(0, std_level * 0.3)
                    rows.append((sid, ts, round(lv, 3)))

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO gw_history (station_id, timestamp, level) VALUES (?,?,?)",
                rows,
            )

    # ── 이력 적재 ─────────────────────────────────────────────────────────
    def _ingest_observation(self, station_id: str, level: float) -> None:
        """단일 관측값을 DB에 적재한다 (실시간 폴링 시 호출)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO gw_history (station_id, timestamp, level) VALUES (?,?,?)",
                (station_id, time.time(), level),
            )
            # 30일 초과 이력 삭제 (DB 크기 제어)
            cutoff = time.time() - _HIST_DAYS * 86400
            conn.execute(
                "DELETE FROM gw_history WHERE station_id=? AND timestamp<?",
                (station_id, cutoff),
            )

    # ── σ 계산 ────────────────────────────────────────────────────────────
    def _compute_sigma(
        self, station_id: str, current_level: float
    ) -> float | None:
        """관측정 30일 이력을 1D 칼만 필터(Kalman Filter) 상태공간 모델에 통과시켜
        예측 잔차(Residual) 기반의 σ 이상도를 반환한다.

        Returns:
            σ 이상도. None이면 이력 부족.
        """
        cutoff = time.time() - _HIST_DAYS * 86400
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT level FROM gw_history WHERE station_id=? AND timestamp>=? ORDER BY timestamp",
                (station_id, cutoff),
            )
            levels = [row[0] for row in cur.fetchall()]

        if len(levels) < 10:
            return None  # 이력 부족

        arr = np.array(levels, dtype=np.float64)
        
        # 1D Kalman Filter 초기화
        x_hat = arr[0]  # 상태 추정치 (초기값은 첫 관측치)
        p = 1.0         # 추정 오차 공분산
        q = 0.05        # 프로세스 노이즈 분산 (추세 변화 수용도)
        r = 0.5         # 측정 노이즈 분산 (센서 오차 수용도)

        # 과거 이력 순차 학습
        for z in arr[1:]:
            # 예측 (Prediction)
            x_pred = x_hat
            p_pred = p + q
            
            # 업데이트 (Update)
            k = p_pred / (p_pred + r)  # 칼만 이득(Kalman Gain)
            x_hat = x_pred + k * (z - x_pred)
            p = (1 - k) * p_pred

        # 현재 수위(current_level)에 대한 다음 시점 예측
        x_pred_next = x_hat
        p_pred_next = p + q

        # 잔차(Residual) 계산: 실제 관측치 - 예측치
        residual = current_level - x_pred_next
        
        # 잔차의 표준편차 (예측 불확실성 + 측정 노이즈)
        residual_std = np.sqrt(p_pred_next + r)

        if residual_std < 1e-6:
            return 0.0

        # Z-Score 형태의 이상도 반환
        return float(residual / residual_std)

    # ── 연속 조건 판정 ────────────────────────────────────────────────────
    def _check_consecutive(self, station_id: str, sigma: float) -> bool:
        """최근 CONSEC_N회 관측 모두 1σ 급락이면 True 반환."""
        cutoff = time.time() - 3 * 3600  # 최근 3시간 이내 관측만 체크
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT level FROM gw_history WHERE station_id=? AND timestamp>=? ORDER BY timestamp DESC LIMIT ?",
                (station_id, cutoff, _CONSEC_N),
            )
            recent = [row[0] for row in cur.fetchall()]

        if len(recent) < _CONSEC_N:
            return False

        # 최근 N회 모두 현재 σ 방향과 같은지 확인 (단순화 버전)
        arr_recent = np.array(recent, dtype=np.float64)

        # 30일 기준 통계 재사용
        all_cutoff = time.time() - _HIST_DAYS * 86400
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT level FROM gw_history WHERE station_id=? AND timestamp>=?",
                (station_id, all_cutoff),
            )
            all_levels = np.array([r[0] for r in cur.fetchall()], dtype=np.float64)

        if len(all_levels) < 10:
            return False

        mean, std = all_levels.mean(), all_levels.std()
        if std < 1e-6:
            return False

        sigmas_recent = (arr_recent - mean) / std
        # 최근 N회 중 N회 모두 drop < -1σ 이면 연속 조건 충족
        return bool(np.sum(sigmas_recent < -1.0) >= _CONSEC_N)

    # ── fetch() ──────────────────────────────────────────────────────────
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        """격자별 σ 이상도 배열을 반환한다.

        Args:
            grid_df: 격자 DataFrame (id, lat, lon, gu)

        Returns:
            shape (N,): σ 이상도. 결측은 np.nan.
        """
        n = len(grid_df)
        result = np.full(n, np.nan, dtype=np.float64)

        if not self.json_path.exists():
            return result

        try:
            with open(self.json_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            warnings.warn(f"[SeoulGroundwaterSource] JSON 파싱 실패: {e}", stacklevel=2)
            return result

        stations = data.get("stations", [])
        if not stations:
            return result

        # 관측정별 σ 계산
        station_lats, station_lons, station_sigmas = [], [], []
        consec_flags = []

        for station in stations:
            sid   = station.get("id") or station.get("station_id", "unknown")
            slat  = float(station["lat"])
            slon  = float(station["lon"])
            level = float(station.get("level") or station.get("level_m", 20.0))

            # DB에 현재 관측값 적재
            self._ingest_observation(sid, level)

            sigma = self._compute_sigma(sid, level)
            if sigma is None:
                continue

            consec = self._check_consecutive(sid, sigma)

            station_lats.append(slat)
            station_lons.append(slon)
            station_sigmas.append(sigma)
            consec_flags.append(consec)

        if not station_lats:
            return result

        # 연속 조건: 전체 관측정의 과반이 충족하면 True
        self._is_consecutive_valid = (
            sum(consec_flags) >= max(1, len(consec_flags) // 2)
        )

        # IDW 보간으로 격자 투영
        st_coords   = np.column_stack([station_lats, station_lons])
        grid_coords = np.column_stack([grid_df["lat"].values, grid_df["lon"].values])
        st_sigmas   = np.array(station_sigmas, dtype=np.float64)

        result = _idw_interpolate(st_coords, st_sigmas, grid_coords, power=_IDW_POWER, max_dist_deg=_IDW_MAX_KM / 111.0)
        return result

    @property
    def is_consecutive_valid(self) -> bool:
        """연속 2회 조건 충족 여부."""
        return self._is_consecutive_valid

    @property
    def channel(self) -> str:
        return "groundwater"


# ── IDW 보간 유틸 ─────────────────────────────────────────────────────────

def _idw_interpolate(
    obs_coords: np.ndarray,
    obs_values: np.ndarray,
    target_coords: np.ndarray,
    power: float = 2,
    max_dist_deg: float = 0.2,
) -> np.ndarray:
    """역거리 가중(IDW) 보간.

    Args:
        obs_coords:    shape (M, 2): 관측소 [lat, lon]
        obs_values:    shape (M,): 관측소별 σ 값
        target_coords: shape (N, 2): 격자 [lat, lon]
        power:         거리 지수
        max_dist_deg:  최대 반경 (도 단위). 초과 격자는 np.nan.

    Returns:
        shape (N,): 보간된 σ 값.
    """
    n_targets = len(target_coords)
    result = np.full(n_targets, np.nan, dtype=np.float64)

    for i in range(n_targets):
        target = target_coords[i]
        diffs  = obs_coords - target
        dists  = np.sqrt(np.sum(diffs ** 2, axis=1))

        mask = dists <= max_dist_deg
        if not np.any(mask):
            continue

        d_masked = dists[mask]
        v_masked = obs_values[mask]

        # 완전 겹침 처리
        zero_dist = d_masked == 0.0
        if np.any(zero_dist):
            result[i] = v_masked[zero_dist][0]
            continue

        weights = 1.0 / (d_masked ** power)
        result[i] = np.dot(weights, v_masked) / weights.sum()

    return result
