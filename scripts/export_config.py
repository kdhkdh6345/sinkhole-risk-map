"""
export_config.py — 브라우저용 설정 JSON 내보내기

AGENTS.md 규칙에 따라, 브라우저 환경(sim.js)에서도 파라미터를 하드코딩하지 않고
weights.yaml과 grid.yaml의 설정을 읽어서 사용해야 합니다.
GitHub Pages에서 상위 디렉터리 접근이 불가능하므로, 이 스크립트가 YAML을 합쳐 
web/data/config.json 으로 출력합니다.
"""

from __future__ import annotations

import json
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_YAML = PROJECT_ROOT / "config" / "weights.yaml"
GRID_YAML = PROJECT_ROOT / "config" / "grid.yaml"
OUT_JSON = PROJECT_ROOT / "web" / "data" / "config.json"


def export_config() -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    
    with open(WEIGHTS_YAML, "r", encoding="utf-8") as f:
        weights = yaml.safe_load(f)
        
    with open(GRID_YAML, "r", encoding="utf-8") as f:
        grid = yaml.safe_load(f)
        
    # 두 설정을 병합 (최상위에 keys)
    combined = {
        "weights": weights,
        "decay": grid.get("decay", {}),
        "stages": weights.get("stages", {})
    }
    
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
        
    print(f"[export_config] 설정 내보내기 완료: {OUT_JSON}")


if __name__ == "__main__":
    export_config()
