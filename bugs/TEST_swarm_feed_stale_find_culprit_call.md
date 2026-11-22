# TEST: test_swarm_feed.py calls find_culprit(stdlib=...), which swarm.py does not accept

Found 2026-11-22 while checking the swarm feeder change (doc_claims) by its quick tests.

## What I ran

    python3 tools/test_swarm_feed.py

## What I saw

The first culprit-search cases pass, then the run dies:

    File "tools/test_swarm_feed.py", line 241, in main
      S.find_culprit(["a", "b", "c"], ["j"], stdlib=False)
    TypeError: find_culprit() got an unexpected keyword argument 'stdlib'

`swarm.py`'s `find_culprit(seq, failing)` (line ~970) takes two parameters. The
present-at-HEAD signature has no `stdlib` argument, and the test was not updated
when the culprit search changed (commit 3e0aa0503 rewrote it to probe behind the
batch's gate).

Because `main()` aborts there, the cases after line 241 (the feed tests) never run.
This was broken before the claim change; it is not caused by it.

## Expected

Either the test drops the `stdlib=` argument (if the stdlib distinction is gone
from the design), or `find_culprit` regains the parameter if the design still needs
it. Decide from commit 3e0aa0503's intent, then make the whole file run to its end.

## Exact next step

    git show 3e0aa0503 -- tools/swarm.py tools/test_swarm_feed.py

to see what the stdlib flag meant, fix the one side that is stale, and run
`python3 tools/test_swarm_feed.py` until it prints all cases and exits 0.
