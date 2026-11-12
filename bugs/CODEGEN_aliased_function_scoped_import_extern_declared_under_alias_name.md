# CODEGEN: an aliased function-scoped import's extern is declared under the LOCAL alias, so every call through the mangled name is an implicit declaration

Status: OPEN. Filed 2026-11-12 while fixing the `gen_module_impl` `char *` ← `int64_t` import-extern clobber (that doc is deleted with its fix); the instance below was in the reduced single-module repro of `mojo/backend_gimple/module_gen.py` before and after that fix — a different root cause.

## Symptom

`mojo/backend_gimple/module_gen.py:10053` is

```python
from mojo.middle.module_shared import module_qualifier as _gmiq
```

(a function-scoped aliased import through a re-export). In the importer's generated C the import-extern preamble emits

```c
#ifndef exprtypes_module_qualifier_d719e0
extern char * _gmiq (char * q);  /* from mojo.middle.exprtypes */
#endif
```

— the `#ifndef` guard is the CANONICAL mangled name but the declared function is the LOCAL alias. Every call site is emitted under the canonical name (`exprtypes_module_qualifier_d719e0 (_t22546);` — five call sites in the same unit), so gcc sees:

```
error: implicit declaration of function 'exprtypes_module_qualifier_d719e0' [-Wimplicit-function-declaration]
error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]   (×5, the implicit-declaration `int` return)
```

## Root cause (measured)

Two rewrites of the signature disagree. The function-scoped import pre-pass (mojo/backend_gimple/emit_funcs.py, the `symbol_name != name` arm beside its `_note_own_func_home` call) rewrites the loader's signature `char * module_qualifier (char * q)` to the alias: `char * _gmiq (char * q)`, and stores it in `imported_symbols[symbol_name]['signature']`. The import-extern block (gen_module_impl, mojo/backend_gimple/module_gen.py) then does `signature = _replace_first_ident(signature, orig_name, safe)` with `orig_name = 'module_qualifier'` and `safe = 'exprtypes_module_qualifier_d719e0'` — but the signature no longer CONTAINS `module_qualifier`, so the replace is a no-op and the extern keeps the alias name, while `safe` (the guard and the call sites) is the mangled one.

Note the guard is inert in the other direction too: it is `#ifndef exprtypes_module_qualifier_d719e0` with no matching `#define`, so the (wrongly-named) extern re-emits once per importing module — the known hazard documented beside that block.

## Scope

1. Make the two rewrites agree: either the pre-pass keeps the original name in `sym_info['signature']` (and records the alias separately), or the extern block replaces the alias when the original is absent (keying on `sym_info['original_name']` AND the local name).
2. Reduce to a two-module program with a function-scoped aliased import of a `str`-returning function and add a regression test with the gcc `-fgimple -Os -g -ftrivial-auto-var-init=zero` verdict (assert the extern is declared under the same name the call site uses).

## Done when

The reduced instance compiles with no implicit declaration and no `char *` ← `int` assignment. Measured in the single-module build only; in the self-host CLOSURE the name is inlined and the extern path is skipped, so this does not currently break `fire.o` — but it breaks every single-module compile of a module with an aliased function-scoped import of a pointer-returning function. A worker does not run the self-host build; say so.
