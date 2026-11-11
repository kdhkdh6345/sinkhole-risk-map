"""
sources/kma_live.py — 기상청 API허브 실시간 강수 어댑터 (Phase 6-1)

시도 순서 (앞 단계가 실패하면 다음 단계로):
  1) AWS 매분자료 (nph-aws2_min)  — 서울 내 관측소 수십 곳, 격자별로 가장 가까운 관측소 값 사용
  2) ASOS 시간자료 (kma_sfctm3)   — 서울(108) 1개 지점 값을 전 격자에 동일 적용
  3) 고정 샘플(KmaRainfallSource) — 키가 없거나 API가 모두 실패한 경우

반환: (N, 3) 배열 [1h_mm, 3h_mm, 12h_mm]. 결측은 np.nan.
상태: self.origin = "live"(1·2 성공) / "fixture"(3) → snapshot.source_status에 반영.
     self.detail 에 사용한 경로와 관측소 수를 기록해 로그로 확인할 수 있게 한다.

키: 환경변수 KMA_API_KEY (GitHub Secrets). 코드·저장소에 키를 적지 않는다.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np
import pandas as pd

from .base import RainSourceAdapter
from .kma import KmaRainfallSource

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover
    cKDTree = None  # type: ignore[assignment]

KST = timezone(timedelta(hours=9))
URL_AWS_MIN = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min"
URL_STN_INF = "https://apihub.kma.go.kr/api/typ01/url/stn_inf.php"
URL_ASOS_HR = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"

# 응답에 헤더가 없을 때 쓰는 AWS 매분자료 기본 컬럼 순서
AWS_MIN_DEFAULT_COLS = [
    "TM", "STN", "WD1", "WS1", "WDS", "WSS", "WD10", "WS10", "TA", "RE",
    "RN-15m", "RN-60m", "RN-12H", "RN-DAY", "HM", "PA", "PS", "TD",
]
ASOS_RN_INDEX = 15  # kma_sfctm3 응답의 RN(시간강수량) 위치 (docs/reference/kma_asos.py와 동일)

# 서울 주변 관측소만 사용 (격자 bbox보다 약간 넓게)
SEOUL_BBOX = {"lat_min": 37.38, "lat_max": 37.75, "lon_min": 126.72, "lon_max": 127.23}


def _norm(name: str) -> str:
    """컬럼 이름 비교용 정규화: 'RN-60m' → 'RN60M'."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def _rows(text: str) -> tuple[list[str] | None, list[list[str]]]:
    """API허브 텍스트 응답 → (헤더 후보, 데이터 행). '#' 줄은 주석/헤더."""
    header = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            toks = re.split(r"[\s,]+", s.lstrip("#").strip())
            up = {_norm(t) for t in toks}
            if "STN" in up and (any(t.startswith("RN") for t in up) or "LAT" in up):
                header = toks
            continue
        toks = [t for t in re.split(r"[\s,]+", s) if t != ""]
        if len(toks) >= 3:
            rows.append(toks)
    return header, rows


def _num(tok: str) -> float:
    try:
        v = float(tok)
    except (TypeError, ValueError):
        return np.nan
    return np.nan if v <= -9 else v  # 기상청 결측 표기(-9, -99, -999 …)


