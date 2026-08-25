"""
core/store.py — state.npz 스냅샷 저장·복원 (Phase 3)

수용 기준 5번:
  "프로세스를 종료 후 재시작해도 state.npz에서 감쇠 진행 상태가 복원된다."

저장 내용:
  r_scores, g_scores, t_scores        — 이벤트 시점 원시 점수
  r_event_time, g_event_time, t_event_time — 이벤트 가상 타임스탬프
  last_virtual_time                    — 저장 시점의 가상 시각

복원 시 AcceleratedClock의 start를 last_virtual_time으로 설정하면
감쇠 진행이 저장 시점부터 계속된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .field import GridRiskField

STATE_PATH = Path(__file__).resolve().parents[3] / "data" / "state.npz"


def save_state(field: "GridRiskField", path: Path | None = None) -> Path:
    """GridRiskField 상태를 state.npz에 저장한다.

    Args:
        field: 저장할 GridRiskField 인스턴스
        path:  저장 경로. None이면 data/state.npz 사용.

    Returns:
        저장된 파일 경로
    """
    save_path = path or STATE_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)

    np.savez(
        save_path,
        r_scores=field._r_scores,
        g_scores=field._g_scores,
        t_scores=field._t_scores,
        r_event_time=field._r_event_time,
        g_event_time=field._g_event_time,
        t_event_time=field._t_event_time,
        last_virtual_time=np.array([field.clock.now()]),
    )
    return save_path


def load_state(field: "GridRiskField", path: Path | None = None) -> float:
    """state.npz에서 GridRiskField 상태를 복원한다.

    Args:
        field: 복원 대상 GridRiskField (배열 크기가 일치해야 함)
        path:  저장 경로. None이면 data/state.npz 사용.

    Returns:
        저장 시점의 가상 타임스탬프 (AcceleratedClock.reset(start=...)에 사용)

    Raises:
        FileNotFoundError: state.npz가 없는 경우
        ValueError: 격자 수가 일치하지 않는 경우
    """
    load_path = path or STATE_PATH
    if not load_path.exists():
        raise FileNotFoundError(f"상태 파일 없음: {load_path}")

    data = np.load(load_path)

    n_saved = len(data["r_scores"])
    n_field = len(field._r_scores)
    if n_saved != n_field:
        raise ValueError(
            f"격자 수 불일치: 저장={n_saved}, 현재={n_field}. "
            f"grid.parquet이 변경되었는지 확인하세요."
        )

    field._r_scores = data["r_scores"].copy()
    field._g_scores = data["g_scores"].copy()
    field._t_scores = data["t_scores"].copy()
    field._r_event_time = data["r_event_time"].copy()
    field._g_event_time = data["g_event_time"].copy()
    field._t_event_time = data["t_event_time"].copy()

    last_virtual_time = float(data["last_virtual_time"][0])
    return last_virtual_time


def has_state(path: Path | None = None) -> bool:
    """state.npz가 존재하는지 확인한다."""
    return (path or STATE_PATH).exists()
