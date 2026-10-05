# FORMAL: a comprehension whose ELEMENT is a container aliases every iteration's element to the LAST one

**Area:** FORMAL (both backends; the comprehension lowering, which both share
through `fire_compiler.py::genexp_body` and their own `_emit_compr_gen`-shaped
walks).

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