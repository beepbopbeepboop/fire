# GIR stage 4: the single-type equality tests (`== 'MojoDict *'`, ...) have exact predicates and no codemod

Found 2026-11-23 reviewing stage 4 (`doc/GIR.md`). `TypeLattice` already has exact single-spelling
predicates whose call sites were never converted. Each answers exactly `t == '<spelling>'`, and
`test_type_lattice_predicates.py` pins it:

| spelling | predicate | `==`/`!=` tests left (2026-11-23) | predicate's call sites |
|---|---|---|---|
| `'MojoDict *'` | `is_dict` | 105 | 0 |
| `'MojoBytes *'` | `is_bytes` | 90 | 1 |
| `'void'` | `is_void` | 75 | 1 |
| `'MojoSet *'` | `is_set` | 52 | 0 |
| `'void *'` | `is_voidp` | 41 | 3 |
| `'char'` | `is_char` | 37 | 12 |
| `'MojoStr *'` | `is_str` | 12 | 1 |

`tools/type_string_codemod.py`'s `EQ` table only knows `char *`, `MojoList *`, `_Bool`, `double` and
`int64_t`.

## What to do

1. In `tools/type_string_codemod.py`, add these seven rows to `EQ`: `'MojoDict *'` -> `is_dict`,
   `'MojoBytes *'` -> `is_bytes`, `'void'` -> `is_void`, `'MojoSet *'` -> `is_set`, `'void *'` ->
   `is_voidp`, `'char'` -> `is_char`, `'MojoStr *'` -> `is_str`. Check first, in
   `mojo/middle/types.py`, that each predicate is exactly `t == '<spelling>'` (with None giving
   False). If one is not exact, leave that spelling out and say so in your report.
2. Run `python3 tools/type_string_codemod.py --check` and read the list. Then run it without
   `--check`.
3. Do not add anything else to the table. In particular, do not map `'int'` or `'float'`: no exact
   predicate exists for those yet. `bugs/GIR_stage4_rewrites_must_be_exact.md` adds them.
4. Some sites the codemod skips: a left side that is a call, and tests inside a string. Leave them.

## Checks

    python3 -c "import ast; [ast.parse(open(f).read()) for f in <every file the codemod changed>]"
    python3 tools/c_oracle.py check --base <start sha> -j 4      # all programs identical C
    python3 test_type_lattice_predicates.py && python3 test_gimple_lint.py
    python3 test_type_string_ratchet.py   # lower any baseline it says fell

Also run the closure check once: `python3 tools/c_oracle.py check --base <start sha> --closure`
(5-8 min). The rewrite adds calls of `TypeLattice` methods in modules that may never have called
them, and a self-host stub would only show up there.

Delete this doc in the same commit.
