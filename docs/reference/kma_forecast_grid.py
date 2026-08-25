#!/usr/bin/env python3
"""
기상청 API허브 — 단기예보 격자 강수량(RN1) 수집 스크립트

API: nph-dfs_vsrt_grd (수치예보 단기예보 격자자료)
  - 격자: 5km × 5km (동서 149 × 남북 253)
  - 발표: 10분 간격
  - 예보: 발표 기준 +1h ~ +6h (1시간 단위)
  - 변수: RN1 = 1시간 강수량(mm)

사용법:
  export KMA_API_KEY="발급받은키"
  python kma_forecast_grid.py                  # 최신 발표 기준 6시간 예보
  python kma_forecast_grid.py --tmfc 202408051200  # 특정 발표 시각 지정
"""

import argparse
import io
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_vsrt_grd"

NX = 149   # 동서 격자 수
NY = 253   # 남북 격자 수


def get_key(cli_key=None) -> str:
    key = cli_key or os.environ.get("KMA_API_KEY")
    if not key:
        sys.exit("인증키가 없습니다. export KMA_API_KEY=... 또는 --key 옵션을 사용하세요.")
    return key


def latest_tmfc(now: datetime = None) -> str:
    """현재 시각 기준 가장 최근 10분 단위 발표시각 반환 (YYYYMMDDHHMM)"""
    if now is None:
        now = datetime.now()
    # 10분 단위로 내림
    minutes = (now.minute // 10) * 10
    tmfc = now.replace(minute=minutes, second=0, microsecond=0)
    return tmfc.strftime("%Y%m%d%H%M")


def fetch_grid(key: str, tmfc: str, tmef: str, var: str = "RN1") -> np.ndarray | None:
    """
    단기예보 격자 데이터 1개 시각 조회

    Parameters
    ----------
    tmfc : 발표시각 YYYYMMDDHHMM
    tmef : 예보시각 YYYYMMDDHH  (발표 기준 +1h~+6h)
    var  : 예보변수 (기본 RN1 = 1시간 강수량)

    Returns
    -------
    numpy.ndarray shape (NY, NX) 또는 None (실패 시)
    """
    params = {
        "tmfc": tmfc,
        "tmef": tmef,
        "vars": var,
        "authKey": key,
    }
    try:
        r = requests.get(BASE_URL, params=params, timeout=30)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  [오류] {tmef} 요청 실패: {e}", file=sys.stderr)
        return None

    text = r.content.decode("euc-kr", errors="replace")

    # 인증키 오류 감지
    if "인증키" in text and ("유효" in text or "확인" in text or "오류" in text):
        sys.exit(f"인증키 오류:\n{text[:300]}")

    # 응답이 비어 있거나 너무 짧은 경우
    if len(text.strip()) < 100:
        print(f"  [경고] {tmef} 응답이 너무 짧습니다. (데이터 없음?)", file=sys.stderr)
        return None

    return _parse_grid_text(text)


def _parse_grid_text(text: str) -> np.ndarray | None:
    """
    기상청 typ01 격자 텍스트 응답 파싱
    응답 형식: 쉼표(,) 구분 숫자 배열, NY×NX 순서
    결측값(-99, -99.00 등) → NaN
    """
    # 쉼표 + 공백 구분자로 모든 숫자 추출
    import re
    tokens = re.split(r'[,\s]+', text.strip())
    values = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue

    expected = NX * NY
    if len(values) < expected:
        print(f"  [경고] 파싱된 값 수({len(values)}) < 기대값({expected})", file=sys.stderr)
        if len(values) == 0:
            return None

    arr = np.array(values[:expected], dtype=np.float32).reshape(NY, NX)

    # 결측 처리 (-9, -99 계열)
    arr[arr <= -9.0] = np.nan

    # 음수 강수량 → 0 (물리적으로 불가)
    arr[(arr < 0) & ~np.isnan(arr)] = 0.0

    return arr


def fetch_forecast_sequence(key: str, tmfc: str, hours: int = 6) -> dict:
    """
    발표시각(tmfc) 기준 +1h ~ +hours 예보 격자 수집

    Returns
    -------
    dict: {예보시각(datetime): np.ndarray(NY, NX)}
    """
    base = datetime.strptime(tmfc, "%Y%m%d%H%M")
    results = {}

    print(f"발표시각: {tmfc} 기준 {hours}시간 예보 격자 수집 중...")
    for h in range(1, hours + 1):
        valid_dt = base + timedelta(hours=h)
        tmef = valid_dt.strftime("%Y%m%d%H")
        print(f"  +{h:02d}h ({tmef}) 요청 중...", end=" ", flush=True)

        grid = fetch_grid(key, tmfc, tmef)
        if grid is not None:
            results[valid_dt] = grid
            # 유효 격자 수 & 강수 발생 격자 수 출력
            valid = int(np.sum(~np.isnan(grid)))
            rainy = int(np.sum(grid > 0))
            print(f"완료 (유효 격자: {valid}, 강수 격자: {rainy})")
        else:
            print("데이터 없음")

        time.sleep(0.3)   # API 과부하 방지

    return results


def save_to_csv(forecast: dict, out_dir: str = ".") -> list:
    """
    각 시각별 격자 데이터를 CSV로 저장
    컬럼: nx, ny, lat, lon, RN1
    """
    try:
        from grid_utils import KMAGrid
        grid_converter = KMAGrid()
        has_latlon = True
    except ImportError:
        print("[경고] grid_utils.py를 찾지 못해 위경도 변환 생략")
        has_latlon = False

    os.makedirs(out_dir, exist_ok=True)
    saved = []

    for dt, arr in sorted(forecast.items()):
        rows = []
        for ny in range(NY):
            for nx in range(NX):
                val = arr[ny, nx]
                row = {"nx": nx + 1, "ny": ny + 1, "RN1": val}
                if has_latlon:
                    lat, lon = grid_converter.grid_to_latlon(nx + 1, ny + 1)
                    row["lat"] = round(lat, 5)
                    row["lon"] = round(lon, 5)
                rows.append(row)

        df = pd.DataFrame(rows)
        fname = os.path.join(out_dir, f"forecast_rn1_{dt.strftime('%Y%m%d%H')}.csv")
        df.to_csv(fname, index=False, encoding="utf-8-sig")
        saved.append(fname)
        print(f"저장: {fname}")

    return saved


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="기상청 단기예보 격자 강수량(RN1) 수집")
    ap.add_argument("--key", help="KMA API 인증키 (없으면 환경변수 KMA_API_KEY 사용)")
    ap.add_argument("--tmfc", help="발표시각 YYYYMMDDHHMM (기본: 최신)")
    ap.add_argument("--hours", type=int, default=6, help="예보 시간 수 (기본 6)")
    ap.add_argument("--out", default=".", help="CSV 저장 폴더 (기본 현재 폴더)")
    args = ap.parse_args()

    key = get_key(args.key)
    tmfc = args.tmfc or latest_tmfc()
    print(f"사용 발표시각: {tmfc}")

    forecast = fetch_forecast_sequence(key, tmfc, args.hours)

    if not forecast:
        print("수집된 데이터가 없습니다. API 신청 상태 또는 인증키를 확인하세요.")
        sys.exit(1)

    saved = save_to_csv(forecast, args.out)
    print(f"\n총 {len(saved)}개 파일 저장 완료.")
    print("다음 단계: python visualize_risk_map.py 로 지도 생성")


if __name__ == "__main__":
    main()
