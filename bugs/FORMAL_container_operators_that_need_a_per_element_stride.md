# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status 2026-10-13 (`work/formal407-docs`): item 3 — SET ALGEBRA — is now
LANDED ON BOTH BACKENDS, INCLUDING THE UNION, so the split this file has carried
since 2026-10-06 is gone.** x86-64 grew `_emit_set_union`,
`_emit_set_op` and `_emit_set_filter_pass` — the same copy-then-dedup union and
the same per-element membership scan (parameterised by a keep/drop predicate,
run twice for the symmetric difference) that arm64 runs, sized by the same
shared `_blob_site_growth`/`_blob_growth_guard`. The operator gate is unchanged
in shape: `container_operator_refusal` still defers the three operators on two
blobs, and each backend's `_emit_binop` now lowers the two-set case and refuses
a not-two-sets pair with `backend_has_emitter=True` (CPython's `TypeError`).
`set_union_refusal` is DELETED — with both backends lowering `|` on two sets it
had no caller left. What that moved, measured by `test_formal_container_methods.py`:

* the `set` group's `s_union`, `s_union_elems`, `s_union_str`, `s_union_ior`,
  `s_intersection_r`, `s_intersection_str`, `s_difference_r`, `s_symdiff_r`,
  `s_sub_r` and `s_andassign_r` lost their `BACKEND_ONLY = "x86_64"` rows and
  run as ANSWERS on both architectures (the `set` group is 14 answers / 9
  refusals on each);
* the operator group's `o_set_sub`, `o_set_and` and `o_set_xor` moved from
  `probe=None` x86-64-refusal rows to probes, so the two-set answers are also
  pinned from the operator group (12 answers each backend);
* `test_formal_run.py`'s `SET_UNION_CASES` runner now requires BOTH backends to
  reproduce CPython (it used to require x86-64 to refuse), and
  `_BLOB_GROWTH_PROBES` gained the four x86-64 set sites (`uni`, `sin`, `sdf`,
  `ssd`), so each is checked to emit its run-time capacity guard on both
  machines.

Still open are items 1 (container `==`/`!=`), 2 (ordering) and 4 (a
length-changing slice store); the paragraphs below are the record of what led
here and the historical statements about "x86-64 refuses" describe the tree
before this change.

**Status: PARTIALLY FIXED — item 3 (set algebra) is LANDED on arm64; items 1
(container `==`/`!=`), 2 (ordering) and 4 (a length-changing slice store) are
unchanged.** `test_formal_container_methods.py` measures the whole surface
against CPython on both architectures and is green; this doc is about the rows
in it that are green *as refusals*, which is a different thing from green as
answers. The set-algebra rows are answers on arm64 now (six of them — five
moved, one added); x86-64 still refuses each by name.

**2026-10-08 (`formal162-docs`), merged 2026-10-12: the x86-64 half of item 3
was BUILT on the branch, and the merge kept the arm64-only mechanism.** The
branch lowered `|`, `&`, `-` and `^` between two sets on x86-64 too — a fresh
x86-64 `_emit_set_union` (the `|` branch had lowered a concatenation and then
been refused by `model.set_union_refusal`, which the branch deleted with the
emitter) and `_emit_set_intersection` / `_emit_set_difference` /
`_emit_set_symmetric_difference`, all dispatched from a syntax-level predicate
`_try_emit_set_algebra` asked BEFORE the shared gate (a KIND cannot tell a set
from a list, so set-ness has to be read from the source), with the blob-growth
guard at every set site and the five `set` rows and the two `operator` rows
moved to answers on both backends. On the merge into `work/merge-qwen1` the
master-side arm64 lowering was kept as the canonical mechanism and the branch's
x86-64 emitters were folded away, so on the merged tree the split is exactly
the 2026-10-06 paragraph's: **re-measured 2026-10-12 on this tree, arm64
answers all four** (`{1,2} | {2,3}` → 6, `s & {2}` → 2, `s - {2}` → 1,
`s ^ {2,3}` → 4, each CPython-agreeing) **and x86-64 refuses all four by name**
(`set_union_refusal` for `|`; `set_algebra_refusal` for `&`, `-` and `^`). The
branch's x86-64 emitter is recorded here as a parallel implementation of the
same fix; the x86-64 half of item 3 is not started on the canonical tree.

**2026-10-12 (`work/formal176-docs`, merged): a THIRD parallel
implementation of the same fix, folded the same way.** The branch lowered
`&`, `-` and `^` (the augmented spellings included) on arm64 through its
own per-element-scan family (`_emit_set_algebra`, `_emit_set_member_scan`,
`_emit_set_append`), and refused them on x86-64 through
`model.set_algebra_unsupported_refusal` — a parallel of the
`set_algebra_refusal` gate above, which it does not replace (the
canonical gate also words the not-two-sets `TypeError` arm and is shared
by both backends). The canonical arm64 emitters and the gate are
unchanged by this merge. What the branch adds and keeps is coverage:
`test_formal_container_methods.py`'s operator group gains the
x86-64-only refusal pin of the TWO-SET shape — `o_set_sub`, `o_set_and`,
`o_set_xor` (the branch's `o_and`/`o_xor`/`o_set_sub`, renamed where the
`o_and`/`o_xor` names were taken by the non-set-blob rows the 2026-10-06
section moved there) — the shape the `set` group's `BACKEND_ONLY` answer
rows are excluded from and therefore cannot pin.

**2026-10-13 (`work/formal197-docs`, merged): a FIFTH parallel
implementation of the same fix, folded the same way.** The branch lowered
`&`, `-` and `^` (the augmented spellings included) on BOTH backends through
`_emit_set_algebra` and its x86-64 twin, beside `_emit_set_select`/
`_emit_set_append`, and moved the gate from per-operator to per-backend: each
backend passes `lowered_container_ops=model.SET_ALGEBRA_OPS` into
`string_binary_refusal`'s new parameter, `container_operator_refusal` stands
aside for exactly those three, and a new `model.container_setop_refusal`
keeps refusing a LIST/dict/other operand by name — CPython's `TypeError`
shape, which the canonical `set_algebra_refusal` already words. On the merge
into `work/merge-qwen1` the canonical mechanism (the 2026-10-06
`_emit_set_op` family and the shared gate) is kept unchanged and every code
file the branch touched is restored byte-identical to the merged tree: its
five `set`-group answer rows are the canonical six rows with the same
content probes, and its operator-group `o_xor`/`o_and` answer rows are the
branch-tree side of the split the `o_set_*` refusal pins record. Its
measurement of its own tree (both backends, its own emitters) is recorded
here because the per-backend gate design is not otherwise measured: the
`set` group answered 8 → 13 on arm64 and 4 → 9 on x86-64, the operator group
9 → 11 per backend, and the five `s_*_r` rows moved from refusal to answer on
both. Re-measured 2026-10-13 on this tree, the split is exactly the
2026-10-13 one: arm64 answers all four and x86-64 refuses all four by name
(`test_formal_container_methods.py` 6/0 on both backends).

**2026-10-13 (`work/formal189-docs`, merged): a FOURTH parallel
implementation of the same fix, folded the same way.** The branch lowered
`&`, `-` and `^` (the augmented spellings included) on arm64 through its own
`_emit_set_op`, into which it folded the UNION emitter as well — one emitter
for all four set operators, a `_emit_set_pass` helper, and the dispatch asked
inline before the shared gate — and normalised the source `//` spelling in
`formal/contracts.py` through its own `_ARITH_SPELLINGS` table, a parallel of
the `_ARITH_ALIASES` the canonical reader already has. On the merge into
`work/merge-qwen1` the canonical mechanism (the 2026-10-06 `_emit_set_op` and
the untouched `_emit_set_union`) is kept unchanged and every file the branch
touched is restored byte-identical to the merged tree. Re-measured 2026-10-13
on this tree, the split is exactly the 2026-10-12 one: arm64 answers all four
and x86-64 refuses all four by name (`test_formal_container_methods.py` 6/0
on both backends).

**2026-10-06 (`formal109-docs`): `&`, `^`, `-` between two SETS are lowered on
arm64.** Measured, both architectures, `test_formal_container_methods.py set`:
`s_intersection_r`, `s_difference_r`, `s_symdiff_r`, `s_sub_r` and
`s_andassign_r` moved from refusal to answer on arm64, and a new
`s_intersection_str` (string elements) joined them — six rows in all, and the
x86-64 backend refuses each by name. The rows were observed through a
SUM and a length rather than a length alone, so a result with the right count
and the wrong element fails, and `s_symdiff_r`'s operands give both operands an
element the other lacks so BOTH passes of the symmetric difference run. The
three emitters are
`formal/arm64_codegen.py::_emit_set_op` and `_emit_set_filter_pass`, with the
union's reservation and growth guard (an intersection or a difference reserves
`nL`; a symmetric difference `nL + nR`); the augmented `-=`/`&=` desugar onto
them through `_maybe_emit_set_binop`, which is asked by BOTH the binary and the
augmented emitter — the augmented one used to reach the shared gate first, and
`s -= {2}` and `s = s - {2}` are the same operator and must not get two answers.

