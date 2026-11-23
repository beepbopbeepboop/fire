# CODEGEN: an UNANNOTATED module-level scalar global imported by name reads 0 in the per-file compile (replan part 1 of 4)

## Goal

In the per-file (`do_imports=False`) compile the bootstrap `--dump` stages use, a bare
`from helper import CONST` must read the defining module's value when `helper.py` declares it
UNANNOTATED (`CONST = 41`). Today it reads 0.

The export machinery and the definer's accessor already work for an ANNOTATED global
(`CONST: int = 41`), so this part is the classifier that decides whether an unannotated
`NAME = RHS` line is exported at all.

## Where and what was measured (2026-11-23)

Fixture: `helper.py` = `CONST = 41\ndef double_it(x: int) -> int:\n    return x * 2\n`,
`main.py` = `from helper import CONST\nprint(CONST)\n`. Both compiled through
`build_stdlib_dylib.compile_module_to_c` (the per-file path), linked with
`runtime/fire_runtime.c`, run.

- Unannotated: the importer's C carries `_t1 = (int64_t)0;  /* ct param or undeclared: CONST */`
  and the program prints `0` where CPython prints `41` — a silent wrong answer.
- The SAME fixture with `CONST: int = 41` prints `41`, so `module_loader`'s export entry,
  `_emit_imported_global_accessors`, and the definer's `helper__mojo_global_get_CONST` are all
  fine; only the unannotated RHS is not classified.
- A plain string-literal global (`NAME = 'x'`) already prints `x`, so the "unannotated but
  decidable" path itself is sound; an integer literal is simply not one of the shapes it decides.
- An arithmetic RHS (`N = 40 + 1`) also prints `0` today. That is the same silent-0 gap, but
  deciding it needs constant folding the text scanner does not do, so it is deliberately NOT
  part of this part's acceptance (do not assert it in the test; it stays open).
- The defining module types an unannotated integer-literal global `int` (measured:
  `int CONST;` and `int helper__mojo_global_get_CONST (void) { return _helper_globals.CONST; }`),
  which is exactly what `_ml_py_ann_ctype('int')` answers for the annotated spelling.

Cause: `module_loader._ml_py_global_ctype` (module_loader.py, ~line 270) returns `''` for an
unannotated RHS unless it is a whole-RHS plain string literal or a whole-RHS call to a same-file
`def`. `CONST = 41` matches neither, so no export entry is written and the importer keeps the
"undeclared -> 0" placeholder.

## Acceptance

- `CONST = 41` imported by name prints `41`, and the importer's C names
  `helper__mojo_global_get_CONST` (no `ct param or undeclared: CONST` placeholder).
- A plain string literal global (`NAME = 'x'`) and the annotated `int` / `float` / `str` forms
  keep printing CPython's answer (all three are measured-green today).
- An exported entry's C type is the one the defining module's accessor really returns
  (`int` for an integer literal), so the importer's extern and the accessor agree by
  construction.

## Done when

File: `test_codegen_imported_global_unannotated_scalar.py` (new).

Command:

    python3 tools/memslot.py --gb 8 --label imported-global-unannotated -- python3 test_codegen_imported_global_unannotated_scalar.py

It builds the two-module fixture through `compile_module_to_c`, links it with
`runtime/fire_runtime.c`, runs it and compares stdout with CPython. It is RED on HEAD at the
unannotated case (prints 0) and GREEN after this part; the annotated and string-literal cases
are in the same file so the fix cannot regress them.
