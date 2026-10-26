# FORMAL: `import m as n` binds `n`, but the backend's module-reference recogniser only knows `m`, so every `n.f(…)` is refused as "'n' has no home"

**Area:** FORMAL, `formal/build.py`'s module-qualified call recognition
(`_this_unit_modules`) and `formal/model.py::dylib_module_reference`. **Status:
OPEN, found 2026-10-13 on `work/formal398-docs`** while adding cross-module
one-field-struct binding (that work is in `formal/imports.py`::
`imported_module_function_defs`, ``imported_function_defs``, and
`formal/build.py`). **Not fixed here** — it is a different construct from that
change's subject (an aliased module BASE, not a callee's declared `-> T`) and it
touches shared check paths, so it is filed rather than worked.

## What I ran, what I saw, what I expected

A library and a program, in one directory:

```mojo
# lib2.mojo
def answer() -> Int:
    return 42
```

```mojo
# main_alias.mojo
import lib2 as L

def main() -> Int:
    return L.answer()
```

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove --backend=arm64 \
    -o /tmp/main_alias.out main_alias.mojo
build: main: 'L' has no home: this module declares no module-level name by that
  spelling, and the reading function declares no local or parameter by it either.
  …
```

**Expected:** the program builds and exits 42. The SAME program WITHOUT the
alias is fine on both backends:

```mojo
import lib2

def main() -> Int:
    return lib2.answer()
```

builds and, run, exits 42. The only difference is `as L`.

## Why

`formal/model.py::dylib_module_reference` is THE recogniser of "is the root of
this dotted chain a module, or a value?" and it is handed
`imports.imported_modules(stmts)` — the modules that must be on the link line —
NOT the names this file BOUND for them. `imported_modules` answers "which
modules" and is deliberately blind to the alias: for `import lib2 as L` it
returns `['lib2']`, so the call's root `L` matches nothing in that tuple and the
chain is treated as a value receiver. The refusal then comes from the ordinary
unresolved-name rule, which is where "'L' has no home" is; it is a
consistent-but-wrong sentence about an import that is right there in the file.

The `from … import f as g` half is NOT affected — that is a bound NAME and
`imported_bindings` already carries `g` (I verified: `from lib2 import make as
mk; var r = mk(9); return r.returncode` builds and answers 9). It is only the
module-base alias, whose binding is `(alias, module, module)` in
`model.import_bindings`, that this recogniser never sees.

`formal/imports.py` already reads the alias for the callee-declaration table
(`imported_module_function_defs` keys by `alias or part.split(".")[0]`), so the
data is one call away; what is missing is that the SAME local name is not in the
tuple `dylib_module_reference` consults.

## The exact next step

The tuple handed to the recogniser has to be "the names in this file that name a
module", not "the modules". One reader, used everywhere the recogniser is:

1. Add `formal/imports.py::imported_module_bindings(stmts) -> tuple` (or reuse
   the alias half of `imported_module_function_defs`): the LOCAL name of every
   module binding — `m` for `import m`, `n` for `import m as n`, `os` for
   `import os.path` — read from `model.import_bindings` and kept in source
   order.
2. Pass it where `imports.imported_modules(stmts)` is passed to a MODULE-
   REFERENCE check (`_prepare_functions`' `_this_unit_modules` at the
   `_rewrite_method_calls` call, `_formal_module_functions`' sibling, and
   `check_module_symbols`' `imported_module_names`), keeping
   `imported_modules` for the LINK LINE, where the real name is what a manifest
   is keyed by. The two answers are different questions about one statement, so
   they must not be one variable.
3. Guard it with a `dylib_export_module` lookup so an alias that names a module
   with no export called `answer` still refuses with the export sentence rather
   than being exempted wholesale — the prefix rule already in
   `dylib_module_reference` covers `import os.path`, so only the alias spelling
   is new.

The pin is a two-file case like the one above (`import lib2 as L` / `lib2.mojo`),
built and RUN on both backends against CPython, in `test_formal_monomorph.py`
(whose `run_pair_case` is the multi-module harness) — the same shape as the two
rows the 2026-10-13 cross-module one-field-struct work added there.
