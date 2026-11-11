"""
sources/gw_live.py — 국가지하수측정망 시간자료 실시간 지하수위 어댑터 (Phase 6-2)

데이터: 국가지하수정보센터(GIMS) '국가지하수측정자료조회서비스(시간자료)'
  요청: gennum(관측소번호), begindate/enddate(YYYYMMDD), datatype=1(실시간)
관측정 목록: data/raw/gw_stations_seoul.csv (서울 격자 10km 이내 21개, 공공데이터포털 위경도 파일)

계산 (AGENTS.md 6절):
  관측정마다 최근 history_days(30일) 수위의 평균·표준편차로 최신 수위의 σ 이상도를 구한다.
  σ < 0 이면 수위 하강. 최근 2회 관측이 모두 -1σ 이하이면 '연속 조건' 충족.
  관측정 σ → IDW 보간으로 격자 투영 (기존 groundwater.py의 보간 함수 재사용).

호출량 제어: refresh_minutes 이내에 받은 관측정 결과가 직전 스냅샷(source_cache)에 있으면 재사용.
실패 시: 기존 샘플 어댑터(SeoulGroundwaterSource)로 대체, origin="fixture".
키: 환경변수 GW_API_KEY (GitHub Secrets).
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

from .base import GroundwaterSourceAdapter
from .groundwater import SeoulGroundwaterSource, _idw_interpolate

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_YAML = PROJECT_ROOT / "config" / "weights.yaml"
STATIONS_CSV = PROJECT_ROOT / "data" / "raw" / "gw_stations_seoul.csv"
PREV_SNAPSHOT = PROJECT_ROOT / "web" / "data" / "snapshot_calm.json"
URL = "http://www.gims.go.kr/api/data/observationStationTimeService/observationStationTimeService"

LEVEL_KEYS = ("elev", "wlevel", "gwl", "level")  # 수위 표고(클수록 수위 높음)
DEPTH_KEYS = ("lev",)                              # 지표에서 수면까지 깊이(클수록 수위 낮음)
TIME_KEYS = ("ymdh", "ymdhm", "time", "hh", "hour", "hhmm")


def _records(obj) -> list[dict]:
    """응답 JSON 어디에 있든 관측 레코드(dict 목록)를 찾아 반환."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and ("ymd" in obj[0] or "gennum" in obj[0]):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            found = _records(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _records(v)
            if found:
                return found
    return []


def _series(recs: list[dict]) -> tuple[np.ndarray, str, str]:
    """레코드 → (시간순 수위 배열(클수록 높음), 마지막 시각 문자열, 사용한 항목명)."""
    keys = {k.lower(): k for k in recs[0]}
    lk = next((keys[k] for k in LEVEL_KEYS if k in keys), None)
    sign = 1.0
    if lk is None:
        lk = next((keys[k] for k in DEPTH_KEYS if k in keys), None)
        sign = -1.0  # 깊이는 부호를 뒤집어 '수위'로 만든다
    if lk is None:
        raise ValueError(f"수위 항목을 찾지 못함 (항목: {list(recs[0])})")
    tk = next((keys[k] for k in TIME_KEYS if k in keys), None)

    def stamp(r):
        return f"{r.get(keys.get('ymd', 'ymd'), '')}{str(r.get(tk, '')).zfill(2) if tk else ''}"

    rows = []
    for r in recs:
        try:
            rows.append((stamp(r), sign * float(r[lk])))
        except (TypeError, ValueError, KeyError):
            continue
    rows.sort(key=lambda x: x[0])
    vals = np.array([v for _, v in rows], dtype=np.float64)
    return vals, (rows[-1][0] if rows else ""), (lk if sign > 0 else f"-{lk}")


