import os
import numpy as np
import pandas as pd
import pytest

from sinkhole.sources.kma import KmaRainfallSource

def test_kma_rainfall_source():
    nc_path = "data/fixtures/kma_sample.nc"
    if not os.path.exists(nc_path):
        pytest.skip(f"Mock NC file not found: {nc_path}")
        
    grid_parquet = "data/grid.parquet"
    if not os.path.exists(grid_parquet):
        pytest.skip(f"Grid file not found: {grid_parquet}")
        
    real_grid = pd.read_parquet(grid_parquet)
    
    # 강남구와 종로구 격자 하나씩 추출
    gangnam_row = real_grid[real_grid['gu'] == '강남구'].iloc[0]
    jongno_row = real_grid[real_grid['gu'] == '종로구'].iloc[0]
    
    test_df = pd.DataFrame([gangnam_row, jongno_row])
    
    source = KmaRainfallSource(nc_path=nc_path)
    result = source.fetch(test_df)
    
    assert result.shape == (2, 3), "Shape must be (N, 3)"
    
    # 강남구: 45, 120, 250
    assert np.isclose(result[0, 0], 45.0)
    assert np.isclose(result[0, 1], 120.0)
    assert np.isclose(result[0, 2], 250.0)
    
    # 종로구: 5, 15, 40
    assert np.isclose(result[1, 0], 5.0)
    assert np.isclose(result[1, 1], 15.0)
    assert np.isclose(result[1, 2], 40.0)
