"""
run_snapshot.py — 스냅샷 생성 메인 스크립트 (Phase 3 완성)

실행:
    python scripts/run_snapshot.py --mode sim --scenario calm
    python scripts/run_snapshot.py --mode sim --scenario heavy_rain
    python scripts/run_snapshot.py --mode sim --scenario extreme
    python scripts/run_snapshot.py --mode real              # Phase 6 이후

산출물:
    web/data/snapshot.json  — 위험도 스냅샷 (AGENTS.md 5.2절 스키마)
    data/state.npz          — 감쇠 진행 상태 (재시작 복원용)

AGENTS.md 5.3절:
  - 계산 실패 시 기존 snapshot.json을 절대 덮어쓰지 않는다.
  - 성공 시에만 파일을 교체한다 (temp 파일 → rename 패턴).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
import yaml

from sinkhole.core.clock import AcceleratedClock, RealClock
from sinkhole.core.field import GridRiskField
from sinkhole.core.store import has_state, load_state, save_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_PARQUET = PROJECT_ROOT / "data" / "grid.parquet"
BASELINE_NPY = PROJECT_ROOT / "data" / "baseline.npy"
SNAPSHOT_JSON = PROJECT_ROOT / "web" / "data" / "snapshot.json"
STATE_NPZ = PROJECT_ROOT / "data" / "state.npz"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="싱크홀 위험도 스냅샷 생성")
    parser.add_argument(
        "--mode",
        choices=["sim", "real"],
        default="sim",
        help="실행 모드 (sim: 시뮬레이션, real: 실제 API)",
    )
    parser.add_argument(
        "--scenario",
        choices=["calm", "heavy_rain", "extreme"],
        default="calm",
        help="[--mode sim 전용] 시나리오",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="기존 state.npz를 무시하고 새로 시작",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"[run_snapshot] mode={args.mode} scenario={args.scenario}")

    # ── 1. 격자 + 기저점수 로드 ────────────────────────────────────────────
    if not GRID_PARQUET.exists():
        print(f"❌ 격자 파일 없음: {GRID_PARQUET}")
        print("   먼저 `python scripts/build_grid.py` 실행하세요.")
        return 1

    if not BASELINE_NPY.exists():
        print(f"❌ 기저점수 파일 없음: {BASELINE_NPY}")
        print("   먼저 `python scripts/build_baseline.py` 실행하세요.")
        return 1

    grid_df = pd.read_parquet(GRID_PARQUET)
    baseline = np.load(BASELINE_NPY)
    print(f"  격자: {len(grid_df):,}개 / 기저점수 범위: {baseline.min():.1f}~{baseline.max():.1f}")

    # ── 2. 시계 생성 ───────────────────────────────────────────────────────
    if args.mode == "sim":
        clock = AcceleratedClock(speed=1.0)  # 시뮬: 실시간 1배속 (스냅샷은 즉시)
    else:
        clock = RealClock()

    # ── 3. GridRiskField 생성 ─────────────────────────────────────────────
    field = GridRiskField(grid_df=grid_df, baseline=baseline, clock=clock)

    # ── 4. 이전 상태 복원 ─────────────────────────────────────────────────
    if not args.no_state and has_state(STATE_NPZ):
        try:
            last_vt = load_state(field, STATE_NPZ)
            clock.set_virtual_time(last_vt)
            print(f"  이전 상태 복원 완료 (last_virtual_time={last_vt:.0f})")
        except Exception as e:
            print(f"  ⚠️  상태 복원 실패 ({e}), 새로 시작합니다.")

    # ── 5. 어댑터 생성 및 업데이트 ────────────────────────────────────────
    if args.mode == "sim":
        from sinkhole.sources.simulated import (
            SimulatedGroundwaterAdapter,
            SimulatedRainAdapter,
            SimulatedTrafficAdapter,
        )

        rain_adapter = SimulatedRainAdapter(scenario=args.scenario)
        gw_adapter = SimulatedGroundwaterAdapter(scenario=args.scenario)
        traffic_adapter = SimulatedTrafficAdapter()
    else:
        # Phase 6-1, 6-2, 6-3: 기상청 강수량 & 지하수위 & 교통량 연동 완비
        from sinkhole.sources.kma import KmaRainfallSource
        from sinkhole.sources.groundwater import SeoulGroundwaterSource
        from sinkhole.sources.traffic import SeoulTrafficSource
        
        rain_adapter = KmaRainfallSource()
        gw_adapter = SeoulGroundwaterSource()
        traffic_adapter = SeoulTrafficSource()

    t_start = time.perf_counter()
    field.update(rain_adapter, gw_adapter, traffic_adapter)
    elapsed_ms = (time.perf_counter() - t_start) * 1000
    print(f"  업데이트 완료 ({elapsed_ms:.1f}ms)")

    # ── 6. 소스 상태 확인 ─────────────────────────────────────────────────
    for ch, status in field.source_status.items():
        icon = "✅" if status == "ok" else "⚠️ "
        print(f"  {icon} {ch}: {status}")

    # ── 7. 스냅샷 계산 (수용 기준 7: 1초 미만) ───────────────────────────
    t_snap_start = time.perf_counter()
    snap = field.snapshot(mode=args.mode)
    snap_elapsed_ms = (time.perf_counter() - t_snap_start) * 1000

    if snap_elapsed_ms > 1000:
        print(f"  ⚠️  스냅샷 계산 {snap_elapsed_ms:.0f}ms — 1초 초과 (수용 기준 위반)")
    else:
        print(f"  스냅샷 계산: {snap_elapsed_ms:.1f}ms ✅")

    # 단계 분포 출력
    cells = snap["cells"]
    from collections import Counter
    stage_counts = Counter(c["stage"] for c in cells)
    print(f"\n  [단계 분포]")
    for s in [1, 2, 3]:
        print(f"    Stage {s}: {stage_counts.get(s, 0):,}개")

    # ── 8. 수용 기준 검증 ─────────────────────────────────────────────────
    stage3_count = stage_counts.get(3, 0)

    if args.scenario == "calm":
        if stage3_count == 0:
            print(f"\n  ✅ calm: Stage 3 없음 ({stage3_count}개)")
        else:
            print(f"\n  ❌ calm: Stage 3 격자 {stage3_count}개 — 수용 기준 1번 위반!")
            return 1

    elif args.scenario == "extreme":
        if stage3_count >= 1:
            print(f"\n  ✅ extreme: Stage 3 {stage3_count}개 존재")
        else:
            print(f"\n  ❌ extreme: Stage 3 격자 없음 — 수용 기준 2번 위반!")
            return 1

    # ── 9. 파일 저장 (실패 시 기존 파일 보존) ────────────────────────────
    import json
    import tempfile
    import os
    from export_config import export_config

    SNAPSHOT_JSON.parent.mkdir(parents=True, exist_ok=True)
    
    # 설정 파일(config.json)도 함께 업데이트
    export_config()
    # temp → rename 패턴: 계산 성공 시에만 기존 파일 교체
    tmp_path = SNAPSHOT_JSON.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(tmp_path, SNAPSHOT_JSON)
        print(f"\n  저장: {SNAPSHOT_JSON}")
    except Exception as e:
        print(f"\n  ❌ 저장 실패: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        return 1
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # ── 10. 상태 저장 ─────────────────────────────────────────────────────
    save_state(field, STATE_NPZ)
    print(f"  상태 저장: {STATE_NPZ}")

    print("\n✅ 스냅샷 생성 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
