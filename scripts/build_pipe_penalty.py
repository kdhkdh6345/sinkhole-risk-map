import json
import math
from pathlib import Path

# Load grid
with open('web/data/grid.json', 'r', encoding='utf-8') as f:
    grid_data = json.load(f)

# Load mock_pipes (which has subways and pipes)
with open('web/data/mock_pipes.geojson', 'r', encoding='utf-8') as f:
    pipes_data = json.load(f)

penalties = {}
threshold_deg = 0.005 # ~500m

for cell in grid_data['cells']:
    cell_id = cell['id']
    lat, lon = cell['lat'], cell['lon']
    has_pipe = False
    for feature in pipes_data['features']:
        # simplistic bounding box check
        for coord in feature['geometry']['coordinates']:
            # GeoJSON is [lon, lat]
            plon, plat = coord[0], coord[1]
            if abs(plon - lon) < threshold_deg and abs(plat - lat) < threshold_deg:
                has_pipe = True
                break
        if has_pipe:
            break
    
    if has_pipe:
        penalties[str(cell_id)] = 10  # 10 point penalty

with open('web/data/pipe_penalties.json', 'w', encoding='utf-8') as f:
    json.dump(penalties, f)

print(f"Computed penalties for {len(penalties)} cells.")
