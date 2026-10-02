# Bootstrap Plan: Mojo Compiler in Mojo

> **ARCHIVED, 2026-10-01. This document describes a bootstrap pipeline that no
> longer exists, and its "✅ COMPLETE" claims are about THAT pipeline, not about
> this compiler.** It is kept as a dated record, with its file names left as
> they were written, because a `sed`-ed rename would produce a document that
> *reads* as current while describing a pipeline with no Makefile rule — and
> that failure mode is worse than an obviously stale one, because it stops
> being obvious.
>
> What it describes: `make transpile` running `apex py2mojo` to write a Mojo
> compiler into `mojo/*.mojo`, compiled from there by a `build/mojo` binary
> into `stage1/mojo` and `stage2/mojo`. None of that exists: there is no
> `transpile:` rule in the Makefile, no `mojo/mojo_main.mojo`, no
> `mojo_compiler.mojo`, and `build/mojo` is written by `build_mojo_cli.py`,
> which nothing runs (see the note in `doc/IMPL.md`).
>
> What the bootstrap is now: `make bootstrap`, which is `tools/suite.py
> bootstrap` — `fire.py --dump-full fire.py` → `fire.ci` → `gcc -fgimple` →
> `stage2/mojo`, verified stage1-vs-stage2-vs-stage3 by `bootstrap-verify`.
> The CLI is `fire.py` (run) or the compiled `mojoc`/`stage*/mojo`. See
> `make check-list` for the steps and `tools/suite.py` for what each one runs.

**Goal**: Produce a self-hosting Mojo compiler ELF binary — a binary that, given the same sources,
produces identical intermediate artifacts to the compiler that built it.

Architecture mirrors GCC's bootstrap: stage1/, stage2/ binaries.

---

## Architecture

```
Python compiler (mojo_compiler.py + gimple_codegen.py + ...)
        │
        │  apex py2mojo  (make transpile)
        ▼
mojo/*.mojo          ← Mojo compiler written in Mojo
        │
        │  build/mojo build  (make stage1)
        ▼
stage1/mojo          ← Mojo compiler compiled by Python compiler
        │
        │  stage1/mojo build  (make stage2)
        ▼
stage2/mojo          ← Mojo compiler compiled by Mojo compiler
        │
        │  --dump-{tokens,ast,c,gimple,all} comparison  (make verify)
        ▼
Bootstrap verified ✓
```

---

## Infrastructure Changes

### 1. `../apex/apex.py` — venv self-activation

Add 4-line re-exec block immediately after imports so apex works from any shell:

```python
_venv = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'bin', 'python3')
if os.path.exists(_venv) and os.path.realpath(sys.executable) != os.path.realpath(_venv):
    os.execv(_venv, [_venv] + sys.argv)
```

### 2. `scripts/py2mojo.sh` — transpile wrapper

Bash script that:
1. Copies named `.py` file to `../apex/workspace/<basename>.py`
2. Pipes `py2mojo <basename>.py\nquit\n` to apex via stdin
3. Copies `../apex/workspace/<basename>.mojo` to `mojo/<basename>.mojo`

Usage: `scripts/py2mojo.sh generated_dispatch.py`

### 3. `build/mojo` — add `--dump-*` flags

Add to Python CLI:

| Flag | Output |
|------|--------|
| `--dump-tokens <file>` | Token stream, one token per line |
| `--dump-ast <file>` | AST, one node per line |
| `--dump-c <file>` | Generated C source (pre-GIMPLE) |
| `--dump-gimple <file>` | Final GIMPLE-annotated C source |
| `--dump-all <file>` | All four above, with section headers |

Same flags go in `mojo/mojo_main.mojo` so both stages support them.

### 4. `mojo/mojo_main.mojo` — hand-written entry point

Imports from transpiled modules; provides full CLI (run/build/repl/--version/--help/--dump-*).
This is the single file compiled into `stage1/mojo` and `stage2/mojo`.

---

## Files to Transpile

| Source | Output | Deps |
|--------|--------|------|
| `generated_dispatch.py` | `mojo/generated_dispatch.mojo` | none |
| `module_loader.py` | `mojo/module_loader.mojo` | none |
| `mojo_compiler.py` | `mojo/mojo_compiler.mojo` | none |
| `gimple_codegen.py` | `mojo/gimple_codegen.mojo` | mojo_compiler, module_loader, generated_dispatch |

Not transpiled: `test_*.py`, `run.py`, `*_gen.py`, `fe_reader.py`, `lang_spec.py`, `build_mojo_cli.py`.

---

## Makefile Targets

```makefile
make bootstrap   # full: preflight → transpile → stage1 → stage2 → verify
make transpile   # apex py2mojo all four compiler .py files → mojo/*.mojo
make stage1      # build/mojo build mojo/mojo_main.mojo -o stage1/mojo
make stage2      # stage1/mojo build mojo/mojo_main.mojo -o stage2/mojo
make verify      # compare --dump-all output of stage1 vs stage2
```

All targets silent on success. Failure prints: stage name, failing file, diff/error, exits 1.

---

## Verify: Intermediate Artifact Comparison

```bash
for f in mojo/mojo_main.mojo mojo/mojo_compiler.mojo mojo/gimple_codegen.mojo; do
    stage1/mojo --dump-all "$f" > build/s1.dump
    stage2/mojo --dump-all "$f" > build/s2.dump
    diff build/s1.dump build/s2.dump || { echo "FAIL verify: $f"; exit 1; }
done
```

All diffs empty = bootstrap verified.

---

## Iteration Strategy

| Stage failure | Fix location |
|--------------|-------------|
| `make transpile` | Fix apex `skills/solver_py2fire.py`; re-run transpile |
| `make stage1` | Fix Mojo parser/compiler for syntax that broke; fix `mojo_main.mojo` |
| `make stage2` | Fix determinism bug in compiler or entry-point |
| `make verify` | Narrow via individual `--dump-*` flags; fix codegen nondeterminism |

Engineering assumption: runtime linkage will work as designed.
If it doesn't, we regroup with the specific failure mode.
