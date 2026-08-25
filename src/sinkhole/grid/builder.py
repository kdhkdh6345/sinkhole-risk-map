"""
grid/builder.py — 서울시 500m 격자 생성 모듈 (Phase 1)

AGENTS.md 규칙:
  - 격자 인덱스 순서는 생성 후 변경 불가 (2절 4항)
  - bbox, grid_size_m 값은 config/grid.yaml에서 읽음 (2절 3항)
  - geopandas로 서울시 행정경계와 교차 판정하여 경계 밖 격자 제거

산출물 스키마 (AGENTS.md 5.1절):
  data/grid.parquet  — 컬럼: id(int), lat(float), lon(float), gu(str)
  web/data/grid.json — {grid_size_m, count, cells:[{id, lat, lon, gu}]}
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from shapely.geometry import Point

# 프로젝트 루트 (scripts/../../)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "grid.yaml"
GEOJSON_PATH = PROJECT_ROOT / "data" / "raw" / "seoul_gu.geojson"
PARQUET_OUT = PROJECT_ROOT / "data" / "grid.parquet"
JSON_OUT = PROJECT_ROOT / "web" / "data" / "grid.json"


def _load_config() -> dict:
    """config/grid.yaml에서 격자 설정을 읽는다."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _meters_to_degrees(meters: float, ref_lat: float) -> tuple[float, float]:
    """미터 단위 거리를 위도·경도 증분으로 변환한다.

    Args:
        meters:  변환할 거리 (m)
        ref_lat: 기준 위도 (경도 변환 시 cos 보정에 사용)

    Returns:
        (dlat_deg, dlon_deg) — 위도 증분, 경도 증분
    """
    # 지구 반경 기반 근사 (WGS84 평균값)
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * math.cos(math.radians(ref_lat))
    return meters / meters_per_degree_lat, meters / meters_per_degree_lon


def _generate_candidate_centers(cfg: dict) -> list[tuple[float, float]]:
    """bbox 내 500m 간격 격자 중심점 목록을 생성한다.

    bounding box 기준으로 격자를 빽빽하게 채운 뒤
    geopandas 교차 판정에서 서울시 경계 밖을 제거한다.

    Args:
        cfg: grid.yaml 설정 딕셔너리

    Returns:
        [(lat, lon), ...] 후보 중심점 목록
    """
    bbox = cfg["bbox"]
    size_m = cfg["grid_size_m"]
    ref_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2.0

    dlat, dlon = _meters_to_degrees(size_m, ref_lat)

    lats = np.arange(bbox["lat_min"] + dlat / 2, bbox["lat_max"], dlat)
    lons = np.arange(bbox["lon_min"] + dlon / 2, bbox["lon_max"], dlon)

    candidates = [(float(lat), float(lon)) for lat in lats for lon in lons]
    return candidates


