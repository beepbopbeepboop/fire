# GIR stage 4: the type-string ratchet counts 7 patterns; about 930 type-string tests remain

Found 2026-11-23 reviewing stage 4 (`doc/GIR.md`). `test_type_string_ratchet.py` counts seven
hand-picked patterns (`== 'int64_t'`, `== 'char *'`, `== '_Bool'`, `== 'double'`,
`== 'MojoList *'`, `endswith(' *')`, and tuples that contain `'int64_t'`). Those are nearly at zero,
so the doc reads as though stage 4's string tests are done. They are not. A count of every
comparison against ANY C type spelling, outside comments, measured on master today:

- `==` / `!=` against a C type string: **619**. Top spellings: `'MojoDict *'` 105, `'MojoBytes *'` 90,
  `'void'` 75, `'MojoSet *'` 52, `'int'` 49, `'void *'` 41, `'char'` 37, `'MojoGenerator *'` 33.
- `in (...)` tuples that name a C type: **270**.
- `.endswith(' *')` / `.endswith('*')`: **38**.

There is a second hole. The ratchet skips the whole of `mojo/middle/types.py` (that skip was added
2026-11-21 so that the predicate DEFINITIONS would not count). The skip also hides that file's own
~86 string tests (for example `join`'s `src in ('int', 'int64_t', '_Bool')`) and four live
`gen._emit(` calls (`types.py` ~2148-2188), which is why the doc's "`gen._emit(` is 0" is not true.

## What to do

1. In `test_type_string_ratchet.py`, replace the seven type patterns with three general ones, built
   from one regex for a C type spelling:

       TY = r"(?:int|int(?:8|16|32|64)_t|uint(?:8|16|32|64)_t|_Bool|bool|char|double|float|long|void|unsigned int|__fp16|size_t|[A-Za-z_][A-Za-z0-9_]* \*)"
       "== type string":   r"[=!]= *'" + TY + "'"
       "in (type tuple)":  r"\bin \([^()]*'" + TY + r"'[^()]*\)"
       "endswith('*')":    r"\.endswith\(\s*' ?\*'\s*\)"

   Count only code lines: skip lines whose first non-blank character is `#`.
2. Stop skipping all of `mojo/middle/types.py`. Skip ONLY the body of `class TypeLattice` (find it
   with `ast`, and skip the line range of its `is_*` methods), because the predicates are the one
   place the spellings are allowed. Every other line of `types.py` is counted, `gen._emit(` included.
3. Keep `gen._emit( text`, `build.raw( text` and `direct word-set use` as they are.
4. Add `--per-file` output for the new patterns, if the current `--per-file` does not already cover
   them.
5. Set `BASELINE` to the numbers the new patterns measure. Expect about 619 / 270 / 38 plus
   `types.py`'s own. Put the date and those numbers in the comment above `BASELINE`.
6. In `doc/GIR.md` stage 4, replace the "*Measured 2026-11-22 after the W1 tail*" sentence about
   the remainder with the new census. Say plainly that stage 4's string tests are about 930, not
   about 30.

Do NOT convert any test in this change. It only makes the count honest.

## Checks

    python3 test_type_string_ratchet.py          # passes at the new baselines
    python3 test_type_string_ratchet.py --counts
    python3 test_gimple_lint.py

Delete this doc in the same commit.
