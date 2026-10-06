# Bootstrap Next Steps

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

## Current Status
- ✅ mojo/simple_compiler.mojo created (bootstrap entry point)
- ✅ Parser enhanced (let keyword, slice support)
- ✅ Transpiler partially fixed (? → AnyType, comment placement)
- 🔄 Agent: Fixing gimple_codegen.mojo parse errors (struct methods, decorators)

## When gimple_codegen.mojo Parses Successfully

### 1. Update simple_compiler.mojo
```mojo
# Replace:
from mojo_compiler import tokenize, Parser, compile as mojo_compile

# With:
from mojo_compiler import tokenize, Parser, compile as mojo_compile
from gimple_codegen import GimpleGen

# Then update mojo_gimple to use GimpleGen instead of Python IR
fn mojo_gimple(src: String) -> String:
    let tokens = tokenize(src)
    let stmts = Parser(tokens).parse_module()
    return GimpleGen().gen_module(stmts)
```

### 2. Run make bootstrap
```bash
make clean-bootstrap
make bootstrap
```

This will:
- Transpile gimple_codegen.py → mojo/gimple_codegen.mojo (now with valid syntax)
- Compile stage1 using Python build/mojo
  - Dumps GIMPLE from mojo/simple_compiler.mojo
  - Links with compiler_main.c + mojo_runtime.c
- Compile stage2 using stage1/mojo
  - Self-compiles the Mojo compiler
- Verify by comparing --dump-all output between stage1 and stage2

### 3. Expected Blockers After gimple_codegen.mojo Parses

#### Link Time
- `mojo_compile`, `tokenize`, Parser not available as C symbols
- Solution: Either (a) provide from Python via C API, or (b) refactor imports

#### Runtime Issues
- GimpleGen may depend on Python structures not available in Mojo
- Need to verify all external dependencies are Mojofied

#### Verification Failures
- stage1 and stage2 may produce different dumps
- Indicates: compilation bugs, determinism issues, or missing features

## Branch Points

### If gimple_compile.mojo still has errors after compiler fixes
- Consider alternative: implement gimple_codegen natively in Mojo (high effort)
- Or: accept Python IR for now, defer full GIMPLE to future

### If link errors prevent stage1 from compiling
- Refactor simple_compiler.mojo to not import unresolved functions
- Provide compiler functions from C harness using Python C API

### If stage1 and stage2 dumps differ
- Debug which part of the compiler has non-determinism
- Check compilation of that module
- May need iterative fixes to compiler/generated code

## Success Criteria

✅ Bootstrap complete when:
1. stage1/mojo compiles successfully
2. stage2/mojo compiles successfully  
3. stage1 and stage2 produce identical --dump-all output
4. stage2/mojo can self-compile itself (mojo build mojo/simple_compiler.mojo)