class KmaLiveRainSource(RainSourceAdapter):
    """기상청 API허브 실시간 강수 어댑터. 실패 시 단계적으로 대체 경로를 사용한다."""

    origin = "fixture"

    def __init__(
        self,
        api_key: str | None = None,
        now_fn: Callable[[], datetime] | None = None,
        max_dist_deg: float = 0.1,
        timeout: float = 15.0,
    ) -> None:
        self._key = api_key if api_key is not None else os.getenv("KMA_API_KEY")
        self._now_fn = now_fn or (lambda: datetime.now(tz=KST))
        self.max_dist_deg = max_dist_deg
        self.timeout = timeout
        self.detail = ""

    # ── HTTP ────────────────────────────────────────────────────────────
    def _get(self, url: str, params: dict) -> str:
        if requests is None:
            raise RuntimeError("requests 미설치")
        r = requests.get(url, params={**params, "authKey": self._key}, timeout=self.timeout)
        r.raise_for_status()
        try:  # API허브 응답은 서비스마다 UTF-8 또는 EUC-KR
            text = r.content.decode("utf-8")
        except UnicodeDecodeError:
            text = r.content.decode("euc-kr", errors="replace")
        if "인증" in text and ("오류" in text or "유효" in text or "확인" in text) and len(text) < 2000:
            raise RuntimeError(f"인증키 오류 응답: {text[:200]!r}")
        return text

    # ── 1) AWS 매분자료 ─────────────────────────────────────────────────
    def _aws_at(self, tm: datetime) -> pd.DataFrame:
        """특정 시각의 AWS 매분자료 → DataFrame[STN, RN60, RN12H]."""
        text = self._get(URL_AWS_MIN, {"tm2": tm.strftime("%Y%m%d%H%M"), "stn": 0, "disp": 0, "help": 1})
        header, rows = _rows(text)
        cols = header if header and len(header) == len(rows[0] if rows else []) else AWS_MIN_DEFAULT_COLS
        idx = {_norm(c): i for i, c in enumerate(cols)}
        i_stn = idx.get("STN", 1)
        i_60 = idx.get("RN60M", idx.get("RN60"))
        i_12 = idx.get("RN12H", idx.get("RN12"))
        if i_60 is None:
            raise RuntimeError(f"AWS 응답에서 RN-60m 컬럼을 찾지 못함 (헤더: {cols})")
        out = []
        for r in rows:
            if len(r) <= max(i_stn, i_60, i_12 or 0):
                continue
            out.append({
                "STN": r[i_stn],
                "RN60": _num(r[i_60]),
                "RN12H": _num(r[i_12]) if i_12 is not None else np.nan,
            })
        return pd.DataFrame(out)

    def _aws_stations(self) -> pd.DataFrame:
        """AWS 지점정보 → DataFrame[STN, LAT, LON] (서울 주변만)."""
        text = self._get(URL_STN_INF, {"inf": "AWS", "stn": "", "tm": "", "help": 1})
        header, rows = _rows(text)
        i_stn, i_lon, i_lat = 0, 1, 2  # 문서 기준 순서: STN LON LAT …
        if header:
            idx = {_norm(c): i for i, c in enumerate(header)}
            i_stn, i_lon, i_lat = idx.get("STN", 0), idx.get("LON", 1), idx.get("LAT", 2)
        st = pd.DataFrame(
            [{"STN": r[i_stn], "LON": _num(r[i_lon]), "LAT": _num(r[i_lat])}
             for r in rows if len(r) > max(i_stn, i_lon, i_lat)]
        ).dropna()
        b = SEOUL_BBOX
        return st[(st.LAT.between(b["lat_min"], b["lat_max"])) & (st.LON.between(b["lon_min"], b["lon_max"]))]

    def _fetch_aws(self, grid_df: pd.DataFrame) -> np.ndarray:
        tm = self._now_fn().astimezone(KST).replace(second=0, microsecond=0) - timedelta(minutes=2)
        now = self._aws_at(tm)
        h1 = self._aws_at(tm - timedelta(hours=1))[["STN", "RN60"]].rename(columns={"RN60": "RN60_1"})
        h2 = self._aws_at(tm - timedelta(hours=2))[["STN", "RN60"]].rename(columns={"RN60": "RN60_2"})
        df = now.merge(h1, on="STN", how="left").merge(h2, on="STN", how="left")
        df["R1"] = df["RN60"]
        df["R3"] = df[["RN60", "RN60_1", "RN60_2"]].sum(axis=1, min_count=3)  # 3시간 모두 있어야 계산
        df["R12"] = df["RN12H"]

        st = self._aws_stations().merge(df, on="STN", how="inner").dropna(subset=["R1"])
        if len(st) == 0:
            raise RuntimeError("서울 주변 AWS 관측값 0개")
        result = self._project(grid_df, st[["LAT", "LON"]].to_numpy(), st[["R1", "R3", "R12"]].to_numpy())
        self.detail = f"AWS 매분자료 {tm:%Y-%m-%d %H:%M} KST, 서울 주변 관측소 {len(st)}곳"
        return result

    # ── 2) ASOS 서울(108) 시간자료 ───────────────────────────────────────
    def _fetch_asos(self, grid_df: pd.DataFrame) -> np.ndarray:
        end = self._now_fn().astimezone(KST).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=11)
        text = self._get(URL_ASOS_HR, {"tm1": start.strftime("%Y%m%d%H%M"),
                                       "tm2": end.strftime("%Y%m%d%H%M"), "stn": 108, "help": 1})
        _, rows = _rows(text)
        rn = [_num(r[ASOS_RN_INDEX]) if len(r) > ASOS_RN_INDEX else np.nan for r in rows]
        if not rows:
            raise RuntimeError("ASOS 응답에 데이터 행 없음")
        rn = np.nan_to_num(np.array(rn, dtype=np.float64), nan=0.0)  # ASOS는 무강수 시 결측 표기
        r1, r3, r12 = rn[-1], rn[-3:].sum(), rn[-12:].sum()
        self.detail = f"ASOS 서울(108) 시간자료 ~{end:%Y-%m-%d %H}시 KST (단일 지점)"
        return np.tile([r1, r3, r12], (len(grid_df), 1)).astype(np.float64)

    # ── 투영 ─────────────────────────────────────────────────────────────
    def _project(self, grid_df: pd.DataFrame, obs_ll: np.ndarray, obs_val: np.ndarray) -> np.ndarray:
        """관측소 값을 격자에 최근접 이웃으로 배정. max_dist_deg 밖은 nan."""
        grid_ll = np.column_stack([grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy()])
        if cKDTree is not None:
            dist, idx = cKDTree(obs_ll).query(grid_ll, k=1)
        else:
            d2 = ((grid_ll[:, None, :] - obs_ll[None, :, :]) ** 2).sum(axis=2)
            idx = d2.argmin(axis=1)
            dist = np.sqrt(d2[np.arange(len(grid_ll)), idx])
        out = obs_val[idx].astype(np.float64)
        out[dist > self.max_dist_deg] = np.nan
        return out

    # ── fetch ───────────────────────────────────────────────────────────
    def fetch(self, grid_df: pd.DataFrame) -> np.ndarray:
        errors = []
        if self._key:
            for name, fn in (("AWS", self._fetch_aws), ("ASOS", self._fetch_asos)):
                try:
                    result = fn(grid_df)
                    self.origin = "live"
                    if errors:
                        self.detail += f" (앞 단계 실패: {'; '.join(errors)})"
                    return result
                except Exception as e:  # 다음 경로로 넘어간다
                    errors.append(f"{name}: {type(e).__name__}: {str(e)[:150]}")
        else:
            errors.append("KMA_API_KEY 없음")

        self.origin = "fixture"
        self.detail = "실시간 실패 → 샘플 파일 사용 / " + "; ".join(errors)
        return KmaRainfallSource().fetch(grid_df)

    @property
    def channel(self) -> str:
        return "rain"