def build_grid() -> None:
    """서울시 500m 격자를 생성하고 parquet / JSON으로 저장한다.

    수용 기준 (BUILD_PLAN.md Phase 1):
      1. 격자 수 2,300~2,600개
      2. id 0부터 연속 (빈 번호 없음)
      3. 자치구 25개 모두 등장, gu 결측 없음
      4. grid.json 500KB 미만
      5. 두 번 실행해도 내용 동일
    """
    print("[Phase 1] 서울시 500m 격자 생성 시작...")

    # ── 1. 설정 및 경계 파일 로드 ─────────────────────────────────────────
    cfg = _load_config()
    print(f"  bbox: {cfg['bbox']}")
    print(f"  grid_size_m: {cfg['grid_size_m']}")

    print(f"  서울시 경계 로드: {GEOJSON_PATH}")
    seoul_gdf = gpd.read_file(GEOJSON_PATH)
    # 좌표계를 WGS84(EPSG:4326)로 통일
    if seoul_gdf.crs is None:
        seoul_gdf = seoul_gdf.set_crs(epsg=4326)
    else:
        seoul_gdf = seoul_gdf.to_crs(epsg=4326)

    # 자치구명 컬럼 확인 (GeoJSON 소스마다 다를 수 있음)
    gu_col = _detect_gu_column(seoul_gdf)
    print(f"  자치구 컬럼: '{gu_col}' / 자치구 수: {seoul_gdf[gu_col].nunique()}")

    # 서울시 전체 유니언 폴리곤 (경계 판정용)
    seoul_union = seoul_gdf.geometry.union_all()

    # ── 2. 후보 격자 생성 ────────────────────────────────────────────────
    candidates = _generate_candidate_centers(cfg)
    print(f"  bbox 내 후보 격자: {len(candidates):,}개")

    # ── 3. 서울시 경계 교차 판정 ─────────────────────────────────────────
    print("  서울시 경계 교차 판정 중...")
    points = [Point(lon, lat) for lat, lon in candidates]
    inside_mask = [seoul_union.contains(p) for p in points]

    inside_candidates = [c for c, m in zip(candidates, inside_mask) if m]
    print(f"  경계 내 격자: {len(inside_candidates):,}개")

    # ── 4. 자치구명 부여 ─────────────────────────────────────────────────
    print("  자치구명 부여 중...")
    records = []
    for idx, (lat, lon) in enumerate(inside_candidates):
        pt = Point(lon, lat)
        # 각 격자 중심이 어느 자치구에 속하는지 공간 조인
        match = seoul_gdf[seoul_gdf.geometry.contains(pt)]
        gu = match.iloc[0][gu_col] if not match.empty else _nearest_gu(pt, seoul_gdf, gu_col)
        records.append({"id": idx, "lat": round(lat, 6), "lon": round(lon, 6), "gu": gu})

    df = pd.DataFrame(records)

    # ── 5. 수용 기준 사전 검증 ───────────────────────────────────────────
    assert 2300 <= len(df) <= 2600, (
        f"격자 수 이상: {len(df)}개 (기대: 2300~2600)"
    )
    assert df["id"].is_monotonic_increasing and df["id"].iloc[0] == 0, (
        "id가 0부터 연속하지 않음"
    )
    assert df["gu"].notna().all(), "gu 결측이 있음"
    n_gu = df["gu"].nunique()
    assert n_gu == 25, f"자치구가 {n_gu}개임 (기대: 25개)"

    # ── 6. 저장 ──────────────────────────────────────────────────────────
    PARQUET_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET_OUT, index=False)
    print(f"  저장: {PARQUET_OUT}")

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    grid_json = {
        "grid_size_m": cfg["grid_size_m"],
        "count": len(df),
        "cells": df.to_dict(orient="records"),
    }
    json_str = json.dumps(grid_json, ensure_ascii=False)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        f.write(json_str)

    json_kb = len(json_str.encode("utf-8")) / 1024
    assert json_kb < 500, f"grid.json이 {json_kb:.1f}KB — 500KB 초과"
    print(f"  저장: {JSON_OUT} ({json_kb:.1f} KB)")

    # ── 7. 결과 요약 ─────────────────────────────────────────────────────
    print(f"\n[결과]")
    print(f"  총 격자 수: {len(df):,}개")
    print(f"  id 범위: {df['id'].min()} ~ {df['id'].max()}")
    print(f"  자치구 수: {df['gu'].nunique()}개")
    print(f"\n[자치구별 격자 수]")
    gu_counts = df.groupby("gu").size().sort_values(ascending=False)
    for gu, cnt in gu_counts.items():
        print(f"  {gu:6s}: {cnt:4d}개")

    print("\n✅ Phase 1 격자 생성 완료")


def _detect_gu_column(gdf: gpd.GeoDataFrame) -> str:
    """GeoDataFrame에서 자치구명 컬럼을 자동 탐지한다."""
    candidates = ["name", "SIG_KOR_NM", "SGG_NM", "adm_nm", "gu", "GU_NM"]
    for col in candidates:
        if col in gdf.columns:
            # 실제 한글 자치구명이 있는지 확인
            sample = str(gdf[col].dropna().iloc[0]) if not gdf[col].dropna().empty else ""
            if any(c in sample for c in "구"):
                return col
    # 마지막 수단: 첫 번째 문자열 컬럼
    for col in gdf.columns:
        if col != "geometry" and gdf[col].dtype == object:
            return col
    raise ValueError(f"자치구명 컬럼을 찾지 못했습니다. 컬럼 목록: {list(gdf.columns)}")


def _nearest_gu(pt: Point, gdf: gpd.GeoDataFrame, gu_col: str) -> str:
    """격자 중심이 어느 자치구에도 속하지 않을 때 가장 가까운 자치구를 반환한다.

    경계 바로 위의 격자 처리에 사용 (센트로이드 거리 기준).
    """
    distances = gdf.geometry.distance(pt)
    nearest_idx = distances.idxmin()
    return gdf.loc[nearest_idx, gu_col]
