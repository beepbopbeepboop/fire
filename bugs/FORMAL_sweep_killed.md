# FORMAL_sweep_killed: the arm64 sweep of 2026-10-01 was SIGKILLed and reported nothing, and why the tool was built so that one file could do that

**Status: the two mechanisms that made it possible are FIXED**
(`tools/formal_sweep.py`, branch `work/formal-sweep-killed`). **The identity of
whatever sent the SIGKILL is NOT established**, and this document says so in
§1 rather than guessing. The fix does not depend on knowing: it makes the sweep
survive being killed, which is the right response to a sender that cannot be
identified from the artifacts.

## What happened

The owner ran two sweeps at once from the main checkout:

```
python3 ./tools/formal_sweep.py --arch x86-64 > /tmp/sweep-x86-4.txt 2>&1 &   # completed
python3 ./tools/formal_sweep.py               > /tmp/sweep-arm-4.txt 2>&1     # died
```

The x86-64 one completed: 623 files, 106 pass. The arm64 one printed its
5-line header and nothing else, and the shell reported `Killed: 9` (SIGKILL):

```
Sweep roots:
  …/mojo-reference  (371 files)
  …/new-modular/Mojo/stdlib/std  (252 files)
Total: 623 files
Sweeping 623 files through build --formal [arm64] (18 workers, 30s timeout)...
Every file is classified (pass / codegen / …); the two codegen classes are …
```

So 623 files produced no classifications, and — this is the part that cost the
diagnosis — **the log cannot say how far it got.** See §2.

## 1. Who sent the SIGKILL: not established, and here is what was ruled out

Every candidate in the task's list, and what the evidence says:

| candidate | verdict | evidence |
|---|---|---|
| `tools/memcap.py` | **ruled out** | the owner ran the bare command; nothing wrapped it |
| `tools/memslot.py` | **ruled out** | same — no reservation was taken, and a memslot client that is killed does not kill its own job |
| `tools/control.py guard` | **ruled out** | the guard (`--limit-gb 55 --total-gb 90`) kills any process whose **cwd** is inside a worker worktree. The owner's sweep ran from `/Users/mrs/net/chatgpt/claude/mojo-reference`, which is **not** in the guard's root set (verified: `control.load()`'s 135 worktrees + `work-integ`; `mojo-reference` is not among them, and the guard's own `MAIN` is whichever tree it was launched from). And `guard.log` is **0 bytes** — it has never killed anything on this box. |
| one file whose build explodes | **ruled out as memory** | see §3. No single file exceeded 0.2 GB; the whole `-j18` sweep peaked at **1.97 GB** across 10 processes |
| one file whose build HANGS | **real, and bounded** | `std/python/bindings.mojo` runs >850 s at a flat 0.06 GB. `-t 30` bounds it, and `subprocess.run`'s timeout was measured to leave no orphan. So it cannot hold the sweep open, but see `bugs/FORMAL_bindings_mojo_build_never_terminates.md` |
| two concurrent sweeps | **ruled out as the cause** | reproduced: an arm64 and an x86-64 sweep, `-j9` each, 320 files each, both complete |
| macOS jetsam | **the remaining candidate, unconfirmed** | jetsam events on this box are real and frequent, but every one in the last 24 h names `ReportCrash` with reason `per-process-limit`; none names a python process, and the sweep is not a plausible jetsam victim at 1.97 GB on a 137 GB box. The box was, however, running ~11 `opencode` workers at 1–3 GB, `FSEvents` at 6.5 GB, `lean` at 3 GB, and two `--dump-full` compiles (`mojoc fire.py --dump-full` in `work-integ`, and a `stage2/mojo --dump-full` reparented to launchd) — the last two are the 15–30 GB jobs in `bugs/CODEGEN_bootstrap_resource_blowup.md`, and swap was 11.3 GB of 12 GB used. **Whole-machine pressure from work that was not the sweep is the most likely story, and it is not a story about the sweep.** |

That last row is the honest answer: the sweep was a small process on a machine
that was under real pressure from something else, and it had no defence. Note
what is NOT in the table: nothing in this repository killed it.

## 2. Why the log could not say how far it got — the actual defect