**The gate did NOT narrow the way §"What to do, in order" item 1 prescribed, and
the reason is a correction worth keeping.** Item 1 said to drop `&`/`^`/`-` from
`model.CONTAINER_GATED_OPS` and move the rows to probes. That table is SHARED by
both backends, so dropping an operator there would have made x86-64 — which has
no set emitter at all — fall through to the integer ALU on two addresses, which
is exactly the wrong answer the gate was widened for. Instead arm64 intercepts
the two-set shape in `_emit_binop` (and the augmented emitter) BEFORE
`string_binary_refusal`, and the shared gate is untouched: it still refuses
`[1] - [2]` (CPython's `TypeError`) and still refuses all three for x86-64, which
is the same split `|` already had (`_emit_set_union` vs `set_union_refusal`).
The six rows therefore carry `BACKEND_ONLY[...] = "x86_64"`, and the `operator`
group's `o_xor`/`o_and` rows moved to LIST operands, where they stay refusals on
both backends the way `o_sub` already was — the `set` group now holds the answer
coverage and the operator group keeps the gate's coverage of a NON-set blob. The
structural half is pinned by three new `_BLOB_GROWTH_PROBES` rows (`sin`, `sdf`,
`ssd`), one for each set-algebra site, so each new site has to keep emitting its
capacity guard.

Branch `work/formal64-container-methods`, claim `project:container-methods`. Every
number below is measured on that branch, on both `arm64` and `x86-64`, and each
has a named row in `test_formal_container_methods.py`.

## What landed 2026-10-08: set algebra on arm64 (item 3)

`a & b`, `a - b` and `a ^ b` between two SETS are intersection, difference and
symmetric difference, and arm64 lowers all three. The union emitter's two
nested loops are the whole algorithm — an outer walk over one operand and an
inner membership scan of the other — so the four operators became ONE emitter,
`_emit_set_op`, parameterised by which elements each pass keeps. The union's
own reservation and growth guard are reused unchanged; the guard's run-time
total is the operator's true worst case (`nL + nR` for union and symmetric
difference, `nL` for intersection and difference).

