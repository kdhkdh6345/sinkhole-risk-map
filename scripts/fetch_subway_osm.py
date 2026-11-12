"""
fetch_subway_osm.py — OpenStreetMap에서 서울 지하철 실제 노선 좌표를 받아 GeoJSON으로 저장

데이터: OpenStreetMap Overpass API, route=subway 관계(relation) (© OpenStreetMap contributors, ODbL)
출력: web/data/snapshot_subway_osm.json  (GeoJSON. 파일명이 snapshot*.json 이라 기존 워크플로가 자동 커밋)

노선 좌표는 거의 바뀌지 않으므로 파일이 없거나 refresh_days(30일)보다 오래됐을 때만 새로 받는다.
run_snapshot.py --mode real 실행 중에 자동 호출된다. 실패해도 다른 처리를 막지 않는다.

직접 실행: python scripts/fetch_subway_osm.py [--force]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data" / "snapshot_subway_osm.json"
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
BBOX = (37.40, 126.75, 37.72, 127.20)  # 남, 서, 북, 동 (서울 격자 범위보다 약간 넓게)
QUERY = f"""[out:json][timeout:120];
relation["route"="subway"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out geom;"""
REFRESH_DAYS = 30


def to_geojson(osm: dict, fetched_at: str) -> dict:
    """Overpass 응답(relation + member geometry) → 노선별 MultiLineString GeoJSON."""
    features = []
    seen = set()
    for el in osm.get("elements", []):
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {})
        lines = []
        for m in el.get("members", []):
            if m.get("type") != "way" or not m.get("geometry"):
                continue
            if m.get("role") not in ("", None):  # 정류장·플랫폼 등은 제외, 선로만
                continue
            coords = [[round(p["lon"], 5), round(p["lat"], 5)] for p in m["geometry"]]
            key = (coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
            rev = (coords[-1][0], coords[-1][1], coords[0][0], coords[0][1])  # 반대 방향 같은 구간
            if len(coords) >= 2 and key not in seen and rev not in seen:
                seen.add(key)
                lines.append(coords)
        if not lines:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": lines},
            "properties": {
                "name": tags.get("name:ko") or tags.get("name") or "지하철",
                "ref": tags.get("ref", ""),
                "color": tags.get("colour", "#0096FF") if str(tags.get("colour", "")).startswith("#") else "#0096FF",
                "type": "subway",
                "osm_id": el.get("id"),
            },
        })
    return {"type": "FeatureCollection", "features": features,
            "meta": {"source": "© OpenStreetMap contributors (ODbL), Overpass API", "fetched_at": fetched_at}}


def needs_refresh(now: datetime) -> bool:
    try:
        meta = json.loads(OUT.read_text(encoding="utf-8")).get("meta", {})
        return now - datetime.fromisoformat(meta["fetched_at"]) > timedelta(days=REFRESH_DAYS)
    except Exception:
        return True


def fetch(force: bool = False) -> str:
    """필요할 때만 받아 저장. 결과 설명 문자열을 반환."""
    now = datetime.now(tz=timezone(timedelta(hours=9)))
    if not force and not needs_refresh(now):
        return "최근 수집본 사용 (30일 주기 갱신)"
    try:
        import requests
    except ImportError:
        return "requests 미설치 — 건너뜀"
    last_err = ""
    for url in ENDPOINTS:
        try:
            r = requests.post(url, data={"data": QUERY}, timeout=180,
                              headers={"User-Agent": "sinkhole-risk-map (student research project)"})
            r.raise_for_status()
            gj = to_geojson(r.json(), now.isoformat(timespec="seconds"))
            if not gj["features"]:
                last_err = "노선 0개"
                continue
            OUT.write_text(json.dumps(gj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n = sum(len(f["geometry"]["coordinates"]) for f in gj["features"])
            return f"OpenStreetMap 노선 {len(gj['features'])}개(선로 구간 {n}개) 저장"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:80]}"
    return f"수집 실패 ({last_err}) — 기존 파일 유지"


if __name__ == "__main__":
    print(fetch(force="--force" in sys.argv))
