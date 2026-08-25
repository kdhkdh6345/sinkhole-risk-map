import os
import json
import random

def generate_sample():
    os.makedirs('data/fixtures', exist_ok=True)
    
    # 3개의 서울 관측소 가상 데이터
    # 강남구 (37.5, 127.05)
    # 서초구 (37.48, 127.02)
    # 종로구 (37.58, 126.98)
    
    data = {
        "status": "OK",
        "stations": [
            {
                "station_id": "GW_GANGNAM_01",
                "lat": 37.50,
                "lon": 127.05,
                "level_m": 12.5  # 극단적 수위 하강 가정
            },
            {
                "station_id": "GW_SEOCHO_01",
                "lat": 37.48,
                "lon": 127.02,
                "level_m": 11.0  # 극단적 수위 하강 가정
            },
            {
                "station_id": "GW_JONGNO_01",
                "lat": 37.58,
                "lon": 126.98,
                "level_m": 22.0  # 정상
            }
        ]
    }
    
    with open('data/fixtures/gw_sample.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
        
    print("Generated mock Groundwater JSON at data/fixtures/gw_sample.json")

if __name__ == '__main__':
    generate_sample()