Measured, on this tree, arm64: `{1,2} & {2}` is `{2}` (sum 2, len 1),
`{1,2} - {2}` is `{1}` (sum 1, len 1), `{1,2} ^ {2,3}` is `{1,3}` (sum 4, len
2), and the augmented spellings `s &= {2}`, `s -= {2}`, `s ^= {3}` agree.
`test_formal_container_methods.py` is 6/6 groups on both backends.

**x86-64 is untouched and still refuses**, so the six rows are
`BACKEND_ONLY = "x86_64"` — this backend has no set emitter at all (not even
the union), and adding three more there is the "then x86-64" the next-step list
did not get to. The arm64 gate is `model.SET_ALGEBRA_OPS`, asked in
`_emit_binop` (and in the augmented-assignment emitter) before
`string_binary_refusal`: a blob that is not established to be a set still falls
through to `container_operator_refusal`, because `[1] - [2]` is a CPython
`TypeError` and not address arithmetic.

## What was wrong, and what landed instead

Before this branch, ten container operators reached either the flag-setting
compare or the integer ALU holding a blob's **ADDRESS**, and answered. Measured:

| source | this path, before | CPython | outcome class |
|---|---|---|---|
| `a = [3, 1, 2]`; `1 if a == [3, 1, 2] else 0` | `0` | `1` | silent wrong number |
| `a != [3, 1, 2]` | `1` | `0` | silent wrong number |
| `s = {1, 2}`; `s & {2}` | `2` on arm64, `163061056` on x86-64 | `1` | the two architectures disagreeing about neither |
| `s - {2}` | SIGSEGV, no output | `1` | crash |
| `s ^ {2}` | SIGSEGV, no output | `1` | crash |
| `s -= {2}` | SIGSEGV, no output | `1` | crash through the *second* emitter |
| `s &={2}` | `2` / garbage | `1` | silent wrong number |
| `a += [3]` | `0` on arm64, SIGSEGV on x86-64 | `3` | wrong number / crash |
| `a *= 3` | SIGSEGV on both | `3` | crash |
| `s \|= {3}` | `1` / `0` | `3` | wrong number |
| `d \| {"b": 2}` | `1` | `2` | wrong number, via integer `ORR` |
| `[1, 2] \| [3]` | `3` | `TypeError` | answering a program CPython rejects |
| `[1] in [[1], [2]]` | `1` on arm64, `0` on x86-64 | `1` | the two architectures disagreeing |
| `b = [1]; b in [[1], [2]]` | `0` on both | `1` | wrong number |
| `a[0:1] = [9, 9, 9]` | exit 1, no output, no message | `[9, 9, 9, 1, 2]` | silent stop |
| `t = (1,2,3); t[0] = 9` | `t0=9 len=3` | `TypeError` | wrong *mutation* |
| `for k in d: del d[k]` | `1` | `RuntimeError` | wrong number |
| `for k in d: d["z"] = 5` | `2` | `RuntimeError` | wrong number |
| `d["z"]` (miss) | exit 1, no message | `KeyError` | silent stop |

