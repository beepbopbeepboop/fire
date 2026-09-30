# A Lean TIMEOUT is published to the proof-verdict cache as if it were a verdict

**Area:** formal / shared infrastructure (`formal/lean.py`). Found while merging
`work/formal-x86-dylib` into the integrator's line; not that branch's area and
not fixed here.

**Status: open, diagnosed, not fixed.** One function's behaviour is the whole
bug: a `subprocess.TimeoutExpired` is a fact about the machine, and it is being
written into a content-addressed cache whose key deliberately says nothing about
the machine.

## What I ran

    python3 tools/memslot.py --gb 8 --label suitedylib -- python3 tools/suite.py formal-dylib

    suite: 3 tests, -j18, parallel, 96 GB memory budget
      FAIL     formal-dylib  (3s)  exit 1
    suite: 2 passed, 1 failed, 0 skipped

`test_formal_dylib.py` on its own: `formal dylib: PASS=11 FAIL=1`, the one
failure being

    FAIL  default path emits a checked proof
          default (prove) dylib build failed: formal dylib: proof check failed:
          ProofLib	Refine	X86	work	lean timed out

## What I expected

Either the proof passes, or the failure names something about the proof. What I
got is a wall-clock timeout reported as the proof's verdict, and — this is the
part that matters — replayed from a cache rather than measured.

## What actually happens

1. `formal/lean.py:1139` `_run_lean` runs `lean` on the generated file with
   `timeout` (1200 s from every caller) and, on `subprocess.TimeoutExpired`,
   returns `False, "lean timed out", 0` (`formal/lean.py:1149`). Up to here that
   is defensible: the check did not pass.
2. `formal/lean.py:867-869` `proof_census` then calls
   `_publish_verdict(key, ok=False, …)` on that outcome, and
   `_publish_verdict` (`formal/lean.py:903`) writes it to the CAS as a record
   whose first line is `fail`.
3. `proof_verdict_key` (`formal/lean.py:795`) hashes the verdict version,
   `lean_version`, the four `LIBRARY_MODULES` stems, each `lib/*.olean` digest,
   and the generated proof's bytes. It does **not** hash the machine, its load,
   or the time budget — correctly, for a verdict; incorrectly, for a timeout.
4. Every later run with the same proof bytes and the same `.olean`s gets
   `stored is not None` at `formal/lean.py:863` and returns the cached `fail`.

So one slow run on one busy box writes a verdict that every later run on every
worktree replays. `checked_run.py` cannot help, and its rule is the rule this
breaks: *"A recorded FAILURE is re-run … a cached red that no fix can clear is
worse than spending the time to find out."* That rule is implemented one layer
up, in the suite runner; the Lean verdict cache re-introduces the exact failure
mode one layer down.

## Evidence that this run replayed a verdict and did not measure one

Walking `~/.gmojo/cas` for `.leanverdict` records whose body contains
`lean timed out` (CAS_DIR from `cas.CAS_DIR`, `VERDICT_EXT` from
`formal.lean`):

    Mon Sep 28 16:42:36 2026  proof/be5f3af7….leanverdict   fail
    Mon Sep 28 21:54:41 2026  proof/c90aada7….leanverdict   fail
    Mon Sep 28 22:17:38 2026  proof/08b76f4d….leanverdict   fail
    Tue Sep 29 21:06:47 2026  proof/c485daf9….leanverdict   fail

    verdict records total 3284, written today 0

Three attempts today (two whole-file runs and one single-subtest run, the last
two of which failed in **0.3 s**) all reported the same failure and **none of
them wrote a record**. A first measurement cannot take 0.3 s, so no measurement
happened: today's proof bytes and `.olean` digests hash to the same key as the
2026-09-29 21:06 record, and that record's `fail` is what was returned. (The
reproducible `.olean` build is why the key survives an olean rebuild.)

## Why this is not the merge's fault

`formal-dylib` was already red before the merge touched anything:

- the newest poisoned record predates this session by ~6 hours;
- the merge resolved exactly one hunk of `formal/build.py`
  (`dylib_exports = dylib_export_lists(dylibs)` beside
  `_audit_link_line_containers`) and took no path into `formal/lean.py`;
- the other **11** subtests of the same file pass, including the three that
  build, sign and RUN Mach-O dylibs with the gimple runtime library on the link
  line — which is the code the merge resolved.

If the merge had changed proof generation at all, the key would have changed
and a fresh 1200 s census would have run. It did not, so the proof bytes are
unchanged and the verdict being replayed is a verdict about those same bytes.

## Next step, exactly

1. **Do not publish a timeout as a verdict.** `formal/lean.py` already has the
   vocabulary for this: `library_census` already returns "unmeasured, and said
   as such" for a module it could not measure (`formal/lean.py:587`, and
   `_LIB_UNMEASURED` at `formal/lean.py:810`). Give `_run_lean` the same third
   state — measured-and-failed vs not-measured — and have `proof_census` report
   the second without calling `_publish_verdict`. A cache that cannot answer
   should be a miss, which is what every other cache in this repository already
   does.
2. **Then measure once, on an idle machine**, to learn the real verdict of those
   four proofs. Step 1 makes the poisoned records unreachable rather than
   needing them deleted — do NOT hand-delete files out of `~/.gmojo/cas`: it is
   machine-wide and shared with every other worktree.
3. **While step 1 is open**, `formal-dylib` stays red in `check` for anyone
   whose `lib/*.olean` digests match, so it is the one row in the tally to read
   with this caveat rather than as a merge regression.
