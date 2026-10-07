# FORMAL: the arm64 compiler-trap recording is LOST (merge `b578b915`) and the stack guard's `getrlimit` is not a trap either — so every arm64 universal theorem stops at `0x10000041c`

**Area:** FORMAL, arm64 only.
`formal/arm64_codegen.py` (`_emit_exit`'s `fflush`, `_emit_stack_floor_guard`'s
`getrlimit`), `formal/arm64_proof_gen.py` (`_program_extern_calls`, the universal
walk's `_unfollowable_calls`), and
`test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall`.

**Status: OPEN, measured 2026-10-07 on master (`8df5b273`), NOT FIXED.** Two
independent defects, both arm64-only, both in the "the COMPILER's own call is
being read as the PROGRAM's" family, and together they make arm64 proof
GENERATION refuse outright for most of `formal/examples` and reduce the rest to a
reachability of the compiler's own `getrlimit`. **None of it is visible to the
gate**: every test that would see it lives in the `proofs` bucket (or is the
`TestTheZeroDivisorGuardAgainstLean` class that skips without a built library),
and `make gate` does not run `proofs`. Filed rather than fixed because the
proof-walk half is `formal108`'s
(`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`)
and the stack-guard half is `formal114`'s, and a light worker may not run the
Lean-checking suites that would verify an emitter change.

## 1. `_emit_trap_flush` from `38880520` is not in HEAD — a merge dropped it

`38880520` ("formal/arm64: a COMPILER's own trap flush is not a call the PROGRAM
makes") added `_emit_trap_flush` and made `_emit_exit` call it, so the `BL
fflush` inside every bounded stop is recorded in `_compiler_trap_addrs` and
published as `info["compiler_traps"]`. It is an ancestor of HEAD, yet:

```console
$ git show HEAD:formal/arm64_codegen.py | grep -c _emit_trap_flush
0
$ git log -S '_emit_trap_flush' --oneline -- formal/arm64_codegen.py
38880520 formal/arm64: a COMPILER's own trap flush is not a call the PROGRAM makes
```

The commit that dropped it is the merge `b578b915` ("Merge branch
'work/formal51-docs'"), whose two parents disagree and whose result took the
side without it:

```console
$ git log -1 --format='%h parents=%p %s' b578b915
b578b915 parents=0bf1d79f ff5ef230 Merge branch 'work/formal51-docs' into work/merge-formal5b-r2-r2-r2-r2
$ for p in 0bf1d79f ff5ef230; do \
    echo "$p: $(git show $p:formal/arm64_codegen.py | grep -c _emit_trap_flush)"; done
0bf1d79f: 0
ff5ef230: 2
```

**The two SURROUNDING hunks survived and the middle one did not**, which is what
makes this silent: the field is still declared and the publication is still
there, so the tree advertises a list that nothing can ever fill.

- `formal/arm64_codegen.py:724` — `self._compiler_trap_addrs: set = set()` (present)
- `formal/arm64_codegen.py:1100` — `"compiler_traps": sorted(self._compiler_trap_addrs)` (present)
- `_emit_trap_flush` and its call site — **gone**; `_emit_exit` is back to the
  pre-`38880520` inline `self._emit_call(F.CallExpr(func=… "fflush" …))`, and
  `_compiler_trap_addrs` is never written by anything.

Consequence: `info["compiler_traps"]` is `[]` for every arm64 image, so
`formal/arm64_proof_gen.py::_program_extern_calls` subtracts nothing, and
`test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall`'s arm64 rows
have been red since the merge (see §4).

## 2. the stack-floor guard's `getrlimit` is a compiler call that is not a trap

`bfeec991` ("derive the stack guard's budget from the process's real
RLIMIT_STACK") put `self._emit_extern_call("getrlimit")` into
`_emit_stack_floor_guard` (`formal/arm64_codegen.py:1962`), the guard that is now
in every prologue. That call is the COMPILER's — it reads `RLIMIT_STACK` once per
process and caches it in `__DATA` — but it lands in `extern_calls` and is not in
`compiler_traps`.

x86-64 has the same `getrlimit` and handles it in `_program_externs` by ADDRESS
against `func_offset` (`formal/x86_64_proof_gen.py:703-716`), because x86-64
emits the guard in a STARTUP STUB below the entry. **arm64 emits the guard in the
PROLOGUE, above the entry and inside the walk's `[func_entry, func_end)`, so that
filter cannot reach it**, and the walk sees the compiler's `getrlimit` as an
opaque call of the program.

## 3. What is measured on master, arm64, `prove=True, check=False`

Every line below is a generation run (`check=False`), so no Lean is involved:

| program | result |
|---|---|
| `formal/examples/count.mojo` | **refused**: `universal theorem: the call at 0x10000041c -> 0x10000086c is the halt address, and it is behind a CONDITIONAL …` |
| `formal/examples/sum.mojo` | **refused**, same, `-> 0x100000880` |
| `formal/examples/fact.mojo` | **refused**, same |
| `formal/examples/mod_by_var.mojo` | **refused**: `2 calls this walk cannot follow (0x10000041c -> 0x100000890 (opaque), 0x100000518 -> 0x100000884 (opaque)) …` |
| `def main(n): return 7` | **generates, but the universal theorem is GONE**: `extern_calls=[getrlimit@0x10000041c]`, `compiler_traps=[]`, no `…_compiles_correctly_universal`, and the only universal is `main_reaches_call_at_0x10000041c` |

`0x10000041c` is `4294968348`, the prologue's `getrlimit` (`otool -tv` on the
same image shows `bl` to the `getrlimit` stub there). So the compiler's own
`RLIMIT_STACK` read is the halt address of the universal theorem, which means a
program that computes correctly gets a theorem that says only "control reached
the stack guard", and a program with one more real call (or a conditional guard
path) is refused before a proof exists. **Before `bfeec991` every one of these
had a `_compiles_correctly_universal`; the guard's `BL` is what removed it.**

## 4. The four registered red rows

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py TestCompilerTrapIsNotAProgramCall
Ran 10 tests … FAILED (failures=4)
  FAIL: test_a_program_whose_only_unbound_call_is_a_trap_gets_its_run_test
  FAIL: test_a_recorded_trap_is_the_bl_and_not_the_instruction_before_it
  FAIL: test_arm64_needs_no_trap_list_and_keeps_its_run_tests
  FAIL: test_arm64_publishes_its_exit_flush_as_a_compiler_trap
```

The first, second and fourth need the `divisor` fixture (`n % d`) to BUILD, and
it refuses in §3; the third asserts `plain`'s `extern_calls` is `[]` and it is
now `['getrlimit']`. `test_formal_call_proof_gen.py` is registered as
`formal-call-proofgen` in the `proofs` bucket, so none of this reaches `gate`.

**And the same regression has made `test_formal.py`'s expectations stale.**
`test_formal.py` is also `[proofs]`-only, and its `EXPECTED_FAILURES` table
attributes the "2 calls this walk cannot follow" refusal of `floordiv`/`udivmod`
to "`//` and `%` each lower to a call to the SAME divide-and-correct helper"
(quoting addresses `0x10000046c`/`0x1000004d8`, which are not the addresses on
this tree). The two calls the walk actually cannot follow for a division are
`0x10000041c` (the guard's `getrlimit`) and `0x100000518` (the arm's `fflush`) —
the compiler's own two, not the program's. Worse, `sum` and `fact` are not in
`EXPECTED_FAILURES` at all and now REFUSE at generation (§3), and `count`'s entry
says "tree recursion whose return frame reads x30 back", which is a Lean-time
reason for a stem that no longer reaches Lean. So a `proofs` run over the corpus
would be red on `sum`/`fact` and mis-reasoned on `count`/`floordiv`/`udivmod`
until this is fixed.

## 5. Why the fix is the recording AND the walk, and in that order

Restoring `_emit_trap_flush` (fflush recorded) is necessary and **not
sufficient**, and recording `getrlimit` too is necessary and still not
sufficient. Measured with hand patches, both reverted before this doc was
written:

* **restore `_emit_trap_flush` alone**: `info["compiler_traps"]` becomes
  `[fflush@0x…518]` for `mod_by_var`, `_program_extern_calls` drops it, and the
  CONCRETE half is right — but the universal half still sees `getrlimit` +
  `fflush` as two opaque calls and refuses, so the `divisor` fixture still does
  not build and the four rows stay red.
* **restore it and record the guard's `getrlimit` too**: `_program_extern_calls`
  is now `[]` for both `plain` and `mod_by_var` (both calls are the compiler's),
  which is what §4's rows want — but the universal walk still counts the two
  `BL`s from the raw bytes and refuses (or, if they are filtered out of
  `_unfollowable_calls`, hits a THIRD wall: `recursion contract: the call in
  block 2 has to be below the source condition's negation`).
* **filter `compiler_traps` out of `_unfollowable_calls`** is what
  `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md`
  option 1 asks for, and this is the measurement that corrects it: it does not
  reach the div0 residual, it reaches the conditional-call refusal. The walk
  needs a terminal proposition for a compiler call (which is not the program's)
  that is not "the run halts here and proves nothing" — the disjunction
  `…_the_walk_cannot_discharge_a_call_on_a_conditional_path.md` owns.

## 6. Exact next step

1. **Restore the recording** (`git show 38880520 -- formal/arm64_codegen.py`) and
   **record the guard's `getrlimit`** beside the exit flush. Both are the
   emitter half, both arm64-only, and neither should move any emitted byte of
   code (the calls are already emitted; this only records their addresses). The
   test is `info["compiler_traps"]` containing the `fflush` — and, once the
   guard's `getrlimit` is recorded, the `test_arm64_publishes_its_exit_flush_as_a_compiler_trap`
   assertion that "every published trap is an `fflush`" must be widened, because
   `getrlimit` is a second compiler call.
2. **Then the walk half**, which is `formal108`'s: `_unfollowable_calls` must not
   count a compiler trap as a program call, and the universal theorem must still
   have a terminal for it. Until that lands, (1) restores only the contiguous
   run tests and the `divisor` fixture still refuses.
3. Update `test_arm64_needs_no_trap_list_and_keeps_its_run_tests` — it asserts
   `plain`'s `extern_calls` is empty, which stopped being true when `bfeec991`
   put `getrlimit` in every prologue; it should assert the `getrlimit` is
   published as a compiler trap instead.
4. Re-run `test_formal_call_proof_gen.py` (generation only, no Lean) and the
   `proofs` bucket's `formal`/`formal-call-proofgen` once the emitter and walk
   halves are both in.

**Anti-rot:** the `formal/examples` generation census is the check. `count`,
`sum` and `fact` generated a proof before `bfeec991` and do not now; a fix is
done when they generate a `_compiles_correctly_universal` again and `plain` has
one too.
