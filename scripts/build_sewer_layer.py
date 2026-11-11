"""
build_sewer_layer.py — 구별 하수관 노후율 지도 레이어 생성

입력: data/raw/seoul_gu.geojson (자치구 경계), data/raw/seoul_sewer_aging.csv (구별 노후율)
출력: web/data/seoul_gu_sewer.geojson — 경계 + ratio_30y/ratio_50y/data_type 속성

노후율은 실측(9개 구, 2023년 12월 기준)과 추정(16개 구)이 섞여 있으며, data_type으로 구분해 화면에 표시한다.
실행: python scripts/build_sewer_layer.py  (입력 자료가 바뀔 때만)
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
gu = json.loads((ROOT / "data/raw/seoul_gu.geojson").read_text(encoding="utf-8"))
aging = pd.read_csv(ROOT / "data/raw/seoul_sewer_aging.csv", comment="#").set_index("gu")

for f in gu["features"]:
    name = f["properties"]["name"]
    row = aging.loc[name] if name in aging.index else None
    f["properties"] = {
        "gu": name,
        "ratio_30y": None if row is None else float(row["ratio_30y"]),
        "ratio_50y": None if row is None else float(row["ratio_50y"]),
        "data_type": None if row is None else str(row["data_type"]),
    }

out = ROOT / "web/data/seoul_gu_sewer.geojson"
out.write_text(json.dumps(gu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"저장: {out} ({len(gu['features'])}개 구)")
