# Task data

The local server reads task folders from this directory (or from the path
set by the `DREAMHOUSE_TASKS_DIR` env var).

Each task is a folder named by its task id, containing 5 reference images:

```
houses/
  AF_01_0018/
    AF_01_0018_skin_front.png
    AF_01_0018_skin_back.png
    AF_01_0018_skin_left.png
    AF_01_0018_skin_right.png
    AF_01_0018_skin_front_right.png   # used as the "top" view
    constraints.json                   # optional
```

If `constraints.json` is missing, the server falls back to conservative
defaults (see `server/tasks.py`).

Real task data is **not** committed to this repository. Keep it local and
either place it here (folders under `houses/` are ignored when you add an
entry to `.gitignore`) or point the server at a different directory:

```bash
export DREAMHOUSE_TASKS_DIR=/absolute/path/to/your/houses
```
