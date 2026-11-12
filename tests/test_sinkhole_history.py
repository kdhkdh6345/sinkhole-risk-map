"""tests/test_sinkhole_history.py — 국토교통부 지하안전정보 응답 파싱·위치 배정 (활용가이드 v1.4 항목 기준)"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_sinkhole_history as fh  # noqa: E402

LIST_JSON = json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 3, "items": {"item": [
    {"sagoNo": "20240001", "siDo": "서울특별시", "siGunGu": "서대문구", "sagoDetail": "하수관 손상", "sagoDate": "20240829", "no": 1},
    {"sagoNo": "20240002", "siDo": "부산광역시", "siGunGu": "사하구", "sagoDetail": "기타", "sagoDate": "20240901", "no": 2},
    {"sagoNo": "20250003", "siDo": "서울특별시", "siGunGu": "강동구", "sagoDetail": "굴착공사", "sagoDate": "20250324", "no": 3},
]}}}})
INFO = {
    "20240001": {"sagoNo": "20240001", "siGunGu": "서대문구", "dong": "연희동", "addr": "성산로", "sagoDate": "20240829",
                 "sinkWidth": "6", "sinkExtend": "4", "sinkDepth": "2.5", "deathCnt": "0", "sagoDetail": "하수관 손상"},
    "20250003": {"sagoNo": "20250003", "siGunGu": "강동구", "dong": "명일동", "addr": "", "sagoDate": "20250324",
                 "sinkWidth": "20", "sinkExtend": "20", "sinkDepth": "20", "deathCnt": "1", "sagoDetail": "굴착공사"},
}
XML = "<response><header><resultCode>00</resultCode></header><body><items><item><sagoNo>1</sagoNo><siDo>서울특별시</siDo></item></items><totalCount>1</totalCount></body></response>"


def test_parse_json_and_xml():
    items, total, code = fh.parse_items(LIST_JSON)
    assert len(items) == 3 and total == 3 and code == "00"
    items, total, _ = fh.parse_items(XML)
    assert items == [{"sagoNo": "1", "siDo": "서울특별시"}] and total == 1


def test_build_seoul_only_and_located():
    def fake_get(op, params):
        if op == "getSubsidenceList01":
            return fh.parse_items(LIST_JSON)
        return [INFO[params["sagoNo"]]], 1, "00"
    orig = fh._get
    fh._get = fake_get
    try:
        data, msg = fh.build(datetime(2026, 11, 12, tzinfo=fh.KST), {})
    finally:
        fh._get = orig
    ev = {e["sagoNo"]: e for e in data["events"]}
    assert set(ev) == {"20240001", "20250003"}                 # 부산 제외
    assert ev["20240001"]["loc_level"] == "동" and ev["20240001"]["adm_dongs"] == ["서울특별시 서대문구 연희동"]
    assert ev["20250003"]["grade"] == 3                       # 사망자 → 3등급
    assert data["by_dong"]["서울특별시 서대문구 연희동"] == {"count": 1, "grade": 2}
    g = data["by_grid"][str(ev["20240001"]["cell"])]
    assert g["date"] == "2024-08-29" and "하수관" in g["cause"]
    assert "서울 2건" in msg
