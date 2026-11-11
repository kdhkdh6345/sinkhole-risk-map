"""
check_apis.py — 외부 API 연결 진단 (GitHub Actions 로그 확인용)

실행:  python scripts/check_apis.py
환경변수: KMA_API_KEY, SEOUL_API_KEY, GW_API_KEY (GitHub Secrets에서 주입)

각 API를 한 번씩 호출해 HTTP 상태와 응답 앞부분을 출력한다.
키는 출력에서 '***'로 가린다. 실패해도 종료 코드는 항상 0 (배포를 막지 않음).
이 출력 결과를 보고 교통·지하수 어댑터의 응답 파싱을 확정한다.
"""

from __future__ import annotations

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


def probe(title: str, url: str, params: dict | None = None, encoding: str = "utf-8", n: int = 900) -> None:
    print(f"\n===== {title} =====")
    try:
        r = requests.get(url, params=params, timeout=20)
        text = r.content.decode(encoding, errors="replace")
        print(f"HTTP {r.status_code}  ({len(text)}자)")
        print(_mask(text[:n]))
    except Exception as e:
        print(f"요청 실패: {type(e).__name__}: {_mask(str(e))[:300]}")


def main() -> int:
    if requests is None:
        print("requests 미설치 — 진단 생략")
        return 0
    print("등록된 키:", {k: ("있음" if v else "없음") for k, v in KEYS.items()})

    kma = KEYS["KMA_API_KEY"]
    if kma:
        tm = (datetime.now(tz=KST) - timedelta(minutes=2)).strftime("%Y%m%d%H%M")
        probe("기상청 AWS 매분자료",
              "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min",
              {"tm2": tm, "stn": 0, "disp": 0, "help": 1, "authKey": kma}, "euc-kr", 1500)
        probe("기상청 AWS 지점정보",
              "https://apihub.kma.go.kr/api/typ01/url/stn_inf.php",
              {"inf": "AWS", "stn": "", "tm": "", "help": 1, "authKey": kma}, "euc-kr", 1500)

    seoul = KEYS["SEOUL_API_KEY"]
    if seoul:
        base = f"http://openapi.seoul.go.kr:8088/{seoul}/json"
        probe("서울시 실시간 도로 소통 정보 (TrafficInfo, 링크 미지정)", f"{base}/TrafficInfo/1/5/")
        probe("서울시 실시간 도시데이터 (citydata, 광화문·덕수궁)",
              f"{base}/citydata/1/5/{quote('광화문·덕수궁')}", n=1500)

    if KEYS["GW_API_KEY"]:
        print("\n===== 지하수 =====\nGW_API_KEY 등록됨 — 사용할 API 주소가 정해지면 진단 항목을 추가한다.")

    print("\n진단 완료 (이 로그를 복사해 전달하면 어댑터를 마무리할 수 있음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
