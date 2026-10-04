# FORMAL_the_two_architectures_have_different_container_budgets: a list literal one machine lowers is a refusal on the other

**Area:** formal codegen · **found by:** `tools/formal_fuzz.py --mix limits`
(seed `sweepG` 8000-8099, `REFUSAL-DIVERGES-X86+ARM`) · **filed 2026-10-03, NOT fixed**

## What I ran

    python3 tools/memslot.py --gb 8 --label limits -- \
        python3 tools/formal_fuzz.py --mix limits --seed sweepG \
            --seeds 8000-8099 -j 3 --max-min-steps 30 --work .tmp/fz4/limits-sweep

## What I saw

Five of a hundred programs, every one of them a `big_blob` (a 2100-2400 element
list literal), and every one of them the same shape:

    x86_64  build: a list literal does not fit in the frame: it needs 17608 bytes
            and this function has 16344 left for containers.
    arm64   build: '+' on two strings is refused on this path. …

arm64 got PAST the literal and refused a later construct in the same program;
x86-64 refused the literal. The counts are the whole of it: arm64's scratch is
128 KB and x86-64's blob region is 16 KB, which `formal/model.py`'s
`frame_blob_refusal` documents in its own docstring — so the difference is
intended and the refusal is TRUE on both machines. What is not intended is that
"the program this machine will not build" is a property of the ARCHITECTURE
rather than of the source: the same source builds and runs on one machine and is
refused on the other, and `tools/formal_fuzz.py`'s `REFUSAL-DIVERGES` verdict is
exactly that observation, because a construct one machine declines is a parity
finding whatever the reason.

The two messages differ for a second reason worth separating from the first: the
machines refuse at different POINTS, so the arm64 message names a different
construct entirely. `test_formal_run.py` already has the vocabulary for that
shape (`refuse_either:`, written for `del a[i, j]` refusing at the subscript on
one machine and at the statement on the other) and the fuzzer has none — it
reports both shapes under one verdict, which is right, because "the two machines
do not agree about this program" is the finding either way.

## What I expected

Either the budgets to match, or a documented answer to "which machine decides".
There is one for the CONTAINER (`frame_blob_refusal` names both budgets, and it
is why this row is filed rather than fixed) and none for the corpus: `limits`
carries `big_blob` at weight 2, so roughly one `limits` sweep in twenty
programs reports this, and every reader has to re-derive the two numbers to know
whether a `REFUSAL-DIVERGES` is this or something new.

## Why it is not fixed

Closing it means either raising x86-64's blob region to arm64's 128 KB — a
frame-layout change with a proof obligation on the x86-64 model (the stack-floor
and frame-bound lemmas in `lib/X86.lean`) — or making the two emitters reserve
from one shared budget constant and accepting whichever machine has the smaller
frame. Both are projects, not patches, and both land on `formal/x86_64_codegen.py`
plus the model's frame arithmetic, which is the write set of other claims.

## The exact next step

One line, and it is worth doing before either of those: put the two budgets in
`formal/model.py` as named constants beside `frame_blob_refusal` (it already
states 128 KB and 16 KB in prose) and have both emitters read them, so the number
in the message is one number in the tree rather than two literals in two
emitters. Then the corpus row becomes: emit the size from the SMALLER budget, and
the `limits` mix stops producing a `REFUSAL-DIVERGES` that is really a fact
about the frame — which is the only way to tell that class apart from a real one
in a tally.
