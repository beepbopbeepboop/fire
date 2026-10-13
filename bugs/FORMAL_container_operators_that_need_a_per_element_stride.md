# The container operators CPython answers and this path now refuses: element-wise equality, ordering, set algebra, and a length-changing slice store

**Status: PARTIALLY FIXED — items 1 and 3 are LANDED, and item 1 is landed on
BOTH backends for the word-element case; item 2 (ordering) and item 4 (a
length-changing slice store) are unchanged.** `test_formal_container_methods.py`
measures the whole surface against CPython on both architectures and is green;
this doc is about the rows in it that are green *as refusals*, which is a
different thing from green as answers. Eight of those rows are answers now —
five from item 3 (`s_intersection_r`, `s_difference_r`, `s_symdiff_r`,
`s_sub_r`, `s_andassign_r`) and three from item 1 (`o_eq`, `o_ne`, `t_eq_r`) —
with three further item-1 ANSWER rows pinning the edges of that lowering and
five more for the compare CHAIN; §"Item 1 landed" below has the measurement and
names exactly which shapes still refuse.

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

## Item 1 landed (2026-10-13): `==`/`!=` between two blobs of WORDS, both backends

Item 1 was filed as "compare lengths, then compare element by element at the
element's stride", and the stride is the whole of the fear (§"The obstacle"
below): a string element is a `char *`, so a word compare answers by interning
order, and a nested container's element is another blob's ADDRESS, so the
compare is recursive. The landing is therefore scoped to the element kind where
that fear is absent — an INTEGER element, whose value IS the word — and every
other shape keeps the shared `container_operator_refusal`.

**The predicate is shared; the class is flow-sensitive.** `model.blob_equality_
word_comparable` says whether *both* operands are blobs whose element kind is a
word (`BLOB_EQUALITY_WORD_KINDS` is `{int}`). Set-ness and dict-ness cannot live
there — a set lowers as a list, so the KIND cannot tell them apart — so each
backend's `_equality_blob_class` asks its own `_set_vars`/`_dict_vars` and, for a
LIST-versus-TUPLE question the value model has never kept, a new positive
`_list_vars` beside `_tuples_vars`. Both classes must be KNOWN and EQUAL, because
`[1] == (1,)` is False in CPython whatever the elements: answering it off "not a
tuple" would call a call's return value a list and print 1 where CPython prints
0. A known-but-different pair is answered directly (CPython: never equal);
anything unknown refuses.

**Measured, both architectures, `test_formal_container_methods.py`:**
`operator` 20 → 30 answers (10 → 15 per backend), `tuple` 16 → 18 (8 → 9 per
backend), `PASS=6 FAIL=0`. The moved rows are:

| row | was | now |
|---|---|---|
| `o_eq` (`a == [3, 1, 2]`) | refusal (answered 0 before the gate) | `1` |
| `o_ne` | refusal | `0` |
| `t_eq_r` (`(1,2,3) == (1,2,3)`) | refusal | `1` |
| `o_eq_diff_elem` (same length, one element differs) | — (new) | `0` |
| `o_eq_diff_len` (different lengths) | — (new) | `0` |
| `o_eq_mixed` (`[1] == (1,)`) | — (new) | `0` |

The two new element rows exist because a length-only or address-only lowering
would pass `o_eq` by accident; `o_eq_diff_elem` is the row that requires a real
per-element compare, and `o_eq_mixed` is the row that requires the class.

**What still refuses, and each is a new pinned row rather than a hole:** a
`char *` element (`o_eq_str_r`), a nested blob (`o_eq_nested_r`), a set
(`o_eq_set_r`, order-independent) and a dict (`o_eq_dict_r`, pair stride). So
`model.CONTAINER_GATED_OPS` is NOT narrowed — dropping `==` there would send
x86-64 into the integer ALU on two addresses for exactly those shapes — and the
emitters intercept before the shared gate the same way `|` already splits
`_emit_set_union` from `set_union_refusal`.

The arm64 flag path needed one extra hook: `_emit_branch_unless` branches on
`CMP` flags rather than materializing a boolean, so `if a == b:` would have
reached the refusal while `r = a == b` answered. It now falls through to the
truthiness path when `_blob_equality_plan` accepts the pair. x86-64 has one
comparison hook (`_emit_binop`), so it needed nothing extra.

**A THIRD entry point, and it was a pre-existing SILENT WRONG ANSWER: the
compare CHAIN.** `a == b == c` is one `F.CompareChain` and neither backend's
`_emit_compare_chain` ever went through `_emit_binop`, so no gate reached it and
each link was a raw word compare of two blob ADDRESSES. Measured on both
backends before the fix: `a == b == c` for three equal lists answered **0 where
CPython answers 1**, exit 0 — the wrong-answer class this whole document exists
to prevent, reached by a spelling nobody had looked at. The chain emitter now
asks the same `_blob_equality_plan` for each `==`/`!=` link: an accepted pair is
lowered from the bases the chain has ALREADY evaluated (it must not re-evaluate
a call operand — `_emit_blob_word_equality_bases` is the register-level body the
binary spelling wraps) and ANDed into the running result; a blob link the
lowering does not accept raises the shared refusal; a blob against a scalar
falls through, because the address compare below is CPython's own answer there.
Pinned by `o_chain_eq`, `o_chain_eq_false`, `o_chain_mixed`, `o_chain_ne` and
`o_chain_eq_str_r` in `test_formal_container_methods.py`, on both backends.

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
2. **`==` / `!=` between two containers** (item 1) — **DONE FOR WORD ELEMENTS
   on both backends (2026-10-13).** The length check plus the per-element word
   compare is landed, and the three shapes whose element is NOT a word (a
   `char *`, a nested blob, a set's order) each keep the shared refusal, pinned
   by a row. See §"Item 1 landed" for the measurement and the exact shapes.
   **What is left on item 1** is those three: a CONTENT compare for `char *`
   elements, a recursive descent for nested blobs, and set equality as a
   membership relation rather than a positional one. Each is a value-model
   question and not only an emitter one, which is why they were not folded into
   this landing. Item 1's proof obligation (a data-dependent loop where every
   other container loop is count-bounded) is still owed for the part that
   landed.
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