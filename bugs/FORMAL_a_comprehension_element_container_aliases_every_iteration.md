# FORMAL: a comprehension whose ELEMENT is a container aliases every iteration's element to the LAST one

**Status: FIXED for every shape a word copy can make right (2026-10-05,
`work/formal40-1-r2`), and the one shape it cannot is now a REFUSAL instead of
a wrong number.** §0 is what landed and §0a is the residue. Both backends, and
the refusal is one shared sentence rather than two.

## 0. What landed: the element gets a per-iteration COPY, indexed by the count
## the append already writes at

**The defect was a per-SITE reservation read as if it were per-ITERATION.** The
element expression is emitted once, at the element's own place in the source, so
a container it BUILDS is materialised into the same frame words on every
iteration of the generator; `_compr_append_elem` then copies the ADDRESS, which
is the same address every time. Every element of the result is one container
holding the LAST iteration's contents — measured before the change on both
architectures, exit 0 and nothing on stderr: `[[y] for y in ys]` answered 90
where CPython answers 60, `[(y, y+1) …]` and `[[x+y for x in [1,2]] …]` 93 where
CPython answers 63.

**So the fix is not "is the element a container" but "did the element reserve
anything HERE", and the frame ledger already answers that**: `_list_cursor` moves
only when something was reserved, and a name, an arithmetic expression and the
generator's own target all reserve nothing. `formal/arm64_codegen.py::
_emit_compr_element` and its x86-64 twin return `(copies_base, span)` — `cap`
slots of the element's reserved span — and `_emit_compr_element_copy` fills slot
`count` with a word copy of it.

That rule, rather than a container predicate, is what makes the three things
this document separated come out right without a rule for each:

| element | before | after | why the one rule answers it |
|---|---|---|---|
| `[[y] for y in ys]` | 90 | **60** | the display reserved 16 bytes here |
| `[(y, y + 1) for y in ys]` | 93 | **63** | the tuple display did; a fix scoped to `F.ListExpr` would have left it |
| `[[x + y for x in [1, 2]] for y in ys]` | 93 | **63** | the inner comprehension reserved its result AND its iterable |
| `[ys[0:1] + [y] for y in ys]` | 90 | **60** | the concat's operands are displays, so it reserved all three blobs |
| `[mk(y) for y in ys]` | 90 | **60** | **a returned blob does not move the ledger** — `container_returned_blob_sites` parks it above the blob region up front, so `span` is the cursor delta PLUS that block's bytes, and a rule that only watched the cursor would have fixed the four rows above and left this one wrong |
| `[one for _ in range(3)]` | `same=1` | **`same=1`** | a NAME reserves nothing and CPython aliases it too, so copying would be the bug in the other direction |

**The copy is emitted INSIDE `_compr_append_elem`, not beside it.** The capacity
guard that append already runs answers an out-of-range iteration with `exit(1)`,
so an index of `cap` — one slot past the reservation — is already impossible by
the time the copy runs; a second guard would be a second answer to a question
the append asks, and the two could disagree. `_emit_compr_element_copy` takes
the frame SLOT the element was parked in (`[sp+0]`, or `[sp+8]` for a dict
comprehension's value) and writes the copy's address back to that same slot, so
neither append learned that copies exist.

**The copy is over the element's whole RESERVED SPAN, not over its blob alone**,
and the span is what makes one mechanism cover every shape: a nested
comprehension also reserves its iterable and a display's capacity scan can
enlarge its own, so the element's blob is only ever a PART of `span` words. A
blob's count word is what every reader goes by, so the words past the live
elements are never read.

### The cost, and what it is bounded by

`cap * span` bytes, and **`cap` is a hard bound here for the same reason the
result blob's own reservation is**: the append exits(1) rather than writing a
`cap`-th slot, so a generator cannot run past it.

**Measuring that cost found a defect in the reservation itself, and that is the
second half of what landed.** arm64's `_compr_cap` reads a `range` literal out
of the generator header; x86-64's reaches its bound through `_blob_est`, **which
had no `range` arm at all**, so every `range` iterable was
`BLOB_ESTIMATE_FALLBACK` there. Measured on `[[j + i for j in range(3)] for i in
range(20)]`: arm64 reserved a 20-element result and x86-64 a 64-element one, for
the same source — and `_compr_cap`'s own docstring claimed "the two backends now
size one comprehension's reservation identically", which was false. With the copy
cost being `cap * span`, a 3.2x over-estimate is the difference between answering
and REFUSING on x86-64's 16 KiB blob region:

```
build: a comprehension's own copy of its element does not fit in the frame: it
needs 35328 bytes and this function has 15144 left for containers
```

So: x86-64's `_blob_est` grew the `range` arm its twin already had, and **both**
arms now read the header through `_range_info` — the one normaliser for the
three spellings, which the loop's own head test and `_blob_range_trip_bound`
already went through — instead of indexing `args[0..2]` and re-deriving "absent
means None". That last part is a second fix in the same two lines, and it is what
gives the **one-argument** `range(3)` a bound at all: it used to reach
`loop_trip_count` as `(3, None, 1)`, and `stop is None` means "no compile-time
bound" there, so the spelling almost every `range` in this repository and the
stdlib is written was the no-bound answer. Measured after, both backends agree:
`_compr_cap` 20 and 3 on each, `_blob_est(range(20))` 20 on each.

**The arm64 half of that is a de-duplication and a smaller reservation, not a
fixed wrong answer** — narrowing `_blob_est` can only ever shrink what it feeds
`blob_loop_growth`, and for `for i in range(3): s = s + [1]` it makes the
growth arithmetic exact (`1 + 1*3 = 4` words) where the fallback gave it 65.
`test_formal_run.py`'s `blob-growth-guard` group (the one that wraps
`_emit_blob_growth_guard` and records which sites actually emit one) is 5/0
after it.

The one measured cost that remains is a frame refusal where a comprehension's
element subtree is itself large — a concat of a dynamic slice under a dynamic
iterable reserves ~1 KB per slot and, at `cap = 64`, does not fit x86-64's
region. That trade is deliberate and it is the document's own §"Why it is a
refusal-shaped question" applied to the shapes that cannot be paid for: the
program used to build and answer 90, so this is a refusal where there was a
wrong number, which is the direction the whole formal path takes. Measured over
this repository's own corpus the cost is **nothing**: `test_formal_run.py`
(1126 cases), `test_formal_value_model.py`, `test_x86_64_containers.py`,
`test_formal_closures.py`, `test_formal_list_splat.py`, `test_formal_globals.py`,
`test_formal_json.py`, `test_ast_formal.py`, `test_formal_frame_len.py`,
`test_formal_optional.py`, `test_formal_int_semantics.py` and
`test_formal_core_hostmods.py` are unchanged, and the two failures in
`test_x86_64_containers.py` (`with-statement`) and
`test_formal_x86_64_parity.py` (`printf_float_operand_read_from_an_xmm_register`)
are the pre-existing pair the previous commit recorded as verified against
master.

### The tests, and what each one is for

Six ORACLE rows in `test_formal_value_model.py`'s `CASES` (CPython as the oracle,
both architectures), one per row of the table above plus the direction guard
and the sizing row:

* the five aliasing shapes, each measuring a **SUM of `v[0]`** rather than a
  print of it — three copies of one container and three distinct containers have
  the same COUNT, so a suite that measured `len` could not have seen this at
  all, which is why this document's own §0a insisted on `v[0]`;
* `a_comprehension_whose_element_is_a_bare_name_still_aliases_it`, which reads
  `vs[0] is vs[1]`. `is` is this path's unboxed integer equality, so it compares
  the two ADDRESSES — the observation that separates "copy it" from "leave it
  alone", and one a sum would agree with either way;
* `a_comprehension_over_a_range_iterable_is_answered_on_both_architectures`,
  which pins the SIZING half and is the row that fails without the `_blob_est`
  fix (x86-64 refuses it). It is an ORACLE row and not a reservation number
  because a reservation is not observable at run time and this difference IS:
  the frame runs out. Its inner generator's target is `j` and not `i` — with `i`
  shadowed the element does not depend on the outer loop variable, the shared
  blob happens to hold the right value, and the row would pass with the aliasing
  defect in place.

and one `REFUSALS` row, `a_comprehension_whose_element_holds_an_inner_container_is_refused`,
for §0a below. Its needle is the clause that says the element holds an ADDRESS,
because a row pinning the SHAPE alone would be satisfied by any message at all,
which is how a shape that became answerable would keep its refusal.

**Verified to fail without the fix**: with `_emit_compr_element` returning `None`
before the copy on both backends, `PASS=2 FAIL=5` and the five answers are
`90 / 93 / 93 / 90 / 90` where CPython answers `60 / 63 / 63 / 60 / 60`. The
bare-name row and the refusal row pass either way, which is what they are for.

## 0a. What is left, and it is one shape

**A comprehension whose element blob holds the ADDRESS of a container the same
expression rebuilds** — `[[[i] for i in [y]] for y in [10, 20, 30]]` — is now
REFUSED on both backends rather than answered 90 where CPython answers 60.

The reason a word copy cannot reach it, and it is the reason this document
called the fix a layout change: copying the element's words gives iteration `i`
its own copy of the OUTER blob and every word in that copy is right, **except a
word that is the address of a container the same expression rebuilt**, because
the copy is right and the thing it points at is still the one site every
iteration shares. Fixing it properly means relocating the inner addresses as
well, and a blob has no tags, so nothing on this path knows which of its words
are addresses.

`formal/model.py::comprehension_element_borrowes_inner_container` is the ONE
reader of that question, asked of the element expression and **one level, not a
descent**, because the question is only ever about that blob's own words. Each
of its `False`s is a separate reason rather than a gap: a concat, a repetition
and a slice put their operands' WORDS in the result (a slice's source is not
rebuilt per iteration), and a generator's ITERABLE is not an element position at
all — which is why `[[x + y for x in [1, 2]] for y in ys]`, whose inner
comprehension iterates a list display, is answered rather than refused.

**The census says the refusal is nearly free, and §0's is the measurement.** Over
this repository's own 516 `*.py`/`*.mojo` files, parsed and walked with the
predicate the emitters ask (`.tmp`-derived directories pruned through
`checked_run.is_derived_dir`, as `tools/formal_template_call_census.py` §0
established): **2357 comprehension nodes, 174 whose element builds a container,
and 0 of those whose blob holds a container it also builds.** 153 are copy-able
flat elements; 21 are built by a shape the copy still covers (a dict display, a
star-splat display, a slice, a concat). So the refusal this document would have
recommended outright — which §0 measured at 323 program sites — is now paid by
**none** of them, and the shape that is refused is not in this corpus at all.

**One residual inside the fix's own reach, stated rather than left implicit**: a
call that returns a container is covered when it IS the element (the row above),
and not when it is nested INSIDE a container-building element — the inner call's
block would need relocating for the same reason, and `container_returned_blob_sites`
is keyed by node so the outer copy has no way to see it. No such site is in this
corpus either, and the predicate cannot see one, so it is not pinned; it is
recorded here because a reader of `_emit_compr_element` would otherwise have to
rediscover it.

## The original report, unchanged

This document's §"Why it is a refusal-shaped question" priced refusing at "6 of
the 610 stdlib modules". **Measured over this repository's own 516 `*.py`/`*.mojo`
files: 113 files carry 323 comprehension sites whose element BUILDS a
container.**

```
files scanned: 516
files with a comprehension whose element BUILDS a container: 113
comprehension sites total: 323
of which in formal/ or test_formal_*: 53 files, 189 sites
```

"Builds a container" is the predicate the fix needs and the one this section's
own measurements use: `F.ListExpr` / `TupleExpr` / `SetExpr` / `DictExpr` /
`Comprehension` / `SliceExpr`, or a `+`/`|`/`*`/`or`/`and` over such a thing. **A
bare NAME is deliberately excluded**, and that exclusion is a correctness
requirement rather than a narrowing: `[inner for y in ys]` where `inner` is one
object gives three references to ONE list in CPython too, so aliasing a name's
container is the right answer and only a container the element position BUILDS is
the bug.

**A container CONSTRUCTOR call is excluded for a measured reason, not a
convenience one**, and the measurement is a trap worth recording because it
fooled this section's first attempt at the table below: `[list(y for y in [1])
for z in [10, 20]]` is **REFUSED** on both architectures — "`list`: a counted
blob this path CAN lay out (`BLOB_TYPE_CTORS`) but cannot COPY from another blob
at run time" — so `sorted`/`set`/`reversed`/`tuple`/`dict`/`range` in an element
position are not live shapes here and including them would overstate the census
by 25 sites. (The first attempt read **93** for that row, which was the
PREVIOUS row's image: the probe reused `$out` without deleting it, so a stale
binary was measured. Both architectures are re-measured here with the output
removed first.)

Every one of the 323 is a program this backend builds today and would stop
building under the refusal this document recommended, and 189 of them are in
`formal/` and the `test_formal_*.py` suites that the gate runs. **So the trade
this document called "cheap in coverage and worth considering as the interim
answer" is not cheap, and the decision it deferred is now made: do not refuse.**

The census's shape is also why the fix is not the one this document proposed.
A per-iteration materialisation needs somewhere to put iteration `i`'s container,
and the two candidates are both worse than they look:

  * **Inside the result blob.** Its count field is the number of ELEMENTS, so a
    flattened `[count][e0][e1]…` with a two-word element would make `v[1]` read
    word 1 of element 0 — and `len(v)` would be 6 where CPython says 3. Making it
    right needs a per-element length prefix, which is a new blob layout read by
    `v[i]`, `len(v)`, iteration, `print`, and every container helper downstream.
  * **Beside the blob, at `cap * elem_words` reserved words.** Feasible for a
    STATICALLY sized element and not otherwise, and `cap` is an estimate rather
    than a count, so the reservation is a claim about a loop this backend cannot
    bound — which is the same estimate `_blob_site_growth` exists to keep honest,
    and the same reason a reservation that cannot be kept is a wrong answer.

So the honest statement of what is left is a layout change plus a
per-iteration-copy pass, with a proof obligation per element kind (a list
display, a tuple display, a dict display, a slice and a nested comprehension each
materialise their result differently), and it is worth **0 sweep files today** in
exchange for 323 program sites this repository would otherwise lose. That is a project, and a next session should price it
against a corpus census of its own rather than against this one.

## 1. The signature, as it stood before §0 (the original measurement, kept)

Every row is the same program with a different element, summing `v[0]` over the
result — the observation `v[0]` rather than `len`, because three copies of the
last iteration and one element per iteration have the SAME COUNT, and a suite
that measured the count could not see a content defect at all.

| element | CPython | arm64 | x86-64 |
|---|---|---|---|
| `[[y] for y in [10, 20, 30]]` | 60 | **90** | **90** |
| `[(y, y + 1) for y in [10, 20, 30]]` | 60 | **90** | **90** |
| `[[x + y for x in [1, 2]] for y in [10, 20, 30]]` | 63 | **93** | **93** |
| `[[x for x in [1, 2, 3]] for y in [10, 20, 30]]` (coincidence control) | 3 | 3 | 3 |
| `[list(y for y in [1]) for z in [10, 20]]` (a CALL, for contrast) | 2 | REFUSED | REFUSED |
| `[[1, 2], [3, 4]]` — the same displays, **outside** a comprehension | 4 | 4 | 4 |

**The second row is new and it is a TUPLE display**, which this document's
signature table does not contain: a list display is not the only node type that
aliases, so a fix scoped to `F.ListExpr` alone would leave tuples. **The last row
is the boundary the fix must not cross**: the same two list literals outside a
comprehension are two DISTINCT objects and both backends answer CPython, so the
defect is the comprehension's per-iteration materialisation and nothing about a
list display as a value. **The fifth row is why the census below excludes
constructor calls**: they are refused, not wrong.

**Each of the first three rows is a row in §0's tests now**, and the fourth —
the coincidence control — is why §0's rows measure `v[0]` and not `len`: the
control is RIGHT today and would stay right, so a count-based row would have
passed with the defect in place.

**Found while measuring comprehensions against CPython** in a round whose claim
is `project33:closures-lambdas` (`test_formal_closures.py`). **Not fixed there**:
the fix is a per-iteration storage decision inside both emitters' comprehension
lowering, which is a different area and a larger change than that round had
budget to prove. Filed with the signature measured, because the signature is the
useful part — it is NOT B1, B2 or B4 in `bugs/OPEN_WORK.md` §B, and those three
are all nested-comprehension defects already characterised as not-fixed, so a
future session must not re-derive this as one of them.

## What was run

    $ cat v.mojo
    def main():
        s = 0
        for v in [[x + y for x in [1, 2]] for y in [10, 20, 30]]:
            s = s + v[0]
        print(s)
        return 0
    main()
    $ python3 v.mojo
    63
    $ python3 fire.py build --formal --no-prove -o v v.mojo && ./v
    93
    $ # identical on --backend=x86_64

## What was seen

Every outer iteration's `v` is the SAME container, and it holds the LAST
iteration's contents: 93 = 31 + 31 + 31 where 31 is `y == 30`'s element. Exit
status 0 on both backends, no diagnostic, nothing on stderr.

## What was expected

CPython's `63` = 11 + 21 + 31: three distinct lists.

## The signature, measured

Every row run on both backends; both agree in every row, so this is not a
cross-backend divergence either.

| program | CPython | arm64 / x86-64 |
|---|---|---|
| `[[x + y for x in [1, 2]] for y in [10, 20, 30]]`, sum of `v[0]` | 63 | **93** (31 × 3) |
| `[[x + y for x in range(2)] for y in [10, 20, 30]]`, sum of `v[0]` | 60 | **90** (30 × 3) |
| `[[y, y + 1] for y in [10, 20, 30]]`, sum of `v[0]` — **no inner comprehension at all** | 60 | **90** (30 × 3) |
| `[[x for x in [1, 2, 3]] for y in [10, 20, 30]]`, sum of `v[0]` | 3 | 3 (correct by coincidence — the element does not depend on `y`, so one shared blob holds the right value) |
| the first program with ONE outer iteration, `for y in [10]` | 11 | 11 (correct) |
| `[i + j for i in [1, 2] for j in [3, 4]]` — two GENERATOR clauses, flat, not nested | 20 | 20 (correct) |
| `v = [x + y for x in [1, 2]]` as a STATEMENT inside a `for y in [10, 20]` body | 32 | 32 (correct) |
| `v = [y, y + 1]` as a statement inside a loop body | 30 | 30 (correct) |

**The two facts that locate it.** The third row has no inner comprehension, so
"nested comprehension" is not the subject; the last row is the same literal in
the same loop and is right, so "a container built in a loop" is not the subject
either. What the wrong rows share and the right rows do not is that the
container is the **element expression of a comprehension**: it is materialised
once, at the element site, and the comprehension's append of it into the result
blob copies the ADDRESS rather than a per-iteration container. With one outer
iteration there is nothing to alias, and with an element that does not depend on
the loop variable the shared blob happens to hold the right value — which is why
the coincidental row must not be mistaken for a pass.

## Why it is not B1 / B2 / B4

`bugs/OPEN_WORK.md` §B holds three nested-comprehension defects, and the
distinction matters because all three are already-characterised open work:

- **B1** — `[i + j for i in range(n) for j in range(n)]`, n = 5, returns 98 for
  100. Two generator clauses in ONE comprehension (flat), and it is *two short*,
  not a repeat of the last iteration. **Re-measured on this tree: it returns 100 on
  both backends**, so B1 does not reproduce as written.
- **B2** — the same flat shape with `len` reading 4 for 16: a COUNT defect.
  Mine has the correct count and wrong *contents*.
- **B4** — arm64 4×4 sums to exactly double, with the count correct. Mine is not
  a doubling: it is N copies of the last element.

So this is a fifth signature in the same neighbourhood and needs its own row.

## Why it is a refusal-shaped question, not only a fix-shaped one — REFUTED by §0's census, and the reasoning is kept

The alternative to fixing the storage is refusing a comprehension whose element is
a container, which is this backend's standing answer for a construct with no
representation. That trade should be measured, not guessed, and the measurement
goes in the other direction from what one would assume: **6 of the 610 stdlib
modules** in this repository's own stdlib contain a comprehension whose element
opens a list literal (63 lines). So refusing is cheap in coverage and worth
considering as the interim answer — a wrong element list is worse than a refusal,
because a caller that appends to the comprehension's result gets a list whose
elements are all the same object, which is silent in a way a missing feature is
not. The decision belongs with whoever fixes the storage.

**The 6 was the wrong instrument and this section's own grep was never run.** The
predicate that decides is not "opens a list literal" but "the element builds a
container", which also counts a tuple display, a nested comprehension, a slice, a
concat and a call that returns one — and over this repository's own 516 files
that is **174 sites, not 6 modules** (§0). So the refusal this section called
cheap would have cost 174 program sites, 189 of the old count's kind sitting in
`formal/` and the `test_formal_*.py` suites the gate runs. §0's copy keeps all
174 building, which is why the fix is a fix and the refusal is only §0a's.

## The next step — DONE, and §0 is the answer to each half

Read the two emitters' comprehension element materialisation and ask where the
element's storage is allocated: if it is a slot reserved per element SITE (as
`frame_slots`/the local allocator would do), the fix is a per-iteration
materialisation or a copy at the append, and the proof obligation is whatever
that emitter already discharges for a list literal in a loop body — which the
last two rows of the table show is CORRECT today, so the machinery exists and is
being used in the wrong place.

**It is a slot reserved per element SITE, and it is the copy at the append.** §0
is that, on both backends, and the "proof obligation" is discharged by the
appender's own capacity guard rather than by a new one — which is why §0's copy
is emitted inside `_compr_append_elem` instead of beside it.

Check the fix against all three of: one outer iteration (regression guard for
the case that works today), an element that does not depend on the loop variable
(which must stay right), and a two-generator FLAT comprehension (B1's shape,
which must stay right). Fixing storage without those three will look like a fix
and will not be one.

**All three are rows, and the first is the sharpest of them.** One outer
iteration is `a_comprehension_whose_element_is_a_list_display_gives_each_one`
with a one-element literal, where the copy has exactly one slot and cannot
differ; the element that does not depend on the loop variable is
`a_comprehension_whose_element_is_a_bare_name_still_aliases_it`, which is
stronger than the doc asked for — a NAME reserves nothing, so it keeps
aliasing, which is CPython's own answer and the direction a copy must not
overshoot into; and B1's flat two-generator shape is
`test_formal_closures.py` and `test_formal_run.py`'s existing rows, both
unchanged.

## Test coverage — §0's, and this section's reasoning for having none is why

None yet, deliberately: `test_formal_closures.py`'s answered rows require the
formal stdout to EQUAL CPython's, so pinning today's `93` would assert the bug,
and its refusal rows require a refusal, which this is not. The rows belong in
`test_x86_64_containers.py` next to the `nested-comprehension*` group once the
answer is CPython's; the table above is the reproduction.

**Both halves of that reasoning were right and the conclusion has changed.** The
answer IS CPython's now, and the rows went to `test_formal_value_model.py`'s
`CASES` rather than to `test_x86_64_containers.py` — six ORACLE rows compared
against CPython on both architectures, which is a stronger pin than a
fixed-expectation table, plus one `REFUSALS` row for §0a. The reasoning that no
row could be written is what made the six worth writing: `test_formal_value_
model.py` would have gone red at 93 immediately, and that is exactly the signal
a suite for this construct should give.