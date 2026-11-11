"""tests/test_sewer_live.py — 하수관로 수위 구별 요약 (2026-11-12 실제 응답 형식)"""
from sinkhole.sources.sewer_live import _gu_name, summarize

ROWS = [
    {"UNQ_NO": "01-0001", "SE_NM": "종로", "MSRMT_YMD": "2026-11-12 07:52:12.0", "MSRMT_WATL": 0.0, "SGN_STTS": "통신양호", "PSTN_INFO": "새문안로"},
    {"UNQ_NO": "01-0005", "SE_NM": "종로", "MSRMT_YMD": "2026-11-12 07:22:12.0", "MSRMT_WATL": 0.50, "SGN_STTS": "통신양호", "PSTN_INFO": "세종로208"},
    {"UNQ_NO": "01-0005", "SE_NM": "종로", "MSRMT_YMD": "2026-11-12 07:52:12.0", "MSRMT_WATL": 0.16, "SGN_STTS": "통신양호", "PSTN_INFO": "세종로208"},
    {"UNQ_NO": "01-0009", "SE_NM": "종로", "MSRMT_YMD": "2026-11-12 07:52:12.0", "MSRMT_WATL": 9.9, "SGN_STTS": "통신불량", "PSTN_INFO": "x"},
]


def test_summarize_latest_per_station():
    s = summarize(ROWS)
    assert s["gu"] == "종로구" and s["n"] == 2          # 통신불량 제외, 측정소별 최신값
    assert s["max_m"] == 0.16 and s["max_addr"] == "세종로208"
    assert s["time"] == "2026-11-12 07:52"


def test_gu_name():
    assert _gu_name("중") == "중구" and _gu_name("강남구") == "강남구"


def test_empty():
    assert summarize([]) is None
