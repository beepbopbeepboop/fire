# GIR stage 4: 15 type-test rewrites widened the test; make each one exact

Found 2026-11-23 reviewing stage 4 (`doc/GIR.md`). Stage 4's rewrites are a REFACTOR: each
`t in (...)` tuple test must become a predicate that answers exactly the same set of spellings.
Commits `6a89c722e` and `cf600c4d5` instead replaced 15 tuples with a predicate that accepts MORE
spellings, and `test_type_lattice_predicates.py` excuses that with its `ALLOWED_EXTRA` table.
Generated C did not change on `tools/pydiff_corpus`, but only because no corpus program passes the
extra spelling. That proves nothing about the compiler's own code or the stdlib.

A real example. `emit_loops.py` (the `for k in d` key target, from `6a89c722e`) was
`if vt in ('int64_t', 'int', 'int32_t'):` and is now `if gimple_ctypes.TypeLattice.is_int(vt):`.
A `uint8_t` target used to take the other branch. It now takes this one and stores an `int64_t`
pointer box into a `uint8_t` variable.

## The 15 lines (the ORIGINAL text; find today's line by its context in the same function)

    6a89c722e  emit_exprs.py   if _ptr_ty in ('int', 'int64_t', '_Bool', 'double', 'float'):
    6a89c722e  emit_exprs.py   if lv in _tagged and lv in _boxed and rt in ('int', 'int64_t', 'double', 'float'):
    6a89c722e  emit_exprs.py   if rv in _tagged and rv in _boxed and lt in ('int', 'int64_t', 'double', 'float'):
    6a89c722e  emit_infra.py   if vt in ('int64_t', 'int', 'int32_t'):
    6a89c722e  emit_loops.py   if vt in ('int64_t', 'int', 'int32_t'):        (two places)
    6a89c722e  emit_loops.py   if vt0 in ('int64_t', 'int', 'int32_t'):
    6a89c722e  infra_infer.py  elif _t in ('int', 'int64_t', '_Bool', 'double', 'float') \
    cf600c4d5  emit_calls.py   and _ctor_rt in ('int64_t', '')
    cf600c4d5  emit_calls.py   if obj_type not in ('int64_t', 'void *', ''):
    cf600c4d5  emit_exprs.py   if _pv_type in ('int64_t', 'int', ''):
    cf600c4d5  emit_methods.py if (struct_name in ('int64_t', 'int', 'long', '')
    cf600c4d5  emit_methods.py if dt not in ('int64_t', 'int', '_Bool', 'double', ''):
    cf600c4d5  module_gen.py   if _cur in (None, 'int64_t', 'int', ''):
    cf600c4d5  module_gen.py   if isinstance(_bm_rt, str) and _bm_rt not in ('', 'int64_t', 'void'):
    cf600c4d5  funcs_shared.py if ctype in ('int64_t', 'int', ''):

Use `git show 6a89c722e` / `git show cf600c4d5` to see each line's before and after.

The three kinds of widening:
- `is_int` accepts every integer width plus `unsigned int`, where the tuple listed two or three.
- `is_float` accepts `__fp16` as well as `double` and `float`.
- `is_unsolved` accepts `'unknown'` as well as `''`. The backend does produce `'unknown'`: about 26
  sites compare against it, for example `module_gen.py`, where `sym_info.get('return_type') ==
  'unknown'`.

## What to do

1. For each line, write the test as an `or` of EXACT single-spelling predicates, so it accepts
   exactly the tuple's members. Example: `('int64_t', 'int', 'int32_t')` becomes
   `TL.is_word(vt) or TL.is_c_int(vt) or TL.is_i32(vt)`, where `TL` is
   `gimple_ctypes.TypeLattice` (write it out in full). Keep `not` around the whole `or` for a
   `not in` test.
2. If an exact single-spelling predicate does not exist yet, add it to `mojo/middle/types.py` beside
   the others, in the same style. Use a plain equality, return False for `None`, and add a
   docstring naming the spelling. Expected new ones: `is_c_int` (`'int'`), `is_i32` (`'int32_t'`),
   `is_c_float` (`'float'`), `is_no_type` (`''` only, not `'unknown'`). Add each one to `ANSWER_KEY`
   in `test_type_lattice_predicates.py`.
3. Delete `ALLOWED_EXTRA` from `test_type_lattice_predicates.py`, together with the code that reads
   it. Every codemod table entry must then emit EXACTLY its tuple. If a table entry in
   `tools/type_string_codemod.py` emits a wider class, change it to emit the exact `or` of
   single-spelling predicates, so that a future run cannot widen again.
4. Do NOT decide here whether a widening was "more correct" C. If you believe one was, say so in
   your report. It becomes its own bug doc with a test that shows the new behaviour.

## Checks

    python3 test_type_lattice_predicates.py            # passed: 0 failure(s), ALLOWED_EXTRA gone
    python3 tools/c_oracle.py check --base <start sha> -j 4   # identical C (the old tuples did too)
    python3 test_type_string_ratchet.py && python3 test_gimple_lint.py
    python3 -c "import ast; ..."                       # over each touched file

Delete this doc in the same commit.
