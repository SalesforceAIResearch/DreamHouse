# DreamHouse Benchmark

Evaluate AI models on timber-frame structure generation. Your model receives reference images and constraints, generates 3D geometry in Blender, and the server validates it against 10 structural engineering tests.

## Prerequisites

- **Python 3.9+**
- **Blender** — free and open-source, download at [blender.org/download](https://www.blender.org/download/). No add-ons or plugins needed — just a standard install.
- `pip install -r requirements.txt`

## Server

The evaluation server is hosted at:

```
https://dreamhouse-eval.example.com
```

Interactive Swagger docs: `https://dreamhouse-eval.example.com/docs`

---

## How It Works

```
Step 1:  Get a task and prompt your model           → your model outputs Blender Python code
Step 2:  Execute the code in Blender, export geometry → produces a JSON submission file
Step 3:  Submit to the server and get results         → pass/fail on 10 structural tests
Step 4:  (Optional) Feed failures back, iterate
```

Full working code for every step: [`examples/quickstart.py`](examples/quickstart.py)
Example inputs/outputs for every step: [`examples/walkthrough/`](examples/walkthrough/)

### Step 1: Get a task and prompt your model

Fetch a task from the server — you'll get constraints (footprint, stories, roof type) and 5 reference images (front, back, left, right, top). Pass these to your model and ask it to generate a Blender Python script.

```python
import requests

SERVER = "https://dreamhouse-eval.example.com"
task = requests.get(f"{SERVER}/v1/tasks/AF_01_0018").json()
```

Example task response: [`examples/walkthrough/1_task_response.json`](examples/walkthrough/1_task_response.json)
Example prompt for your model: [`examples/walkthrough/2_example_prompt.md`](examples/walkthrough/2_example_prompt.md)

### Step 2: Execute in Blender and prepare submission

Run your model's output in Blender headless, then export the geometry using the bundled helper script.

```python
import subprocess

subprocess.run(["blender", "--background", "--python", "generated_code.py"], check=True)
subprocess.run([
    "blender", "--background", "structure.blend",
    "--python", "helpers/blender_export.py",
    "--", "submission.json", "AF_01_0018"
], check=True)
```

This produces `submission.json` — a list of members with their names, positions, and bounding boxes. Example: [`examples/walkthrough/4_submission.json`](examples/walkthrough/4_submission.json)

### Step 3: Submit and get validation results

Create a session, submit the geometry, and poll for results.

```python
import json, time

session = requests.post(f"{SERVER}/v1/sessions", json={
    "task_id": "AF_01_0018", "model_id": "my-model-v1", "protocol": "stepwise",
}).json()

with open("submission.json") as f:
    geometry = json.load(f)

job = requests.post(
    f"{SERVER}/v1/sessions/{session['session_id']}/submit",
    json={"members": geometry["members"]},
).json()

while True:
    time.sleep(2)
    result = requests.get(
        f"{SERVER}/v1/sessions/{session['session_id']}/results/{job['job_id']}"
    ).json()
    if result["status"] in ("complete", "failed"):
        break

print(result["results"]["all_passed"])  # True or False
print(result["results"]["tests"])       # per-test pass/fail
```

Example results: [`examples/walkthrough/7_result_pass.json`](examples/walkthrough/7_result_pass.json), [`examples/walkthrough/7_result_fail.json`](examples/walkthrough/7_result_fail.json)

### Step 4: (Optional) Iterate

If tests failed, feed the results back to your model, regenerate, and submit again to the same session.

---

## Structural Tests

Each submission is validated against 10 tests. `all_passed` is `true` only when all 10 pass.

| Test | What it checks |
|------|---------------|
| `completeness` | Has members from all 4 categories: foundation, floor, walls, roof |
| `load_path` | Continuous load path from roof down to foundation |
| `span_limits` | Joists/rafters don't exceed allowable spans for their size |
| `deflection` | Members stay within deflection limits |
| `roof_coverage` | Rafters cover the full footprint without large gaps |
| `gap_detection` | No gaps larger than 24" on-center between framing members |
| `point_load` | Posts/beams align with supports below |
| `cantilever` | Cantilevers don't exceed backspan/4 or 24" |
| `stability_score` | At least 80% of members are connected to the ground |
| `dual_end_connection` | Rafters and studs are supported at both ends |

## Member Naming

The validator infers each member's role from its name. Include one of these keywords (case-insensitive):

| Category | Keywords |
|----------|----------|
| Foundation | `Sill`, `Post`, `BeamPost`, `Foundation` |
| Floor | `CenterBeam`, `Rim`, `Joist` |
| Walls | `Plate`, `Stud`, `King`, `Trimmer`, `Header`, `Cripple` |
| Roof | `Ridge`, `Rafter`, `Raf`, `Collar`, `Lookout`, `Purlin`, `Valley`, `Hip` |

Names must be unique: `Stud_01`, `Stud_02`, etc.

## Rate Limits

- Session creation: 5/minute
- Geometry submission: 10/minute
- Sessions expire after 48 hours

## Ready-to-Run Examples

- **[`examples/quickstart.py`](examples/quickstart.py)** — Full working loop. Replace `call_your_model()` with your model.
- **[`examples/pipeline_scaffold.py`](examples/pipeline_scaffold.py)** — Multi-step pipeline with retry logic. Subclass `ModelBackend` to plug in your model. Configured via YAML ([`examples/config_example.yaml`](examples/config_example.yaml)).

## License

See LICENSE for details.
