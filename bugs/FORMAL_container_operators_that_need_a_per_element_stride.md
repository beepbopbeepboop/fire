# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED 2026-10-08 — item 3 (set algebra `&`, `^`, `-`) is
lowered on arm64 and x86-64 refuses the three by name; items 1 (`==`/`!=`), 2
(ordering) and 4 (a length-changing slice store) still stand as refusals.**
`test_formal_container_methods.py` measures the whole surface against CPython on
both architectures and is green; this doc is about the rows in it that are
green *as refusals*, which is a different thing from green as answers. §"What
landed 2026-10-08" has the measurement and the ONE place this deviated from
§"What to do, in order".

Branch `work/formal64-container-methods`, claim `project:container-methods`. Every
number below is measured on that branch, on both `arm64` and `x86-64`, and each
has a named row in `test_formal_container_methods.py`.

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

1. **`&`, `^`, `-` between two sets** (item 3). arm64 only, then x86-64; both
   already have `_set_vars` and `container_union_refusal` to gate on, so the
   gate narrows from "refuse" to "lower" without new machinery. Each row in
   `test_formal_container_methods.py`'s `set` group
   (`s_intersection_r`, `s_difference_r`, `s_symdiff_r`, `s_sub_r`,
   `s_andassign_r`) becomes an answer case, and `container_operator_refusal`
   loses that operator from `CONTAINER_GATED_OPS` — the table is the only place
   the operator set is written, which is why widening it was one line.
2. **`==` / `!=` between two containers** (item 1). Both backends. Bigger than
   item 3 because the answer may be a recursive descent over nested blobs and a
   content compare over `char *` elements, so it is a value-model question and
   not only an emitter one. It also has a proof obligation the others do not:
   the loop is data-dependent, where every current container loop is
   count-bounded.
3. **Ordering** (item 2). Both backends. Strictly after item 1, and it reuses
   item 1's compare — a three-way element compare is the same inner loop with a
   different exit.
4. **A length-changing slice store** (item 4). arm64 first (it is the backend
   that has the store), and only then x86-64, which needs a slice to stop being
   a materialized copy before the store can mean anything.

## What landed 2026-10-08: item 3, set algebra, on arm64

**Item 3 is lowered, and it is the only part of this document that is.**
`formal/arm64_codegen.py::_emit_set_algebra` computes `&`, `-` and `^` over two
set blobs with the two nested loops item 3 describes: for each element of one
operand, a membership scan over the other, and an append of the elements the
predicate keeps. It is ONE method parameterised by the predicate (and one helper
for the pass), not three near-identical emitters, because the three differ only
in whether a found element is kept — `&` keeps it, `-` and `^` drop it, and `^`
runs the pass once more over the right operand. The result starts at count 0 and
grows, and the site carries the union's run-time capacity guard (the reservation
is `nL + nR`, the widest any of the three can be), pinned by a new
`_BLOB_GROWTH_PROBES` row (`arm64/setalg`).

**Measured, both architectures.** `test_formal_container_methods.py`'s `set`
group moved five rows and added a sixth from *refusal* to *answer* on arm64:
`s_intersection`, `s_difference`, `s_symdiff` (whose operands `{1,2} ^ {2,3}`
exercise BOTH halves of the symmetric difference), the augmented `s_sub` and
`s_andassign` (which desugar onto the binary emitter), and a new
`s_intersection_str` over string elements. All agree with CPython on the
elements' SUM and the result's length, not on a length alone — the same
observation `s_union_elems` makes. x86-64 refuses all six by name
(`model.set_algebra_refusal`, the sibling of `set_union_refusal`) and the rows
are `BACKEND_ONLY` there, as `s_union` already is.

**The ONE deviation from §"What to do, in order", and why.** Item 3 says to drop
the operator from `model.CONTAINER_GATED_OPS`. That table is consulted for EVERY
blob, so removing `&` from it would also stop refusing `[1] & [2]` — a CPython
`TypeError` with no set answer — and let it reach the integer ALU on a list's
address, which is the exact wrong answer the gate was built to refuse. So the
table is unchanged and the two-SET case is caught at the codegen site instead
(`op in M.SET_ALGEBRA_OPS and _expr_is_set_like(left) and
_expr_is_set_like(right)`), before the shared gate; everything else falls through
to `container_operator_refusal` and keeps its sentence. The two operator-group
rows (`o_and`, `o_xor`) moved from set operands to LIST operands for the same
reason — they exist to hold the gate's coverage of a non-set blob, and the
two-set shape is now the `set` group's answer row.

**`_expr_is_set_like` now knows a set algebra of two sets is a set**, so a
later operator on its result is classified correctly; `&`/`^`/`-` require BOTH
sides to be sets for that, unlike `+`/`|` which keep their existing one-side
rule.

**Still open, and unchanged by this**: items 1 (`==`/`!=` between two
containers), 2 (ordering) and 4 (a length-changing slice store) — and the x86-64
half of item 3, which the ordered list stages "after" arm64.

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