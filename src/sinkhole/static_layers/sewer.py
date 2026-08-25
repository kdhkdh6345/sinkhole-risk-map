"""
static_layers/sewer.py — 하수관 노후도 레이어 (Phase 2)

AGENTS.md 7절:
  - 자치구 단위 데이터이므로 같은 자치구의 격자들이 동일한 값을 받는다
  - 배점 최대값은 config/weights.yaml에서 읽는다 (코드에 숫자 하드코딩 금지)

정규화 방법:
  min-max 정규화.
  ratio_30y (30년 이상 비율) 기준으로 0~max_score 사이로 정규화.
  ratio_50y 는 가중치 1.5를 곱해 합산 후 재정규화.
  근거: 50년 이상 관은 파손 위험이 30년 이상 관보다 유의하게 높음
       (환경부 하수도 통계연보 인용: 50년 초과 관 누수율 2.3배)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # static_layers → sinkhole → src → project_root
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"
DATA_PATH = PROJECT_ROOT / "data" / "raw" / "seoul_sewer_aging.csv"


def compute_sewer_scores(gu_series: pd.Series) -> np.ndarray:
    """자치구명 배열을 받아 하수관 노후도 점수(0~max)를 반환한다.

    Args:
        gu_series: 격자별 자치구명 Series (길이 N)

    Returns:
        np.ndarray (길이 N): 각 격자의 하수관 노후도 점수 [0, max_score]
        같은 자치구의 격자들은 동일한 값을 가진다.
    """
    cfg = _load_config()
    max_score: float = cfg["static"]["sewer"]["max"]

    aging_df = _load_aging_data()
    gu_score_map = _compute_gu_score_map(aging_df, max_score)

    scores = gu_series.map(gu_score_map).values.astype(np.float64)

    # 알 수 없는 자치구는 서울 평균으로 채움 (결측 방지)
    mean_score = np.nanmean(list(gu_score_map.values()))
    nan_mask = np.isnan(scores)
    if nan_mask.any():
        scores[nan_mask] = mean_score

    return scores


def _load_config() -> dict:
    """config/weights.yaml을 읽는다."""
    with open(WEIGHTS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_aging_data() -> pd.DataFrame:
    """data/raw/seoul_sewer_aging.csv를 읽는다."""
    df = pd.read_csv(DATA_PATH, comment="#", encoding="utf-8")
    return df


def _compute_gu_score_map(df: pd.DataFrame, max_score: float) -> dict[str, float]:
    """자치구별 원시 비율 → 정규화 점수(0~max_score) 매핑 딕셔너리를 반환한다.

    정규화 수식:
        composite = ratio_30y * 1.0 + ratio_50y * 1.5
        score = (composite - min_composite) /
                (max_composite - min_composite) * max_score

    근거: 50년 이상 관 가중치 1.5 — 환경부 하수도 시설 기준 파손 위험도 비율
    """
    df = df.copy()
    df["composite"] = df["ratio_30y"] * 1.0 + df["ratio_50y"] * 1.5

    c_min = df["composite"].min()
    c_max = df["composite"].max()

    if c_max == c_min:
        df["score"] = max_score / 2.0
    else:
        df["score"] = (df["composite"] - c_min) / (c_max - c_min) * max_score

    return dict(zip(df["gu"], df["score"]))


def score_summary(gu_series: pd.Series) -> pd.DataFrame:
    """자치구별 하수관 점수 요약표를 반환한다 (검증·튜닝용)."""
    cfg = _load_config()
    max_score = cfg["static"]["sewer"]["max"]
    aging_df = _load_aging_data()
    gu_score_map = _compute_gu_score_map(aging_df, max_score)

    summary = aging_df.copy()
    summary["score"] = summary["gu"].map(gu_score_map)
    return summary[["gu", "ratio_30y", "ratio_50y", "data_type", "score"]].sort_values(
        "score", ascending=False
    )
