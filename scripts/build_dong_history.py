import json
import os

HISTORY_PATH = "web/data/history.json"
GEOJSON_PATH = "web/data/seoul_dong.geojson"
OUTPUT_PATH = "web/data/dong_history.json"

def main():
    if not os.path.exists(HISTORY_PATH):
        print(f"Error: {HISTORY_PATH} not found")
        return
    if not os.path.exists(GEOJSON_PATH):
        print(f"Error: {GEOJSON_PATH} not found")
        return

    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)

    dong_counts = {}
    for h in history.values():
        loc = h.get("location", "")
        parts = loc.split()
        if len(parts) >= 3:
            dong = parts[2]
            dong_counts[dong] = dong_counts.get(dong, 0) + 1

    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    features = geojson.get("features", [])
    
    dong_result = {}
    for feat in features:
        adm_nm = feat["properties"]["adm_nm"]
        dong_result[adm_nm] = {"count": 0, "grade": 1}

    for dong, count in dong_counts.items():
        base_name = dong[:-1] if dong.endswith("동") else dong
        
        for adm_nm in dong_result.keys():
            adm_dong = adm_nm.split()[-1]
            if adm_dong.startswith(base_name):
                dong_result[adm_nm]["count"] += count

    for adm_nm, data in dong_result.items():
        c = data["count"]
        if c <= 2:
            data["grade"] = 1
        elif c <= 5:
            data["grade"] = 2
        elif c <= 8:
            data["grade"] = 3
        elif c <= 12:
            data["grade"] = 4
        else:
            data["grade"] = 5

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dong_result, f, ensure_ascii=False, indent=2)

    print(f"✅ Generated {OUTPUT_PATH} for {len(dong_result)} administrative dongs.")

if __name__ == "__main__":
    main()
