import json
import random
import os

# Load snapshot.json to get valid cell IDs
snapshot_path = 'web/data/snapshot_calm.json'
history_path = 'web/data/history.json'

if not os.path.exists(snapshot_path):
    snapshot_path = 'web/data/snapshot.json'

with open(snapshot_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

cells = data.get('cells', [])
cell_ids = [c['id'] for c in cells]

# Select 15 random cells to have historical sinkholes
random.seed(42)  # For reproducibility
selected_ids = random.sample(cell_ids, 15)

history_data = {}
for cid in selected_ids:
    history_data[str(cid)] = {
        "date": f"2023-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
        "time": f"{random.randint(0,23):02d}:{random.randint(0,59):02d}",
        "location": f"서울특별시 송파구 가락동 {random.randint(1,999)}-{random.randint(1,99)}"
    }

with open(history_path, 'w', encoding='utf-8') as f:
    json.dump(history_data, f, ensure_ascii=False, indent=2)

print(f"Generated {history_path} with {len(selected_ids)} mock historical events.")
