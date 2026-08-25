"""
core/field.py — GridRiskField: 격자별 위험도 상태 관리 (Phase 3)

AGENTS.md 7절:
  "격자 상태는 격자당 객체가 아니라 길이 N의 numpy 배열 세트로 관리한다.
   반복문 대신 벡터 연산을 쓴다."

상태 배열:
  _r_scores      (N,): 마지막 업데이트 시점의 R 점수 (감쇠 전)
  _g_scores      (N,): 마지막 업데이트 시점의 G 점수 (감쇠 전)
  _t_scores      (N,): 마지막 업데이트 시점의 T 점수 (감쇠 전)
  _r_event_time  (N,): R 이벤트 가상 타임스탬프 (clock.now() 단위)
  _g_event_time  (N,): G 이벤트 가상 타임스탬프
  _t_event_time  (N,): T 이벤트 가상 타임스탬프
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import yaml

from ..fusion.decay import apply_decay
from ..fusion.scoring import compute_g, compute_r, compute_stages, compute_t
from ..fusion.bayes import bayesian_fuse, simple_fuse

if TYPE_CHECKING:
    from ..core.clock import Clock
    from ..sources.base import (
        GroundwaterSourceAdapter,
        RainSourceAdapter,
        TrafficSourceAdapter,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = PROJECT_ROOT / "config" / "weights.yaml"
GRID_YAML = PROJECT_ROOT / "config" / "grid.yaml"


class GridRiskField:
    """격자별 싱크홀 위험도 상태를 numpy 배열 세트로 관리한다.

    AGENTS.md 규칙:
      - 격자당 객체 금지: 모든 상태는 (N,) 배열
      - time.time() 직접 호출 금지: clock 주입
      - 배점·임계값 코드 박기 금지: weights.yaml 참조
    """

    def __init__(
        self,
        grid_df: pd.DataFrame,
        baseline: np.ndarray,
        clock: "Clock",
    ) -> None:
        """
        Args:
            grid_df:  격자 DataFrame (id, lat, lon, gu)
            baseline: shape (N,) — 정적 기저점수 B
            clock:    Clock 인터페이스 (RealClock 또는 AcceleratedClock)
        """
        self.grid_df = grid_df.reset_index(drop=True)
        self.baseline = baseline.copy()
        self.clock = clock

        # 설정 파일 로드
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            self._weights_cfg = yaml.safe_load(f)
        with open(GRID_YAML, encoding="utf-8") as f:
            self._grid_cfg = yaml.safe_load(f)

        N = len(grid_df)
        t0 = clock.now()

        # 이벤트 점수 배열 (감쇠 전 원시 점수)
        self._r_scores = np.zeros(N, dtype=np.float64)
        self._g_scores = np.zeros(N, dtype=np.float64)
        self._t_scores = np.zeros(N, dtype=np.float64)

        # 이벤트 타임스탬프 (가상 시각, 초 단위)
        self._r_event_time = np.full(N, t0, dtype=np.float64)
        self._g_event_time = np.full(N, t0, dtype=np.float64)
        self._t_event_time = np.full(N, t0, dtype=np.float64)

        # 소스 상태 추적
        self.source_status: dict[str, str] = {
            "rain": "unknown",
            "groundwater": "unknown",
            "traffic": "unknown",
        }

    # ── 상태 갱신 ────────────────────────────────────────────────────────────

    def update(
        self,
        rain_adapter: "RainSourceAdapter",
        gw_adapter: "GroundwaterSourceAdapter",
        traffic_adapter: "TrafficSourceAdapter",
    ) -> None:
        """세 채널 어댑터로부터 데이터를 받아 상태를 갱신한다.

        각 채널은 독립적으로 실패할 수 있다. 실패한 채널은 np.nan을 유지하고
        나머지 채널로 계산을 계속한다 (AGENTS.md 5.3절).
        """
        t_now = self.clock.now()

        # ── 강수 채널 ─────────────────────────────────────────────────────
        try:
            rain_raw = rain_adapter.fetch(self.grid_df)       # (N, 3)
            r_new = compute_r(rain_raw, self._weights_cfg)    # (N,)
            self._r_scores = r_new
            self._r_event_time = np.full(len(self.grid_df), t_now)
            self.source_status["rain"] = "ok"
        except Exception as e:
            self.source_status["rain"] = f"error: {type(e).__name__}"

        # ── 지하수위 채널 ─────────────────────────────────────────────────
        try:
            sigma_raw = gw_adapter.fetch(self.grid_df)        # (N,)
            # G는 현재 R 점수 (감쇠 전 원시값)를 기준으로 조건 판단
            g_new = compute_g(
                sigma_raw,
                self._r_scores,
                gw_adapter.is_consecutive_valid,
                self._weights_cfg,
            )
            self._g_scores = g_new
            self._g_event_time = np.full(len(self.grid_df), t_now)
            self.source_status["groundwater"] = "ok"
        except Exception as e:
            self.source_status["groundwater"] = f"error: {type(e).__name__}"

        # ── 교통 채널 ─────────────────────────────────────────────────────
        try:
            traffic_raw = traffic_adapter.fetch(self.grid_df)  # (N,)
            t_new = compute_t(traffic_raw, self._weights_cfg)   # (N,)
            self._t_scores = t_new
            self._t_event_time = np.full(len(self.grid_df), t_now)
            self.source_status["traffic"] = "ok"
        except Exception as e:
            self.source_status["traffic"] = f"error: {type(e).__name__}"

    # ── 스냅샷 계산 ──────────────────────────────────────────────────────────

    def snapshot(self, mode: str = "sim", use_bayes: bool = True) -> dict:
        """현재 가상 시각 기준 위험도 스냅샷을 계산한다.

        감쇠를 적용한 R/G/T + B로 총점과 단계를 계산한다.
        AGENTS.md 5.2절 스키마를 정확히 따른다.

        Args:
            mode:      "sim" 또는 "real"
            use_bayes: True이면 베이지안 융합 (unc 필드 채움), False이면 단순 가중합

        Returns:
            dict: snapshot.json 구조 (generated_at, mode, source_status, cells)
        """
        t_now = self.clock.now()

        # 경과 시간 (시간 단위)
        elapsed_r = (t_now - self._r_event_time) / 3600.0
        elapsed_g = (t_now - self._g_event_time) / 3600.0
        elapsed_t = (t_now - self._t_event_time) / 3600.0

        # 감쇠 적용 (세 채널 공용 감쇠 함수)
        r_dec = apply_decay(self._r_scores, elapsed_r, self._grid_cfg)
        g_dec = apply_decay(self._g_scores, elapsed_g, self._grid_cfg)
        t_dec = apply_decay(self._t_scores, elapsed_t, self._grid_cfg)

        # 총점 + 불확실성 (Phase 7-1 베이지안 융합)
        if use_bayes:
            total, unc_arr = bayesian_fuse(self.baseline, r_dec, g_dec, t_dec)
        else:
            total   = simple_fuse(self.baseline, r_dec, g_dec, t_dec)
            unc_arr = np.full(len(self.baseline), np.nan)

        # 단계 판정 (감쇠된 R/G 사용 — 단순 가중합과 동일 기준)
        stages = compute_stages(self.baseline, r_dec, g_dec, self._weights_cfg)

        # generated_at: 현재 KST (UTC+9)
        kst = timezone(timedelta(hours=9))
        generated_at = datetime.now(tz=kst).isoformat(timespec="seconds")

        # cells 배열 구성 (벡터 연산 후 list 변환)
        ids = self.grid_df["id"].tolist()
        cells = [
            {
                "id": int(ids[i]),
                "stage": int(stages[i]),
                "score": round(float(total[i]), 2),
                "b": round(float(self.baseline[i]), 2),
                "r": round(float(r_dec[i]), 2),
                "g": round(float(g_dec[i]), 2),
                "t": round(float(t_dec[i]), 2),
                "unc": round(float(unc_arr[i]), 4) if not np.isnan(unc_arr[i]) else None,
            }
            for i in range(len(ids))
        ]

        return {
            "generated_at": generated_at,
            "mode": mode,
            "source_status": dict(self.source_status),
            "cells": cells,
        }

    def write_snapshot_json(self, path: Path, mode: str = "sim") -> None:
        """스냅샷을 JSON 파일로 저장한다.

        AGENTS.md 5.3절: 실패해도 기존 파일을 덮어쓰지 않는다.
        write_snapshot_json()는 계산 성공 후에만 호출해야 한다.
        """
        snap = self.snapshot(mode=mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
