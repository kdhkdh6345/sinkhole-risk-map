"""
tests/test_kma_live.py — 기상청 실시간 강수 어댑터 테스트 (네트워크 없이 가짜 응답 사용)

검증:
  1. AWS 매분자료 + 지점정보 파싱 → 격자별 최근접 관측소 값 배정, origin="live"
  2. 헤더 없는 AWS 응답도 기본 컬럼 순서로 파싱
  3. AWS 실패 시 ASOS 서울(108)로 대체
  4. 키 없음 → 샘플 경로(origin="fixture")
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from sinkhole.sources.kma_live import KST, KmaLiveRainSource

NOW = datetime(2026, 8, 4, 15, 30, tzinfo=KST)

GRID = pd.DataFrame({
    "id": [0, 1, 2],
    "lat": [37.57, 37.50, 33.50],     # 종로 부근, 강남 부근, 제주(서울 밖 → nan)
    "lon": [126.98, 127.04, 126.50],
    "gu": ["종로구", "강남구", "기타"],
})

STN_INF = """# STN LON LAT STN_SP HT STN_KO
#START7777
400 126.98 37.57 1 30 종로
401 127.04 37.50 1 20 강남
999 129.00 35.10 1 5 부산
#7777END
"""

AWS_HEADER = "# YYMMDDHHMI STN WD1 WS1 WDS WSS WD10 WS10 TA RE RN-15m RN-60m RN-12H RN-DAY HM PA PS TD\n"


def _aws_rows(rn60_jongno: float, rn60_gangnam: float) -> str:
    return (
        f"202608041528 400 1 1 1 1 1 1 25 1 5 {rn60_jongno} 120.0 130.0 90 1000 1010 20\n"
        f"202608041528 401 1 1 1 1 1 1 25 1 0 {rn60_gangnam} 10.0 12.0 90 1000 1010 20\n"
        "202608041528 999 1 1 1 1 1 1 25 0 0 0.0 0.0 0.0 90 1000 1010 20\n"
    )


class FakeSource(KmaLiveRainSource):
    """_get을 가짜 응답으로 대체. aws_ok=False면 AWS 호출에서 예외."""

    def __init__(self, aws_ok=True, header=True, **kw):
        super().__init__(api_key="TEST", now_fn=lambda: NOW, **kw)
        self.aws_ok, self.header = aws_ok, header

    def _get(self, url, params):
        if "nph-aws2_min" in url:
            if not self.aws_ok:
                raise RuntimeError("AWS 서버 오류")
            hour = params["tm2"][8:10]
            vals = {"15": (40.0, 3.0), "14": (30.0, 1.0), "13": (25.0, 0.0)}.get(hour, (0.0, 0.0))
            return (AWS_HEADER if self.header else "") + _aws_rows(*vals)
        if "stn_inf" in url:
            return STN_INF
        if "kma_sfctm3" in url:
            # 12시간치, RN은 16번째 칸(인덱스 15). 마지막 3시간: 10, 20, 30mm
            rows = []
            for i in range(12):
                rn = [-9.0] * 9 + [10.0, 20.0, 30.0]
                vals = ["0"] * 46
                vals[0], vals[1], vals[15] = f"2026080415{i:02d}", "108", str(rn[i])
                rows.append(" ".join(vals))
            return "#START\n" + "\n".join(rows) + "\n"
        raise AssertionError(url)


def test_aws_projection_live():
    src = FakeSource()
    out = src.fetch(GRID)
    assert src.origin == "live"
    assert "AWS" in src.detail
    np.testing.assert_allclose(out[0], [40.0, 95.0, 120.0])   # 종로: 1h=40, 3h=40+30+25, 12h=120
    np.testing.assert_allclose(out[1], [3.0, 4.0, 10.0])      # 강남: 3+1+0
    assert np.all(np.isnan(out[2]))                           # 서울 밖 격자 → nan


def test_aws_without_header():
    out = FakeSource(header=False).fetch(GRID)
    np.testing.assert_allclose(out[0], [40.0, 95.0, 120.0])


def test_fallback_to_asos():
    src = FakeSource(aws_ok=False)
    out = src.fetch(GRID)
    assert src.origin == "live"
    assert "ASOS" in src.detail and "AWS" in src.detail
    np.testing.assert_allclose(out[0], [30.0, 60.0, 60.0])    # 결측(-9)은 무강수 0으로 처리
    np.testing.assert_allclose(out[2], out[0])                # 단일 지점 → 전 격자 동일


def test_no_key_uses_fixture():
    src = KmaLiveRainSource(api_key="", now_fn=lambda: NOW)
    out = src.fetch(GRID)
    assert src.origin == "fixture"
    assert out.shape == (3, 3)
    assert "KMA_API_KEY 없음" in src.detail
