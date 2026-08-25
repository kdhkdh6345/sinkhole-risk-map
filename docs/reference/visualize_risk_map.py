#!/usr/bin/env python3
"""
싱크홀 위험도 — 시간별 지도 애니메이션 생성기

단기예보 격자 강수량(RN1)을 기반으로 싱크홀 위험도를 계산하고
날씨앱 강수 레이더처럼 시간별로 슬라이딩되는 HTML 지도를 생성합니다.

출력: sinkhole_risk_map.html (브라우저에서 바로 열 수 있음)

사용법:
  # 1) 먼저 데이터 수집
  python kma_forecast_grid.py

  # 2) 지도 생성
  python visualize_risk_map.py

  # 또는 API 키로 한 번에
  python visualize_risk_map.py --key 발급받은키
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# 의존성 체크
try:
    import folium
    from folium.plugins import TimestampedGeoJson
except ImportError:
    sys.exit("folium이 없습니다: pip install folium")

try:
    from grid_utils import KMAGrid
except ImportError:
    sys.exit("grid_utils.py를 찾을 수 없습니다. 같은 폴더에 있는지 확인하세요.")

try:
    from sinkhole_risk import RiskCalculator
except ImportError:
    sys.exit("sinkhole_risk.py를 찾을 수 없습니다. 같은 폴더에 있는지 확인하세요.")


# ── 설정 ─────────────────────────────────────────────────────
# 서울 중심 표시 (원하면 다른 지역으로 변경)
MAP_CENTER = [37.5665, 126.9780]
MAP_ZOOM   = 11

# 서울 격자 범위 (전국에서 서울만 필터링, 속도 향상)
# 대략적인 서울 위경도 범위
SEOUL_LAT_MIN, SEOUL_LAT_MAX = 37.40, 37.72
SEOUL_LON_MIN, SEOUL_LON_MAX = 126.75, 127.20


def load_forecast_csvs(folder: str = ".") -> dict:
    """
    kma_forecast_grid.py 가 저장한 forecast_rn1_*.csv 파일들을 로드

    Returns
    -------
    dict: {datetime: DataFrame(nx, ny, lat, lon, RN1)}
    """
    pattern = os.path.join(folder, "forecast_rn1_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return {}

    result = {}
    for fpath in files:
        # 파일명에서 시각 파싱: forecast_rn1_2024080512.csv
        basename = os.path.basename(fpath)
        time_str = basename.replace("forecast_rn1_", "").replace(".csv", "")
        try:
            dt = datetime.strptime(time_str, "%Y%m%d%H")
        except ValueError:
            continue
        df = pd.read_csv(fpath)
        result[dt] = df
    return result


def fetch_live_forecast(key: str) -> dict:
    """API에서 실시간으로 데이터 가져오기 (CSV 없을 때 폴백)"""
    try:
        from kma_forecast_grid import fetch_forecast_sequence, latest_tmfc
    except ImportError:
        return {}

    tmfc = latest_tmfc()
    raw = fetch_forecast_sequence(key, tmfc, hours=6)
    if not raw:
        return {}

    grid_conv = KMAGrid()
    result = {}
    for dt, arr in raw.items():
        rows = []
        for ny in range(arr.shape[0]):
            for nx in range(arr.shape[1]):
                lat, lon = grid_conv.grid_to_latlon(nx + 1, ny + 1)
                rows.append({"nx": nx+1, "ny": ny+1, "lat": lat, "lon": lon, "RN1": arr[ny, nx]})
        result[dt] = pd.DataFrame(rows)
    return result


def df_to_geojson_features(dt: datetime, df: pd.DataFrame,
                            rc: RiskCalculator,
                            seoul_only: bool = True) -> list:
    """
    DataFrame → GeoJSON Feature 리스트 (시간별 폴리곤)
    각 5km 격자를 작은 사각형 폴리곤으로 표현
    """
    HALF = 0.0225   # 약 2.5km (위경도 단위)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%S")

    features = []
    for _, row in df.iterrows():
        lat, lon = row["lat"], row["lon"]
        rn1 = row["RN1"]

        # 서울 범위 필터
        if seoul_only:
            if not (SEOUL_LAT_MIN <= lat <= SEOUL_LAT_MAX and
                    SEOUL_LON_MIN <= lon <= SEOUL_LON_MAX):
                continue

        if np.isnan(rn1):
            rn1 = 0.0

        risk_score = rc.score(rn1)
        if risk_score <= 0:
            continue  # 안전 격자는 표시 생략 (지도 가독성)

        color   = rc.color(risk_score)
        opacity = rc.opacity(risk_score)
        label   = rc.label(risk_score)

        # 격자 폴리곤 좌표 (GeoJSON: [lon, lat] 순서)
        coords = [
            [lon - HALF, lat - HALF],
            [lon + HALF, lat - HALF],
            [lon + HALF, lat + HALF],
            [lon - HALF, lat + HALF],
            [lon - HALF, lat - HALF],
        ]

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords],
            },
            "properties": {
                "time": ts,
                "style": {
                    "color":       color,
                    "fillColor":   color,
                    "fillOpacity": opacity,
                    "weight":      0.5,
                    "opacity":     0.8,
                },
                "popup": (
                    f"<b>{dt.strftime('%m/%d %H시')}</b><br>"
                    f"강수량: {rn1:.1f} mm<br>"
                    f"위험도: {risk_score:.0f}점 {label}"
                ),
                "icon":         "circle",
                "iconstyle": {},
            },
        }
        features.append(feature)

    return features


def build_map(forecast: dict, out_path: str = "sinkhole_risk_map.html") -> str:
    """
    시간별 위험도 애니메이션 지도 생성

    Parameters
    ----------
    forecast : {datetime: DataFrame}
    out_path : 출력 HTML 경로

    Returns
    -------
    str: 생성된 파일 경로
    """
    rc = RiskCalculator()

    # ── 기본 지도 ──────────────────────────────────────────
    m = folium.Map(
        location=MAP_CENTER,
        zoom_start=MAP_ZOOM,
        tiles="CartoDB dark_matter",   # 어두운 배경 → 위험 색상 대비 선명
    )

    # ── 범례 ───────────────────────────────────────────────
    legend_html = """
    <div style="
        position: fixed; bottom: 30px; right: 30px; z-index: 9999;
        background: rgba(20,20,30,0.88); border-radius: 10px;
        padding: 14px 18px; color: white; font-family: sans-serif;
        font-size: 13px; box-shadow: 0 2px 12px rgba(0,0,0,0.5);
    ">
        <b>🌧️ 싱크홀 위험도</b><br><br>
        <span style="color:#d73027">■</span> 위험 (75+)<br>
        <span style="color:#fc8d59">■</span> 경고 (50~74)<br>
        <span style="color:#fee08b">■</span> 주의 (20~49)<br>
        <span style="color:#91cf60">■</span> 관심 (1~19)<br>
        <span style="color:#d9d9d9">■</span> 안전 (0)<br>
        <br><small>기상청 단기예보 RN1 기반<br>5km×5km 격자</small>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # ── 시간별 GeoJSON 피처 수집 ───────────────────────────
    all_features = []
    sorted_times = sorted(forecast.keys())

    print("GeoJSON 피처 생성 중...")
    for dt in sorted_times:
        df = forecast[dt]
        features = df_to_geojson_features(dt, df, rc, seoul_only=True)
        all_features.extend(features)
        print(f"  {dt.strftime('%H시')} 예보: {len(features)}개 격자 (위험 격자)")

    if not all_features:
        print("[경고] 표시할 위험 격자가 없습니다. 강수 예보가 없는 시간대입니다.")
        m.save(out_path)
        return out_path

    # ── 시간 슬라이더 레이어 추가 ──────────────────────────
    geojson_data = {
        "type": "FeatureCollection",
        "features": all_features,
    }

    TimestampedGeoJson(
        geojson_data,
        period="PT1H",            # 1시간 단위
        duration="PT1H",
        auto_play=True,
        loop=True,
        max_speed=3,
        loop_button=True,
        date_options="HH:mm",
        time_slider_drag_update=True,
        add_last_point=False,
    ).add_to(m)

    # ── 제목 ───────────────────────────────────────────────
    title_html = f"""
    <div style="
        position: fixed; top: 15px; left: 50%; transform: translateX(-50%);
        z-index: 9999; background: rgba(20,20,30,0.88);
        padding: 10px 24px; border-radius: 8px;
        color: white; font-family: sans-serif; font-size: 15px; font-weight: bold;
        box-shadow: 0 2px 10px rgba(0,0,0,0.5);
    ">
        🕳️ 싱크홀 발생 위험도 예측 지도 — {sorted_times[0].strftime('%Y.%m.%d')}
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    m.save(out_path)
    return out_path


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="싱크홀 위험도 시간별 지도 생성")
    ap.add_argument("--key", help="KMA API 인증키 (없으면 환경변수 KMA_API_KEY 사용)")
    ap.add_argument("--data", default=".", help="forecast_rn1_*.csv 파일이 있는 폴더")
    ap.add_argument("--out", default="sinkhole_risk_map.html", help="출력 HTML 파일명")
    args = ap.parse_args()

    # 1) CSV 파일 우선 로드
    forecast = load_forecast_csvs(args.data)

    # 2) CSV 없으면 API에서 실시간 수집
    if not forecast:
        print("CSV 파일 없음 → API에서 실시간 수집...")
        key = args.key or os.environ.get("KMA_API_KEY")
        if not key:
            sys.exit("인증키가 필요합니다. --key 또는 KMA_API_KEY 환경변수를 설정하세요.")
        forecast = fetch_live_forecast(key)

    if not forecast:
        sys.exit("데이터를 가져올 수 없습니다. kma_forecast_grid.py 를 먼저 실행하세요.")

    print(f"\n총 {len(forecast)}개 시각 데이터 로드됨")
    out = build_map(forecast, args.out)
    print(f"\n✅ 지도 생성 완료: {out}")
    print("브라우저에서 열기...")
    import subprocess
    subprocess.run(["open", out])


if __name__ == "__main__":
    main()
