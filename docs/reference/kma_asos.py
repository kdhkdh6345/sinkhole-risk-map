#!/usr/bin/env python3
"""
기상청 API허브 - ASOS(종관기상관측) 시간자료 조회 스크립트

사용법:
  1) API허브(https://apihub.kma.go.kr) 가입 후 마이페이지에서 인증키 확인
  2) 환경변수로 키 설정:  export KMA_API_KEY="발급받은키"
     (또는 --key 옵션으로 직접 전달)

  # 지점 목록 받아서 CSV 저장
  python kma_asos.py stations

  # 수원(119) 최근 30일 시간자료 → CSV 저장
  python kma_asos.py fetch --stn 119 --days 30

  # 기간 직접 지정 (KST, YYYYMMDDHHMM)
  python kma_asos.py fetch --stn 108 --tm1 202607010100 --tm2 202608010000

의존성: requests, pandas  (pip install requests pandas)
"""

import argparse
import io
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE = "https://apihub.kma.go.kr/api/typ01/url"

# kma_sfctm2/sfctm3 (help=1) 문서 기준 출력 컬럼 순서 (46개)
SFCTM_COLUMNS = [
    "TM", "STN", "WD", "WS", "GST_WD", "GST_WS", "GST_TM",
    "PA", "PS", "PT", "PR", "TA", "TD", "HM", "PV",
    "RN", "RN_DAY", "RN_JUN", "RN_INT",
    "SD_HR3", "SD_DAY", "SD_TOT",
    "WC", "WP", "WW",
    "CA_TOT", "CA_MID", "CH_MIN", "CT", "CT_TOP", "CT_MID", "CT_LOW",
    "VS", "SS", "SI", "ST_GD", "TS",
    "TE_005", "TE_01", "TE_02", "TE_03",
    "ST_SEA", "WH", "BF", "IR", "IX",
]

# 결측 표기값 (기상청 관례: -9, -99 계열)
MISSING_TOKENS = {"-9", "-9.0", "-99", "-99.0", "-999", "-999.0", "-9.00", "-99.00"}


def get_key(cli_key: str | None) -> str:
    key = cli_key or os.environ.get("KMA_API_KEY")
    if not key:
        sys.exit("인증키가 없습니다. export KMA_API_KEY=... 또는 --key 옵션을 사용하세요.")
    return key


def _request(url: str, params: dict) -> str:
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    text = r.content.decode("euc-kr", errors="replace")  # API허브 typ01은 EUC-KR 응답
    if "인증키" in text and ("유효" in text or "확인" in text):
        sys.exit(f"인증키 오류로 보입니다. 응답:\n{text[:500]}")
    return text


