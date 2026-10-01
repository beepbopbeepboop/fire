# FORMAL_field_set_method_name_and_kwarg_blind_spot: the derived field set invents a slot for a method name and misses every keyword argument — the two must be fixed together

**Status: found, NOT fixed.** Two coupled defects in
`formal/model.py`'s `_self_field_names`, found 2026-09-30 while landing the
`__init__`-assignment type source (which is what first made
`formal/arm64_codegen.py` report `self._untyped_callee` instead of `self.asm`).
Not claimed by any live task. **The important part of this doc is that fixing
either one ALONE makes the compiler wrong**, and the reason is measured below.

## The two defects

**A. A keyword argument is invisible to the field set.**
`_self_field_names` opens with

```python
if isinstance(node, list):
    for x in node:
        _self_field_names(x, out, receivers)
    return
```

`list`, not `(list, tuple)`. `CallExpr.kwargs` is `list[tuple[str, Expr]]`, so
every `f(x, field=self.field)` — every keyword argument on this path — is walked
one string and one expression at a time, and the expression is never examined.
So `self._untyped_callee` in

```python
reason = M.string_binary_refusal(
    op, self._expr_str_kind(e.left), self._expr_str_kind(e.right),
    left=e.left, right=e.right, fn=self._cur_fn,
    untyped_callee=self._untyped_callee)
```

contributes nothing to `ARM64Codegen`'s field set. `iter_nodes`, twenty lines
below, gets it right (`isinstance(node, (list, tuple))`), so the file has two
node-walkers that disagree about what a tuple is — which is the whole reason
`iter_nodes` exists and says so in its own docstring.

Missing a field is documented, in `_self_field_names` and in
`struct_field_names`, as "the one error this whole rule is built to avoid": two
real fields alias into one slot.

**B. A value-position method reference invents a slot.** The same function has a
guard for a method CALL:

```python
if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr) \
        and isinstance(node.func.obj, F.IdentExpr) \
        and node.func.obj.name in receivers:
    ...
    return          # `self.helper()` contributes NOTHING
```

and no guard for the bare `self.helper`. A bound method read as a field name
becomes field `k`, the frame grows a slot for it, nothing ever writes it, and
the read returns zero. Measured, on a six-line program:

```
$ python3 fire.py build --formal --no-prove -o /tmp/u13b u13b.py && /tmp/u13b ; echo $?
1
```

`u13b.py` is `o.size() * 100 + o.size2()` where `Outer.size` returns `self.helper`
and `Outer.helper` returns `1`. The source says `o.size()` is a method object and
`o.size2()` is `1`; the image says `0 * 100 + 1`. **The program builds, runs, and
returns a number the source never wrote** — the outcome this whole backend design
exists to make impossible, and `bugs/FORMAL_wide_receiver_by_reference.md`'s
`struct_frame_slot_candidates` section is the rule that was supposed to prevent
it.

Confirmed pre-existing: the same binary and the same exit status on the tree with
`formal/model.py` at its previous contents.

## Why fixing A alone is worse than fixing neither

This is the part worth reading twice, and it is why nothing here was landed
as a one-word change.

With A fixed, `ARM64Codegen` and `X86_64Codegen` each GAIN `_untyped_callee` as a
field (measured, below). Nothing ever writes it, so it becomes a real slot
holding zero, and the honest refusal these two files give today —
"`self._untyped_callee` … which is a METHOD of ARM64Codegen rather than one of
its fields" — silently becomes a load of zero. A is currently *masking* B's
wrong answer by leaving the name out of the layout, and the masking is
accidental.

So the fix is A **and** B together, and B is the part with a real price.

## The measured exposure of B

Counted by parsing every `.py` and `.mojo` in this repository and under
`../modular/mojo/stdlib/std` — 714 structs — and asking which ones have a METHOD
name in `struct_field_names`:

```
structs parsed: 714   with a method name counted as a field: 32   files: 29
  formal/arm64_codegen.py                ARM64Codegen          ['func_name']
  formal/x86_64_codegen.py               X86_64Codegen         ['func_name']
  formal/model.py                        ParamShape            ['names']
  std/builtin/coroutine.mojo             Coroutine             ['_get_ctx']
  std/builtin/simd.mojo                  SIMD                  ['_refine', '_shuffle_list', ...]
  std/collections/list.mojo              List                  ['_write_self_to']
  std/collections/string/string_slice.mojo StringSlice         ['_strip']
  std/memory/unsafe_pointer.mojo         Pointer               ['_store', 'load', 'store', ...]
  ... 22 more
```

**32 of 714 structs, 29 files.** Most are stdlib files that are already refused
for other reasons, but three are this repository's own and two of them are the
formal backends themselves. A correct B removes a slot from each of those
structs — which is the SOUND direction (a refusal, not a wrong number) and a
coverage regression whose size cannot be measured without a full sweep. **A
worker picking this up must run the full arm64 sweep before and after; the
`pass` count is the number that decides whether it is worth it, exactly as
`bugs/FORMAL_sweep_work_map_2026-09-30.md` §3 argues for every other cause.**

The measured exposure of A, for contrast, is tiny and is also the reason A
cannot be landed alone: fixing A changes the field set of exactly **3 structs in
3 files** —

```
formal/arm64_codegen.py      ARM64Codegen  gains ['_untyped_callee']
formal/x86_64_codegen.py     X86_64Codegen gains ['_untyped_callee']
std/benchmark/bencher.mojo   Bench         gains ['_test']
```

— and two of the three are the wrong-answer case above.

## The exact next step

1. **B first, at the READ site and not in the field set.** The sound and narrow
   place is the depth-1 member-read arm of `_frame_receivers` in
   `formal/build.py`: if `model.structs_declaring_method(cands, name)` is
   non-empty, refuse with `model.member_read_without_a_field`'s METHOD sentence
   even when a slot exists. That converts a silently-wrong zero into an honest
   refusal without touching the layout, so the sweep's slot-index diagnostics and
   every `struct_field_count`-driven width stay exactly where they are.
   *Measure the 32/714 census as a sweep delta at this step, before step 2.*
2. **A** as `(list, tuple)`, matching `iter_nodes`.
3. **Then, and only then**, the field-set derivation itself: a bare
   `<receiver>.<name>` that is a method of this struct should not become a field
   by being READ, while a `self.<name> = …` WRITE still should — that is Python's
   own rule (an instance attribute shadows the class's method) and it is what
   makes step 2 safe rather than merely necessary.
4. A case per step. `u13b.py` above is the wrong-answer case and belongs in
   `test_formal_run.py` as a `refuse:` case pinned to the METHOD sentence, with
   the *return-code-per-read* structure the other wrong-answer cases use — the
   current program's single `1` does not distinguish "read zero" from "computed
   one", and a case that cannot distinguish them is not a test of this.

## What was measured, and what was not

* Both defects: the two programs, on this tree and (for B) on the tree with the
  previous `formal/model.py`.
* Both censuses, by parsing the 714 structs; the census scripts are in the
  filing session's `.tmp/` and are short enough to redo.
* **NOT measured: the sweep delta for step 1 or step 2.** No sweep was run over
  the corpus for this, so "how many files lose a build" is unknown. That is the
  first thing to measure.
