"""
check_apis.py — 외부 API 연결 진단 (GitHub Actions 로그 확인용)

실행:  python scripts/check_apis.py
환경변수: KMA_API_KEY, SEOUL_API_KEY, GW_API_KEY (GitHub Secrets에서 주입)

각 API를 한 번씩 호출해 HTTP 상태와 응답 앞부분을 출력한다.
키는 출력에서 '***'로 가린다. 실패해도 종료 코드는 항상 0 (배포를 막지 않음).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

KST = timezone(timedelta(hours=9))
KEYS = {k: os.getenv(k, "") for k in ("KMA_API_KEY", "SEOUL_API_KEY", "GW_API_KEY")}


def _mask(text: str) -> str:
    for v in KEYS.values():
        if v:
            text = text.replace(v, "***").replace(quote(v), "***")
    return text


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("euc-kr", errors="replace")


def probe(title: str, url: str, params: dict | None = None, n: int = 900) -> str:
    print(f"\n===== {title} =====")
    try:
        r = requests.get(url, params=params, timeout=20)
        text = _decode(r.content)
        print(f"HTTP {r.status_code}  ({len(text)}자)")
        print(_mask(text[:n]))
        return text
    except Exception as e:
        print(f"요청 실패: {type(e).__name__}: {_mask(str(e))[:300]}")
        return ""


def citydata_traffic(base: str) -> str | None:
    """실시간 도시데이터에서 도로소통 부분만 구조를 보여준다. 첫 링크 아이디를 반환."""
    print("\n===== 서울시 실시간 도시데이터 — 도로소통 부분 =====")
    try:
        r = requests.get(f"{base}/json/citydata/1/5/{quote('광화문·덕수궁')}", timeout=30)
        data = json.loads(_decode(r.content))
    except Exception as e:
        print(f"요청/파싱 실패: {type(e).__name__}: {_mask(str(e))[:300]}")
        return None
    city = data.get("CITYDATA", {})
    print("CITYDATA 최상위 키:", list(city.keys()))
    road = city.get("ROAD_TRAFFIC_STTS")
    if road is None:
        print("ROAD_TRAFFIC_STTS 없음")
        return None
    if isinstance(road, dict):
        print("ROAD_TRAFFIC_STTS 키:", list(road.keys()))
        print("AVG_ROAD_DATA:", json.dumps(road.get("AVG_ROAD_DATA"), ensure_ascii=False)[:600])
        links = road.get("ROAD_TRAFFIC_STTS") or []
    else:
        links = road
    print(f"링크 개수: {len(links)}")
    for item in links[:2]:
        print(json.dumps(item, ensure_ascii=False)[:900])
    if links and isinstance(links[0], dict):
        return str(links[0].get("LINK_ID") or "")
    return None


def main() -> int:
    if requests is None:
        print("requests 미설치 — 진단 생략")
        return 0
    print("등록된 키:", {k: ("있음" if v else "없음") for k, v in KEYS.items()})

    kma = KEYS["KMA_API_KEY"]
    if kma:
        tm = (datetime.now(tz=KST) - timedelta(minutes=2)).strftime("%Y%m%d%H%M")
        probe("기상청 AWS 매분자료 (앞부분)",
              "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min",
              {"tm2": tm, "stn": 0, "disp": 0, "help": 1, "authKey": kma}, 400)
        probe("기상청 AWS 지점정보 (403이면 API허브에서 '지점정보' 활용신청 필요)",
              "https://apihub.kma.go.kr/api/typ01/url/stn_inf.php",
              {"inf": "AWS", "stn": "", "tm": "", "help": 1, "authKey": kma}, 1500)

    seoul = KEYS["SEOUL_API_KEY"]
    if seoul:
        base = f"http://openapi.seoul.go.kr:8088/{seoul}"
        link_id = citydata_traffic(base)
        probe("서울시 실시간 도시데이터 — 장소코드(POI001)로 조회되는지 확인",
              f"{base}/json/citydata/1/5/POI001", n=300)

        # 하수관로 수위 (서울 열린데이터광장 OA-2527, 30분 간격). 서비스명·인자 확인용 시험 호출
        now = datetime.now(tz=KST)
        t1 = (now - timedelta(hours=2)).strftime("%Y%m%d%H")
        t2 = now.strftime("%Y%m%d%H")
        probe("서울시 하수관로 수위 (인자 없음)", f"{base}/json/DrainpipeMonitoringInfo/1/5/", n=600)
        probe("서울시 하수관로 수위 (구분코드 01, 최근 2시간)",
              f"{base}/json/DrainpipeMonitoringInfo/1/5/01/{t1}/{t2}", n=1500)
        if link_id:
            probe(f"서울시 실시간 도로 소통 정보 (TrafficInfo, xml, 링크 {link_id})",
                  f"{base}/xml/TrafficInfo/1/5/{link_id}")

    # 지하수(GIMS)는 호출 한도가 있어 진단에서 호출하지 않는다. 상태는 Generate new snapshot 로그에서 확인.

    print("\n진단 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
