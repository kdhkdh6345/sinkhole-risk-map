"""
fetch_sinkhole_history.py — 국토교통부 지하안전정보(JIS) 실제 지반침하 사고를 받아 지도용 파일로 저장

API (공공데이터포털 '국토교통부_지하안전정보', 활용가이드 v1.4):
  getSubsidenceList01  sagoDateFrom, sagoDateTo(YYYYMMDD), numOfRows, pageNo
                       → sagoNo, siDo, siGunGu, sagoDetail, sagoDate
  getSubsidenceInfo01  sagoNo → dong, addr, sinkWidth, sinkExtend, sinkDepth, grdKind, sagoDetail, deathCnt …
응답에 좌표가 없으므로 '시군구 + 읍면동'을 행정동 경계(seoul_dong.geojson)와 이름으로 맞춰
그 동(들)의 중심에 배치한다(동 단위 위치). 동을 찾지 못하면 구 중심에 배치한다.

출력: web/data/snapshot_sinkhole_history.json (파일명이 snapshot*.json 이라 기존 워크플로가 자동 커밋)
  events  : 서울 사고 목록 (위치 정밀도 loc_level = "동" 또는 "구")
  by_grid : 격자 id → 지도 '과거 싱크홀 발생 현황' 레이어용 요약
  by_dong : 행정동명 → {count, grade} (지도 '동별 발생 건수' 레이어용)
갱신: 하루 1회 (이미 받은 사고의 상세정보는 다시 요청하지 않음). 키: 환경변수 JIS_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data" / "snapshot_sinkhole_history.json"
STATUS = ROOT / "web" / "data" / "snapshot_sinkhole_history_status.json"  # 마지막 시도 결과 (실패 원인 확인용)
DONG_GEO = ROOT / "web" / "data" / "seoul_dong.geojson"
GU_GEO = ROOT / "data" / "raw" / "seoul_gu.geojson"
GRID = ROOT / "web" / "data" / "grid.json"
BASE = "https://apis.data.go.kr/1613000/undergroundsafetyinfo01"  # 공공데이터포털 End Point (기관코드 1613000)
KST = timezone(timedelta(hours=9))
START = "20180101"   # 지하안전법 시행(2018.1) 이후 자료
REFRESH_HOURS = 24
RETRY_MINUTES = 60   # 실패하면 5분마다 재시도하지 않고 1시간 뒤에 다시 시도 (일일 호출 한도 보호)
PAGE_ROWS = 100      # 한 페이지 건수 (너무 크면 400 오류)


# ── 응답 파싱 (JSON/XML 모두 대응) ────────────────────────────────────────
def parse_items(text: str) -> tuple[list[dict], int | None, str]:
    """응답 본문 → (item 목록, totalCount, resultCode)."""
    text = text.strip()
    if text.startswith("{"):
        d = json.loads(text)
        resp = d.get("response", d)
        header = resp.get("header", {})
        body = resp.get("body", {}) or {}
        items = (body.get("items") or {})
        items = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(items, dict):
            items = [items]
        total = body.get("totalCount")
        code = str(header.get("resultCode", "") or resp.get("resultCode", ""))
        msg = str(header.get("resultMsg", "") or resp.get("resultMsg", ""))
        if code not in ("", "0", "00") and msg:
            code = f"{code} {msg}"
        return list(items or []), (int(total) if total not in (None, "") else None), code
    root = ET.fromstring(text)
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    total = root.findtext(".//totalCount")
    code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or ""
    msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or ""
    if code not in ("", "0", "00") and msg:
        code = f"{code} {msg}"
    return items, (int(total) if total and total.isdigit() else None), code


def _get(op: str, params: dict) -> tuple[list[dict], int | None, str]:
    import requests
    from urllib.parse import unquote
    # Encoding 키(%2B, %3D 포함)를 넣어도 두 번 인코딩되지 않도록 먼저 풀어 둔다. Decoding 키는 그대로다.
    key = unquote(os.getenv("JIS_API_KEY", "").strip())
    p = {"serviceKey": key, "_type": "json", "type": "json", **params}
    r = requests.get(f"{BASE}/{op}", params=p, timeout=30)
    body = r.content.decode("utf-8", errors="replace")
    if r.status_code != 200:
        # 오류 원인을 로그에서 바로 볼 수 있도록 응답 본문 앞부분을 함께 남긴다 (키는 남기지 않음).
        raise RuntimeError(f"HTTP {r.status_code} 응답={body[:300]!r} ({op}, {params})")
    return parse_items(body)


# ── 위치: 행정동 이름 매칭 ────────────────────────────────────────────────
def _centroid(geom: dict) -> tuple[float, float]:
    """폴리곤 외곽선 꼭짓점 평균 (위도, 경도). 동 단위 표시용 근사 중심."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    pts = [pt for poly in polys for pt in poly[0]]
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def _base(name: str) -> str:
    """법정동·행정동 이름에서 비교용 어근: '역삼1동'→'역삼', '종로1가'→'종로', '면목본동'→'면목'."""
    name = re.sub(r"\(.*?\)", "", str(name or "")).strip()
    return re.sub(r"(제?[\d·]+)?(가동|본동|동|가|로)$", "", name)


