# `tools/formal_metamorph.py`: `t_reorder` reads `_Info.heap_write`, which `_Info.__slots__` does not define — the transform is dead on EVERY pair

**Area:** `tools/formal_metamorph.py`, §8 `t_reorder` / `_Info` / `_info`.
**Status: OPEN, measured 2026-10-17 on `work/bunny-merge26` while merging
`work/formal402-docs`. Not fixed here — the fix belongs with whoever owns the
metamorphic ledger, and the exact restoration is recorded below so it is a
mechanical change rather than a design decision.**

## What I ran, and what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_metamorph.py
...
ERROR: test_every_transform_preserves_the_meaning (__main__.TransformSoundness.test_every_transform_preserves_the_meaning)
  File "test_formal_metamorph.py", line 104, in twin
    out = M.TRANSFORMS[tname](tree, M.Analysis(tree), random.Random(...))
  File "tools/formal_metamorph.py", line 2187, in t_reorder
    if a.heap_write and (b.heap_read or b.heap_write):
       ^^^^^^^^^^^^
AttributeError: '_Info' object has no attribute 'heap_write'
Ran 63 tests in 35.997s
FAILED (errors=4)
```

The same run on a `git archive master` tree gives **the same 4 errors**, so this
is on `master` and predates the merge that surfaced it. `t_reorder` cannot apply
to a single pair: the `AttributeError` is raised before `pairs` is even
considered, and it is not `NotApplicable`, so it escapes `twin()`.

## Which half of which merge

Two commits in this tree fix the same `t_reorder` soundness hole by two
mechanisms, and only half of the second one is here:

| commit | mechanism | on `master`? |
|---|---|---|
| `0146290e` (2026-10-07 17:23) | `_Info.mutates` + `_function_aliases` — an assignment `x = <expr>` puts an edge between `x` and each name in `<expr>`, closed transitively | complete |
| `1721be54` (2026-10-08 21:24) | `_Info.heap_write` / `_Info.heap_read` + `CONTAINER_CONTENTS` — every container base collapses to one unspellable cell, so `A32 = h31.b23` makes `A32[0]` and `h31.b23[0]` ONE element | **half** |

`git merge-base --is-ancestor 1721be54 master` says yes, so the commit IS
reachable. What master has of it is the two `t_reorder` guards (lines 2187 and
2189) and the `CONTAINER_CONTENTS` declaration (line 1829 — **referenced nowhere
else in the file**, which is the tell). What master does NOT have:

- `_Info.__slots__` is `("reads", "writes", "escapes", "terminal", "effectful",
  "mutates")` — no `heap_write`, no `heap_read`;
- `_Info.__init__` sets neither;
- `_info` contains no `out.heap_write = True` / `out.heap_read = True`.

The two mechanisms are complementary rather than competing: `mutates` +
`_function_aliases` closes "one name is the contents of another name's object",
and `heap_*` + `CONTAINER_CONTENTS` closes "two unrelated names reach the same
container cell". Both guards are wanted, and both are already written.

## The exact next step

Restore the missing half of `1721be54` — its own diff is the specification, so
nothing here is a judgement call. In `tools/formal_metamorph.py`:

1. `_Info.__slots__`: add `"heap_write", "heap_read"` after `"mutates"`.
2. `_Info.__init__`: add `self.heap_write = False` and `self.heap_read = False`,
   each with the commit's own one-line reason (a statement that writes/reaches a
   container's CONTENTS rather than binding a local).
3. `_info`: the three assignments `1721be54` adds — `out.heap_write = True` for a
   subscript/attribute STORE, `out.heap_read = True` for a subscript/attribute
   LOAD, and the container-base collapse that uses `CONTAINER_CONTENTS`
   (`git show 1721be54 -- tools/formal_metamorph.py` lines around the `_info`
   hunk).
4. Re-run `python3 test_formal_metamorph.py` before and after and keep it only if
   `reorder` still applies to at least as many corpus programs as before — the
   fix is an over-approximation, so the way it can go wrong is by refusing
   swaps, and that is measurable (`tools/formal_metamorph.py --list-transforms`
   / the file's own census).

Then record the result in `bugs/FORMAL_metamorphic_ledger.md` §5's defect list
(defect 13 is the `_function_aliases` half; this is its sibling) and delete this
doc with the fix.

## Why it survived

Nothing reads `_Info`'s attributes for existence. The transform is called
through `M.TRANSFORMS[tname](...)` and its `AttributeError` is indistinguishable
from any other error the driver raises, and the four tests that hit it are four
rows of one file's 63 — so a whole transform can be dead for days with the rest
of the corpus green. A `__slots__` class is the one place where a renamed or
dropped attribute is checkable without running anything: every read of
`a.<name>` is a read of a name in `__slots__`. If a future change wants that
covered mechanically, a test that walks `t_reorder`'s AST for `Attribute`
subscripts and asserts each against `_Info.__slots__` would have caught this on
the day `1721be54`'s half went missing.