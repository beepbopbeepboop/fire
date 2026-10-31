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

## CORRECTION, measured while merging: there are TWO floors, and the
## recommended version is on the wrong side of one of them

The measurement above is right about the failure and about the direction of the
answer, and its recommended version is one release too low for half the tree.

```
$ /opt/homebrew/bin/python3.11 -c "compile(open('formal/arm64_proof_gen.py').read(),'x','exec')"
  File "formal/arm64_proof_gen.py", line 8600
    """
SyntaxError: f-string expression part cannot include a backslash
```

PEP 701 (backslashes inside f-string expression parts) is **3.12+**, and
`formal/arm64_proof_gen.py` uses it. So there are TWO floors in this tree, not
one, and which one you meet depends on what you are running:

| what | floor | why |
|---|---|---|
| `tools/formal_sweep.py`, `fire.py build --formal --no-prove` | **3.10+** | `formal/build.py` imports only `formal/{model,imports,arm64_codegen,x86_64_codegen,…}`; `arm64_proof_gen` is behind `if prove:`, so `--no-prove` never reaches it |
| `fire.py build` WITH proofs, `tools/suite.py`'s closure fingerprint, anything importing `formal.arm64_proof_gen` | **3.12+** | PEP 701 in that one file |

Two consequences worth stating:

* a 3.11 host running the second thing produces a *different* and much more
  confusing symptom than the 3.9 one this doc measured — a `SyntaxError` with
  a bare `"""` for a caret line hundreds of lines from the real one, rather
  than the `TypeError` at `formal/model.py:1668`;
* `doc/mojo-manual-python.md:29`'s `python==3.11` and step 1's
  `PYTHON ?= python3.11` would both land on the wrong side of the SECOND floor
  while looking like they satisfy the first, which is the worst of the two
  arrangements: a reader who checked the sweep would conclude 3.11 is enough.

`tools/formal_sweep.py`'s own `interpreter_diagnosis()` guard
(`work/formal4-sweep-x86-a`, `5cd35093`) is right to say 3.10, because the
guard IMPORTS `formal.build` and the sweep runs `--no-prove` — it checks the
floor that applies to it rather than the floor that applies to the tree.

`/opt/homebrew/bin/python3` (3.14.7) is on the right side of both.
Re-measured on the merged tree:

```
$ /opt/homebrew/bin/python3.14 -c "import formal.build, formal.model, \
      formal.arm64_proof_gen, formal.arm64_codegen, formal.x86_64_codegen"
(clean)
```

Nothing else in the tree needs 3.13+ — `compile()` over every top-level `.py`,
plus `formal/*.py` and `tools/*.py`, succeeds on 3.14 with zero syntax failures,
and the modules above import on 3.14 with no warning — so **3.12 is the number
to write down** and 3.14 is what to run.

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
   needs 3.12+: PEP 604 annotations in `gimple_codegen.py` and `formal/` are
   evaluated at def time, and `formal/arm64_proof_gen.py`'s f-strings need
   PEP 701"), or `PYTHON ?= python3` with `/opt/homebrew/bin` ahead of
   `/usr/bin` on the PATH documented.
2. **Or make the failure legible instead.** `fire.py`'s `except ImportError`
   around `_load_formal_build` does not catch a `TypeError` raised during
   `import_module`, so a 3.9 host gets a raw traceback from line 1668 of
   `formal/model.py` and no indication that the interpreter is the problem.
   Wrapping it would turn a 94-file mystery into one sentence.
3. **Do not "fix" it by rewriting the annotations.** `typing.Optional` on 341
   sites is a large diff to `gimple_codegen.py` and `mojo/middle/*`, which are
   the files that owe a full `make gate` (see `CLAUDE.md`), for a problem the
   host's `PATH` already solves.