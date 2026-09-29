import json
from pathlib import Path

# 실제 보도된 서울 주요 싱크홀 사고 (뉴스 팩트 기반)
REAL_SINKHOLES = [
    {"date": "2024-08-29", "location": "서대문구 연희동 성산로", "grade": 3, "lat": 37.568, "lon": 126.931, "dong": "서울특별시 서대문구 연희동"},
    {"date": "2024-08-31", "location": "종로구 종로5가역 인근", "grade": 2, "lat": 37.570, "lon": 127.001, "dong": "서울특별시 종로구 종로5·6가동"},
    {"date": "2024-09-01", "location": "강남구 역삼동 차병원사거리", "grade": 2, "lat": 37.508, "lon": 127.036, "dong": "서울특별시 강남구 역삼1동"},
    {"date": "2014-08-05", "location": "송파구 석촌지하차도 앞", "grade": 3, "lat": 37.502, "lon": 127.104, "dong": "서울특별시 송파구 석촌동"},
    {"date": "2014-08-13", "location": "송파구 석촌호수 부근 (다수 발견)", "grade": 3, "lat": 37.505, "lon": 127.100, "dong": "서울특별시 송파구 석촌동"},
    {"date": "2018-12-21", "location": "여의도 지하도로 공사장", "grade": 3, "lat": 37.525, "lon": 126.924, "dong": "서울특별시 영등포구 여의동"},
    {"date": "2015-02-20", "location": "용산구 용산역 앞", "grade": 3, "lat": 37.529, "lon": 126.965, "dong": "서울특별시 용산구 한강로동"},
    {"date": "2020-08-26", "location": "구로구 구로동 도로", "grade": 2, "lat": 37.495, "lon": 126.887, "dong": "서울특별시 구로구 구로3동"},
    {"date": "2023-05-12", "location": "강남구 삼성역 부근", "grade": 2, "lat": 37.511, "lon": 127.059, "dong": "서울특별시 강남구 삼성1동"},
    {"date": "2022-08-09", "location": "강남구 대치동 학원가 (폭우)", "grade": 2, "lat": 37.498, "lon": 127.060, "dong": "서울특별시 강남구 대치1동"},
    {"date": "2022-08-11", "location": "서초구 서초동 강남역 부근", "grade": 3, "lat": 37.497, "lon": 127.027, "dong": "서울특별시 서초구 서초2동"},
    {"date": "2019-12-31", "location": "여의도 IFC몰 인근", "grade": 2, "lat": 37.525, "lon": 126.925, "dong": "서울특별시 영등포구 여의동"},
    {"date": "2021-06-15", "location": "영등포구 영등포동", "grade": 1, "lat": 37.520, "lon": 126.903, "dong": "서울특별시 영등포구 영등포동"},
    {"date": "2024-04-12", "location": "마포구 홍대입구역 부근", "grade": 2, "lat": 37.556, "lon": 126.923, "dong": "서울특별시 마포구 서교동"}
]

# Load grid to find nearest cells
grid_path = Path("web/data/grid.json")
with open(grid_path, "r", encoding="utf-8") as f:
    cells = json.load(f)["cells"]

history_map = {}
dong_counts = {}

for ev in REAL_SINKHOLES:
    # 1. Map to grid
    closest_cell = None
    min_dist = float('inf')
    for c in cells:
        d = (c['lat'] - ev['lat'])**2 + (c['lon'] - ev['lon'])**2
        if d < min_dist:
            min_dist = d
            closest_cell = c
            
    if closest_cell:
        cid = str(closest_cell['id'])
        history_map[cid] = {
            "date": ev['date'],
            "time": "알수없음",
            "location": ev['location'],
            "grade": ev['grade']
        }
    
    # 2. Count for Dong
    dname = ev['dong']
    dong_counts[dname] = dong_counts.get(dname, 0) + 1

# Save history.json
with open("web/data/history.json", "w", encoding="utf-8") as f:
    json.dump(history_map, f, ensure_ascii=False, indent=2)

# Save dong_history.json
with open("web/data/dong_history.json", "r", encoding="utf-8") as f:
    dong_hist = json.load(f)

for k in dong_hist:
    dong_hist[k] = {"count": 0, "grade": 1}

for dname, count in dong_counts.items():
    if dname in dong_hist:
        dong_hist[dname]["count"] = count
        if count >= 4:
            dong_hist[dname]["grade"] = 5
        elif count == 3:
            dong_hist[dname]["grade"] = 4
        elif count == 2:
            dong_hist[dname]["grade"] = 3
        elif count == 1:
            dong_hist[dname]["grade"] = 2

with open("web/data/dong_history.json", "w", encoding="utf-8") as f:
    json.dump(dong_hist, f, ensure_ascii=False, indent=2)

print(f"Mapped {len(REAL_SINKHOLES)} real sinkhole incidents.")
for dname, count in dong_counts.items():
    print(f"{dname}: {count}건")
