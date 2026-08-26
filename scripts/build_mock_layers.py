import json
import random
import os

# Bounds for Seoul roughly
MIN_LNG = 126.8
MAX_LNG = 127.2
MIN_LAT = 37.45
MAX_LAT = 37.65

def generate_mock_pipes():
    features = []
    # Generate 5 major subway-like lines
    for i in range(5):
        coords = []
        # Random start point
        lng, lat = random.uniform(MIN_LNG, MAX_LNG), random.uniform(MIN_LAT, MAX_LAT)
        for _ in range(8):
            coords.append([lng, lat])
            # Random drift
            lng += random.uniform(-0.03, 0.03)
            lat += random.uniform(-0.03, 0.03)
        features.append({
            "type": "Feature",
            "properties": {"type": "subway", "name": f"Subway Line {i+1}"},
            "geometry": {"type": "LineString", "coordinates": coords}
        })
    # Generate 20 minor sewer lines
    for i in range(20):
        coords = []
        lng, lat = random.uniform(MIN_LNG, MAX_LNG), random.uniform(MIN_LAT, MAX_LAT)
        for _ in range(4):
            coords.append([lng, lat])
            lng += random.uniform(-0.01, 0.01)
            lat += random.uniform(-0.01, 0.01)
        features.append({
            "type": "Feature",
            "properties": {"type": "sewer", "name": f"Old Sewer Pipe {i+1}"},
            "geometry": {"type": "LineString", "coordinates": coords}
        })
    return {"type": "FeatureCollection", "features": features}

def generate_mock_complaints():
    complaints = []
    for i in range(50):
        complaints.append({
            "id": i,
            "lng": random.uniform(MIN_LNG, MAX_LNG),
            "lat": random.uniform(MIN_LAT, MAX_LAT),
            "type": random.choice(["지반침하 의심", "도로 패임 (포트홀)", "상하수도 악취 및 누수"]),
            "urgency": random.randint(1, 3)
        })
    return complaints

if __name__ == "__main__":
    pipes = generate_mock_pipes()
    complaints = generate_mock_complaints()
    
    os.makedirs("web/data", exist_ok=True)
    with open("web/data/mock_pipes.geojson", "w") as f:
        json.dump(pipes, f)
    with open("web/data/mock_complaints.json", "w") as f:
        json.dump(complaints, f)
    print("Generated mock layers.")
