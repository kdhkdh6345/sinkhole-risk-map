"""
static_layers/baseline.py — 정적 기저점수 B 계산 (Phase 2)

네 레이어를 합산하여 격자별 기저점수 B (0~60)를 계산하고
data/baseline.npy에 저장한다.

AGENTS.md 2절 3항: 배점·임계값 코드 하드코딩 금지 → 전부 weights.yaml에서 읽음
AGENTS.md 7절: 결측은 np.nan으로 두고 해당 채널만 제외 (0으로 채우지 않음)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # static_layers → sinkhole → src → project_root
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"
GRID_PARQUET = PROJECT_ROOT / "data" / "grid.parquet"
BASELINE_NPY = PROJECT_ROOT / "data" / "baseline.npy"

from .sewer import compute_sewer_scores
from .borehole import compute_borehole_scores
from .history import compute_history_scores
from .liquefaction import compute_liquefaction_scores


def build_baseline() -> np.ndarray:
    """네 정적 레이어를 합산하여 기저점수 B를 계산하고 저장한다.

    Returns:
        np.ndarray (길이 N): 격자별 기저점수 B [0, 60]
    """
    print("[Phase 2] 정적 기저점수 B 계산 시작...")

    # 격자 데이터 로드
    grid_df = pd.read_parquet(GRID_PARQUET)
    N = len(grid_df)
    print(f"  격자 수: {N:,}개")

    # 레이어별 점수 계산
    print("  레이어 1/4: 하수관 노후도...")
    sewer = compute_sewer_scores(grid_df["gu"])
    print(f"    범위: {sewer.min():.2f} ~ {sewer.max():.2f}")

    print("  레이어 2/4: 시추공 N값 (스텁 — 0점)...")
    borehole = compute_borehole_scores(N)

    print("  레이어 3/4: 과거 침하 이력 (스텁 — 0점)...")
    history = compute_history_scores(N)

    print("  레이어 4/4: 액상화 위험등급 (스텁 — 0점)...")
    liquefaction = compute_liquefaction_scores(N)

    # 합산 (결측 채널 제외 — AGENTS.md 7절)
    layers = np.stack([sewer, borehole, history, liquefaction], axis=1)  # (N, 4)
    # 현재는 스텁 레이어들이 0이라 nan 처리 불필요하지만, 인터페이스 준비
    baseline = np.nansum(layers, axis=1)

    # 수용 기준 검증
    assert len(baseline) == N, f"길이 불일치: {len(baseline)} != {N}"
    assert np.all(baseline >= 0), f"음수 점수 존재: {baseline.min():.2f}"
    assert np.all(baseline <= 60), f"60 초과 점수 존재: {baseline.max():.2f}"

    # 저장
    BASELINE_NPY.parent.mkdir(parents=True, exist_ok=True)
    np.save(BASELINE_NPY, baseline)
    print(f"\n  저장: {BASELINE_NPY}")

    return baseline


def print_distribution(baseline: np.ndarray) -> None:
    """점수 분포 백분위수와 단계 판정 비율을 출력한다 (수용 기준 4번).

    BUILD_PLAN.md Phase 2 수용 기준:
      - 점수 분포의 백분위수(10/25/50/75/90) 출력
      - B >= 30 기준으로 1단계에 해당하는 격자 비율 보고
      - 90% 이상 또는 5% 미만이면 임계값 이상 → 사용자에게 보고
    """
    cfg = _load_config()
    stage1_threshold = cfg["stages"]["stage1"]["b_min"]

    percentiles = [10, 25, 50, 75, 90]
    pct_values = np.percentile(baseline, percentiles)

    print("\n[점수 분포 백분위수]")
    for p, v in zip(percentiles, pct_values):
        print(f"  P{p:2d}: {v:.2f}")

    stage1_count = int(np.sum(baseline >= stage1_threshold))
    stage1_ratio = stage1_count / len(baseline) * 100
    print(f"\n[단계 판정]")
    print(f"  B >= {stage1_threshold} (1단계 기준): {stage1_count:,}개 ({stage1_ratio:.1f}%)")

    if stage1_ratio >= 90:
        print(f"\n⚠️  경고: 1단계 비율이 {stage1_ratio:.1f}% — 임계값 B>={stage1_threshold}이 너무 낮음.")
        print("    코드를 수정하지 말고 사용자에게 보고: 임계값 튜닝 필요")
    elif stage1_ratio <= 5:
        print(f"\n⚠️  경고: 1단계 비율이 {stage1_ratio:.1f}% — 임계값 B>={stage1_threshold}이 너무 높음.")
        print("    코드를 수정하지 말고 사용자에게 보고: 임계값 튜닝 필요")
    else:
        print(f"  → 분포 정상 (5%~90% 범위 내)")


def _load_config() -> dict:
    with open(WEIGHTS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)
