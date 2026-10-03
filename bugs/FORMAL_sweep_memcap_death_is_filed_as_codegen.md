# FORMAL_sweep_memcap_death_is_filed_as_codegen: a build whose wrapper died is published to the CAS as a backend gap

**Status: FIXED in full, and the doc goes with the fix — in two parts, four days
apart.**

* **`6febd26e`** — the MISCLASSIFICATION. A build whose memcap wrapper died is
  `tool`/`wrapper-died` with no verdict about the source, and is not published.
* **`d5c1a3e7`** — **WHAT KILLED THE WRAPPER**, which this doc recorded as
  unestablished. It is now established two ways: the one signal class that could
  produce the silent state has been **removed** (memcap handles SIGTERM and
  SIGINT: it takes its tree down, prints `interrupted`, and exits 143/130), and
  what is left is a SIGKILL, which the `tool` row now **names** — read off the
  wrapper's own exit status — together with the only thing in this repository
  that sends one (`tools/control.py guard`).

Everything below is the original report, kept because it is what made the fix
legible: the effect, the evidence, and the table of three states that turned out
to be four.

---

**Class:** instrument defect (`tools/formal_sweep.py` + `tools/procrun.py` +
`tools/memcap.py`).
**Effect:** a machine fact entered the `codegen` class — the class whose count is
a gap in the backend, the class that fails a run, and the class
`tools/formal_sweep_causes.py` ranks — **and was written to the CAS**, so every
later sweep replayed it until the cache key changed. **Seen:** 6 files per
architecture in the `-6` sweep of 2026-10-02 (§"What was run").

## What was run

Three sweeps of this repository + the stdlib on 2026-10-02, all with the
per-file memory ceiling on (`-M`, default 4 GB), logs in
`bugs/sweeps/sweep-{arm,x86}-6.txt` and in the predecessor's tree as described in
`bugs/FORMAL_sweep_work_map_2026-10-02_b6.md` §1.

## What was seen

Six lines per architecture, of class **`codegen`**:

```
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/__init__.mojo        (memcap: __init__.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/bit.mojo             (memcap: bit.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/mask.mojo            (memcap: mask.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/_format_float.mojo (memcap: _format_float.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/_startup.mojo     (memcap: _startup.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/anytype.mojo      (memcap: anytype.mojo -- ceiling 4.0 GB across the process tree)
```

**The same files get real verdicts in the other architecture's run**, which is
what makes this a fact about the machine rather than about the files: diffing the
two arms' classified lines gives 10 file/architecture pairs where exactly one arm
produced a `memcap:` row, including `bit/mask.mojo` as a `memcap` row on arm64
and a real `codegen/dependency` verdict on x86-64 **in the same run, minutes
apart**.

**The files are not memory hogs.** Same tree, same flags, same 4 GB ceiling:

```
$ time GMOJO_HOME=$PWD/.tmp/gmojo-exp python3 tools/memcap.py --limit-gb 4 \
    --label mask.mojo -- python3 fire.py build --formal --no-prove \
    --backend=arm64 -o .tmp/exp-mask.bin ../new-modular/Mojo/stdlib/std/bit/mask.mojo
real 3m37.9s   user 0m56.0s   sys 0m15.8s
memcap: mask.mojo -- ceiling 4.0 GB across the process tree
memcap: done, peak 0.1 GB across up to 1 procs (ceiling 4.0 GB), child exit 1
```

## Why the silent-death fallback is not the answer here

`tools/formal_sweep.py`'s silent-death fallback is sound for what it was written
for: no traceback is no evidence of a crash. The gap was that "no message" is not
one state. It is three:

| what the output holds | what happened | class it deserves |
|---|---|---|
| the build's own refusal | the backend refused a construct | `codegen` (correct) |
| `memcap: BREACH …` | the ceiling fired | `tool`/`memory-killed` (correct) |
| `memcap: <banner>` and nothing else | **the wrapper died before it could account for the run** | `tool`, cause of its own — misfiled as `codegen` |

## Part 1 — the misclassification (`6febd26e`)

