"""
sources/sewer_live.py — 서울시 하수관로 실시간 수위 (지도 표시용, 위험도 점수에는 미반영)

데이터: 서울 열린데이터광장 '서울시 하수관로 수위 현황' (OA-2527, 30분 간격)
  요청: /{KEY}/json/DrainpipeMonitoringInfo/{시작}/{끝}/{구분코드 01~25}/{YYYYMMDDHH}/{YYYYMMDDHH}
  응답: UNQ_NO(측정소), SE_NM(구 이름), MSRMT_YMD(측정시각), MSRMT_WATL(수위 m), SGN_STTS(통신상태), PSTN_INFO(주소)

측정소 좌표가 제공되지 않으므로(주소 문자열만 있음) 구 단위로 집계한다:
  구별 측정소 수, 최고 수위, 평균 수위, 최고 수위 측정소의 주소, 최근 측정 시각.

호출량 제어: refresh_minutes(30분) 이내에 받은 결과가 직전 스냅샷에 있으면 재사용.
키: 환경변수 SEOUL_API_KEY.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PREV_SNAPSHOT = PROJECT_ROOT / "web" / "data" / "snapshot_calm.json"
URL = "http://openapi.seoul.go.kr:8088/{key}/json/DrainpipeMonitoringInfo/1/1000/{code}/{t1}/{t2}"
GU_CODES = [f"{i:02d}" for i in range(1, 26)]


def _gu_name(se_nm: str) -> str:
    """'종로' → '종로구', '중' → '중구' (이미 '구'로 끝나면 그대로)."""
    se_nm = (se_nm or "").strip()
    return se_nm if se_nm.endswith("구") else f"{se_nm}구"


def summarize(rows: list[dict]) -> dict | None:
    """한 구의 응답 행 → 측정소별 최신값으로 줄인 뒤 구 단위 요약."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("SGN_STTS") and "양호" not in str(r.get("SGN_STTS")):
            continue  # 통신 불량 측정값은 제외
        try:
            level = float(r.get("MSRMT_WATL"))
        except (TypeError, ValueError):
            continue
        uid, t = str(r.get("UNQ_NO")), str(r.get("MSRMT_YMD", ""))
        if uid not in latest or t > latest[uid]["t"]:
            latest[uid] = {"t": t, "level": level, "addr": str(r.get("PSTN_INFO", "")), "gu": _gu_name(r.get("SE_NM"))}
    if not latest:
        return None
    vals = list(latest.values())
    top = max(vals, key=lambda v: v["level"])
    return {
        "gu": vals[0]["gu"],
        "n": len(vals),
        "max_m": round(top["level"], 2),
        "mean_m": round(sum(v["level"] for v in vals) / len(vals), 3),
        "max_addr": top["addr"],
        "time": max(v["t"] for v in vals)[:16],
    }


class SeoulSewerLevelSource:
    def __init__(self, api_key: str | None = None, now_fn: Callable[[], datetime] | None = None,
                 prev_snapshot: Path | None = None, refresh_minutes: float = 30, timeout: float = 20.0):
        self._key = api_key if api_key is not None else os.getenv("SEOUL_API_KEY")
        self._now_fn = now_fn or (lambda: datetime.now(tz=KST))
        self._prev = prev_snapshot or PREV_SNAPSHOT
        self._refresh = timedelta(minutes=refresh_minutes)
        self.timeout = timeout
        self.detail = ""

    def _get(self, code: str, t1: str, t2: str) -> dict | None:
        try:
            r = requests.get(URL.format(key=self._key, code=code, t1=t1, t2=t2), timeout=self.timeout)
            r.raise_for_status()
            rows = (r.json().get("DrainpipeMonitoringInfo") or {}).get("row") or []
            return summarize(rows)
        except Exception:
            return None

    def _reuse(self) -> dict | None:
        try:
            prev = json.loads(self._prev.read_text(encoding="utf-8")).get("sewer") or {}
            fetched = datetime.fromisoformat(prev["fetched_at"])
        except Exception:
            return None
        if self._now_fn() - fetched <= self._refresh and prev.get("by_gu"):
            return prev
        return None

    def fetch(self) -> dict | None:
        """구별 요약 dict 반환 (스냅샷의 'sewer' 필드). 실패 시 None."""
        if not self._key or requests is None:
            self.detail = "SEOUL_API_KEY 없음"
            return None
        prev = self._reuse()
        if prev:
            self.detail = f"하수관로 수위 {prev['fetched_at'][11:16]} 수집값 재사용"
            return prev
        now = self._now_fn()
        t1, t2 = (now - timedelta(hours=1)).strftime("%Y%m%d%H"), now.strftime("%Y%m%d%H")
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = [s for s in ex.map(lambda c: self._get(c, t1, t2), GU_CODES) if s]
        if not results:
            self.detail = "하수관로 수위 응답 0개 구"
            return None
        by_gu = {s["gu"]: s for s in results}
        n = sum(s["n"] for s in results)
        self.detail = f"하수관로 수위 {now:%H:%M} 수집, {len(by_gu)}개 구·측정소 {n}곳"
        return {"fetched_at": now.isoformat(timespec="seconds"), "by_gu": by_gu,
                "source": "서울 열린데이터광장 '서울시 하수관로 수위 현황'"}