class GimsGroundwaterSource(GroundwaterSourceAdapter):
    """국가지하수측정망 시간자료 → 격자별 σ 이상도."""

    origin = "fixture"

    def __init__(
        self,
        api_key: str | None = None,
        now_fn: Callable[[], datetime] | None = None,
        prev_snapshot: Path | None = None,
        stations_csv: Path | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._key = api_key if api_key is not None else os.getenv("GW_API_KEY")
        self._now_fn = now_fn or (lambda: datetime.now(tz=KST))
        self._prev = prev_snapshot or PREV_SNAPSHOT
        self._stations = pd.read_csv(stations_csv or STATIONS_CSV, comment="#")
        with open(WEIGHTS_YAML, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)["realtime"]["groundwater"]
        self._days = int(cfg.get("history_days", 30))
        self._stale = timedelta(hours=float(cfg.get("stale_hours", 48)))
        self._refresh = timedelta(minutes=float(cfg.get("refresh_minutes", 30)))
        self.timeout = timeout
        self.detail = ""
        self.fetched_at: str | None = None
        self.cache: dict | None = None
        self._consec: np.ndarray | bool = False
        self._errors: list[str] = []
        self._fallback_age = timedelta(hours=float(cfg.get("fallback_hours", 6)))

    # ── 관측정 1곳 ───────────────────────────────────────────────────────
    def _station(self, row) -> dict | None:
        now = self._now_fn()
        params = {"KEY": self._key, "type": "JSON", "gennum": int(row.gennum), "datatype": 1,
                  "begindate": (now - timedelta(days=self._days)).strftime("%Y%m%d"),
                  "enddate": now.strftime("%Y%m%d")}
        try:
            r = requests.get(URL, params=params, timeout=self.timeout)
            r.raise_for_status()
            payload = r.json()
            recs = _records(payload)
            if not recs:  # 오류 응답: resultCode를 기록해 원인을 로그로 남긴다
                code = ((payload or {}).get("response") or {}).get("resultCode", "빈 응답")
                self._errors.append(str(code))
                return None
            vals, last, key = _series(recs)
        except Exception as e:
            self._errors.append(type(e).__name__)
            return None
        if len(vals) < 10:
            return None
        try:  # 마지막 관측이 너무 오래됐으면 제외 (시각 형식을 모르면 검사 생략)
            last_dt = datetime.strptime(last[:10] if len(last) >= 10 else last[:8], "%Y%m%d%H" if len(last) >= 10 else "%Y%m%d").replace(tzinfo=KST)
            if now - last_dt > self._stale + timedelta(days=0 if len(last) >= 10 else 1):
                return None
        except ValueError:
            pass
        mean, std = vals.mean(), vals.std()
        if std < 1e-6:
            return None
        z = (vals - mean) / std
        return {"gennum": int(row.gennum), "name": str(row.name), "lat": float(row.lat), "lon": float(row.lon),
                "sigma": round(float(z[-1]), 3), "consec": bool(np.all(z[-2:] <= -1.0)),
                "n": int(len(vals)), "last": last, "key": key}

    # ── 재사용 ───────────────────────────────────────────────────────────
    def _reuse(self, max_age: timedelta | None = None) -> list[dict] | None:
        try:
            with open(self._prev, encoding="utf-8") as f:
                snap = json.load(f)
            cache = (snap.get("source_cache") or {}).get("groundwater") or {}
            fetched = datetime.fromisoformat(cache["fetched_at"])
        except Exception:
            return None
        if self._now_fn() - fetched > (max_age or self._refresh) or not cache.get("stations"):
            return None
        self.fetched_at = cache["fetched_at"]
        return cache["stations"]

    # ── fetch ───────────────────────────────────────────────────────────
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        reason = "GW_API_KEY 없음"
        if self._key and requests is not None:
            stations = self._reuse()
            reused = stations is not None
            if not reused:
                with ThreadPoolExecutor(max_workers=6) as ex:
                    stations = [s for s in ex.map(self._station, self._stations.itertuples()) if s]
                self.fetched_at = self._now_fn().isoformat(timespec="seconds")
            if stations:
                return self._project(grid_df, stations, reused)
            from collections import Counter
            errs = ", ".join(f"{k}×{v}" for k, v in Counter(self._errors).most_common(3)) or "-"
            reason = f"응답 관측정 0곳 (요청 {len(self._stations)}곳, 오류: {errs})"
            # 일시적 실패(호출 한도 등)면 직전 정상값을 최대 fallback_hours까지 계속 사용
            stations = self._reuse(self._fallback_age)
            if stations:
                out = self._project(grid_df, stations, True)
                self.detail += f" — 이번 호출 실패({errs})로 직전 값 사용"
                return out

        self.origin, self.fetched_at, self.cache = "fixture", None, None
        self.detail = f"실시간 실패 → 샘플 사용 / {reason}"
        fallback = SeoulGroundwaterSource()
        out = fallback.fetch(grid_df)
        self._consec = fallback.is_consecutive_valid
        return out

    def _project(self, grid_df: pd.DataFrame, stations: list[dict], reused: bool) -> np.ndarray:
        st_ll = np.array([[s["lat"], s["lon"]] for s in stations])
        grid_ll = np.column_stack([grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy()])
        sig = _idw_interpolate(st_ll, np.array([s["sigma"] for s in stations]), grid_ll,
                               power=2, max_dist_deg=20.0 / 111.0)
        # 연속 조건: 격자마다 가장 가까운 관측정의 판정을 따른다
        nearest = ((grid_ll[:, None, :] - st_ll[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        self._consec = np.array([stations[i]["consec"] for i in nearest], dtype=bool)
        self.origin = "live"
        self.cache = {"fetched_at": self.fetched_at, "stations": stations}
        drop = sum(1 for s in stations if s["sigma"] <= -1)
        t = datetime.fromisoformat(self.fetched_at)
        self.detail = (f"국가지하수측정망 시간자료 {t:%H:%M} 수집{' 재사용' if reused else ''}, 관측정 {len(stations)}곳"
                       f" (항목 {stations[0]['key']}), -1σ 이하 하강 {drop}곳")
        return sig

    @property
    def is_consecutive_valid(self) -> np.ndarray | bool:
        return self._consec

    @property
    def channel(self) -> str:
        return "groundwater"
