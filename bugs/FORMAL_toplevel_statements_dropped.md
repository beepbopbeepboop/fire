# FORMAL_toplevel_statements_dropped: a file whose whole body is top-level code builds, runs, and does nothing

`sys.mojo` is deliberately not one of the 204: it is a module docstring plus
twenty-one `def`s and nothing else, so the module this work added introduces no
instance of the defect it documents.

**Status: OPEN. Pre-existing, and it makes at least one sweep PASS a false pass:
`t1.mojo` — the tree's `sys.exit` test — is reported `pass` and exits 0 where the
source says `sys.exit(3)`.**

Found while writing `sys.mojo` (2026-09-29, the `module:sys` claim), at
`ca6e758`.

---

## What I ran

`t1.mojo`, in full:

```mojo
import sys
sys.exit(3)
```

```console
$ python3 fire.py build --formal --no-prove -o t1.aout t1.mojo
Built: t1.aout  [arm64/macho]
$ ./t1.aout ; echo "exit=$?"
exit=0
```

and through the sweep:

```console
$ python3 tools/formal_sweep.py --no-stdlib t1.mojo
[arm64] 1 files: PASS=1 not-pass=0
```

The program is supposed to exit 3. It exits 0, having done nothing, and the
sweep calls that a pass.

## Why

`ARM64Codegen.compile` and `X86_64Codegen.compile` both begin the same way:

```python
functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
if not functions:
    raise CodegenError("no function definitions to compile")
```

and `formal/build.py`'s `_prepare_functions` filters to `FunctionDef` and
`StructDef` too. So every top-level statement that is not a definition or an
import is **dropped without a diagnostic** — not refused, not lowered, dropped.
`_synthetic_main()` then supplies a `main` that returns the test input, so the
image builds, links, passes the bind audit, and computes nothing.

There is no message anywhere saying "top-level statements are not lowered",
because there is no check. The three late checks in `compile_formal`
(`check_frame_field_blob_premises`, `check_frame_subscript_escapes`,
`check_construction_shapes`, `check_module_symbols`) all walk function bodies.

## How much of the tree is in it

```console
$ python3 - <<'PY'
import os, sys
sys.path.insert(0, '.')
import fire_compiler as F
IGNORE = {"ImportStmt", "FromImportStmt", "FunctionDef", "StructDef",
          "ClassDef", "ExprStmt"}
hits = []
for dirpath, dirnames, filenames in os.walk('.'):
    dirnames[:] = [d for d in dirnames
                   if d not in ('.git', 'build', '.tmp', 'lib', '__pycache__')]
    for fn in filenames:
        if not fn.endswith(('.py', '.mojo')):
            continue
        p = os.path.join(dirpath, fn)
        try:
            stmts = F.Parser(F.py_tokenize(
                open(p, encoding='utf-8', errors='replace').read())
                ).parse_module()
        except Exception:
            continue
        top = [type(s).__name__ for s in stmts
               if type(s).__name__ not in IGNORE]
        if top:
            hits.append((p, top[:4]))
print(len(hits), "files with a top-level statement the formal path drops")
PY
204 files with a top-level statement the formal path drops
   ./test_x86_64_decode.py ['AssignStmt', 'AssignStmt', 'ForStmt', 'ForStmt']
   ./module_spec_gen.py ['IfStmt']
   ./fault_tolerance.py ['AssignStmt', 'AssignStmt', 'AssignStmt', 'AssignStmt']
   …
   ./mojo.mojo ['IfStmt']
```

(204 on this tree at `ca6e758`, one of which is `test_formal_sys.py` itself; by
kind: 580 `AssignStmt`, 74 `IfStmt`, 4 `ForStmt`, 1 `MultiAssignStmt`,
1 `AugAssignStmt` over the first four statements of each file.)

Most of the 204 are module-level `AssignStmt`, which is a **different** case and
mostly harmless: `fold_literal_expr` substitutes a literal-only constant at its
read sites inside the same unit, so a module-level `X = 3` works. The ones that
silently compute nothing are the rest — `IfStmt`, `ForStmt`, calls, and any
`AssignStmt` whose right-hand side is not literal-only. `mojo.mojo`'s top-level
`if` is a `try: import gimple_codegen / except: pass` around an optional import,
so that file's "pass" is hollow in a way nobody can see.

## The exact next step

**Refuse, do not lower.** A top-level statement that is not a definition, a
struct, an import, or a module-level constant the folder can fold is a
construct this path does not implement, and the honest answer is a
`CodegenError` naming the statement's type and the file's line — which puts the
file into `codegen` in the sweep, where it belongs, instead of `pass`.

Where: one new check beside the existing late ones in `formal/build.py`, called
from both `compile_formal` and `_formal_module_functions` (the dylib path drops
them the same way — `compile_formal_dylib` filters to `FunctionDef` too, so a
module whose API is a top-level assignment exports nothing and is refused by
`no_public_api_reason` for the wrong reason). `model.module_symbols` already
walks the module's top level and already knows which names folded, so the
"constant" exemption is a lookup rather than a new analysis.

Two consequences to state before doing it, because they are what makes this
bigger than a check:

* the `codegen` count moves by up to 204 files, and the headline coverage rate
  with it. That is the correct direction — the number was counting files that do
  not run — but it should be landed as its own commit with the before/after
  recorded, so the movement is attributable.
* a handful of those files may be genuinely answerable by LOWERING a top-level
  statement into a synthetic initialiser that runs before `main`. That is a
  bigger change than the refusal (it needs a place to put the result, which is
  `bugs/FORMAL_module_state_no_storage.md`'s `__DATA` question) and should not
  be attempted in the same pass.

Until then, treat a sweep `pass` for a file with top-level statements as
unverified. `t1.mojo` is the tree's own example and it is the reason this is
filed rather than left in the report.
