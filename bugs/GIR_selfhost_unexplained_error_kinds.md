# GIR selfhost: the error kinds outside the extern-return-type family

Part of the whole-closure self-host failure (`python3 test_selfhost.py`). See `doc/GIR.md`,
section "Selfhost closure: remaining errors". The extern-return-type family is
the import-cycle back-edge fix (commits `6826e2aed` ... `2d1a9131c` and the precision work; see `bugs/GIR_type_solver_precision.md`); this doc is everything else.

## Measurement (2026-11-24, master `91140cc58`). This replaces the old table.

The old table (16 rows of `'Scope'/'MojoFunction'/'Interpreter' has no member ...`,
`non-trivial conversion in 'component_ref'`, ...) was counted at `8f244354d`. None of
those rows reproduce on master. Method, so the next round can repeat it exactly:

```
git archive HEAD | tar -x -C <scratch>/master      # clean copy, no untracked files
cd <scratch>/master
python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_ci.py selfhost.ci   # 12.6 GB peak, ~5 min
gcc-mp-15 -O0 -g0 -fgimple -I runtime $(python3-config --cflags) -c -o /dev/null -x c selfhost.ci 2> gcc.log
grep -E "^[^ ]+:[0-9]+:[0-9]+: error:" gcc.log | sed -E 's/.*error: //' | sort | uniq -c
```

`tools/selfhost_ci.py` makes the same `compile_to_gimple_with_cpp` /
`compile_to_gimple_cached` call `fire.build_executable` makes (`fire.py`,
`do_imports=True`) and writes the C. Count only lines matching
`file:line:col: error:`. A bare `grep error:` also counts gcc's source echoes of
string literals that contain "error", which is how earlier counts got inflated.

Result: **40 errors**.

| count | message | owner |
|---|---|---|
| 22 | `assignment to 'int64_t' from 'MojoList *' makes integer from pointer` | extern-return-types (the WIP's regression) |
| 11 | same, `from 'char *'` | extern-return-types |
| 2 | same, `from 'MojoDict *'` | extern-return-types |
| 2 | `cannot convert to a pointer type` (`infra_infer.py:3828-3829`) | extern-return-types (named in that doc) |
| 3 | `invalid operands to binary + (have 'MojoList *' and 'double')` | **this doc** |

So this doc now covers one defect: 3 errors, at `mojo/middle/coro.py:7714` and
`mojo/backend_gimple/elab_intu.py:4166, 4169`.

## The defect (diagnosed; do not re-investigate)

All three sites are `<list> + <slot of an unannotated tuple-returning function>`:

```
out, nested_bodies, local_maps = _hoist_nested_async(out, meta)   # coro.py:7713
out = out + nested_bodies                                         # 7714
concrete, _fnested = _eval_pointer_fields(work, mm, base, concrete)   # elab_intu.py
_nested = (_nested or []) + _fnested
```

The callee returns `(stmts, hoisted, local_maps)` or `(''.join(out), keys or None)`.
The slot's kind is not inferred, so the unpacked local is a may-box `int64_t` word.
The generated C:

```
_t1947 = mojo_unbox_plain (_t1946);   nested_bodies = _t1947;
_t1951 = mojo_box_double (nested_bodies);
_t1952 = out + _t1951;                 /* MojoList * + double: gcc error */
```

The `+` lowering in `mojo/backend_gimple/emit_exprs.py`, function
`_lower_binary_tail` (from about line 4973), has two faults:

1. **The may-box promotion ignores a container on the other side.** The `rv` block
   (about line 5216) has an exception for a `char *` left operand (keep the word,
   `_word_mark_dyn`) and none for a `MojoList *` one. So it falls into
   `mojo_box_double`. Python's `list + x` is only defined when `x` is a list, so a
   word beside a list operand of `+` is a list and must never become a double.
   The same holds for the mirror `lv` block (about line 5197) with a list on the right.
2. **`MojoList * + int64_t → identity` is a silent miscompile** (the arm with the
   comment "DynamicVector not supported; treat as no-op", about line 5279). If fault
   1 were fixed alone, these three sites would reach this arm and drop the right
   operand without any diagnostic. The mirror arm below it
   (`<opaque int64_t> + MojoList *` → concat) already has the right rule.

## Fix plan (one commit)

In `emit_exprs._lower_binary_tail`:

1. Extend both may-box exceptions. `if gen._word_may_be_box(rv) and op == '+' and
   (is_cstr(lt) or is_list(lt)):` → `gen._word_mark_dyn(rv)`, keeping the word. Do
   the same for `lv` with `rt`. Use `gimple_ctypes.TypeLattice.is_list` and
   `is_cstr`; per `doc/GIR.md` rule 1, add no new type comparisons.
2. Replace the identity arm with concatenation, the exact mirror of the
   `<opaque int64_t> + MojoList *` arm:
   `rcast = gen._coerce_to_type(rt, 'MojoList *', rv)`, then
   `mojo_list_concat(lv, rcast)`, carrying `_elem_types` from `lv`. Write the
   comment as the mirror's is written: adding an integer to a list is never
   meaningful, so a list operand makes it a concat.
3. Search the corpus for anything that depended on the identity arm:
   `python3 tools/c_oracle.py check --base <parent>`. Each changed program must be one
   where the old output dropped an operand. Check it with `python3 <prog>` (CPython)
   and list it in the commit message.

The root cause, an unannotated function's tuple-slot kind going unknown, is the
solver's job (`bugs/GIR_type_solver.md`: `tuple_of(slots)` and
`join(x, NONE)` answer `list` for `hoisted` and `keys or None`). This doc's fix is
still needed after the solver exists, because a genuinely dynamic word beside a list
operand of `+` must lower correctly too.

