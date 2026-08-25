"""
build_grid.py — 서울시 500m 격자 생성 스크립트 (Phase 1)

실행:
    python scripts/build_grid.py

산출물:
    data/grid.parquet   — 불변 격자 파일 (id, lat, lon, gu)
    web/data/grid.json  — 웹 표출용 JSON

AGENTS.md 2절 4항: 이 스크립트는 최초 1회만 실행한다.
재실행이 필요하면 사용자에게 먼저 확인받는다.
"""

import sys
import os

# 패키지 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sinkhole.grid.builder import build_grid

if __name__ == "__main__":
    build_grid()
