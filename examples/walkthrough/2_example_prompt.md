# Example Prompt

Below is an example of the kind of prompt you might send to your model.
Adapt it to your model's format — the key information is the constraints
and the reference images.

---

You are building a timber-frame house in Blender using Python.

Here are 5 orthographic reference views of the target structure (front, back, left, right, top).

Build a 2-story American Farmhouse timber-frame structure with these constraints:
- Footprint: 7.32m wide x 10.97m deep
- Roof type: gable
- No wings (simple rectangular plan)

Generate a complete Blender Python script that:
1. Creates a collection named "AF_01_0018"
2. Builds all structural members as cube meshes with real-world lumber dimensions in meters:
   - Sill plates (2x6): 0.038m x 0.14m
   - Studs (2x4): 0.038m x 0.089m, spaced 16" (0.406m) on center
   - Joists (2x10): 0.038m x 0.235m
   - Rafters (2x8): 0.038m x 0.184m
   - Top/sole plates, rim boards, ridge beam, etc.
3. Names each member with a structural keyword and unique number (e.g. Sill_01, Stud_01, Rafter_01)
4. Constructs from the ground up: foundation → floor → walls → second floor → roof