* `procrun.memcap_wrapper_died` is a sibling predicate beside `memcap_verdict`,
  sharing ONE definition of "memcap reported an outcome" (`memcap_accounted`)
  with the breach reader rather than adding a second parser;
* `BuildRun` gained a `wrapper_died` field, and the branch fires only when the
  BUILD printed nothing either, so a build that refused a construct and then had
  its wrapper killed still reports the refusal;
* the same branch stops a silent death's `detail` from being memcap's
  `done … child exit -9` line, and the class is deliberately unchanged (the
  silent-death fallback is a documented choice; the fix is about not putting the
  wrapper's bookkeeping in the file's mouth).

## Part 2 — what killed the wrapper (`d5c1a3e7`)

The original report was careful not to conclude: `tools/control.py guard` was
"a candidate, not a conclusion". Two facts make it a conclusion now, and the
second one means nobody has to reproduce a machine failure to see it.

**The state is no longer reachable by any signal memcap can catch.** memcap had
no SIGTERM handler, so its default action skipped every line it prints — and left
the workload running unmonitored, which is the exact failure the ceiling exists
to prevent. That is the second-order cost, and it is the one that mattered: a
wrapper killed by TERM orphans the build it was watching. `tools/control.py reap`
sends `os.killpg(pid, 15)` and `os.kill(pid, 15)`, so a sweep in a finished
worker's tree was a candidate for exactly this, and so was any operator's
`kill -TERM`. Now:

```
$ python3 tools/memcap.py --limit-gb 4 --label fg -- python3 slow.py &   # then kill -TERM
memcap: fg -- ceiling 4.0 GB across the process tree

memcap: interrupted by signal 15, killing fg -- nothing below this wrapper is
left running, and this run was NOT accounted for by any ceiling
$ echo $?   ->  143
```

and `procrun.memcap_accounted` recognises that line, so `memcap_wrapper_died` is
False for it. The outcome WORD is `interrupted` and not `terminated`, because
`memcap_accounted` reads a set of words and a word outside it would have left a
signalled wrapper still reading as a silent one.

**What is left is a SIGKILL, and the row says so.** The wrapper's own exit status
answers the question this doc could not:

```
the 4 GB per-file wrapper (tools/memcap.py) died before it reported an outcome —
killed by SIGKILL, which nothing here can catch: in this tree that is
tools/control.py guard, aimed at the largest process in a worker worktree once
the tree's RSS sum passes its budget — so its banner is in the output with no
breach and no completion …
```

Which is checkable against this repository rather than asserted: `control.py`
guard is the only code that aims a SIGKILL at a process by name
(`tools/control.py:381`, `os.kill(pid, 9)`), `tools/control.py reap` and
`tools/autointegrate.py` both use 15, memcap's own group kill happens after it
has printed `BREACH`, and the sweep's other kill (`procrun.kill_group`) is on the
timeout path, which raises `TimeoutExpired` and so never reaches this branch. The
row also refuses to name a cause it does not have: a wrapper that exited without a
signal says so instead of claiming the guard.

**Three cases in `TestWrapperDied`** (plus the five from `6febd26e`): the row
names SIGKILL and the guard for `-9`, names the signal and NOT the guard for
`-15`, and declines to invent a cause for a positive exit code; and one case runs
the real `tools/memcap.py` binary, sends it a SIGTERM and asserts all three
things the silent-death reader depends on — an outcome `memcap_accounted`
recognises, exit 143, and **the workload gone** (polled, because it is reparented
to init when it dies). `test_formal_sweep.py`: 95 tests OK.

## The cost of the fix, which the reader should not have to rediscover

`tools/formal_sweep.py`'s own bytes are in every cache key (`_criteria_id`), so
the classification change invalidated the CAS for every sweep on the machine and
the next sweep rebuilt. That is the tool working as designed — a rule change must
take effect — and it is the price of the fix.

Until this landed, a reader of any sweep log should treat a `codegen` line whose
detail starts with `memcap:` as a `tool` row, and should know that the CAS was
serving it as a finding.