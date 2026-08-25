import os
import numpy as np
import netCDF4 as nc
import pandas as pd

def generate_sample():
    os.makedirs('data/fixtures', exist_ok=True)
    grid_path = 'data/grid.parquet'
    
    if not os.path.exists(grid_path):
        print(f"{grid_path} not found. Cannot generate mock.")
        return
        
    grid = pd.read_parquet(grid_path)
    n_grids = len(grid)
    
    nc_path = 'data/fixtures/kma_sample.nc'
    with nc.Dataset(nc_path, 'w', format='NETCDF4') as rootgrp:
        rootgrp.createDimension('point', n_grids)
        
        lat = rootgrp.createVariable('lat', 'f4', ('point',))
        lon = rootgrp.createVariable('lon', 'f4', ('point',))
        rn_1h = rootgrp.createVariable('rn_1h', 'f4', ('point',))
        rn_3h = rootgrp.createVariable('rn_3h', 'f4', ('point',))
        rn_12h = rootgrp.createVariable('rn_12h', 'f4', ('point',))
        
        # 기상청 관측소가 격자와 1:1로 매핑되어있다고 가정(노이즈 약간 추가)
        lat[:] = grid['lat'].values + np.random.normal(0, 0.001, n_grids)
        lon[:] = grid['lon'].values + np.random.normal(0, 0.001, n_grids)
        
        # 특정 구역(강남구, 서초구 등)에 비가 많이 온 상황 가정
        is_heavy = grid['gu'].isin(['강남구', '서초구']).values
        
        r1 = np.where(is_heavy, 45.0, 5.0)  # 45mm/h in Gangnam/Seocho
        r3 = np.where(is_heavy, 120.0, 15.0)
        r12 = np.where(is_heavy, 250.0, 40.0)
        
        rn_1h[:] = r1
        rn_3h[:] = r3
        rn_12h[:] = r12

    print(f"Generated mock NetCDF4 at {nc_path}")

if __name__ == '__main__':
    generate_sample()
