# FORMAL: a comprehension whose ELEMENT is a container aliases every iteration's element to the LAST one

**Status: NOT FIXED, and the two options this document weighed are BOTH now
measured, and the one it recommended is REFUTED by its own census.** §0 is the
census the document's next step asked for and did not have ("That census is a
grep and has not been run"), and it is over 50x larger than the estimate here.
**Nothing is pinned as a passing row and nothing asserts today's wrong answer**,
because this backend has no mechanism for the alternative; §0 says what the fix
would actually be and why it is a layout change rather than the per-iteration
copy this document proposed.

## 0. The census, run, and what it refutes

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

## 0a. The shapes, measured on both architectures, and one this document did not test

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
list display as a value. **The fifth row is why the census above excludes
constructor calls**: they are refused, not wrong.

**No test is added, and that is a decision rather than an omission.** The three
suites this construct could be pinned in all want one of two things:
`test_formal_value_model.py`'s `CASES` rows compare against CPython and would go
red immediately (93 vs 63), and its `REFUSALS` rows require a refusal, which this
is not; `test_x86_64_containers.py` is a fixed-expectation table, so a row there
would assert 93 — i.e. assert the bug. A row that pins a wrong answer is worse
than no row, and the anti-rot this needs is a `KNOWN_DIVERGENCES` entry in
`tools/formal_fuzz.py` plus a generator family that emits the shape on purpose,
which is the same construction `set_order` has and the one this document's own
§"Test coverage" declined to reach for.

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

## Why it is a refusal-shaped question, not only a fix-shaped one

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

## The next step

Read the two emitters' comprehension element materialisation and ask where the
element's storage is allocated: if it is a slot reserved per element SITE (as
`frame_slots`/the local allocator would do), the fix is a per-iteration
materialisation or a copy at the append, and the proof obligation is whatever
that emitter already discharges for a list literal in a loop body — which the
last two rows of the table show is CORRECT today, so the machinery exists and is
being used in the wrong place.

Check the fix against all three of: one outer iteration (regression guard for the
case that works today), an element that does not depend on the loop variable
(which must stay right), and a two-generator FLAT comprehension (B1's shape,
which must stay right). Fixing storage without those three will look like a fix
and will not be one.

## Test coverage

None yet, deliberately: `test_formal_closures.py`'s answered rows require the
formal stdout to EQUAL CPython's, so pinning today's `93` would assert the bug,
and its refusal rows require a refusal, which this is not. The rows belong in
`test_x86_64_containers.py` next to the `nested-comprehension*` group once the
answer is CPython's; the table above is the reproduction.