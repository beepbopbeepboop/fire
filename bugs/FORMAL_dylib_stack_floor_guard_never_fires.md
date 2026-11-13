# FORMAL: a dylib's stack-floor guard compares SP against a word nothing initialises

Found 2026-11-12 while fixing `_semantics_total` for a branching export — the named termination obligation that
export's stack-floor guard's trap arm caused. The proof's reason for treating that trap arm as dead is that the
walk's model starts at `Arm64State.init`, whose `mem` is `fun _ => 0` — and the emitted LIBRARY agrees with that
model for a reason that is itself wrong: the guard's floor word in a dylib is zero and nothing ever writes it.

## Symptom

Every guarded prologue in a dylib carries the guard, but the guard can never fire, so a stack overflow inside
a library is still a `SIGSEGV` rather than `exit(STACK_TRAP_STATUS)`.

## Measured

Building `def branchy(n): if n > 3: return 1; return 0` with
`compile_formal_dylib(...)` and disassembling the export's own code:

    0x1000003fc  adrp x17, page ; add x17, x17, #8
    0x100000404  ldr  x16, [x17]          ; the floor word
    0x100000408  add  x17, sp, #0
    0x10000040c  cmp  x17, x16
    0x100000410  b.hs ok                  ; SP >= floor
    0x100000414  <write the message ; movz x0/#2 ; movz x16/#1 ; svc>   SP < floor

The same build's `__DATA` segment (parsed from the Mach-O: `vmaddr 0x100400000`, `fileoff 0x4000`) has
`0x0000000000000000` at the word the guard loads (`0x100400008`). `built["info"]` carries
`extern_calls == []`, `external_syms == []` and `mod_init_addrs == []`, so nothing in the image can write it
before an export is called, and the library has no startup stub.

