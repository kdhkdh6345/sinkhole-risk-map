import os
import sqlite3
import numpy as np
import pandas as pd
import pytest

from sinkhole.sources.groundwater import SeoulGroundwaterSource

def test_groundwater_source():
    json_path = "data/fixtures/gw_sample.json"
    db_path = "data/gw_history_test.db"
    
    if not os.path.exists(json_path):
        pytest.skip(f"Mock JSON file not found: {json_path}")
        
    grid_parquet = "data/grid.parquet"
    if not os.path.exists(grid_parquet):
        pytest.skip(f"Grid file not found: {grid_parquet}")
        
    # 기존 테스트 DB 삭제
    if os.path.exists(db_path):
        os.remove(db_path)
        
    real_grid = pd.read_parquet(grid_parquet)
    gangnam_row = real_grid[real_grid['gu'] == '강남구'].iloc[0]
    jongno_row = real_grid[real_grid['gu'] == '종로구'].iloc[0]
    test_df = pd.DataFrame([gangnam_row, jongno_row])
    
    source = SeoulGroundwaterSource(json_path=json_path, db_path=db_path)
    result = source.fetch(test_df)
    
    assert result.shape == (2,), "Shape must be (N,)"
    
    # 2회 연속 하강을 유도하기 위해 한번 더 fetch
    result2 = source.fetch(test_df)
    
    assert source.is_consecutive_valid == True, "Should be true after two consecutive drops"
    
    # 강남구 (index 0)는 극단적 수위하강(12.5m)이므로 σ < -2.0 이어야 함
    assert result2[0] < -2.0
    
    # 종로구 (index 1)는 정상 (22.0m) 이므로 σ > 0 이어야 함
    assert result2[1] > 0.0

    if os.path.exists(db_path):
        os.remove(db_path)
