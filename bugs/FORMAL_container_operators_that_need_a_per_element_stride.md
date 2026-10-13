# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED — item 3 (set algebra) is LANDED on arm64, and item
1's INTEGER-element half (container `==`/`!=`) is LANDED on BOTH backends
(2026-10-13); item 2 (ordering) and item 4 (a length-changing slice store) are
unchanged, and item 1's other element kinds (a set, a dict, a nested or a string
element) still reach the shared gate.** `test_formal_container_methods.py`
measures the whole surface against CPython on both architectures and is green;
this doc is about the rows in it that are green *as refusals*, which is a
different thing from green as answers. Several of those rows are answers now.

**2026-10-13 (`work/formal376-docs`): `==`/`!=` between two INTEGER-element
sequence blobs is lowered on both backends, and the boundary is pinned.** The
decision is one shared predicate, `model.container_equality_is_lowered`, so the
two architectures cannot disagree about which operand pair is lowered. Measured
with `test_formal_container_methods.py operator tuple`: the `o_eq`, `o_ne` and
`t_eq` rows moved from refusals to answers that equal CPython on BOTH
architectures, and four new rows pin the boundary — `o_eq_miss` (equal lengths,
one element different) and `o_eq_short` (a prefix) pin the element and length
halves of the answer, and `o_set_eq_r`, `o_nested_eq_r` and `o_strlist_eq_r`
pin that a set (order-independent), a nested blob (recursive) and a string
element (content compare) are STILL refused by the shared gate rather than
word-compared. The gate was NOT narrowed the way "What to do, in order" item 1
prescribed, and the reason is the one §3 already gives for the set operators:
`CONTAINER_GATED_OPS` is SHARED by both backends and by every element kind, so
dropping `==`/`!=` from it would send a set, a dict and a nested blob into the
address comparison the gate exists to prevent. The lowering therefore sits
BESIDE the gate, the backend intercepts the integer-list/tuple shape first
exactly as it intercepts two sets for `&`/`-`/`^`, and the message stands for
the rest. What is left of item 1 is the recursive/content compares —
`[[1]] == [[1]]` and `["ab"] == ["ab"]` — which are the "value-model question"
the section below describes and are still refusals.**

The whitelist is one element kind and it is deliberate: `WORD_EQUALITY_ELEM_KINDS`
holds `int` alone, because it is the set of kinds whose CPython equality IS the
word equality. `float64` is excluded (CPython says `0.0 == -0.0` while the two
have different words), `str` is a content compare, and a nested kind is a
recursion. An unrecognised element kind falls on the refusing side by default.

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

1. **`&`, `^`, `-` between two sets** (item 3) — **DONE on arm64
   (2026-10-06).** The rows moved to probes and the augmented forms desugar onto
   the binary lowering; x86-64 still refuses all three, so the rows carry
   `BACKEND_ONLY`. What did NOT happen is the prescribed removal from
   `CONTAINER_GATED_OPS`: that table is shared, and dropping an operator there
   would send x86-64 into the ALU on two addresses. The backend intercepts
   first, the way `|` already splits `_emit_set_union` from
   `set_union_refusal`. The remaining x86-64 half is item 3's second half and is
   not started. See the Status at the top for the measurements and the emitters.
2. **`==` / `!=` between two containers** (item 1) — **the INTEGER-element
   half is DONE on both backends (2026-10-13)**; the rest is the recursive
   descent over nested blobs and the content compare over `char *` elements,
   which is what makes the remainder a value-model question and not only an
   emitter one. The lowering that landed is `model.container_equality_is_lowered`
   plus `_emit_blob_eq` in each backend, and it is reached at the comparison
   site and in the CONDITION emitter (`arm64`'s `_emit_branch_unless`), because a
   comparison in a condition is a separate emitter that never went through
   `_emit_binop`. Its "data-dependent loop" is the same shape the set emitters
   already emit and it has the same proof story: a proof generator that cannot
   contract it refuses rather than admits, which is the honest outcome and not a
   wrong answer.
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