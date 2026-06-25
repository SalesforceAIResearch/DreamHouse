# DreamHouse Benchmark

Evaluate AI models on timber-frame structure generation. Your model receives
reference images and constraints, generates 3D geometry in Blender, and
DreamHouse validates it against 10 structural engineering tests.

## Links

- [Project page](https://luluyuyuyang.github.io/dreamhouse/)
- [Run benchmark tutorial](https://luluyuyuyang.github.io/dreamhouse/run.html)
- [arXiv paper](https://arxiv.org/abs/2603.24866)
- [GitHub repository](https://github.com/SalesforceAIResearch/DreamHouse)

## Recommended Install

The easiest way to run DreamHouse is through the published Python package:

```bash
pip install dreamhouse
dreamhouse --help
```

Then let the CLI check your environment and set up the runtime artifacts:

```bash
dreamhouse doctor
dreamhouse setup --download-artifacts
```

If Blender is not installed, the CLI can install the tested default runtime:

```bash
dreamhouse setup --download-artifacts --install-blender
```

For a step-by-step walkthrough, see the
[Run Benchmark tutorial](https://luluyuyuyang.github.io/dreamhouse/run.html).

## Prerequisites

- **Python 3.9+**
- **Blender 4.5.4 LTS** is the recommended runtime. This release uses
  Blender's bundled Python 3.11, which matches the provided validator artifact.
- The `dreamhouse` CLI from PyPI, installed with `pip install dreamhouse`

## Server

The evaluator runs **locally on your machine**. The server in this repo mirrors the public `/v1/...` API and invokes Blender under the hood to validate each submission.

```
http://localhost:8000
```

Interactive Swagger docs: `http://localhost:8000/docs`

See [Running the server locally](#running-the-server-locally) below for setup.

---

## Quick Start

Install the package from PyPI:

```bash
pip install dreamhouse
```

You do **not** need to clone this repository for the standard CLI workflow.
For development from a cloned repository, use `pip install -e .` instead.

Check your local environment:

```bash
dreamhouse doctor
```

Set up benchmark artifacts. This downloads the split task pack, reassembles
it, verifies the checksum, and installs the validator artifact:

```bash
dreamhouse setup --download-artifacts
```

If Blender is not already installed, use the tested default:

```bash
dreamhouse setup --download-artifacts --install-blender
```

The recommended runtime is **Blender 4.5.4 LTS** with bundled **Python 3.11**.
If you use your own Blender install, run `dreamhouse doctor` and make sure its
Python version is 3.11.x.

Validator artifacts are selected by Blender's bundled Python version. The
initial release provides `validation.pyc` for Python 3.11. Future releases may
include versioned artifacts such as `validation-cp311.pyc`; `dreamhouse setup`
will choose the matching file automatically.

Run a harness smoke test:

```bash
dreamhouse smoke-test --task BN_01_0003 --output-dir ./runs/smoke_BN_01_0003
```

This uses a built-in stub agent. It verifies setup, Blender execution,
geometry export, server submission, and validation. It is **not** a model
evaluation.

Run one task with your own agent:

```bash
dreamhouse run \
  --task BN_01_0003 \
  --agent my_agent:generate \
  --output-dir ./runs/BN_01_0003
```

Your agent function must accept `(prompt: str, images: list[str],
feedback: list[dict])` and return Blender Python code. See
[`examples/agent_template.py`](examples/agent_template.py).

Two common agent patterns are supported out of the box:

Hosted OpenAI API:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4.1
dreamhouse run --task BN_01_0003 --agent examples.openai_agent:generate
```

Self-hosted OpenAI-compatible endpoint:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8001/v1
export OPENAI_API_KEY=dummy
export OPENAI_MODEL=my-vision-model
dreamhouse run --task BN_01_0003 --agent examples.openai_compatible_agent:generate
```

For local integration testing without a real model, run the mock endpoint:

```bash
python examples/mock_openai_server.py --port 8001
```

List available task ids:

```bash
dreamhouse list-tasks --limit 20
```

You can also start only the local API server:

```bash
dreamhouse server --port 8000
```

---

## How It Works

### Inputs and outputs

Users provide:

- `dreamhouse_tasks_1200.dhpack`
- installed validator artifact
- Blender path
- model code that turns a task prompt + 5 reference images into Blender Python

Each run outputs:

- generated Blender code
- generated `structure.blend`
- exported geometry submission
- validation results and feedback history

The benchmark does not require users to access the original source `.blend`
files.

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

SERVER = "http://localhost:8000"
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

## Running the server locally

The standard CLI path above starts and manages the local server for you. This
section is for users who want to run the API server manually from a cloned
repository.

The benchmark runs locally. Manual server setup needs Blender and the provided
benchmark artifacts:

- `dreamhouse_tasks_1200.dhpack` — task metadata and reference images
- compiled validator artifact — installed into `server/_private/`

The original benchmark source `.blend` files are not required to run
evaluation.

### 1. Install dependencies

```bash
pip install dreamhouse
```

For local development from this repository:

```bash
pip install -e .
```

### 2. Download benchmark artifacts

Download the runtime artifacts from the maintainer-provided release folder:

https://drive.google.com/drive/folders/1hY4xohyQ7IxxQSG5tz0U-e6OZOdGOV3b?usp=drive_link

The folder should contain:

```text
SHA256SUMS.txt
validation.pyc
dreamhouse_tasks_1200.dhpack.part-00
dreamhouse_tasks_1200.dhpack.part-01
dreamhouse_tasks_1200.dhpack.part-02
```

The recommended setup command performs the download, reassembly, checksum
verification, and validator install automatically:

```bash
dreamhouse setup --download-artifacts
```

For manual setup, download all files into one local directory and reassemble
the task pack:

```bash
cat dreamhouse_tasks_1200.dhpack.part-* > dreamhouse_tasks_1200.dhpack
shasum -a 256 dreamhouse_tasks_1200.dhpack
```

Expected checksum:

```text
390273e4b300ea35985ea569e4b1684a60ce3feb865f8194ff87c801109dff86
```

If the checksum does not match, re-download the split files before running the
benchmark.

### 3. Install the validator

Install the validator artifact provided with the benchmark release:

```bash
python scripts/install_validator.py /path/to/validation.pyc

# Verify it is in place
python scripts/install_validator.py --check
```

If you are a maintainer working from source, the same command also accepts a
local `validation.py` and compiles it for you. The installed validator lives
in `server/_private/`, which is ignored by git.

### 4. Point the server at the task pack

Set `DREAMHOUSE_TASKS_PACK` to the `.dhpack` file:

```bash
export DREAMHOUSE_TASKS_PACK=/absolute/path/to/dreamhouse_tasks_1200.dhpack
```

Do not unpack the task pack. The local server reads it directly.

### 5. Start the server

```bash
# Blender executable (adjust for your OS if different)
export BLENDER_PATH=/Applications/Blender.app/Contents/MacOS/Blender

uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Swagger UI: http://localhost:8000/docs
Health check: http://localhost:8000/healthz

If port 8000 is already in use (e.g. by another local service), pick a
different port and tell the example clients about it:

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8765
export DREAMHOUSE_SERVER=http://localhost:8765
```

### Configuration

| Env var                      | Purpose                                    | Default                                                 |
|------------------------------|--------------------------------------------|---------------------------------------------------------|
| `DREAMHOUSE_TASKS_PACK`      | Path to the provided task pack             | unset                                                   |
| `DREAMHOUSE_VALIDATOR`       | Path to the compiled validator             | `<repo>/server/_private/validation.pyc`                 |
| `DREAMHOUSE_BLENDER_TIMEOUT` | Seconds per validation run                 | `180`                                                   |
| `BLENDER_PATH`               | Blender executable                         | auto-detected by `dreamhouse`; server fallback is macOS default |
| `DREAMHOUSE_SERVER`          | Server URL used by the example clients     | `http://localhost:8000`                                 |

---

## Rate Limits

- Session creation: 5/minute
- Geometry submission: 10/minute
- Sessions expire after 48 hours

## Ready-to-Run Examples

### `examples/quickstart.py` — single-task loop

```bash
export DREAMHOUSE_SERVER=http://localhost:8000      # if different, e.g. 8765
python examples/quickstart.py \
  --task BN_01_0003 \
  --agent my_agent:generate \
  --output-dir ./runs/BN_01_0003
```

Use `dreamhouse run --agent module:function` for real model evaluation.
The shipped stub is only used by `dreamhouse smoke-test`; it emits four sill
plates so you can verify the harness plumbing.

For direct script-level harness testing only, pass `--use-stub`.

#### What to expect in the console

A successful run prints 7 numbered phases per attempt, then an Artifacts
summary:

```
[1] Fetching task BN_01_0003...         pulls task spec + 5 reference images
[2] Creating eval session...            returns a session_id
[3] Generating code (attempt N)...      calls your --agent function
[4] Executing in Blender...             runs the code, saves structure.blend
[5] Exporting geometry...               writes submission.json with N members
[6] Submitting to eval server...        POSTs /v1/sessions/.../submit
[7] Results: [VALIDATION FAILED]        validator's verdict on those members
      Passed: 5/10
      Failed tests: completeness, load_path, roof_coverage, ...
```

If `all_passed` is `True` the loop exits; otherwise it retries up to
`--max-retries` times (default 3) using the feedback.

With the **stub model** you should expect:

- Steps 1-6 all succeed (plumbing is fine)
- `Passed: 5/10` every attempt (sill plates only)
- Failing tests: `completeness`, `load_path`, `roof_coverage`,
  `gap_detection`, `stability_score`
- Member count grows each retry (4 → 8 → 12) because the Blender scene is
  *preserved across retries* and the stub keeps adding the same 4 sills.
  Real iterative models use this to refine their previous attempt.

If any step fails before `[7]` you'll see one of:

- `Blender error:` — generated code raised in Blender (syntax error,
  bad API call, etc.)
- `No members exported` — Blender ran but the collection was empty
- `No results from server` — submit/poll timed out or the server hit an
  internal error. Check the uvicorn log and that the validator is
  installed (`python scripts/install_validator.py --check`).

#### Output layout

`--output-dir` (or a fresh temp directory if omitted):

```
<output_dir>/
├── task.json               task spec fetched from the server
├── images/                 reference images for this task only
├── structure.blend         last Blender scene produced by the model
├── submission.json         latest export (same content as newest attempt's)
├── attempts/
│   ├── attempt_1/
│   │   ├── code.py         model-generated Blender Python for this attempt
│   │   ├── submission.json exported geometry sent to the server
│   │   └── result.json     full validation result returned by the server
│   └── attempt_2/...
├── results.json            latest validation result (shortcut)
└── summary.json            task id, session id, every attempt, final verdict
```

**How to read each file**

- **`task.json`** — exactly what the server handed the model, including
  the constraints (footprint, stories, roof type) used to write the
  prompt. Useful when debugging why the model misunderstood the task.
- **`images/*.png`** — the 5 reference views for the current task.
- **`attempts/attempt_N/code.py`** — the raw Blender Python the model
  produced for attempt N. Open it in any editor to inspect what the
  model chose to generate.
- **`attempts/attempt_N/submission.json`** — the geometry that was
  actually sent to the server. One entry per framing member with
  `name`, `location`, `dimensions`, `bbox_world_corners`, `matrix_world`.
  The `name` prefix (`Sill_`, `Stud_`, `Rafter_`, ...) is what the
  validator uses to classify each member.
- **`attempts/attempt_N/result.json`** — the full response from
  `/v1/sessions/.../results/...`, including `tests` (per-test pass/fail),
  `all_passed`, `pass_rate`, and `stability_details` /
  `dual_end_details` diagnostics.
- **`structure.blend`** — the Blender scene after the *last* attempt.
  Open in Blender to visually inspect what was built; handy for
  debugging geometry issues the numeric tests point at.
- **`results.json`** — a shortcut to the last attempt's `result.json`,
  so you don't have to know which attempt number was last.
- **`summary.json`** — the single most useful file. Contains the task
  id, session id, final `status` (`passed`, `failed`, `blender_error`,
  `export_empty`, `submit_failed`, or `no_submission`), every attempt's
  member count / pass rate / failed tests / feedback string, and the
  final `results` object. This is what you read into a notebook or
  dashboard when scoring a model across many tasks.

#### Interpreting the tests

All 10 tests are described in detail in the [Structural Tests](#structural-tests)
table above. When reading `results.json["tests"]`, the most common
failure patterns are:

| Failure          | Usually means                                                   |
|------------------|-----------------------------------------------------------------|
| `completeness`   | Model didn't produce at least one member from each of foundation / floor / walls / roof |
| `load_path`      | Loads from roof/floors don't reach a foundation member          |
| `roof_coverage`  | Rafters don't span the full footprint (partial roof)            |
| `gap_detection`  | Framing spacing is wider than 24" on-center in some region      |
| `stability_score`| <80% of members are connected (via adjacency) to the ground     |
| `dual_end_connection` | Rafters or studs not supported at both ends               |
| `point_load`     | Posts/beams landing on unsupported spans                        |
| `cantilever`     | Overhang exceeds `backspan/4` or 24"                            |
| `span_limits`    | Joist/rafter spans exceed IRC tables for their cross-section    |
| `deflection`     | Members sag more than the allowable deflection limit            |

### `examples/pipeline_scaffold.py` — multi-step pipeline with retries

```bash
python examples/pipeline_scaffold.py --config examples/config_example.yaml
```

Configured via [`examples/config_example.yaml`](examples/config_example.yaml).
Subclass `ModelBackend` (see `DummyBackend` in the file) to plug in your
own model. Writes per-step validation reports and per-attempt artifacts
into the configured `output_dir`.

The `DREAMHOUSE_SERVER` env var **overrides** the YAML `server_url`, so a
single config file works across ports without edits.

## License

See LICENSE for details.
