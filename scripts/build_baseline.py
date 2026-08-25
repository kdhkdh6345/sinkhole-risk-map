"""
build_baseline.py — 정적 기저점수 B 계산 스크립트 (Phase 2)

실행:
    python scripts/build_baseline.py

산출물:
    data/baseline.npy     — 격자별 기저점수 B (0~60)
    docs/tuning.md        — 점수 분포 기록
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sinkhole.static_layers.baseline import build_baseline, print_distribution

if __name__ == "__main__":
    baseline = build_baseline()
    print_distribution(baseline)

    # tuning.md 기록
    import numpy as np
    from pathlib import Path
    from datetime import datetime

    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    docs_dir.mkdir(exist_ok=True)
    tuning_path = docs_dir / "tuning.md"

    pct = np.percentile(baseline, [10, 25, 50, 75, 90])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry = f"""
## {now} — Phase 2 기저점수 분포

| 백분위 | 값 |
|--------|-----|
| P10 | {pct[0]:.2f} |
| P25 | {pct[1]:.2f} |
| P50 | {pct[2]:.2f} |
| P75 | {pct[3]:.2f} |
| P90 | {pct[4]:.2f} |

- 하수관 노후도만 실제 데이터 적용 (나머지 3개 레이어: 0점 스텁)
- B >= 30 격자: {int(np.sum(baseline >= 30)):,}개 ({int(np.sum(baseline >= 30))/len(baseline)*100:.1f}%)
- 전체 격자: {len(baseline):,}개

"""
    with open(tuning_path, "a", encoding="utf-8") as f:
        if not tuning_path.exists() or tuning_path.stat().st_size == 0:
            f.write("# tuning.md — 점수 분포 및 임계값 조정 기록\n\n")
        f.write(entry)

    print(f"\n  분포 기록: {tuning_path}")
    print("\n✅ Phase 2 기저점수 계산 완료")
