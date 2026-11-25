# CODEGEN: a module global's store type reads shared tables that other modules can change

Found 2026-11-24 while fixing the `sty.BOOL` / `mojo/ir/types.py` `BOOL` gcc errors (the fix is
commit `cbdfe68bf`, `test_global_homonym_struct.py`).

## Symptom (fixed for one case, the general case remains)

A module declares a global `X` with a struct-pointer type of its own. Another module, imported
during this compile, declares a global with the same bare name and a different struct pointer.
Before the fix, the owner's store cast its value to the OTHER module's type, and gcc rejected the
translation unit (`assignment to 'STy *' from incompatible pointer type 'Type *'`).

## Mechanism (measured with a scratch copy and a traced dict)

`gimple_codegen._own_overlay_global_ctype` (rules 1-4) decides a global's C type for both the field
declaration and the stores (`_global_dst_ctype`). Its rule 3 returned the SHARED
`_global_c_decl_types` entry whenever one existed. The shared table is keyed by bare name across
every module in the compile, and it changes while a module is being compiled, because imported
modules are compiled inside the importer's import step. So the same owner reads a different type
at its declaration and at its store.

## What the fix covers, and what it does not

The fix (commit `cbdfe68bf`) returns the owner's own conclusion when both it and the shared entry are
NON-container struct pointers that differ. It does NOT cover:

- containers (`MojoList *` etc.) and scalars, which still defer to the shared entry in rule 3 and rule
  2 respectively;
- a shared entry that is `int64_t` where the owner has a struct pointer (rule 3 still returns the
  shared `int64_t`);
- any other place that reads `_global_c_decl_types` or `_global_var_types` by bare name at a point
  after an import compiled (`stmts_shared.py` ~299 is one).

## Next step

1. Make the owner's conclusion the single source: record it once, at the owner's Phase 1.7 scan,
   and never let a foreign module's entry change it (the owner overlay should win for every kind
   the owner declares itself).
2. Audit the bare-name readers listed above and route them through `_global_dst_ctype` /
   `_own_overlay_global_ctype`.
3. Regression: `test_global_homonym_struct.py` extended with a container global and a scalar
   global of the same bare name in the two modules.

## Progress (2026-11-24)

- DONE: the module-level tuple-unpacking store (`mojo/middle/stmts_shared.py`) now asks
  `_global_dst_ctype`, the one owner-first rule, instead of reading `_global_c_decl_types` /
  `_global_var_types` by bare name. Verified: c_oracle identical vs 4a4dca532 (286 + 35), compile_stdlib
  610/0, and `test_global_homonym_struct.py` extended with a container and a scalar global that share
  bare names with other modules' globals (PASS).
- OPEN (the remaining audit): the other bare-name readers of the shared tables that run after an import
  compiled. Start from `grep -rn "_global_c_decl_types\|_global_var_types" mojo/backend_gimple mojo/middle`
  and route each store-type read through `_global_dst_ctype`; reads that only need the field's
  declared type should use the owner's declaration (`_own_overlay_global_ctype`).
