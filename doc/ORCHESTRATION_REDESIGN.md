# Orchestration redesign: landing without a single blocking lock

Status: PLAN, 2026-11-20. Nothing here is implemented yet. Phase 1 needs the owner's go-ahead
because it changes what the live integrator does.

## 1. What is wrong, measured on 2026-11-20

- `tools/integrate.py` takes one `flock` on `.git/control/integrator.lock` for the whole round:
  merge, gate, confirm, fast-forward master (`main()`, lines ~645-820).
- The confirm step (`integrate.py` ~763) re-runs every red job alone, under that same lock. Pid 17157
  has held the lock for 2h13m and is still in its confirm (`work-integ/confirm.log`, "65/66 jobs done,
  1 running, 3303 s elapsed"). It is making no progress that matters: the six branches it merged have
  not landed, and every other landing waits behind it.
- The lock file is 0 bytes. Nothing records who holds it, which round, since when, or what it is
  running. `control.py ps` cannot tell a stuck round from a busy one.
- A round's own gate has no time bound. Nothing stops a confirm from running for hours.
- The full gate ran under the same lock in the old code path (`--stdlib` was the only cheap path).
  Removed on 2026-11-20 (landing = `gates.json` `landing` only), but the lock still covers the
  whole round.

Consequence: one stuck round stops every landing, and no operator can see why.

## 2. Target design

Split the round into the parts that need exclusion and the parts that do not.

| step | today | target |
|---|---|---|
| merge candidates | under lock, in `../work-integ` | in a **per-round** worktree `../work-round-<id>` |
| landing gate | under lock, in `../work-integ` | in the same per-round worktree, **no lock**: rounds gate in parallel |
| confirm re-run of reds | under lock, unbounded | in the round worktree, **bounded by a round deadline** |
| fast-forward master | under lock (the same lock) | under a **short** `master.lock` held only for `merge --ff-only` plus the re-gate-if-master-moved check |
| holder record | none (0-byte lock) | `integrator.lock` contains JSON: `{pid, round, started, deadline, tree}`, rewritten at each step |

Invariants:
1. Only one process moves master at a time (`master.lock`).
2. A landing is only ever the tree that was gated, or a tree re-gated after master moved in real files.
3. A round that exceeds its deadline is terminated by its own process group (never by name match,
   never another lane's pid), and its tasks are marked `integration-failed`, branches intact.
4. `control.py status` and `ps` show the holder from the JSON record: round, age, deadline, step.

## 3. Phases

**Phase 1 (smallest, unblocks landing; touches only `integrate.py`, `control.py status`):**
- Write the JSON holder record into `integrator.lock` at each step.
- Give each round a deadline (default 45 min, `--deadline`). The confirm re-run gets the remaining
  budget; on overrun the round kills its own children and marks its tasks `integration-failed`.
- `control.py status` prints the current holder (round, step, age, deadline).
- Test: a new `tools/test_integrate_deadline.py` that uses a fake gate command which sleeps past
  the deadline; the round must exit, mark the tasks `integration-failed`, and leave master untouched.

**Phase 2 (parallel rounds; touches `integrate.py`, `swarm.py` probe):**
- Per-round worktrees; `master.lock` for the fast-forward only.
- `swarm.py`'s `probe()` and `find_culprit()` already re-run merges; they gain the per-round tree.
- Test: two concurrent `--probe` runs on disjoint branches both report GREEN without touching each
  other's worktree.

**Phase 3 (out of scope here):** `verify_landed.py` stays as is (full gate, off the landing path,
its own `verify.lock`).

## 4. Decisions the owner must make

1. Phase 1 changes the live integrator's behaviour. Is it acceptable to rewrite `integrator.lock`
   contents while pid 17157 is still running? (Plan: the new record is only written by the new code,
   so the running process is unaffected until it exits.)
2. Deadline default: 45 minutes per round? The cheap landing gate takes about 36 s, so a round that
   takes 45 minutes is stuck, not slow.
3. Should a deadline overrun kill the round's children with SIGTERM (plan) or only mark the round and
   leave the processes (safer, slower to clear)?

## 5. Verification (per phase)

- `python3 -I tools/test_integrate_*.py` and the swarm tests named in the phase.
- `compile_stdlib.py` stdlib-syntax step (the landing gate) once, at the end of the phase.
- No full `make gate` by agents (CLAUDE.md, verification policy).
