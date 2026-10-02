# INFRA: the host's bare `python3` is 3.9.6 and the tree needs 3.10+, so a formal sweep run with it reports 100 % `backend-crash`

**Area:** INFRA (the toolchain's interpreter floor). Found 2026-10-02 on
`work/formal4-sweep-std-a`, slice `sweep:std-a`. **NOT FIXED, and it is a
machine/PATH fact rather than a source defect** — see "Whose".

## What was run

```
$ python3 -V
Python 3.9.6
$ python3 tools/formal_sweep.py -j2 -t 90 --no-stdlib \
      ../new-modular/Mojo/stdlib/std/{builtin,collections,memory,algorithm,bit}
[arm64] 94 files: PASS=0 not-pass=94
  backend-crash                  94   the backend RAISED rather than refusing
```

Every one of the 94 lines carried the same terminal reason:

```
BACKEND-CRASH: …/std/memory/pointer.mojo  (the backend raised:
  TypeError: unsupported operand type(s) for |: 'type' and 'NoneType')
```

and it is not the sweep's classification — `fire.py` does the same:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 \
      -o .tmp/popcount.macho …/std/bit/bit.mojo
  File "formal/model.py", line 1668, in <module>
    def call_callee_name(func) -> str | None:
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

## Why

`str | None` in a `def`'s return annotation is evaluated at DEFINITION time, so
PEP 604 needs **3.10+**. Measured over the whole repo with `ast`, **341 sites in
46 files**, and they are not confined to the formal tier:

| file | sites |
|---|---|
| `gimple_codegen.py` | 60 |
| `mojo/middle/exprtypes.py` | 43 |
| `mojo/middle/coro.py` | 35 |
| `formal/model.py` | 39 |
| `mojo/backend_gimple/*` (9 files) | 41 |
| `fe_reader.py`, `mlir.py`, `mojo/middle/*` (rest), `formal/*` (rest) | the remainder |

So `python3` on the PATH has to be 3.10 or newer for **anything** here, and
`formal/model.py` is merely the first import in the chain (`fire.py build
--formal` → `formal.build` → `formal.model`) so it is where the message points.

The same commands under `/opt/homebrew/bin/python3.11` (3.11.16 — the version
`doc/mojo-manual-python.md:29` names, `pixi add "python==3.11"`) classify all 94
files normally. `/opt/homebrew/bin/python3` is 3.14.7 and every other worker on
this machine is already invoking it by absolute path.

## The part that is not a machine fact

**Nothing in the repository states the floor.** `Makefile`'s `PYTHON ?= python3`
and `SUITE = python3 tools/suite.py` are bare, `pixi.toml`'s
`formalbuild = "python3 fire.py formalbuild"` is bare, and `pixi.toml` pins only
`lean4`. A bare `python3` that cannot import the tree's own compiler is a
failure mode with no message saying so — and it fails as a **`backend-crash`**,
which the sweep's own documentation says means "a bug in the compiler's own
plumbing" and which is explicitly "never cached, so it re-runs until the cause
is gone". A reader who ran the sweep that way and read only the summary would
conclude the formal backend crashes on every input, which is the opposite of
the measured `112 pass / 417` on a working interpreter.

## Whose

Not `sweep:std-a`'s, and not worth editing the tree for: the fix is either a
floor in the docs/CI or `/opt/homebrew/bin` on the PATH, both of which are the
machine owner's or the integrator's. This doc exists so that the next person
who sweeps does not spend the ten minutes I did, and so that the 94
`backend-crash` rows are not read as coverage data. `tools/control.py`'s worker
prompt does not put `/opt/homebrew/bin` on the PATH, and that prompt is
`tools/control_prompt.md` in the reference checkout — not this worktree's to
edit under a sweep claim.

## Next step

1. **Put the floor where a reader meets it.** One line in `CLAUDE.md` next to
   the `make check` block ("every recipe here is bare `python3`, and the tree
   needs 3.10+: PEP 604 annotations in `gimple_codegen.py` and `formal/` are
   evaluated at def time"), or `PYTHON ?= python3.11` in the Makefile with the
   override documented.
2. **Or make the failure legible instead.** `fire.py`'s `except ImportError`
   around `_load_formal_build` does not catch a `TypeError` raised during
   `import_module`, so a 3.9 host gets a raw traceback from line 1668 of
   `formal/model.py` and no indication that the interpreter is the problem.
   Wrapping it would turn a 94-file mystery into one sentence.
3. **Do not "fix" it by rewriting the annotations.** `typing.Optional` on 341
   sites is a large diff to `gimple_codegen.py` and `mojo/middle/*`, which are
   the files that owe a full `make gate` (see `CLAUDE.md`), for a problem the
   host's `PATH` already solves.