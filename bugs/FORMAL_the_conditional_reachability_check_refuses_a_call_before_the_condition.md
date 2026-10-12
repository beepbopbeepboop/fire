# FORMAL_the_conditional_reachability_check_refuses_a_call_before_the_condition

**Status: NOT FIXED — filed 2026-10-07 by `work/formal119-docs`, found while
running the narrow suites for `FORMAL_proof_coverage_census_2026-10-03.md` and
`FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment.md`. Both of
those docs' pins are RED on this tree and this is why. The code is another
claim's (`_reached_without_a_condition` was added by `2b7e5ec8`, the subject of
`FORMAL_integer_overflow_at_run_time_is_still_untrapped.md` and
`FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`), so it
is filed rather than edited.**

Two distinct root causes, both measured, both in the arm64 proof path.

## 1. `_reached_without_a_condition` answers "is a source condition reachable",
## not "is `pc` reachable WITHOUT crossing one"

`formal/arm64_proof_gen.py:6590`'s docstring states the question: *"Whether `pc`
is reachable from `func_entry` on a path that crosses no SOURCE conditional."*
The body is a BFS, and its source-conditional arm is

```python
        elif block["kind"] == "cbz":
            if cond_branches and block["instrs"][-1] in cond_branches:
                return False           # a SOURCE condition sits on the path
```

`return False` fires the moment the traversal ENTERS a source-conditional block
— whichever path reached it, and whether or not `pc` is beyond it. Since the
walk explores every non-source branch (both edges of an emitter-internal
`cbz`), it always eventually reaches the program's source conditional and
refuses, even when `pc` is on the straight-line path BEFORE it.

Measured on `formal/examples/count.mojo` (arm64), whose only opaque call is the
stack-floor guard's `getrlimit`:

```
$ python3 -c "import formal.build as fb; r = fb.compile_formal(
      'formal/examples/count.mojo', output='.tmp/c.aout', arch='arm64',
      prove=False, check=False); print(r['info']['extern_calls'],
      r['info']['cond_branches'])"
[{'sym': 'getrlimit', 'addr': 4294968348}]   # 0x10000041c, the guard's call
[4294968532]                                 # 0x1000004d4, the `if n == 0`
```

`getrlimit` at `0x10000041c` is before the conditional at `0x1000004d4`, so the
run reaches it whatever `n` is and the answer must be `True`; the function
returns `False` (instrumented call on this tree), so `count` refuses with

```
universal theorem: the call at 0x10000041c -> 0x10000086c is the halt address,
and it is behind a CONDITIONAL, …
```

`wdiff`, and the whole recursion family (`fact`, `pow2`, `sqsum`, `sum`, `sgt8`,
`sle8`, `ug8`, `both`, `either`) refuse identically.

### The fix

A source conditional's OWN branch pc is reached whatever the data — only its
SUCCESSORS depend on it. So when the traversal reaches a source-conditional
block, mark it reached (as the code already does above the branch) and do NOT
enqueue its successors, instead of returning `False`:

```python
        elif block["kind"] == "cbz":
            if cond_branches and block["instrs"][-1] in cond_branches:
                # Reached, so a `pc` IN this block is on a condition-free path;
                # which successor runs is the fact about the data, so neither
                # edge is followed. Do not return False: the block being
                # reachable is not the same as `pc` being behind it.
                continue
            queue.extend(t for t in block["targets"] if t is not None)
```

Then `return any(pc in b["instrs"] …)` is the right answer: `True` iff `pc` is
in a block reachable without crossing a source conditional. This keeps both of
`2b7e5ec8`'s measured controls correct — `if n > 100: printf("hi"); return 0`
still refuses (the `printf` block is a successor of the conditional), and
`printf("hi"); return 0` still proves.

## 2. The stack-floor guard's `getrlimit` is not a `compiler_trap`, so a
## one-`print` program is a "two opaque calls" program

`formal/arm64_codegen.py`'s `_emit_stack_floor_guard` calls `getrlimit(2)`
lazily and caches the result in a module global. That `BL getrlimit` is a
COMPILER-own call the run reaches, but it is not recorded in
`info["compiler_traps"]` (which holds only `_emit_exit`'s `fflush`), and
`generate_arm64_proof`'s `_calls = _unfollowable_calls(...)` does not subtract
compiler traps at all (that subtraction exists only in
`_program_extern_calls`, for the run test).

So a program with ONE real call has TWO opaque calls:

```
$ python3 -c "…compile_formal('def main(x):\n    y = x * 3\n    print(y)\n
    return y\n', prove=True, check=False)…"
# info['extern_calls'] = [{'sym': 'getrlimit', 'addr': 0x10000041c},
#                         {'sym': 'printf',    'addr': 0x100000500}]
# info['compiler_traps'] = []
universal theorem: 2 calls this walk cannot follow (0x10000041c ->
0x100000870 (opaque), 0x100000500 -> 0x10000087c (opaque)), every one of them
OUT OF THE IMAGE, and ONE halt address cannot discharge them.
```

That is why `test_formal_proof_breadth.py::test_a_census_that_does_not_ask_lean_
says_so` is RED: its fixture is exactly this program and it expects
`proof-emitted`, which it got before the stack-floor guard grew the `getrlimit`
call. **Fix 1 alone does not clear this row** — the two-call refusal at
`arm64_proof_gen.py:11099` runs before the reachability check.

## What is red because of these, measured 2026-10-07

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_breadth.py
Ran 26 tests … FAILED (failures=1)
FAIL: test_a_census_that_does_not_ask_lean_says_so
      AssertionError: 'proof-refused' != 'proof-emitted'

$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 -m unittest test_formal_call_proof_gen.TestTheRecursionFamiliesStillGenerate
Ran 3 tests … FAILED (failures=12)   # count/fact/pow2/sqsum/sum/sgt8/sle8/ug8/both/either
```

`2b7e5ec8`'s own message claims the 52-example corpus regenerates to the same
verdict; it does not any more, and fix 1 is the correction to the question it
asked.

## The exact next step

1. Apply fix 1 (§1), then re-run
   `test_formal_call_proof_gen.TestTheRecursionFamiliesStillGenerate` — the
   eleven should generate again and `sum_range` should be back to its owned
   loop-contract refusal.
2. Decide fix 2 with the stack-floor guard's owner: either record the guard's
   `getrlimit` address in `info["compiler_traps"]` AND subtract compiler traps
   from `_calls` at `arm64_proof_gen.py:11067`, or model `getrlimit` so the
   guard is not opaque. **Subtracting it is not obviously safe** — unlike
   `_emit_exit`'s `fflush`, the run genuinely reaches `getrlimit` on the
   straight-line path, so the universal theorem's halt address moves and the
   `_gen_extern_test` substitution has to move with it. That is why this half
   is a decision, not a patch.
