import pandas as pd

df = pd.read_csv("E:\PJ\vietnam-tourism-lakehouse\data\places.csv", dtype=str, encoding="utf-8-sig").fillna("")

print("File:", "E:\PJ\vietnam-tourism-lakehouse\data\places.csv")
print("Columns:", df.columns.tolist())
print("Total places:", len(df))

target = "OSM_node_4346215389"

if "place_id" not in df.columns:
    print("ERROR: Missing place_id column")
else:
    df["place_id"] = df["place_id"].str.strip()
    matched = df[df["place_id"] == target]

    if matched.empty:
        print(f"\nNOT FOUND: {target}")
        print("\nSimilar IDs:")
        print(df[df["place_id"].str.contains("4346215389", regex=False)]["place_id"].to_string(index=False))
    else:
        print("\nMATCHED PLACE:")
        cols = [
            c for c in [
                "place_id", "place_name", "province_id",
                "province_name", "crawl_eligible", "validation_status"
            ] if c in df.columns
        ]
        print(matched[cols].to_string(index=False))