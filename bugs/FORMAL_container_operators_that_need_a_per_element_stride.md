# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED — item 3 (set algebra) is LANDED on BOTH backends
(arm64 2026-10-06, x86-64 2026-10-13); items 1 (container `==`/`!=`), 2
(ordering) and 4 (a length-changing slice store) are unchanged.** The one
container operator this doc's item 3 has left is `|` (the union) on x86-64, and
it is a DIFFERENT gap from the three: `test_formal_container_methods.py`
measures the whole surface against CPython on both architectures and is green;
this doc is about the rows in it that were green *as refusals*, which is a
different thing from green as answers. The three set operators are answers on
both backends now.

**2026-10-06 (`formal109-docs`): `&`, `^`, `-` between two SETS are lowered on
arm64.** Measured, both architectures, `test_formal_container_methods.py set`:
13 answers equal CPython on arm64 (up from 10 — `s_intersection_r`,
`s_difference_r`, `s_symdiff_r`, `s_sub_r`, `s_andassign_r` moved), x86-64
unchanged at 4 with the same 9 refusals. The five rows were observed through a
SUM and a length rather than a length alone, so a result with the right count
and the wrong element fails. The three emitters are
`formal/arm64_codegen.py::_emit_set_op` and `_emit_set_filter_pass`, with the
union's reservation and growth guard (an intersection or a difference reserves
`nL`; a symmetric difference `nL + nR`); the augmented `-=`/`&=` desugar onto
them through `_maybe_emit_set_binop`, which is asked by BOTH the binary and the
augmented emitter — the augmented one used to reach the shared gate first, and
`s -= {2}` and `s = s - {2}` are the same operator and must not get two answers.

**2026-10-13 (`formal326-docs`): the same three are lowered on x86-64, so item
3 is done on BOTH backends.** `formal/x86_64_codegen.py` grew `_emit_set_op`,
`_emit_set_filter_pass` and `_maybe_emit_set_binop` as the twins of arm64's,
with the same capacity rule (an intersection or a difference reserves `nL`, a
symmetric difference `nL + nR`) and the same shared `_emit_blob_growth_guard`.
The register discipline is `_emit_list_concat`'s rather than a second one: the
left and right operands are the bases, the source is walked with a countdown,
and the result count word is re-stored on every append (the pass returned an
EMPTY set the first time it ran because the count word was written once, as
zero, and never again — that is the one defect the differential caught).
Measured, both architectures, `test_formal_container_methods.py set` and
`operator`: **x86-64 4 answers → 9** in the set group (13 on arm64, the
difference being the four `s_union*` rows, which are still `BACKEND_ONLY` —
`|` is a separate gap and is unchanged), and the `operator` group is now **11
answers on each architecture** instead of 11/6. `o_xor`/`o_and` were the two
`operator` rows carrying the split and they are gone from `BACKEND_ONLY`, as
are `s_intersection_r`, `s_difference_r`, `s_symdiff_r`, `s_sub_r` and
`s_andassign_r`; the table's own rule — "a backend that grows one has to delete
its row" — is what this deletion is.

**The `s_symdiff_r`/`o_xor` cases were strengthened in the same commit, and
they were a real gap**: both were `s = {1, 2}`; `t = s ^ {2}`, whose right
operand holds NOTHING the left does not, so the second half of the symmetric
difference — the elements only the right holds — never appended and a
half-implemented `^` passed. They are `s ^ {2, 3}` now (sum 4, len 2, and `3`
is the right-only element), which is the case that reads both passes. The
difference between the two is the difference between a test that pins the
lowering and one that pins half of it.

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
The five rows therefore carry `BACKEND_ONLY[...] = "x86_64"`, and the `operator`
group's duplicate `o_xor`/`o_and` rows were re-pointed at probes the same way
(`o_sub`, a LIST difference, stays a refusal on both backends). The structural
half is pinned by four new `_BLOB_GROWTH_PROBES` rows, so each new site has to
keep emitting its capacity guard.

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

1. **`&`, `^`, `-` between two sets** (item 3) — **DONE on BOTH backends
   (arm64 2026-10-06, x86-64 2026-10-13).** The rows moved to probes, the
   augmented forms desugar onto the binary lowering, and both backends'
   `_emit_set_op`/`_emit_set_filter_pass` are the per-element scans. What did
   NOT happen is the prescribed removal from `CONTAINER_GATED_OPS`: that table
   is shared, and dropping an operator there would send a backend with no
   emitter into the ALU on two addresses. Each backend intercepts first, the
   way `|` already splits `_emit_set_union`/`set_union_refusal` on arm64. The
   `BACKEND_ONLY` rows are deleted now that the second backend grew its own.
   See the Status at the top for the measurements and the emitters.
   **What is still open on item 3 is `|` (the union) on x86-64, which is a
   different lowerer from the three and is not attempted here.**
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