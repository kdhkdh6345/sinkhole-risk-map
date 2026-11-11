"""
sources/traffic_live.py — 서울 실시간 도시데이터(도로소통) 교통 어댑터 (Phase 6-3)

데이터: 서울 열린데이터광장 '서울시 실시간 도시데이터' (citydata)
  - 주요 장소(POI001~)마다 주변 도로 링크의 실시간 소통 등급(IDX: 원활/서행/정체)과
    링크 좌표(XYLIST)를 준다.
  - 링크 중점 좌표를 격자에 배정하고, 소통 등급을 저하율(0~1)로 바꿔 격자별 평균을 낸다.
  - 도시데이터가 다루는 장소 주변만 값이 있다. 그 밖의 격자는 0(정체 정보 없음)으로 둔다.

호출량 제어:
  장소마다 1회씩 호출하므로, refresh_minutes(기본 30분) 이내에 받은 값이 있으면 재사용한다.
  재사용 값은 직전에 커밋된 web/data/snapshot_calm.json의 t 값과 source_time에서 읽는다.

실패 시: 기존 고정 샘플(SeoulTrafficSource)로 대체하고 origin="fixture"로 표시한다.
키: 환경변수 SEOUL_API_KEY (GitHub Secrets).
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import yaml

from .base import TrafficSourceAdapter
from .traffic import SeoulTrafficSource

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover
    cKDTree = None  # type: ignore[assignment]

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_YAML = PROJECT_ROOT / "config" / "weights.yaml"
PREV_SNAPSHOT = PROJECT_ROOT / "web" / "data" / "snapshot_calm.json"
BASE_URL = "http://openapi.seoul.go.kr:8088/{key}/json/citydata/1/5/{area}"
AREA_CODES = [f"POI{i:03d}" for i in range(1, 131)]  # 존재하지 않는 코드는 오류 응답 → 건너뜀


def _parse_links(payload: dict, congestion: dict) -> list[tuple[str, float, float, float]]:
    """도시데이터 응답 → [(LINK_ID, lat, lon, 저하율)]. 링크 중점 좌표 사용."""
    road = (payload.get("CITYDATA") or {}).get("ROAD_TRAFFIC_STTS") or {}
    links = road.get("ROAD_TRAFFIC_STTS") if isinstance(road, dict) else road
    out = []
    for lk in links or []:
        ratio = congestion.get(str(lk.get("IDX", "")).strip())
        if ratio is None:
            continue
        pts = []
        for xy in str(lk.get("XYLIST") or "").split("|"):
            try:
                lon, lat = (float(v) for v in xy.split("_")[:2])
                pts.append((lat, lon))
            except ValueError:
                continue
        if not pts:
            continue
        lat, lon = np.mean(pts, axis=0)
        out.append((str(lk.get("LINK_ID", "")), float(lat), float(lon), float(ratio)))
    return out


class SeoulCitydataTrafficSource(TrafficSourceAdapter):
    """서울 실시간 도시데이터 도로소통 → 격자별 교통 저하율."""

    origin = "fixture"

    def __init__(
        self,
        api_key: str | None = None,
        now_fn: Callable[[], datetime] | None = None,
        prev_snapshot: Path | None = None,
        area_codes: list[str] | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._key = api_key if api_key is not None else os.getenv("SEOUL_API_KEY")
        self._now_fn = now_fn or (lambda: datetime.now(tz=KST))
        self._prev = prev_snapshot or PREV_SNAPSHOT
        self._areas = area_codes or AREA_CODES
        self.timeout = timeout
        with open(WEIGHTS_YAML, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)["realtime"]["traffic"]
        self._congestion = cfg.get("congestion", {"원활": 0.0, "서행": 0.5, "정체": 1.0})
        self._refresh = timedelta(minutes=float(cfg.get("refresh_minutes", 30)))
        self._radius = float(cfg.get("link_radius_deg", 0.005))
        self._t_max = float(cfg.get("max", 5))
        self.detail = ""
        self.fetched_at: str | None = None

    # ── 재사용: 직전 스냅샷 ───────────────────────────────────────────────
    def _reuse_previous(self, grid_df: pd.DataFrame) -> np.ndarray | None:
        try:
            with open(self._prev, encoding="utf-8") as f:
                snap = json.load(f)
        except Exception:
            return None
        if (snap.get("source_status") or {}).get("traffic") != "ok":
            return None
        ts = (snap.get("source_time") or {}).get("traffic")
        if not ts:
            return None
        fetched = datetime.fromisoformat(ts)
        if self._now_fn() - fetched > self._refresh:
            return None
        t_by_id = {c["id"]: c.get("t") or 0.0 for c in snap.get("cells", [])}
        ids = grid_df["id"].tolist()
        if not all(i in t_by_id for i in ids):
            return None
        self.fetched_at = ts
        self.detail = f"도시데이터 도로소통 {fetched:%H:%M} 수집값 재사용 ({int(self._refresh.total_seconds() // 60)}분 주기 갱신)"
        return np.array([t_by_id[i] / self._t_max for i in ids], dtype=np.float64)

    # ── 새로 받기 ─────────────────────────────────────────────────────────
    def _get_area(self, area: str) -> list[tuple[str, float, float, float]]:
        r = requests.get(BASE_URL.format(key=self._key, area=area), timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        code = (payload.get("RESULT") or {}).get("RESULT.CODE", "")
        if code and code != "INFO-000":
            return []
        return _parse_links(payload, self._congestion)

    def _collect(self) -> tuple[list[tuple[str, float, float, float]], int]:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(self._safe_get, self._areas))
        places_ok = sum(1 for r in results if r)
        uniq = {}
        for res in results:
            for link_id, lat, lon, ratio in res:
                uniq[link_id] = (lat, lon, ratio)
        return [(k, *v) for k, v in uniq.items()], places_ok

    def _safe_get(self, area: str) -> list[tuple[str, float, float, float]]:
        try:
            return self._get_area(area)
        except Exception:
            return []

    def _project(self, grid_df: pd.DataFrame, links: list) -> tuple[np.ndarray, int]:
        grid_ll = np.column_stack([grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy()])
        link_ll = np.array([[lat, lon] for _, lat, lon, _ in links], dtype=np.float64)
        ratio = np.array([r for *_, r in links], dtype=np.float64)
        out = np.zeros(len(grid_ll), dtype=np.float64)  # 정보 없는 격자는 0 (정체 정보 없음)
        covered = 0
        if cKDTree is not None:
            neigh = cKDTree(link_ll).query_ball_point(grid_ll, r=self._radius)
        else:
            d = np.sqrt(((grid_ll[:, None, :] - link_ll[None, :, :]) ** 2).sum(axis=2))
            neigh = [np.where(row <= self._radius)[0].tolist() for row in d]
        for i, idx in enumerate(neigh):
            if idx:
                out[i] = ratio[idx].mean()
                covered += 1
        return out, covered

    # ── fetch ───────────────────────────────────────────────────────────
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        if self._key and requests is not None:
            reused = self._reuse_previous(grid_df)
            if reused is not None:
                self.origin = "live"
                return reused
            links, places_ok = self._collect()
            if links:
                out, covered = self._project(grid_df, links)
                now = self._now_fn()
                self.origin = "live"
                self.fetched_at = now.isoformat(timespec="seconds")
                self.detail = (f"도시데이터 도로소통 {now:%H:%M} KST, 장소 {places_ok}곳·링크 {len(links)}개, "
                               f"정보 있는 격자 {covered}개 (나머지 0)")
                return out
            reason = f"응답 장소 0곳 (요청 {len(self._areas)}곳)"
        else:
            reason = "SEOUL_API_KEY 없음"

        self.origin = "fixture"
        self.fetched_at = None
        self.detail = f"실시간 실패 → 샘플 파일 사용 / {reason}"
        return SeoulTrafficSource(json_path=str(PROJECT_ROOT / "data" / "fixtures" / "traffic_sample.json")).fetch(grid_df)

    @property
    def channel(self) -> str:
        return "traffic"
