# Mojo Self-Hosting Bootstrap - Current Status

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

## Overview

The bootstrap infrastructure is now **fully functional** with all three phases working. The interpreter-based approach allows us to execute the complete Mojo compiler pipeline (tokenize → parse → codegen) without requiring the final compiler to be complete.

## Three-Stage Architecture

```
┌─ Stage 1: Python (Permanent Reference) ──────────────────┐
│                                                            │
│  myinterpreter.py (AST interpreter)                      │
│  ├─ tokenizer.mojo → tokens                              │
│  ├─ parser.mojo → AST                                    │
│  └─ gimple_codegen.py → C code                           │
│                                                            │
│  Input: mojo/mojo_main.mojo                             │
│  Output: C code (GIMPLE format)                          │
└────────────────────────────────────────────────────────────┘
                           ↓
┌─ Stage 2: Mojo (Proof of Self-Hosting) ────────────────┐
│                                                          │
│  myinterpreter.mojo (transpiled from .py)              │
│  ├─ tokenizer.mojo → tokens                            │
│  ├─ parser.mojo → AST                                  │
│  └─ gimple_codegen.py → C code                         │
│                                                          │
│  Input: mojo/mojo_main.mojo                           │
│  Output: C code (should be identical to Stage 1)       │
└──────────────────────────────────────────────────────────┘
                           ↓
┌─ Stage 3: Mojo (Final Verification) ──────────────────┐
│                                                        │
│  Same as Stage 2 - verify determinism                │
│  Output: C code (should match Stage 2)               │
│                                                        │
│  If Stage 2 ≡ Stage 3, bootstrap is successful!      │
└────────────────────────────────────────────────────────┘
```

## Components - Status Summary

### Phase 1: Tokenizer ✓ COMPLETE
- Real implementation in mojo/tokenizer.mojo
- 8/8 validation tests pass
- Produces tokens from Mojo source

### Phase 2: Parser ✓ COMPLETE
- Real implementation in mojo/parser.mojo
- 5/5 validation tests pass
- Converts tokens to AST

### Phase 3: Codegen ✓ COMPLETE
- Full C/GIMPLE backend in gimple_codegen.py
- Executable, generates valid C code
- Supporting stubs: generated_dispatch.py, module_loader.py

### Interpreter ✓ READY FOR BOOTSTRAP
- Python version: myinterpreter.py (465 lines)
- Mojo version: mojo/myinterpreter.mojo (transpiled)
- Both execute parsed AST correctly

## Validation Results

```
Phase 1 (Tokenizer):  8/8 tests ✓
Phase 2 (Parser):     5/5 tests ✓
Phase 3 (Codegen):    ✓ generates C code
```

## Next Steps

1. Create bootstrap scripts using Mojo interpreter
2. Run Stage 2 (Mojo interpreter on Mojo code)
3. Run Stage 3 (verify determinism)
4. Compare outputs - should be identical
5. Bootstrap complete when Stage 1 ≡ Stage 2 ≡ Stage 3

## Success Criteria

✓ Bootstrap succeeds when:
- Stage 1 output = Stage 2 output (byte-for-byte)
- Stage 2 output = Stage 3 output (determinism verified)