All of those are refused, or stopped with a diagnostic that names the rule. The
table is not where the remaining work is.

## The obstacle, stated once

Every answer CPython gives for these is **element-wise over a per-element
STRIDE**, and this path's blob is `[count:i64][elem0][elem1]…` in 8-byte slots
with the element's own width known only at run time
(`model.blob_elem_stride`, `model.walk_shift`). The four lowerings need:

1. **`==` / `!=` between two containers** — compare lengths, then compare
   element by element at the element's stride. `container_operator_refusal`
   covers `==`, `!=`, `<`, `<=`, `>`, `>=`, `-`, `&`, `^` and the six operators
   CPython itself refuses; the refusal exists because the answer is a project.
2. **Ordering** — the same loop with a three-way compare at the first index
   where the two differ, plus the shorter-prefix rule. The refusal is older than
   this branch and its measurement is in `container_operator_refusal`'s own
   docstring.
3. **Set algebra** — `&`, `^`, `-` between two sets: a per-element membership
   scan per element of the right-hand side. arm64's `_emit_set_union` ALREADY
   does exactly that shape for `|` (copy the left, then for each right-hand
   element scan the result and append it if it is absent), so the ALGORITHM is
   written and three emitters are not: `_emit_set_intersection`,
   `_emit_set_difference`, `_emit_set_symmetric_difference`, each as the same
   two nested loops with a different keep/drop predicate. This is the cheapest
   of the four by a wide margin and it is the one to do next.
