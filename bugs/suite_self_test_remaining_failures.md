# suite-self-test: 7 remaining internal failures after OPEN_WORK.md fix

Status: PARTIAL — bugs/OPEN_WORK.md stale block fixed (via formal_doc_index.py --write); 7 internal checks still red.

What I ran:
  $ python3 tools/formal_doc_index.py --write   # rewrote bugs/OPEN_WORK.md
  $ python3 tools/suite.py --no-cache suite-self-test  # still fails

Remaining failures (from build/suite.log, 358 passed, 7 failed):
  - budgets: residue census disagrees (55 files vs census 48)
  - budgets: residue is not allowed to grow
  - the estate: 39+ test files unregistered / not in UNREGISTERED
  - dangling refs: 12 dangling citations outside test_suite.py
  - dangling refs: BARE walk not vacuous (191 citations of 115 names nowhere)
  - dangling refs: BARE class ledger gains
  - expect count: registry counts don't match marker prose

Next step: update UNREGISTERED / budget census / dangling-ref baselines and reconcile expect= markers with current registry counts (see test_suite.py checks for budgets/estate/dangling-refs/expect-count).