class Locator:
    def __init__(self):
        dong = json.loads(DONG_GEO.read_text(encoding="utf-8"))
        self.dongs = []  # (구, 행정동 이름, 어근, 중심)
        for f in dong["features"]:
            p = f["properties"]
            gu, dnm = p["sggnm"], p["adm_nm"].split()[-1]
            self.dongs.append((gu, p["adm_nm"], _base(dnm), _centroid(f["geometry"])))
        gu = json.loads(GU_GEO.read_text(encoding="utf-8"))
        self.gu_center = {f["properties"]["name"]: _centroid(f["geometry"]) for f in gu["features"]}
        cells = json.loads(GRID.read_text(encoding="utf-8"))["cells"]
        self.cells = [(c["id"], c["lat"], c["lon"]) for c in cells]

    def locate(self, gu: str, dong: str) -> tuple[float, float, str, list[str]]:
        b = _base(dong)
        same_gu = [d for d in self.dongs if d[0] == gu]
        hits = [d for d in same_gu if b and d[2].startswith(b)]
        if not hits and len(b) >= 2:  # '여의도동'(법정동) ↔ '여의동'(행정동)처럼 행정동 이름이 더 짧은 경우
            hits = [d for d in same_gu if len(d[2]) >= 2 and b.startswith(d[2])]
        if hits:
            lat = sum(h[3][0] for h in hits) / len(hits)
            lon = sum(h[3][1] for h in hits) / len(hits)
            return lat, lon, "동", [h[1] for h in hits]
        if gu in self.gu_center:
            lat, lon = self.gu_center[gu]
            return lat, lon, "구", []
        raise KeyError(gu)

    def nearest_cell(self, lat: float, lon: float) -> int:
        return min(self.cells, key=lambda c: (c[1] - lat) ** 2 + (c[2] - lon) ** 2)[0]


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def grade_of(ev: dict) -> int:
    """규모 등급(1~3): 깊이 2m 이상 또는 사망자 → 3, 깊이 1m 이상 또는 폭 2m 이상 → 2, 그 외 1."""
    if ev["depth_m"] >= 2 or ev["death"] > 0:
        return 3
    if ev["depth_m"] >= 1 or ev["width_m"] >= 2:
        return 2
    return 1