`tools/formal_sweep.py` collected every verdict into a dict inside the
`ThreadPoolExecutor` block and printed the per-file lines in a loop **after the
pool drained**. So a run killed at file 600 of 623 produced an output file
identical to one killed at file 1: a header and nothing else. The 5-line header
is printed before any build starts; the first line that names a file is printed
after the last build finishes.

This is why "not one file was classified" is not evidence about the timing, and
it is why §1 has a `not established` in it. The instrument destroyed the one
piece of evidence that would have answered the question.

**Fixed.** Each row is printed as it is classified, with an explicit `flush=True`
— the flush is load-bearing, because a redirected stdout is a block-buffered
FILE and unflushed lines are lost exactly the same way. A `SIGINT`/`SIGTERM` now
drains cleanly, prints and publishes what it classified, and exits **3**;
a partial run publishes its ledger under its OWN extension (`.ledger.partial`)
so the next run's history diff is against the last COMPLETE run and an unreached
file is never reported as a verdict that changed.

## 3. Why one file could take the run down at all

The sweep launched `jobs` (= 18) `fire.py build` processes with **nothing
between any of them and the machine**: no per-file memory ceiling, no
reservation, and a build driver that recurses through a module closure. A single
unbounded child in a fan-out that wide is enough.

**Fixed.** Every build now runs under `tools/memcap.py` at a per-file ceiling
(`-M`, 4 GB default). A file that exceeds it is killed, classified
`tool`/`memory-killed` **with its measured peak**, and the sweep continues. It
is deliberately not a timeout under another name: the two share a class and need
opposite responses — a timeout says raise `-t`, a memory kill says this build is
a different shape and running it wider will not help.

The ceiling is the **shared** `memcap`, not a second process walk, and its
verdict is read through `procrun.memcap_verdict` rather than the exit code,
because exit 125 is also what a build that exits 125 by itself produces.

**How big the ceiling had to be is the measured part, and the answer is
"not big at all":**

| measured | value | how |
|---|---|---|
| worst single-file build, arm64 | **0.19 GB** | 89 files sampled individually, plus every file that passed on x86-64, plus the largest 30 by size |
| the 30 largest files | ≤ 0.07 GB each | same |
| whole `-j18` sweep, one process tree | **1.97 GB** across 10 procs | `procrun.tree_rss` sampled flat out |
| whole `-j18` sweep under `memcap --limit-gb 16` | 0.4 GB, "done" | the run completed; nothing was near the ceiling |
| whole `-j6` sweep under `memcap --limit-gb 16` | 0.4 GB, "done" | same |

So 4 GB is an order of magnitude above everything observed. It is here for the
file nobody has run yet, not to bound anything measured, and the honest
description of the 2026-10-01 kill is **not** "a file used too much memory" —
it is "the sweep had no bound, and the machine was under pressure from
elsewhere".

## 4. Also fixed, and it was a real defect in its own right

One sweep per **architecture** at a time, under an `flock`. Two same-arch sweeps
share the formal module-dylib output directory
(`~/.gmojo/cas/formal-imports/<arch>/`) and the ledger, and the manifests there
are **rewritten in place** — which is the mechanism behind
`bugs/FORMAL_dylib_manifest_written_in_place.md`, and behind the
`json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` rows
this sweep reports.

The key is the architecture and not the cache, because the owner's own
two-at-once run was an arm64 sweep and an x86-64 one and those two are
genuinely independent: separate dylib directories, separate cache keys,
separate ledgers. Refusing that pair would have refused a legitimate use.

## 5. Reproducing the fix, cheaply

```sh
# a file that blows the ceiling is classified and the sweep CONTINUES
python3 tools/formal_sweep.py -j4 -t 60 -M 0.02 <two files>
#   TOOL: …  (killed at the 0.02 GB per-file ceiling)
#   [arm64] 2 files: PASS=0 not-pass=2        <- both classified, run finished

# an interrupted run keeps what it classified, and says how much it reached
python3 tools/formal_sweep.py -j4 -t 60 -M 0.02 <40 files> & sleep 4; kill -TERM %1
#   …24 rows already on stdout, unflushed…
#   [arm64] INTERRUPTED: 25 of 40 files classified; the rest were not reached
#   exit 3
```

Both are in `test_formal_sweep.py` as unit tests (`TestPerFileMemoryCeiling`,
`TestResultsSurviveAnInterruptedRun`), so neither needs a heavy run to keep
fixed.
