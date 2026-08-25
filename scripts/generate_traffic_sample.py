import os
import json
import numpy as np
import pandas as pd

def generate_sample():
    os.makedirs('data/fixtures', exist_ok=True)
    grid_path = 'data/grid.parquet'
    
    if not os.path.exists(grid_path):
        print(f"{grid_path} not found. Cannot generate mock.")
        return
        
    grid = pd.read_parquet(grid_path)
    
    links = []
    
    # 격자들 중에서 일부(특히 강남/서초)를 극심한 정체 상태로 만들고, 나머지는 원활로 만듦
    for _, row in grid.iterrows():
        lat = row['lat'] + np.random.normal(0, 0.001)
        lon = row['lon'] + np.random.normal(0, 0.001)
        
        # 기본 60km/h (원활)
        speed = 60.0
        
        if row['gu'] in ['강남구', '서초구']:
            # 강남, 서초 지역은 5km/h 수준의 극심한 정체
            speed = 5.0
            
        links.append({
            "link_id": f"LINK_{row['id']}",
            "start_lat": lat,
            "start_lon": lon,
            "speed_kmh": speed
        })
    
    data = {
        "status": "OK",
        "timestamp": "2024-01-01T12:00:00",
        "links": links
    }
    
    with open('data/fixtures/traffic_sample.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
        
    print("Generated mock Traffic JSON at data/fixtures/traffic_sample.json")

if __name__ == '__main__':
    generate_sample()