# ── 메인 ─────────────────────────────────────────────────────────────────
def build(now: datetime, prev: dict) -> tuple[dict, str]:
    known = {e["sagoNo"]: e for e in prev.get("events", [])}
    # 한 번에 긴 기간·많은 건수를 요청하면 400 Bad Request가 나므로, 1년 단위로 100건씩 나눠 받는다.
    rows, codes, year_errors = [], [], []
    for year in range(int(START[:4]), now.year + 1):
        d_from = max(f"{year}0101", START)
        d_to = min(f"{year}1231", now.strftime("%Y%m%d"))
        got, page = 0, 1
        try:
            while page <= 50:
                items, total, code = _get("getSubsidenceList01", {"sagoDateFrom": d_from, "sagoDateTo": d_to,
                                                                  "numOfRows": PAGE_ROWS, "pageNo": page})
                codes.append(code)
                rows += items
                got += len(items)
                if not items or (total is not None and got >= total) or len(items) < PAGE_ROWS:
                    break
                page += 1
        except Exception as e:  # 한 해가 실패해도 나머지 해는 계속 받는다
            year_errors.append(f"{year}: {type(e).__name__} {str(e)[:150]}")
    if not rows:
        codes_txt = ",".join(sorted(set(c for c in codes if c))) or "-"
        raise RuntimeError(f"목록 응답 없음 (resultCode={codes_txt}; 오류={year_errors[:2]})")
    uniq = {}
    for r in rows:  # 같은 사고가 두 번 오면(페이지 경계 등) 한 번만 센다
        uniq.setdefault(str(r.get("sagoNo")), r)
    rows = list(uniq.values())
    seoul = [r for r in rows if "서울" in str(r.get("siDo", ""))]

    loc = Locator()
    events, new, detail_fail = [], 0, []
    for r in seoul:
        no = str(r.get("sagoNo"))
        ev = known.get(no)
        if ev is not None and not ev.get("detail_ok"):
            ev = None  # 지난번에 상세조회가 실패한 사고는 다시 조회한다 (동 정보를 채우기 위해)
        if ev is None:
            info, detail_ok = {}, False
            try:
                items, _, code = _get("getSubsidenceInfo01", {"sagoNo": no, "numOfRows": 10, "pageNo": 1})
                info = items[0] if items else {}
                detail_ok = bool(info)
                if not info:
                    detail_fail.append(code or "빈 응답")
            except Exception as e:
                detail_fail.append(type(e).__name__)
            gu = str(info.get("siGunGu") or r.get("siGunGu") or "").strip()
            dong = str(info.get("dong") or r.get("dong") or "").strip()
            if not dong:  # 동 칸이 비어 있으면 주소에서 '○○동'을 찾아 쓴다
                m = re.search(r"([가-힣0-9·]+동)(?:\s|$|\d)", str(info.get("addr") or r.get("addr") or ""))
                dong = m.group(1) if m else ""
            ev = {
                "sagoNo": no, "date": str(info.get("sagoDate") or r.get("sagoDate") or ""),
                "gu": gu, "dong": dong, "addr": str(info.get("addr") or ""),
                "cause": str(info.get("sagoDetail") or r.get("sagoDetail") or ""),
                "width_m": _num(info.get("sinkWidth")), "extend_m": _num(info.get("sinkExtend")),
                "depth_m": _num(info.get("sinkDepth")), "death": int(_num(info.get("deathCnt"))),
                "ground": str(info.get("grdKind") or ""), "detail_ok": detail_ok,
            }
            new += 1
        try:
            lat, lon, level, adm = loc.locate(ev["gu"], ev["dong"])
        except KeyError:
            continue
        ev.update({"lat": round(lat, 6), "lon": round(lon, 6), "loc_level": level, "adm_dongs": adm,
                   "cell": loc.nearest_cell(lat, lon), "grade": grade_of(ev)})
        events.append(ev)

    by_grid: dict[str, dict] = {}
    for ev in sorted(events, key=lambda e: e["date"]):
        d = ev["date"]
        g = by_grid.setdefault(str(ev["cell"]), {"count": 0, "grade": 1})
        g.update({"date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d, "time": "-",
                  "location": f"{ev['gu']} {ev['dong']} {ev['addr']}".strip() + (" (동 단위 위치)" if ev["loc_level"] == "동" else " (구 단위 위치)"),
                  "cause": ev["cause"], "size": f"폭 {ev['width_m']}m · 깊이 {ev['depth_m']}m"})
        g["count"] += 1
        g["grade"] = max(g["grade"], ev["grade"])
    by_dong: dict[str, dict] = {}
    for ev in events:
        for name in ev["adm_dongs"][:1] or []:  # 법정동이 여러 행정동에 걸치면 첫 행정동에 집계
            by_dong.setdefault(name, {"count": 0})["count"] += 1
    for v in by_dong.values():
        v["grade"] = min(5, v["count"] + 1)  # 0건→1 … 4건 이상→5 (기존 색상 단계와 동일)

    data = {"meta": {"source": "국토교통부 지하안전정보(JIS), 공공데이터포털 '국토교통부_지하안전정보'",
                     "fetched_at": now.isoformat(timespec="seconds"), "period": f"{START}~{now:%Y%m%d}",
                     "total_national": len(rows), "seoul": len(events),
                     "dong_level": sum(e["loc_level"] == "동" for e in events),
                     "detail_failed": len(detail_fail), "year_errors": year_errors},
            "events": events, "by_grid": by_grid, "by_dong": by_dong}
    msg = (f"전국 {len(rows)}건 중 서울 {len(events)}건 (동 단위 {data['meta']['dong_level']}건, "
           f"새 상세조회 {new}건, 상세조회 실패 {len(detail_fail)}건), 격자 {len(by_grid)}개, 동 {len(by_dong)}곳")
    if detail_fail:
        msg += f" / 상세조회 실패 원인 예: {sorted(set(detail_fail))[:3]}"
    if year_errors:
        msg += f" / 목록 실패 연도: {year_errors[:3]}"
    return data, msg


def fetch(force: bool = False) -> str:
    if not os.getenv("JIS_API_KEY"):
        return "JIS_API_KEY 없음 — 건너뜀"
    now = datetime.now(tz=KST)
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    try:
        last = datetime.fromisoformat(prev["meta"]["fetched_at"])
        if not force and now - last < timedelta(hours=REFRESH_HOURS):
            return f"최근 수집본 사용 ({last:%m-%d %H:%M}, 서울 {prev['meta']['seoul']}건)"
    except Exception:
        pass
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8"))
        last_try = datetime.fromisoformat(st["tried_at"])
        if not force and not st.get("ok") and now - last_try < timedelta(minutes=RETRY_MINUTES):
            return f"직전 실패 후 {RETRY_MINUTES}분 대기 중 ({last_try:%H:%M} 실패: {st.get('message', '')[:200]})"
    except Exception:
        pass
    try:
        data, msg = build(now, prev)
        ok = bool(data["events"])
        if not ok:
            msg = f"서울 사고 0건 — 기존 파일 유지 ({msg})"
    except Exception as e:
        data, ok = None, False
        msg = f"수집 실패 ({type(e).__name__}: {str(e)[:500]}) — 기존 파일 유지"
    STATUS.write_text(json.dumps({"tried_at": now.isoformat(timespec="seconds"), "ok": ok, "message": msg},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    if ok:
        OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return msg


if __name__ == "__main__":
    print(fetch(force="--force" in sys.argv))
