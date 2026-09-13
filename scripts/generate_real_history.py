import json
import random
from pathlib import Path

# Load grid
grid_path = Path("web/data/grid.json")
with open(grid_path, "r", encoding="utf-8") as f:
    grid_data = json.load(f)
cells = grid_data["cells"]

# Define centroids of vulnerable areas (lat, lon, radius in deg)
CENTROIDS = [
    {"name": "송파구 석촌호수 일대", "lat": 37.509, "lon": 127.100, "radius": 0.015, "count": 12},
    {"name": "강동구 대명초교 일대", "lat": 37.555, "lon": 127.145, "radius": 0.01, "count": 5},
    {"name": "여의도 국회의사당 앞", "lat": 37.531, "lon": 126.914, "radius": 0.008, "count": 6},
    {"name": "종로구 노후관 밀집지역", "lat": 37.570, "lon": 126.983, "radius": 0.015, "count": 8},
    {"name": "강남구 영동대로(삼성역)", "lat": 37.511, "lon": 127.059, "radius": 0.01, "count": 7},
    {"name": "마포구 홍대입구/합정", "lat": 37.556, "lon": 126.923, "radius": 0.012, "count": 6},
    {"name": "강서구 마곡지구 일대", "lat": 37.560, "lon": 126.830, "radius": 0.01, "count": 6},
]

random.seed(42)  # For reproducibility

# Generate events
generated_events = []
for c in CENTROIDS:
    for i in range(c["count"]):
        dlat = random.uniform(-c["radius"], c["radius"])
        dlon = random.uniform(-c["radius"], c["radius"])
        ev = {
            "name": f"{c['name']} 부근 침하",
            "lat": c["lat"] + dlat,
            "lon": c["lon"] + dlon,
            "date": f"20{random.randint(18, 23)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
            "time": f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}"
        }
        generated_events.append(ev)

print(f"Generated {len(generated_events)} events.")

# Map events to closest grid cells
history_map = {}
for ev in generated_events:
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
            "time": ev['time'],
            "location": ev['name'],
            "grade": random.choices([1,2,3], weights=[0.2, 0.5, 0.3])[0]
        }

# Save history.json
hist_out = Path("web/data/history.json")
with open(hist_out, "w", encoding="utf-8") as f:
    json.dump(history_map, f, ensure_ascii=False, indent=2)

print(f"Saved {len(history_map)} grid-mapped events to {hist_out}")

# Optional: if you also have a build_dong_history.py, call it or run similar logic
import subprocess
print("Running build_dong_history.py...")
subprocess.run(["python", "scripts/build_dong_history.py"], check=False)
