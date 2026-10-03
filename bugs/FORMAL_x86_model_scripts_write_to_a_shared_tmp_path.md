# the two x86-64 model scripts write their generated Lean to a shared hard-coded /tmp path

**Area:** FORMAL (`formal/x86_64_model_coverage_test.py`,
`formal/x86_64_model_test.py`). **Status: OPEN, two lines, found 2026-10-02 on
`work/formal8-14` while re-running the coverage check after B24.** Not fixed
there: that branch's claims are three bug docs, and this is not one of them.

## What I ran

```
$ python3 formal/x86_64_model_coverage_test.py
x86-64 model coverage: 151 samples over 57 forms — all steppable
step-lemma applicability: 22 lemma(s) at 48 real encoding(s), 482 hypotheses — every hypothesis satisfiable
```

and, in the same worktree, `formal/x86_64_model_test.py` and the
`formal/x86_64_endtoend_test.py` sweep. Both scripts passed, and both had
written outside the checkout.

## What I saw

```python
formal/x86_64_model_coverage_test.py:684:    workdir = os.path.join("/tmp", "x86_model_coverage")
formal/x86_64_model_test.py:123:    workdir = os.path.join("/tmp", "x86_model_test")
```

`os.makedirs(workdir, exist_ok=True)`, then the generated `Coverage.lean` /
`Model.lean` is written there and handed to `lean` **by relative name with
`cwd=workdir`**:

```python
cp = L.run_lean(lean, [os.path.basename(src)], cwd=workdir, env=env, wall_s=…, cpu_s=…)
```

## Why it is a bug, and it is not "outside the sandbox"

Three things, in increasing order of how much they cost.

1. **It violates the rule every worker in this tree operates under.** Scratch
   belongs inside the checkout (`.tmp/`, git-ignored); `/tmp` is not writable
   from some of the sandboxes these jobs run in, and a file there is not covered
   by the cleanup that `.tmp/` gets for free.

2. **The path is SHARED, so two runs collide on the same file.** Both scripts are
   registered suite jobs (`formal-x86-model`, `formal-x86`), the corpus has
   several worktrees, and `tools/suite.py` runs `-j 18`. Two concurrent
   invocations — two worktrees, or one worktree and a direct run — write the
   SAME `Coverage.lean` and then `lean` it, and the second writer's bytes are what
   the first invocation's `lean` reads. This is precisely the hazard
   `formal/lean.py::ensure_library` documents at length and takes an exclusive
   `flock` over, with a private temp plus `os.replace`, to prevent:

   > concurrent unsynchronised writes to one output path can interleave into a
   > truncated or mixed `.olean`, and every later typecheck then reads it.

   The coverage file is 151 `native_decide` goals plus 482 more, so an
   interleaved read is not a small corruption and the failure would be reported
   as "a form is not steppable" or "hypothesis N does not hold" — a model or
   lemma bug, in the wrong file.

3. **The same name is used by two different scripts**, so the collision is not
   even between copies of one script.

## Exact next step

Replace both with `tempfile.mkdtemp()` and clean up after, in the `finally` the
coverage script's `run_lean` result is already computed in:

```python
workdir = tempfile.mkdtemp(prefix="x86_model_coverage")
try:
    …
finally:
    shutil.rmtree(workdir, ignore_errors=True)
```

`tempfile` and `shutil` are not imported in either file yet. Both scripts take
`LEAN_PATH = workdir:LIB`, so the generated file is found either way — the
substitution is confined to the two lines named above plus the cleanup.

**Worth checking in the same pass:** `tools/tu_grind.py:30` does
`os.path.join(os.environ.get('CLAUDE_JOB_DIR', '/tmp'), 'tu')`, which has the
same shape and defaults to `/tmp` when that variable is unset. That file is
outside FORMAL, so it is named here rather than fixed.