def parse_typ01(text: str, columns: list[str] | None = None) -> pd.DataFrame:
    """API허브 typ01(텍스트) 응답 파싱. '#'으로 시작하는 줄은 주석/헤더."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line.split())
    if not rows:
        return pd.DataFrame()

    ncol = max(len(r) for r in rows)
    if columns and len(columns) == ncol:
        names = columns
    else:
        # 문서와 실제 컬럼 수가 다르면 안전하게 일반 이름으로 저장 (원본도 함께 확인 권장)
        names = (columns or [])[:ncol] + [f"col_{i}" for i in range(len(columns or []), ncol)]
        if columns:
            print(f"[경고] 문서상 컬럼 {len(columns)}개 vs 실제 {ncol}개. "
                  f"뒤쪽 컬럼명은 col_N으로 저장됩니다. raw 파일을 확인하세요.")
    rows = [r + [None] * (ncol - len(r)) for r in rows]
    df = pd.DataFrame(rows, columns=names)

    # 결측 처리 + 숫자 변환
    df = df.replace(list(MISSING_TOKENS), pd.NA)
    for c in df.columns:
        if c in ("TM", "WW", "CT", "GST_TM"):
            continue
        converted = pd.to_numeric(df[c], errors="coerce")
        # 원래 값이 있는데 변환 후 전부 NaN이 되는 문자열 컬럼은 원본 유지
        if converted.notna().sum() > 0 or df[c].isna().all():
            df[c] = converted
    return df


def fetch_hourly(key: str, stn: int, tm1: str, tm2: str) -> pd.DataFrame:
    """시간자료 기간 조회(kma_sfctm3). 1회 호출 최대 31일 → 자동 분할."""
    fmt = "%Y%m%d%H%M"
    t1, t2 = datetime.strptime(tm1, fmt), datetime.strptime(tm2, fmt)
    if t1 > t2:
        sys.exit("tm1이 tm2보다 늦습니다.")

    chunks, raw_all = [], []
    cur = t1
    while cur <= t2:
        end = min(cur + timedelta(days=31) - timedelta(hours=1), t2)
        params = {
            "tm1": cur.strftime(fmt),
            "tm2": end.strftime(fmt),
            "stn": stn,
            "help": 1,
            "authKey": key,
        }
        print(f"요청: {params['tm1']} ~ {params['tm2']} (stn={stn})")
        text = _request(f"{BASE}/kma_sfctm3.php", params)
        raw_all.append(text)
        df = parse_typ01(text, SFCTM_COLUMNS)
        if not df.empty:
            chunks.append(df)
        cur = end + timedelta(hours=1)
        time.sleep(0.5)  # 예의상 호출 간격

    # 원본 응답 백업 (파싱 문제 시 대조용)
    with open(f"asos_{stn}_raw.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(raw_all))

    if not chunks:
        print("데이터가 없습니다. raw 파일을 확인하세요:", f"asos_{stn}_raw.txt")
        return pd.DataFrame()
    out = pd.concat(chunks, ignore_index=True).drop_duplicates(subset=["TM", "STN"])
    return out


def fetch_stations(key: str) -> pd.DataFrame:
    """ASOS 지점정보 조회(stn_inf.php, inf=SFC)."""
    params = {"inf": "SFC", "stn": "", "tm": "", "help": 1, "authKey": key}
    text = _request(f"{BASE}/stn_inf.php", params)
    with open("asos_stations_raw.txt", "w", encoding="utf-8") as f:
        f.write(text)
    # 지점정보 컬럼(문서 기준): STN LON LAT STN_SP HT HT_PA HT_TA HT_WD HT_RN STN_AD STN_KO STN_EN FCT_ID LAW_ID BASIN
    cols = ["STN", "LON", "LAT", "STN_SP", "HT", "HT_PA", "HT_TA", "HT_WD", "HT_RN",
            "STN_AD", "STN_KO", "STN_EN", "FCT_ID", "LAW_ID", "BASIN"]
    df = parse_typ01(text, cols)
    return df


def main():
    ap = argparse.ArgumentParser(description="기상청 API허브 ASOS 시간자료 조회")
    ap.add_argument("--key", help="API 인증키 (없으면 KMA_API_KEY 환경변수 사용)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_f = sub.add_parser("fetch", help="시간자료 조회 → CSV")
    ap_f.add_argument("--stn", type=int, default=119, help="지점번호 (기본 119=수원)")
    ap_f.add_argument("--days", type=int, help="최근 N일 (tm1/tm2 미지정 시)")
    ap_f.add_argument("--tm1", help="시작 YYYYMMDDHHMM (KST)")
    ap_f.add_argument("--tm2", help="종료 YYYYMMDDHHMM (KST)")
    ap_f.add_argument("-o", "--out", help="저장할 CSV 파일명")

    sub.add_parser("stations", help="ASOS 지점 목록 → asos_stations.csv")

    args = ap.parse_args()
    key = get_key(args.key)

    if args.cmd == "stations":
        df = fetch_stations(key)
        df.to_csv("asos_stations.csv", index=False, encoding="utf-8-sig")
        print(f"저장: asos_stations.csv ({len(df)}개 지점)")
        return

    if args.tm1 and args.tm2:
        tm1, tm2 = args.tm1, args.tm2
    else:
        days = args.days or 30
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        tm1 = (now - timedelta(days=days)).strftime("%Y%m%d%H%M")
        tm2 = now.strftime("%Y%m%d%H%M")

    df = fetch_hourly(key, args.stn, tm1, tm2)
    if df.empty:
        return
    out = args.out or f"asos_{args.stn}_{tm1[:8]}_{tm2[:8]}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"저장: {out} ({len(df)}행)")
    print("\n강수량 관련 컬럼 미리보기 (RN=시간강수량 mm):")
    print(df[["TM", "STN", "TA", "RN", "RN_DAY", "RN_INT"]].tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
