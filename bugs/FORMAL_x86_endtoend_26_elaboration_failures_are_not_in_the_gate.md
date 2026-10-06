# `formal-x86-endtoend` fails 26 of 26 `terminates` cases on elaboration errors, and the gate does not run it

**Area:** `formal/x86_64_endtoend_test.py`'s corpus sweep (the registered job
`formal-x86-endtoend`). **Status: OPEN, measured, PRE-EXISTING on `master`
(`b83f2ed2`) and NOT caused by the branch that found it.** Found 2026-10-05 on
`work/gatefix15`, whose diff over that file is `SEARCH_PATHS`/`LEAN_PATH` (one
list instead of a format string at two call sites) and `_module_of`/`_run_lean`
deriving the module name from it — see "Why this is not my fix" below.

**This is NOT one of the two failures the task was given.** `formal-sweep-truth`
and `suite-self-test` were the gate's reds and both are fixed (see the commits on
`work/gatefix15`). This job was found because it is the registered job that runs
the file `formal-sweep-truth`'s end-to-end case lives in, so it is the natural
place to check that the change did not break the emitter — and it is red.

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/suite.py formal-x86-endtoend --no-cache
  FAIL     formal-x86-endtoend  (843s)  exit 1
  wide_recv  terminates: FAIL lean exited -6: libc++abi: terminating due to uncaught excep
  sle8       terminates: FAIL lean exited 1: error: Type mismatch | x86_step_setcc_r8 s24
  twoifs     terminates: FAIL lean exited 1: error: Type mismatch | x86_step_setcc_r8 s26
  vardecl    terminates: PROVED
  …
  terminates : 13 proved with no sorry, 0 proved with a sorry
  failing    : 26
memcap: done, peak 6.1 GB across up to 2 procs (ceiling 8.0 GB), child exit 1
```

**26 of 26 `terminates` cases fail**, and every one of them is an
ELABORATION error — `lean exited 1: error: Type mismatch | x86_step_setcc_r8 sN`
dominant, plus one `Tactic \`rewrite\` failed: Did not find` and one OOM abort.
Not one is a hole, an admission, or a `sorry` report.

## Two facts that make this somebody else's, and both are load-bearing

**1. The job is not in the gate.** `python3 tools/suite.py --dry-run gate`
prints `77 tests, 211 jobs` and does not contain `formal-x86-endtoend`; the
`gate11-full.txt` log's own selected list (`sed -n '14p'`) does not either. The
test is in buckets `proofs` and `x86`, and neither is in `gate` — so this was
never among the gate's reds and the two that were (`formal-sweep-truth`,
`suite-self-test`) are fixed on this branch. Running it was still worth it: it
is the sweep of the file my change lives in.

**2. It fails the same way with my change reverted.** `bb12e6b0`'s commit
message already records the measurement, on `master`, for exactly this file and
exactly this count:

> `python3 formal/x86_64_endtoend_test.py` over the whole corpus is unchanged by
> this: its 26 failures are elaboration errors (`lean exited 1: error: Type
> mismatch | x86_step_setcc_r8 …`) that do not reach `live_hole_phrase` at all,
> since that runs only when `fired` is true.

`bb12e6b0` is an ancestor of `master`, so that measurement IS a master
measurement, and it is the same 26 with the same dominant reason. My change is
also provably not on this path: `_run_lean` returns early on a non-zero exit
(`lean exited 1: error: Type mismatch …`), so `live_hole_phrase` — the only
function I changed the arguments of — is never reached for any of the 26. The
log agrees: `grep -c "proved with a sorry" ` over this job's output is **0**.

So this is a real, pre-existing red in a job the gate does not run, and it is
NOT the failure this task was about.

## Why this is not my fix

The dominant reason names a MODEL lemma, not the emitter or the proof generator:
`x86_step_setcc_r8`. `bugs/FORMAL_x86_64_end_to_end_proof.md` owns that work
("B1–B23, the proof work, the per-form ledger" per `bugs/OPEN_WORK.md`), and
`python3 tools/control.py claims` puts several `formal/` areas under live claims
(`formal35-4`, `formal37-2`, `formal37-3`). Writing a `setcc` lemma or changing
the model's `r8` shape is inside those claims, so the standing rule is to report
it rather than edit it.

## The exact next step

Whoever holds the `lib/X86.lean` `setcc` lemma claim:

1. **Reproduce one case**, which is the cheapest form of the question:
   `python3 formal/x86_64_endtoend_test.py` and read ONE `Type mismatch` for
   `sle8` — the log truncates it to 60 chars by `_run_lean`'s own `[:60]`, so
   the argument types are NOT in the output above. Run `lean` on the generated
   `sle8` proof directly (via `formal/lean.py::run_lean`, with `LEAN_PATH` set
   the way `_run_lean` sets it) to see the whole `Type mismatch`.
2. **Compare `x86_step_setcc_r8`'s stated signature with what
   `x86_step_setcc` concludes** — the same shape as the deleted
   `FORMAL_x86_64_step_lemma_cqo_states_cdq.md` (`bugs/OPEN_WORK.md` records
   that one as a lemma stating a DIFFERENT instruction from the one the model
   decodes, and the whole library failing to build). If `setcc_r8` states a
   width the model does not produce, that is the same class of bug and the fix
   is in the lemma.
3. **`wide_recv`'s `-6` is a separate item**: `lean::memory_exception` on one
   input, i.e. an OOM rather than a mismatch, and
   `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md` is the
   adjacent subject. Do not fold it into the `setcc` work.

**What is deliberately NOT proposed**: an `expect=` marker. It would need a count
("26 of 26"), the count is only checkable against the harness's own summary line,
and — per `CLAUDE.md`'s own rule — a job that is this cheap (843 s, 6.1 GB) with
this many failing items is a real red that should be fixed, not absorbed. It is
in a bucket and therefore visible; that is the right state for a known red.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/suite.py formal-x86-endtoend --no-cache    # 843 s, 6.1 GB
$ python3 tools/suite.py --dry-run gate | grep -c formal-x86-endtoend   # 0
$ git show bb12e6b0 --format=%B --no-patch | grep -n "its 26 failures"
```

The third command is the proof this is pre-existing: `bb12e6b0` is on `master`
and its message already records 26 elaboration errors on this file, not reaching
the reader this branch changed.
