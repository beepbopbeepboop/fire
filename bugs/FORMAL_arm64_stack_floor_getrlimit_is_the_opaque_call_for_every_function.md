# The arm64 stack-floor guard's `getrlimit` is now the ONE opaque call in every
# function, so the arm64 proof corpus has no value theorem left

**Area:** FORMAL, arm64 proof layer — `formal/arm64_codegen.py::_emit_stack_floor_guard`'s
`getrlimit` `BL`, seen by `formal/arm64_proof_gen.py::_unfollowable_calls` and
the `_opaque` arm (and, one level over, by `_reached_without_a_condition`).
**Status: OPEN, measured 2026-10-07 (`work/formal104-docs`), while working a
different bug.** This is a REGRESSION, not a long-standing limit, and it is the
dominant cause of the arm64 corpus's refusals. It is the same mechanism
`bugs/FORMAL_one_opaque_flush_silently_replaces_the_universal_theorem.md`
documents for `_emit_exit`'s `fflush` — but the `fflush` is only on programs that
exit, while this call is in EVERY prologue, so it moves that doc's "0 opaque
calls → `f_compiles_correctly_universal`" row out of reach for the whole corpus.

## What was measured

Generation only (`prove=True, check=False`, no Lean), all 93
`formal/examples/*.mojo`, arm64:

| what the generator did | files | example |
|---|---:|---|
| generated — `f_reaches_call_at_…`, no value theorem | **29** | `ret42.mojo` |
| REFUSED — "the halt address … is behind a CONDITIONAL" | **35** | `absval.mojo` |
| REFUSED — "2 calls this walk cannot follow … OUT OF THE IMAGE" | **11** | `augassign_floordiv.mojo` |
| REFUSED — another model gap (unrelated) | 18 | `accum_max.mojo` |
| generated — `f_compiles_correctly_universal` (a value theorem) | **0** | — |

**Not one example has a value theorem any more**, and 75 of 93 are refused or
downgraded by this one call. The 29 that generate are exactly the straight-line
programs; every program with a source conditional is in the refused group.
Before `bfeec991` ("formal: derive the stack guard's budget from the process's
real RLIMIT_STACK", 2026-10-05) the guard compared a compile-time constant and
emitted no call at all; the doc above measured `either`'s proof at 4306 lines
with a real `either_compiles_correctly_universal`.

The image says it plainly — `either.mojo`, entry `0x1000003d4`, end `0x100000878`:

```console
$ python3 -c "…fb.compile_formal('formal/examples/either.mojo', arch='arm64', prove=False…)"
extern_calls = [{'sym': 'getrlimit', 'addr': 0x10000041c}]     # 4294968348
compiler_traps = []                                            # NOT recorded
cond_branches = [0x100000500]
```

`0x10000041c` is `bl getrlimit` in the prologue, behind the guard's own
`cbnz x16, …` cache test (otool: `10000041c bl 0x100000878`). On a straight-line
program the generated proof contains `f_reaches_call_at_0x10000041c` and NOT
`f_compiles_correctly_universal`; `_opaque` is that call, so the walk halts
there and `concrete_test` is replaced by the "NO CONCRETE RUN TEST" comment.

**Why it is not just the `_reached_without_a_condition` check.** `2b7e5ec8`
turned the conditional-program cases into refusals, but the theorem was already
gone: `bfeec991` alone makes the value theorem unreachable, because `arm64_step`
cannot step a `BL` whose target is outside `code`, so the model halts at
`getrlimit` whatever `_opaque` is set to. Dropping `getrlimit` from
`_unfollowable_calls` would emit a `f_compiles_correctly_universal` that is FALSE
(the run never reaches the sentinel). So the call has to leave the walked path;
it is not a filter bug.

**Why `compiler_traps` is empty here.** `38880520` records `_emit_exit`'s flush in
`info["compiler_traps"]` so `_program_extern_calls` subtracts it, but the stack
guard's `getrlimit` is a DIFFERENT compiler call and is recorded nowhere.
Subtracting it by the same mechanism would not help either: unlike the trap
flush, the run must PASS this call, and the model cannot.

## A second, separable defect this exposed

`_reached_without_a_condition` refuses 35 programs whose `getrlimit` is in the
PROLOGUE, before any source conditional — `absval.mojo`'s `if n > 0:` is at
`0x100000500`, after the `bl` at `0x10000041c`. The BFS returns `False` the
moment it DEQUEUES a block whose terminator is a source conditional, without
asking whether the pc was already reached in an earlier block, so any program
with a source `if` is refused even though the halt call precedes it. That is a
bug in the check independently of `getrlimit`: the correct question for the
"one opaque call" arm is whether the call is on EVERY path (post-dominates the
entry), not whether some condition-free path exists, and neither is "a source
conditional is reachable somewhere". Fixing it alone would turn those 35 into
reach theorems; it would NOT restore a value theorem, which is the `getrlimit`
half above.

## The exact next step

**Move the `RLIMIT_STACK` read out of the prologue into the startup stub, which
is exactly what x86-64 already does.** `formal/x86_64_codegen.py::_emit_stack_floor_init`
reads the limit once before `main` and caches it, so the x86-64 prologue is a
load and a compare with no call, and `_program_externs` drops the stub's
`getrlimit` because its address is BELOW `func_offset`. The arm64 twin is:

1. emit the `getrlimit` read (and the `__DATA` limit cache) in
   `compile()`'s startup stub, beside the entry-argument materializers, for an
   image that has an entry;
2. leave `_emit_stack_floor_guard` as the load-and-compare it already is, with
   the getrlimit fallback removed for the `emit_startup` case (a LIBRARY has no
   stub, so its first guarded prologue still needs the read — the same asymmetry
   x86-64 has);
3. the guard's arithmetic is unchanged (`stack_floor_budget_for_limit` /
   `stack_floor_charge` take the cached limit, not a syscall result).

The anti-rot is `formal/examples/either.mojo` regenerating with a
`theorem either_compiles_correctly_universal` (the doc above's own after-table
row), plus `formal/examples/mod_by_var.mojo` still taking the ordinary run-test
path. `test_formal_call_proof_gen.py`'s `TestTheBranchFlagLemmaIsTheBranchOwns`
is red for exactly this reason on this tree (its EQUALITY shape is refused with
"the call … is behind a CONDITIONAL") and will be green once `getrlimit` is off
the path.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label gen -- python3 - <<'PY'
import sys, os, re
sys.path.insert(0, os.getcwd()); import formal.build as fb
for p in ('formal/examples/ret42.mojo', 'formal/examples/absval.mojo'):
    try:
        r = fb.compile_formal(p, arch='arm64', output='.tmp/g.aout',
                              prove=True, check=False)
        t = open(r['proof_path']).read()
        print(p, 'value' if re.search(r'^theorem \w+_compiles_correctly_universal',
                                      t, re.M) else 'NO VALUE THEOREM',
              'reach' if re.search(r'^theorem \w+_reaches_call_at_', t, re.M) else '')
    except Exception as e:
        print(p, 'REFUSED', str(e)[:110])
PY
# formal/examples/ret42.mojo  NO VALUE THEOREM reach
# formal/examples/absval.mojo REFUSED … the halt address … is behind a CONDITIONAL
```
