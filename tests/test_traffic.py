import os
import pytest
import pandas as pd
import numpy as np

from sinkhole.sources.traffic import SeoulTrafficSource

def test_traffic_source():
    json_path = "data/fixtures/traffic_sample.json"
    if not os.path.exists(json_path):
        pytest.skip("Mock traffic JSON not found")
        
    grid_parquet = "data/grid.parquet"
    if not os.path.exists(grid_parquet):
        pytest.skip(f"Grid file not found: {grid_parquet}")
        
    real_grid = pd.read_parquet(grid_parquet)
    
    # 강남구와 종로구 그리드 하나씩 추출
    gangnam_row = real_grid[real_grid['gu'] == '강남구'].iloc[0]
    jongno_row = real_grid[real_grid['gu'] == '종로구'].iloc[0]
    test_df = pd.DataFrame([gangnam_row, jongno_row])
    
    source = SeoulTrafficSource(json_path=json_path)
    result = source.fetch(test_df)
    
    assert result.shape == (2,), "Shape must be (N,)"
    
    # 강남구 (index 0)는 속도 5km/h 가정 시, 저하율이 1.0 - 5/60 = 0.916 
    assert result[0] > 0.9
    
    # 종로구 (index 1)는 속도 60km/h 가정 시, 저하율이 0.0
    assert result[1] == 0.0
