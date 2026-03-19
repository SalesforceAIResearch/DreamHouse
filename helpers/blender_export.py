"""
DreamHouse Benchmark — Blender Geometry Export Script

Extracts member geometry from a .blend file into the JSON format
required by the DreamHouse evaluation API.

Usage:
  blender --background structure.blend --python blender_export.py -- output.json CollectionName

Arguments (after "--"):
  1. output_path      — Where to write the JSON file
  2. collection_name  — Name of the Blender collection to export

If the named collection is not found, the script falls back to the
collection with the most MESH objects.

Output format:
  {
    "members": [
      {
        "name": "Sill_01",
        "location": [x, y, z],
        "dimensions": [x, y, z],
        "bbox_world_corners": [[x,y,z], ...],   // 8 corners
        "matrix_world": [[...], [...], [...], [...]]  // 4x4
      },
      ...
    ]
  }
"""

import bpy
import json
import sys
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
output_path = args[0]
collection_name = args[1] if len(args) > 1 else None

collection = None
if collection_name:
    collection = bpy.data.collections.get(collection_name)

if collection is None:
    best, best_count = None, 0
    for c in bpy.data.collections:
        n = sum(1 for o in c.objects if o.type == "MESH")
        if n > best_count:
            best, best_count = c, n
    collection = best

members = []
if collection:
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        corners = [list(obj.matrix_world @ Vector(c)) for c in obj.bound_box]
        members.append({
            "name": obj.name,
            "location": [round(v, 6) for v in obj.location],
            "dimensions": [round(v, 6) for v in obj.dimensions],
            "bbox_world_corners": [[round(v, 6) for v in c] for c in corners],
            "matrix_world": [[round(v, 6) for v in row] for row in obj.matrix_world],
        })

with open(output_path, "w") as f:
    json.dump({"members": members}, f, indent=2)

print(f"Exported {len(members)} members to {output_path}")
