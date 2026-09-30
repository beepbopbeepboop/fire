# FORMAL_x86_64_tuple_assignment_member_target: arm64 lowers `self.a, self.b = v1, v2` and x86-64 refuses it

**Status: found, NOT fixed.** Filed 2026-09-30 from the arm64 sweep's row 10
(`bugs/FORMAL_sweep_work_map_2026-09-30.md`), on current master plus
`formal/`'s `__init__`-assignment change. Not claimed by any live task. The next
step is a whole-function property test; the fix itself is small.

## The divergence

`self.a, self.b = 1, 2` — a tuple assignment whose TARGETS are `MemberExpr` — is
lowerable on arm64 and refused on x86-64, from the same source, in the same
build:

```
$ python3 fire.py build --formal --no-prove --backend=arm64   -o /tmp/x t.py
Built: /tmp/x  [arm64/macho]
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/y t.py
build: tuple assignment targets must be plain names on the formal x86-64 path
       (got MemberExpr)
```

The refusing site is `formal/x86_64_codegen.py`'s `_emit_tuple_assign`, which
walks `stmt.target.elements` and accepts `F.IdentExpr` (and a nested
`ListExpr`/`TupleExpr` of names) and refuses everything else. arm64 has no such
check — its `_emit_tuple_assign` emits one store per target, and the store
machinery it reaches already handles a `MemberExpr` through the frame-slot
tables, because that is what `self.x = v` already needs.

**This matters more than a plain divergence, because of the spelling.** A
tuple assignment to `self.<field>` is not an exotic construct: it is the house
style for a class that initialises several fields at once, and
`tools/procrun.py`'s `Tail` is written that way:

```python
class Tail:
    __slots__ = ('limit', '_chunks', '_size')

    def __init__(self, limit=4 << 20):
        self.limit, self._chunks, self._size = limit, [], 0
```

so `test_formal_run.py`'s `init_assigned_*` cases are written with separate
assignments *only* so that they would mean the same thing on both
architectures. A reader of that suite should know the cases dodged a known
divergence, and the comment on `init_assigned_scalar_fields_stay_plain` says so
and names this doc.

## What it costs today, measured

* One arm64 refusal on a class that is otherwise fine is the ONLY thing that
  keeps `formal/model.py`'s `__init__`-assignment source from being exercised on
  the tuple form at all. The evidence source
  (`model._init_field_assignments`) reads all three targets and types the third
  one correctly; the x86-64 backend never gets that far.
* The same construct inside `__init__` ALSO blocks the declared-`__init__`
  inline, with a different and separately-reported message:

  ```
  build: constructing Tail with arguments is a call to a user-defined `__init__`
  whose body this path does not inline: a local assignment (`TupleExpr = …`)
  ```

  So there are two refusals on the tuple spelling, in two different passes, and
  fixing only the emitter's guard leaves the second one. See
  `bugs/FORMAL_struct_construction_shapes.md` §"`__init__`", which owns the
  inline and already names four separate refusals it cannot supply.

## The exact next step

1. Replace `_emit_tuple_assign`'s target-shape guard with the ordinary field
   STORE, one per target, in the arm64 order. The store machinery a
   `MemberExpr` target needs already exists and is already reached by
   `self.x = v`; the guard is the only thing refusing it.
2. Do NOT widen it to a nested `a[i], b[j] = …` — a subscript target has no slot
   index and needs `bugs/FORMAL_read_before_store_dominating_store.md`'s store
   path, which is a separate question.
3. Then write the case that keeps the two architectures from drifting again: a
   `refuse:`-style divergence test is the wrong shape (both must BUILD), so it
   belongs in `test_formal_run.py` as a *positive* case run on BOTH backends.
   `run_case` builds arm64 only for a positive case today, so the runner needs
   one flag — or a second case list that builds and runs both. That gap is worth
   closing on its own: there is currently no test in the suite that would notice
   this class of divergence in a positive case.

## What was measured, and what was not

* The two builds, both directions, on the sources in `.tmp/shapes/` of the
  session that filed this: `t9.py`/`t10.py` (the `Tail` spelling) and
  `tup.py` (plain-name targets, which BOTH backends lower).
* `python3 tools/formal_sweep.py` on the row-10 files: 0 of 10 reach `pass`
  either way, so this is not on the critical path of any measured sweep number.
* **NOT measured: how much of the stdlib this unlocks.** The divergence needs
  the x86-64 backend, and the sweep the map was built from is arm64-only, so
  there is no number for it in this repository's tooling at all. A worker
  picking this up should run the x86-64 sweep before assuming the count is
  large.
