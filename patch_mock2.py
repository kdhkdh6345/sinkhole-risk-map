import json
import random

with open('web/data/seoul_dong.geojson', 'r') as f:
    dong_geo = json.load(f)

dongs = [feat["properties"]["adm_nm"] for feat in dong_geo.get("features", [])]

snapshot_path = 'web/data/snapshot_calm.json'
with open(snapshot_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

cell_ids = [c['id'] for c in data.get('cells', [])]

random.seed(42)
selected_ids = random.sample(cell_ids, min(len(cell_ids), 2000))

history_data = {}
for cid in selected_ids:
    dong_name = random.choice(dongs)
    history_data[str(cid)] = {
        "date": f"2023-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
        "time": f"{random.randint(0,23):02d}:{random.randint(0,59):02d}",
        "location": f"{dong_name} {random.randint(1,999)}-{random.randint(1,99)}"
    }

with open('web/data/history.json', 'w', encoding='utf-8') as f:
    json.dump(history_data, f, ensure_ascii=False, indent=2)