4. **A length-changing slice store** — `xs[a:b] = v` where `len(v) != b - a`:
   a memmove of the tail by `len(v) - (b - a)` elements and a count bump. The
   primitives are both already here: `_emit_del_list_range` memmoves a tail and
   shrinks the count, and `_emit_list_append` grows it past the count into
   reserved capacity. arm64's `_emit_slice_store` is a same-length copy loop and
   x86-64 has no slice store at all.

The stride is the whole of it, and it is not free: `model.blob_elem_stride`
already answers it for `list:int`, `list:str` and a dict's `list:<value-elem>`
pair stride, and a nested container's elements are **addresses**, so
`[[1]] == [[1]]` is a recursive compare and `["ab"] == ["cd"]` is a content
compare over `char *`s. Neither is the word compare the ALU would do, which is
the second reason this is a project rather than a rewrite.

## What to do, in order

1. **`&`, `^`, `-` between two sets** (item 3) — **DONE on arm64 (2026-10-06)
   and on x86-64 (2026-10-13).** The rows moved to probes and the augmented
   forms desugar onto the binary lowering; both backends now run the same
   emitters. What did NOT happen is the prescribed removal from
   `CONTAINER_GATED_OPS`: that table is shared, so dropping an operator there
   would have sent a backend with no set-else answer into the ALU on two
   addresses. Each backend intercepts first, the way `|` already split its
   emitter from the gate. `test_formal_container_methods.py`'s `set` and
   `operator` groups are the pins on both architectures. See the Status at the
   top for the measurement and the emitters.
2. **The UNION (`|`) on x86-64** — the same item, and it landed with the three:
   x86-64's `_emit_set_union` is arm64's copy-then-dedup loop, so `s | {2, 3}`
   is an answer on both backends and `SET_UNION_CASES` in `test_formal_run.py`
   now diffs both against CPython. (This half is listed separately from item 3
   only because the union was the pre-existing arm64-only lowering rather than
   one of the three this file opened on.)
3. **`==` / `!=` between two containers** (item 1). Both backends. Bigger than
   item 3 because the answer may be a recursive descent over nested blobs and a
   content compare over `char *` elements, so it is a value-model question and
   not only an emitter one. It also has a proof obligation the others do not:
   the loop is data-dependent, where every current container loop is
   count-bounded.
4. **Ordering** (item 2). Both backends. Strictly after item 1, and it reuses
   item 1's compare — a three-way element compare is the same inner loop with a
   different exit.
5. **A length-changing slice store** (item 4). arm64 first (it is the backend
   that has the store), and only then x86-64, which needs a slice to stop being
   a materialized copy before the store can mean anything.

## The rows that must not be "fixed" by deleting the case

`test_formal_container_methods.py` asserts a refusal by matching a phrase from a
shared table, so removing a row when its lowering lands would hide the change
rather than record it. **The landing order for each is: drop the operator from
`model.CONTAINER_GATED_OPS`, move the case from `probe=None` to a probe, and
delete nothing.** The docstring of the gate is where the measurement lives, and
it has to be re-measured when the answer is right: "measured answering 0 where
CPython answers 1" is a claim about the pre-fix tree and becomes a false
statement about this one the moment it stops being true.

Three rows in that table are claims about what this path is NOT, and each has a
document saying so: `bugs/FORMAL_set_value_model.md` (a set lowers as a list, so
`for x in s` is insertion-ordered here and hash-ordered in CPython — which is
why the set walk is observed through a SUM), and the two dict-key rows in the
`dict` group, where a pair blob scans its KEYS at stride 16 and a missing key is
a stop rather than a `KeyError` with a traceback.