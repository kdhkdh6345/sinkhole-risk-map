"""
tests/test_gw_live.py — 국가지하수측정망 시간자료 어댑터 테스트 (네트워크 없이 가짜 응답)

검증:
  1. 30일 이력 대비 최신 수위 σ 계산, 연속 하강 판정, 격자 투영 (origin="live")
  2. 수위 항목이 깊이(lev)뿐이면 부호를 뒤집어 처리
  3. 직전 스냅샷 캐시 재사용 (refresh 이내면 API 호출 없음)
  4. 키 없음 → 샘플 경로 (origin="fixture")
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import sinkhole.sources.gw_live as gw
from sinkhole.sources.gw_live import KST, GimsGroundwaterSource

NOW = datetime(2026, 11, 11, 14, 0, tzinfo=KST)
GRID = pd.DataFrame({"id": [0, 1], "lat": [37.577, 37.622], "lon": [126.837, 127.052], "gu": ["강서구", "성북구"]})


def _stations_csv(tmp_path):
    p = tmp_path / "st.csv"
    p.write_text("# test\ngennum,name,type,lat,lon,dist_km\n"
                 "84002,서울마곡,충적,37.577167,126.837119,0.2\n"
                 "95502,서울장위,암반,37.622019,127.052003,0.2\n", encoding="utf-8")
    return p


def _hourly(drop_last: float, key="elev"):
    """30일치 시간자료. 평소 10.0±0.1, 마지막 2시간만 drop_last 만큼 하강."""
    rng = np.random.default_rng(0)
    recs, t = [], NOW - timedelta(days=30)
    while t <= NOW:
        v = 10.0 + rng.normal(0, 0.1)
        if t > NOW - timedelta(hours=2):
            v -= drop_last
        recs.append({"gennum": "0", "ymd": t.strftime("%Y%m%d"), "hh": t.strftime("%H"),
                     key: round(v if key == "elev" else 30 - v, 3)})
        t += timedelta(hours=1)
    return {"response": {"resultData": recs}}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _fake_requests(key="elev", calls=None):
    class R:
        @staticmethod
        def get(url, params=None, timeout=None):
            if calls is not None:
                calls.append(params["gennum"])
            drop = 1.0 if params["gennum"] == 84002 else 0.0   # 마곡만 급락
            return FakeResp(_hourly(drop, key))
    return R


def test_sigma_projection_live(tmp_path):
    orig = gw.requests
    gw.requests = _fake_requests()
    try:
        src = GimsGroundwaterSource(api_key="T", now_fn=lambda: NOW,
                                    prev_snapshot=tmp_path / "none.json", stations_csv=_stations_csv(tmp_path))
        out = src.fetch(GRID)
    finally:
        gw.requests = orig
    assert src.origin == "live"
    assert out[0] < -2.0                         # 마곡 격자: 큰 하강
    assert abs(out[1]) < out[0] * -1             # 장위 쪽은 마곡보다 덜 하강
    st = {s["gennum"]: s for s in src.cache["stations"]}
    assert st[84002]["consec"] is True and st[95502]["consec"] is False
    assert src.is_consecutive_valid[0] and not src.is_consecutive_valid[1]


def test_depth_key_sign_flipped(tmp_path):
    orig = gw.requests
    gw.requests = _fake_requests(key="lev")
    try:
        src = GimsGroundwaterSource(api_key="T", now_fn=lambda: NOW,
                                    prev_snapshot=tmp_path / "none.json", stations_csv=_stations_csv(tmp_path))
        out = src.fetch(GRID)
    finally:
        gw.requests = orig
    assert out[0] < -2.0                         # 깊이가 커짐 = 수위 하강 → 음수
    assert src.cache["stations"][0]["key"] == "-lev"


def test_reuse_cache(tmp_path):
    prev = {"source_cache": {"groundwater": {
        "fetched_at": (NOW - timedelta(minutes=10)).isoformat(),
        "stations": [{"gennum": 84002, "name": "a", "lat": 37.577167, "lon": 126.837119,
                      "sigma": -2.5, "consec": True, "n": 700, "last": "2026111113", "key": "elev"}]}}}
    (tmp_path / "prev.json").write_text(json.dumps(prev), encoding="utf-8")
    calls = []
    orig = gw.requests
    gw.requests = _fake_requests(calls=calls)
    try:
        src = GimsGroundwaterSource(api_key="T", now_fn=lambda: NOW,
                                    prev_snapshot=tmp_path / "prev.json", stations_csv=_stations_csv(tmp_path))
        out = src.fetch(GRID)
    finally:
        gw.requests = orig
    assert calls == []
    assert "재사용" in src.detail
    assert abs(out[0] + 2.5) < 1e-6
    assert np.isnan(out[1])                      # 20km 밖 격자는 결측


def test_no_key_fixture(tmp_path):
    src = GimsGroundwaterSource(api_key="", now_fn=lambda: NOW,
                                prev_snapshot=tmp_path / "none.json", stations_csv=_stations_csv(tmp_path))
    out = src.fetch(GRID)
    assert src.origin == "fixture"
    assert out.shape == (2,)
