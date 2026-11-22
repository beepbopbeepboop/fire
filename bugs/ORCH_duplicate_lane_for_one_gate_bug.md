# ORCH: one gate bug is dispatched twice, under two claim namespaces that never conflict

Filed 2026-11-22 by the `bug-gate-type-string-ratchet` lane (work-7996).

## What I ran

    python3 tools/control.py claims
    python3 tools/control.py status --all

## What I saw

Two live tasks on ONE problem, dispatched in the same batch:

| task | worktree | claim | state when checked |
|---|---|---|---|
| `fix-gate-type-string-ratchet` | work-7994 | `gate:type-string-ratchet` | exited-ok, `DONE`, 1 commit |
| `bug-gate-type-string-ratchet` | work-7996 | `bug:gate-type-string-ratchet` | running |

and the same pairing again, concurrently, for another gate job in this batch:

| task | worktree | claim |
|---|---|---|
| `fix-gate-gimplerunner` | work-7993 | `gate:gimplerunner` |
| `bug-gate-gimplerunner` | work-7995 | `bug:gate-gimplerunner` |

So this is not one unlucky pair; the ledger dispatch built two lanes per gate job.

The `fix-` worker finished the whole change first — `76d79ef95` switched the
`endswith(' *')` test to `TypeLattice.ends_in_star`, dropped the job's
`disabled=` marker, and deleted the gate ledger doc. The `bug-` lane had
therefore nothing left it was allowed to do: rule 5 of the worker task says to
stop and report when the area is claimed by another worker, and the only change
it could have made is the exact one already committed. A whole dispatch was
spent to reach that conclusion (the `fix-` lane's own ledger entry records 123 s
of its 600 s cap, so this one duplicate pair was cheap; the pairing is what
matters, not the seconds).

## Root cause

`conflicts()` compares path COMPONENTS: it splits each claim on `/` and compares
the common prefix. A claim with no `/` is one component, so

    'bug:gate-type-string-ratchet'  vs  'gate:type-string-ratchet'

are different identities and `claim_blocker` admits both. `norm_claim` passes
namespaced keys through unchanged (deliberately: `bug:`, `gate:`, ... are
disjoint namespaces), so nothing relates the two spellings.

They name one item. A gate ledger doc is `gate-<job>.md`, so the bug queue
derives `bug:gate-<job>` while the verifier's repair item derives `gate:<job>`.
The two derivations are structurally linked but textually disjoint, and
`claim_blocker` only understands the textual form.

## Expected

Lanes that repair one gate job are one item for scheduling purposes: starting a
`bug-gate-<job>` lane while a live task holds `gate:<job>` (or the reverse)
should be refused, exactly as two spellings of one bug document are one
`bug:<stem>` after `norm_claim`.

## Exact next step

`tools/control.py`, `claim_blocker` (the single admission point both `spawn` and
`refill` already ask): when a candidate claim is `bug:gate-<stem>`, test
`gate:<stem>` against the live holders as well, and when a candidate claim is
`gate:<stem>`, test `bug:gate-<stem>`. Keep `conflicts()` itself unchanged — it
models path containment and has its own tests; the cross-namespace mapping is a
scheduling rule and belongs where the scheduler asks.

Better (and it makes the reverse direction free): give the `bug-gate-<job>`
item the `gate:<job>` claim in the feeder, so the existing conflict machinery
does the work and `claims` shows the real subject of each lane. Then the doc
claim (`bug:gate-<job>`) keeps the two bug lanes apart as it does today.

Pin it in `tools/test_control_norm_claim.py` (the file that already owns "one
document is one claim"):

- a case asserting a live `gate:type-string-ratchet` holder makes a
  `bug:gate-type-string-ratchet` claim blocked, and the mirror direction;
- a case asserting two DIFFERENT gate jobs still do not block each other, so
  the mapping is not accidentally a prefix rule.

## Done when

`python3 tools/test_control_norm_claim.py` passes with the new cross-namespace
case, and that case fails before the `control.py` change. Witness the failure by
committing the test before the fix, or by running it against a scratch copy of
`control.py` with the mapping removed; the registry half (`python3
tools/control.py claims` showing one lane per gate job) is what a subsequent
batch can confirm.
