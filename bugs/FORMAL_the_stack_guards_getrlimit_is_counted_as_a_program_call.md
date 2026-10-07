# FORMAL_the_stack_guards_getrlimit_is_counted_as_a_program_call: every arm64 program that calls a C function now refuses the universal theorem

**Area:** FORMAL / proof generation — `formal/arm64_codegen.py`'s
`_emit_stack_floor_guard` and `formal/arm64_proof_gen.py`'s `_calls` /
`_opaque` selection. **Status: NOT FIXED.** Found 2026-10-06 while
re-measuring `TestTheRecursionFamiliesStillGenerate` (the pin the
`FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment.md` doc
names).

## What I ran

```console
$ python3 - <<'EOF'
import os, sys, tempfile, shutil
sys.path.insert(0, os.getcwd())
import test_formal_call_proof_gen as T
tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "x.mojo")
open(src, "w").write('def main(n):\n    printf("hi")\n    return 0\n')
try:
    T._compile(src, os.path.join(tmp, "x.aout"), "arm64")
    print("GENERATED")
except Exception as e:
    print(str(e))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
EOF
```

## What I saw

```
universal theorem: 2 calls this walk cannot follow
  (0x10000041c -> 0x100000834 (opaque), 0x1000004cc -> 0x100000840 (opaque)),
every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge
them. ...
```

The first call is `getrlimit`, emitted by the stack-floor guard that
`bfeec991` ("derive the stack guard's budget from the process's real
RLIMIT_STACK") added to **every** arm64 prologue; the second is the program's
own `printf`. The generator counts BOTH as program calls and refuses with its
"a second unfollowable call has paths of its own" rule, so a program that calls
any C function now has no universal theorem.

`TestCallProofs::test_a_call_containing_program_generates_a_proof` and the ten
`GENERATE` rows of `TestTheRecursionFamiliesStillGenerate` are red for this
reason (the loop examples `wdiff`/`sum_range` refuse earlier, in the loop
contract, because `exit_at` is the guard's low address — see below).

## What I expected

The guard's `getrlimit` is a call the COMPILER makes, not the program. The
proof layer already has the vocabulary for that: `formal/arm64_codegen.py`
publishes `info["compiler_traps"]` and
`formal/arm64_proof_gen.py::_program_extern_calls` subtracts it from the run
test's call list (the arm64 twin of x86-64's `_program_externs`). The universal
theorem's `_calls`/`_opaque` boundary must subtract the same set, so the halt
boundary is a call the PROGRAM makes.

## Why it is not a one-line subtraction (measured)

I tried exactly that — publish the `getrlimit` BL's address and subtract it
from `_calls` — and it does not work, for a reason worth writing down so the
next reader does not re-try it: **the walk cannot step a returning extern
call.** With the `getrlimit` filtered out, `_opaque` becomes the program's
`printf`, and to reach it the walk must traverse the `getrlimit` `BL` first.
`_gen_universal_e2e_cfg`'s `bl` arm handles only a call into the SAME image
(`_is_intralocal`) and otherwise falls into the RECURSION arm, so a returning
extern call anywhere before the halt raises

```
recursion contract: the call in block 2 has to be below the source condition's
negation (`u64_sub_one_to_le` needs it), and this walk reached the call with no
enclosing branch condition to take it from
```

Measured on `def main(n): printf("hi"); return 0` with the subtraction in
place. So the fix is one of:

1. **teach the walk's `bl` arm to step a returning extern call** the way
   `_gen_extern_test` already models one (step the `BL`, continue from
   `{pre with pc := bl+4}`), and then subtract the compiler's calls from
   `_calls`; or
2. **keep the guard's `getrlimit` as the halt boundary** (the theorem "the run
   reaches `getrlimit`" is TRUE — the guard runs on the first call) and make
   the "second call" rule and the loop contract agree with that: relax
   `len(_calls) > 1` when the first call is unconditionally reached, and bound
   `_gen_countdown_loop`'s body/exit walk by the function end rather than by
   `exit_pc`.

Option 1 is the one consistent with `_program_extern_calls` and with the run
test, and it is what the fix should be; option 2 is the smaller patch but
leaves the loop contract's `exit_pc` (the run terminal) equal to a prologue
address.

## The second, independent regression this is sitting on

`git show 38880520:formal/arm64_codegen.py` has `_emit_trap_flush`, which
records each `_emit_exit`'s `BL fflush` into `_compiler_trap_addrs` so
`info["compiler_traps"]` is non-empty on arm64. On this tree that method is
**gone**: `_emit_exit` calls `_emit_call(fflush)` directly and
`_compiler_trap_addrs` is never added to, so `info["compiler_traps"]` is
`[]` for every arm64 image and `_program_extern_calls` subtracts nothing. A
merge between `38880520` and this tree dropped the arm64 half of that commit
(the x86-64 half and the proof-gen half survived). Restoring it is independent
of the `getrlimit` question and should be done first — it is the difference
between the trap flush being a program call and a compiler call.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 -m unittest test_formal_call_proof_gen.TestTheRecursionFamiliesStillGenerate
  # 1 failure: wdiff
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 -m unittest test_formal_call_proof_gen.TestCallProofs
  # the call-containing-program rows, red for the getrlimit second-call rule
```

The `TestTheReachedWalkIsPerPath` class in the same file pins the independent
fix that landed with this filing: `_reached_without_a_condition` was refusing
the ten recursive examples because it returned False on meeting ANY reachable
source conditional rather than on the halt's path crossing one. That fix is
real and stays; it moves the class from twelve red rows to one (`wdiff`, whose
loop contract is this document's `exit_at` half).
