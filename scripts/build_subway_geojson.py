import json
from pathlib import Path
import random

features = []
# Create grid of subway lines to mock seoul subway
for i in range(12):
    lat = 37.45 + i * 0.02
    features.append({
        "type": "Feature",
        "properties": {"type": "subway", "name": f"Mock Line {i}"},
        "geometry": {"type": "LineString", "coordinates": [[126.8, lat], [127.2, lat]]}
    })
for i in range(15):
    lon = 126.8 + i * 0.03
    features.append({
        "type": "Feature",
        "properties": {"type": "subway", "name": f"Mock Line {i+12}"},
        "geometry": {"type": "LineString", "coordinates": [[lon, 37.45], [lon, 37.7]]}
    })

geojson = {"type": "FeatureCollection", "features": features}
out_path = Path("web/data/seoul_subway.geojson")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False)
    
print(f"✅ Created mock subway network with {len(features)} lines and saved to {out_path}.")
