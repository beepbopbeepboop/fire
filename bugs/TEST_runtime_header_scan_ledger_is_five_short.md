# TEST_runtime_header_scan_ledger_is_five_short: the header-scan ledger counts 565 declarations and the header has 570

## Status (2026-10-04, measured on `ccb157ed` + `work/gatefix9`)

Pre-existing red on this merge base, NOT caused by and NOT fixable from
`work/gatefix9`: five runtime entry points arrived on branches merged after the
last ledger entry and no ledger row was added for any of them. Found while
landing `mojo_id` (whose own +1 row is in place).

    $ python3 test_runtime_header_scan.py
    FAIL  fire_runtime.h: 565 declarations scanned: got 570
    36 passed, 1 failed, 37 checks

Measured directly, which is what makes it a fact about the tree rather than
about a run:

    $ python3 - <<'EOF'
    import sys; sys.path.insert(0, '.')
    import reflect
    print(len({e['name'] for e in
               reflect.collect_runtime_exports_h('runtime/fire_runtime.h')}))
    EOF
    570

`work/gatefix9` adds `mojo_id` and its ledger row (565 -> 566), so the same
command reports 571 against a ledger of 566. The remaining gap is the SAME
five names, unchanged.

## Why the ledger cannot be repaired from here

`test_runtime_header_scan.py`'s `test_every_declaration_is_seen` is a COUNT,
not a per-name list: the comment above the tuple explains at length that the
number is read off the merged header rather than being any one branch's total,
because two branches that each added names did not each add them to this
header. So there is nothing in the test file that says WHICH five names are
unaccounted for, and the header scan (`reflect.collect_runtime_exports_h`)
reports all 570 without saying which are new. Recovering the five means
bisecting the declaration set across the merge commits that touched
`runtime/fire_runtime.h` since `4b8c27e1` (the commit the 565 row was written
against).

The 489 header names that appear nowhere in `test_runtime_header_scan.py` are
NOT evidence of anything: the ledger is a count, so most names are never
written down individually, and 484 of those 489 predate this gap.

## The next step, exactly

1. `git log --oneline 4b8c27e1..HEAD -- runtime/fire_runtime.h` and, per merge
   commit, count the header declarations on each side
   (`reflect.collect_runtime_exports_h` on that tree's header). The five are
   the difference between "the sum of what the merged branches each added" and
   the merged header's own count — which is the arithmetic the 561 -> 565 row
   documents doing by hand.
2. Add ONE ledger row naming them, in the same shape as the 561 -> 565 row
   above it (what each name is for, and why it is public), and set the count
   to the header's real total.

Do NOT simply set the count to 570 (or 571). That is exactly the failure this
file exists to catch: a count that agrees with the header while no row says
what the five names are. `work/gatefix9` deliberately left the gap visible for
the same reason.
