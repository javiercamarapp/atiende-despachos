import json, sys

# Read entire file
with open("docs/openapi.json") as f:
    raw = f.read()

# The file has a JSON log line followed by the actual JSON.
decoder = json.JSONDecoder()
idx = 0
objects = []
while idx < len(raw):
    try:
        obj, end = decoder.raw_decode(raw, idx)
        objects.append(obj)
        idx = end
    except json.JSONDecodeError:
        idx += 1

# Find the openapi one
for obj in objects:
    if "openapi" in obj:
        with open("docs/openapi.json", "w") as f:
            json.dump(obj, f, indent=2)
        print(f"Fixed! Paths: {len(obj.get('paths', {}))}")
        break
else:
    print("No openapi object found")
    for o in objects:
        if isinstance(o, dict):
            print(type(o), list(o.keys())[:5])