## Tests

- New case in `test_gimple.py` (find the existing binary-op/list-concat cases and
  add it beside them). It must be red before the fix and green after. Show both in
  the commit message.

  ```
  def split(xs):
      kept = []
      for x in xs:
          if x > 1:
              kept.append(x)
      return (xs, kept or None, {})
  def main():
      out, more, m = split([1, 2, 3])
      out = out + more
      print(out)
  main()
  ```

  Expected output (CPython): `[1, 2, 3, 2, 3]`. If this shape does not produce a
  may-box slot on the current tree, reduce from `coro.py:7713` until it does. A test
  that is green before the fix proves nothing.
- `python3 compile_stdlib.py`: U not increased, no new `skip` lines.
- The measurement above, re-run: the 3 `MojoList * and double` lines are gone, and
  there are no new kinds.

When the fix lands, delete this doc in the same commit, update `doc/GIR.md`'s
"Selfhost closure" section, and run `python3 tools/dangling_doc_refs.py --ratchet`.

## Status

- 2026-11-24: counted from the `8f244354d` baseline. Not diagnosed.
- 2026-11-24 (later): re-measured on master. The has-no-member and
  `component_ref` rows are gone. The 3 remaining errors were diagnosed to the `+`
  lowering, and the plan above was written. Next: the fix commit.

## Reproduction from an external checkout (2026-11-24)

A separate checkout built `fire.py --dump-full` and then `gcc-mp-15 -Os -g -fgimple
-ftrivial-auto-var-init=zero` over `fire.ci` (after `sed` renames `int main` to `int mojo_main`).
It reports exactly the three errors in this doc, in `mojo/middle/coro.py:7714` (`out = out + nested_bodies`)
and `mojo/backend_gimple/elab_intu.py:4166` and `:4169` (`_nested = (_nested or []) + ...`), each
`invalid operands to binary + (have 'MojoList *' and 'double')`. The closure compiled with
`tools/selfhost_ci.py` at `183dc10c4` shows the same three and nothing else in that family, so the
closure TU is the oracle for them. The same check also reports the `mojoc` and `selfhost` gate
failures under `make gate` (`WordFacts` unknown type, in a separate build path), which this family
does not explain.
- 2026-11-25: red check for the fix. Two reductions were built on the unchanged tree with
  `fire.py build`, and neither produced the gcc error: (a) the `split`/`kept or None` shape from
  the test above prints `[1, 2, 3, 2, 3]`; (b) a `hoist()` returning `(kept, hoisted, {})` with
  `hoisted` built by `append` prints `[1, 2, 3] 0`, matching CPython. So neither shape gets a
  may-box slot on this tree, and the test above is not a valid red test. Next: reduce from the
  real call (`coro.py:7713`) by dumping its generated C (`fire.py build` on `mojo/middle/coro.py`'s
  `lower` path) and checking which unpacked slot is `int64_t` there, instead of guessing shapes.
  No code has changed for this bug yet.
