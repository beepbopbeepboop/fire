# `tools/tu_grind.py` puts its scratch directory in a shared `/tmp` path by default

**Area:** TOOLS (`tools/tu_grind.py`). **Status: OPEN, one line, found 2026-10-03
while fixing `bugs/FORMAL_x86_model_scripts_write_to_a_shared_tmp_path.md`.** Not
fixed there: `tools/` is claimed by three other workers, so the line was named in
that doc rather than edited.

## What I saw

```python
tools/tu_grind.py:29-30
SCRATCH = os.environ.get('TU_SCRATCH',
                         os.path.join(os.environ.get('CLAUDE_JOB_DIR', '/tmp'), 'tu'))
```

and then `classify()` writes both sides' `.ci` under it:

```python
nat_dir = os.path.join(SCRATCH, 'nat')
```

## Why it is a bug

It is the same three-part defect the FORMAL doc named, and only the first part is
about where the bytes go:

1. **`/tmp` is not writable from some sandboxes**, and a file there is not covered
   by the cleanup `.tmp/` gets for free. The corpus has several worktrees and the
   rule every worker here operates under is that scratch lives inside the
   checkout.
2. **The path is SHARED.** `SCRATCH` is a fixed name, so two concurrent runs — two
   worktrees, or one worktree and a direct run — write the SAME `.ci` file, and
   the second writer's bytes are what the first run's `gcc` reads. `TU_SCRATCH`
   overrides it and `CLAUDE_JOB_DIR` scopes it, so this is avoidable today; it is
   the DEFAULT that is wrong, which is the state a run that set neither is in.
3. There is no cleanup, so the artifacts outlive the run even when nothing else
   collided.

## Exact next step

`SCRATCH` should be a `tempfile.mkdtemp(prefix="tu_grind_")` (which honours
`TMPDIR`, so a worker's checkout-local `TMPDIR` puts it inside the tree), removed
in a `finally` around the run, with `TU_SCRATCH` still honoured as the override
for a caller that wants to KEEP the `.ci` files — that is presumably why the
override exists and the fix must not remove it. The guard added for the FORMAL
half (`test_formal_sweep_truth.py::TestScratchDirEstate::_shared_scratch_dirs`,
2026-10-03) is scoped to files that run Lean and so does not reach this one; if
the two are ever brought into one estate, widen it and drop the exemption.