The reason is in `formal/arm64_codegen.py`: `_emit_stack_floor_init()` — the one writer of that word — is
called only inside `compile()`'s `if emit_startup:` block (arm64_codegen.py:1152-1153), while
`_emit_stack_floor_guard` (arm64_codegen.py:2196-2240) only LOADS it. The docstring at arm64_codegen.py:1825-1832
still says the opposite ("a LIBRARY has no stub, so its first guarded prologue still emits the `getrlimit`
call"), which is what the pre-2026-10-07 shape did and what commit `806e72cb7` moved to the stub. The x86-64
half has the same structure (`_emit_stack_floor_init()` at x86_64_codegen.py:1173, the load-only guard at
x86_64_codegen.py:2180-2210). **Both backends.**

Consequently `SP >= 0` holds for every `UInt64`, the `B.HS`/`JAE` is always taken, and a recursive export in a
dylib that exhausts the stack dies with signal 11 and no output — the exact failure mode the guard exists to
replace, still reachable through the library path.

## Expected

A guarded prologue in a dylib establishes the floor before it compares against it, so a library called at a
depth past the budget exits with `model.STACK_TRAP_STATUS` (2) and the message from
`model.stack_trap_message`, as the executable path does.

## Next step

Give a library a floor init that runs before its first guarded prologue and is not on a condition any path tree
walks. Two shapes that fit:

  * re-emit the pre-`806e72cb7` inline sequence in the first guarded prologue, but store `rlim_cur` from the
    `struct rlimit` (the shape before that commit stored `getrlimit`'s RETURN CODE and clamped the budget);
  * or have the dylib's first guarded prologue call a small emitted helper that does the read, and mark that
    call as a compiler trap so the proof layer subtracts it (the mechanism
    `test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall` already pins).

Then add a pin that builds a dylib exporting a recursive function, calls it through `ctypes` at a depth past
`STACK_FLOOR_BUDGET_BYTES / frame`, and requires exit status 2 rather than a signal. Until then the guard's
trap arm in a dylib is dead code: the termination proof added on 2026-11-12 is sound about the image as well
as about the model, but the guard it steps over protects nothing.

Related: `bugs/mid/FORMAL_svc_exit_handling_incomplete.md` (the `svc` model), and
`bugs/OPEN_WORK.md`'s `FORMAL_stack_floor_does_not_guard_an_acyclic_chain` (which prologues carry the guard).

## Status (2026-11-13): planning round — root cause confirmed by reading, decision needed

No code landed this round; the output is the design guide below. Nothing in the tree changed.

### Current state (measured by reading the source, both backends)

* `formal/arm64_codegen.py`: `compile()` calls `_emit_stack_floor_init()` only inside `if emit_startup:`
  (line ~1153). `_emit_stack_floor_guard()` (line ~2136) only LOADS the floor word and compares. A dylib is
  built with `emit_startup=False` (`formal/build.py` ~23835, ~23920, ~23933), so no writer ever runs.
* `formal/x86_64_codegen.py`: the same split — `_emit_stack_floor_init()` (line ~1173, inside
  `if emit_startup:`), load-only `_emit_stack_floor_guard()` (line ~2151).
* The arm64 docstring at `_emit_stack_floor_guard` (~lines 1825-1832 and ~2165-2170) still describes the
  pre-`806e72cb7` shape ("a LIBRARY has no stub, so its first guarded prologue still emits the `getrlimit`
  call"). That text is stale: the guard no longer emits the call in any shape.
* `formal/model/module.py`: `STACK_FLOOR_BUDGET_BYTES` = 7.5 MiB, `STACK_FLOOR_MARGIN_BYTES` = 256 KiB,
  `STACK_FLOOR_MIN_BUDGET_BYTES` = 2 * `ARM64_CONTAINER_BUDGET`.

### Why "lazy init in the first guarded prologue" is NOT the fix

The shape the doc's first option names (re-emit the inline `getrlimit` read in the first guarded prologue,
gated on a cached-limit word) stores `floor = SP_at_first_call - budget`. That anchors the floor to whichever
caller happens to run first, not to the process's stack:

* first call shallow → floor sits too high → spurious `exit(2)` while real stack remains;
* first call deep (near the bottom) → floor below the real bottom → the guard never fires → SIGSEGV, the bug
  again.

It would pass a ctypes pin that calls the export shallow first, and it would still be wrong. Do not land it.

### The decision

Anchor the library's floor at LOAD time, the same moment the program's floor is anchored at process entry
(the stub runs at the entry SP; the program model already accepts that approximation, with the margin
absorbing the gap). Reading A (recommended) vs reading B:

* **A (recommended): a load-time floor initializer.** Emit the floor init (`getrlimit` read + clamp + store,
  i.e. `_emit_stack_floor_init` unchanged) as a standalone function at the end of the image, and register it
  in `info["mod_init_addrs"]` so the loader runs it at `dlopen`. Consequences that must be handled:
  1. `formal/build.py` decides `has_mod_init` from `M.module_body_functions(ordered)` BEFORE emission, and
     `_mod_init_addrs` refuses a mismatch. `has_mod_init` must become "module body OR floor init", computed
     from one predicate used by both sides.
  2. The init is not an export, so the proof layer must exclude it from the walked range the same way the
     program stub is excluded (`_program_extern_calls` / `func_offset`). Its `bl getrlimit` must be recorded
     as a compiler trap, not a program call (the mechanism `test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall`
     pins). Without this, `extern_calls` stops being `[]` and the dylib proof refuses.
  3. Both containers: Mach-O `__init_offsets` (`formal/macho_linker.py` ~1409-1480) and ELF `DT_INIT_ARRAY`
     (`formal/elf.py` ~863-936) already carry `mod_init_addrs`; no container change should be needed.
  4. The x86-64 half mirrors the same change (`x86_64_codegen.py` ~1345 `mod_init_addrs`).
* **B: an exported `<prefix>_init_stack_floor` the host must call.** Sound but changes the library ABI and
  every ctypes caller. Not recommended.

### Implementation plan (for reading A)

1. `formal/model/module.py`: one predicate `stack_floor_needs_init(...)` / or reuse `module_body_functions`
   with a floor flag, so the build and both emitters ask one question.
2. `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`: add `emit_library_floor_init()` that emits the
   existing `_emit_stack_floor_init` body as its own labelled function ending in `ret`, appended after every
   body and before `resolve()`, when `not emit_startup and guarded`. Record its address in `info`.
3. `formal/build.py`: `has_mod_init` from the shared predicate; `_mod_init_addrs` accepts the floor init.
4. Proof: `formal/arm64_proof_gen.py` / `formal/x86_64_proof_gen.py` exclude the init's range from the walked
   set and register its `getrlimit` as a compiler trap; `lib/ProofLib.lean` / `lib/X86.lean` need no new
   lemma if the init is excluded by address.
5. Fix the stale docstrings at arm64 ~1825-1832 and ~2165-2170 in the same commit.

### Tests that prove it

* **Quick pin (the `## Done when` test, to be added):** in `test_formal_dylib.py`, build a dylib exporting a
  recursive function whose depth passes `STACK_FLOOR_BUDGET_BYTES / frame`, `ctypes.CDLL` it, call it at that
  depth in a child process under a reduced `ulimit -s`, and require exit status `model.STACK_TRAP_STATUS` (2)
  with `model.stack_trap_message` on stderr, not a signal. Run it for both backends' dylib builds.
  It must FAIL on master (signal 11) before the fix.
* **Regression on the existing dylib run:** `test_formal_dylib.py` as a whole (the call-tree and extern
  accounting it already checks must still pass).
* **Proof side:** `test_formal_call_proof_gen.py` for the compiler-trap registration.
* **Gate (integrator only, not run by the worker):** `compile_stdlib.py` / `build_stdlib_dylib.py` skip and
  unexpected-failure counts unchanged.

### What is still needed from the owner

Confirm reading A (load-time initializer). If B is preferred, the pin test changes to call the host-side init
first and the ABI note goes in `doc/`.
