import urllib.request
import json

overpass_query = """
[out:json];
area["name"="서울특별시"]->.searchArea;
(
  way["railway"="subway"](area.searchArea);
);
out geom;
"""

url = "http://overpass-api.de/api/interpreter"
req = urllib.request.Request(url, data=overpass_query.encode('utf-8'), method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode('utf-8'))
        print(f"Got {len(data.get('elements', []))} elements")
except Exception as e:
    print(f"Failed: {e}")
