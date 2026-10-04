# the stack-floor guard's two instructions have no x86-64 step lemma

## Status: OPEN, not fixed — the fix is two real Lean lemmas, and the worker who
## found it was not allowed to run `lean`. Everything around them is measured
## here. Found 2026-10-03 by `work/gatefix4`.

## What I ran

    python3 tools/memslot.py --gb 8 --label fst -- python3 test_formal_sweep_truth.py

    ERROR: test_the_return_is_a_named_fact_and_the_step_uses_it
    ...
    File "formal/x86_64_endtoend_test.py", line 1522, in _plan
      raise ValueError("no step lemma wired for: " + ", ".join(missing))
    ValueError: no step lemma wired for: alu_ri32:sub_reg, lea_r64_rip

    Ran 97 tests in 20.301s
    FAILED (errors=6)

All six errors are `TestX86EndToEndEmitter` cases calling its `_emitted()`
helper, which compiles one fixture:

    struct Point:
        var x: Int
        fn get_x(self) -> Int:
            return self.x

    def main(n) -> Int:
        var p = Point()
        return p.get_x()

## What it is

`_plan` refuses before emitting anything when a decoded form has no row in
`_FORMS` — a coverage check, and a correct one. The fixture's 20 distinct
forms, measured by decoding it (`formal.build.compile_formal(..., arch='x86_64')`
then `x86_64_endtoend_test._shapes`):

    alu_ri32:add_rsp               1
    alu_ri32:sub_reg               2   <-- no lemma
    alu_ri32:sub_rsp               3
    alu_rr:cmp                     2
    alu_rr:test                    2
    call_rel32                     3
    jcc_rel32                      4
    lea_r64_rip                    2   <-- no lemma
    leave                          2
    mov_r64_rm64_disp8             3
    mov_r64_rm64_nodisp            2
    mov_r64_rm64_sib               1
    mov_rm64_imm32                 5
    mov_rm64_r64_disp8             3
    mov_rm64_r64_nodisp            2
    mov_rm64_r64_reg              12
    mov_rm64_r64_sib               1
    push_r64                       2
    ret                            2

Both gaps are the **stack-floor guard**, which
`formal/x86_64_codegen.py::_emit_stack_floor_guard` (line 1532) puts in every
prologue of an image that has an entry. Its own docstring spells the sequence:

    LEA R11, [rip+&floor] ; MOV R10, [R11]   the floor word
    TEST R10, R10 ; JNE done                 already stored
    MOV R10, RSP ; SUB R10, BUDGET ; MOV [R11], R10
    done:
    MOV R11, RSP ; CMP R11, R10
    JAE ok                                    SP >= floor: carry clear
    exit(2)                                   SP < floor
    ok:

Decoded, per function (the fixture has two — `main` and `Point.get_x`):

    18 push_r64
    19 mov_rm64_r64            mov rbp, rsp
    22 alu_ri32:sub            sub rsp, 0x4110       -> sub_rsp, wired
    29 lea_r64_rip             lea r11, [rip+0x3ffc24]  <-- GAP
    36 mov_r64_rm64
    39 alu_rr:test
    42 jcc_rel32
    48 mov_rm64_r64            mov r10, rsp
    51 alu_ri32:sub            sub r10, 0x780000     <-- GAP (general reg)
    ...

and the same eight instructions again at 156–199 in the second function. So the
guard accounts for **4 of the 4** missing-form instances, 2 per function.

## Which commit, and why it is a coverage hole rather than a regression

`e11f066d` "formal: every prologue of an image that has an entry carries the
stack-floor guard" (2026-10-03). Measured: `git merge-base --is-ancestor
e11f066d e59dae8c` says **no** — it arrived in `e59dae8c..86d60026`, the range
the red gate bisected to. It is also in `86d60026` itself.

Before it, no prologue emitted either instruction, so no program could contain
them and `_FORMS` never needed a row. `_FORMS` has `alu_ri32:sub_rsp` and
`alu_ri32:add_rsp` (the stack-pointer special cases) and the general
`alu_ri32:add_reg` and `alu_ri32:and`, and `lea_r64_rm64_disp32` — so `add` was
wired for the general register and `sub` was not, and `lea` was wired for the
base+disp mode and not for the RIP-relative one. Nothing about the guard is
wrong; the coverage census was simply not re-run, and `_plan`'s refusal is what
says so instead of a wrong proof.

`lea_r64_rip` is not exclusive to the guard either: `_emit_global_init` uses a
RIP-relative `lea` for every address-valued module global (its own docstring,
"Why code and not a relocation"). So one lemma closes both producers.

## Next step — two lemmas, and the wiring is already three-quarters written

**`alu_ri32:sub_reg`.** The resolver already has the arithmetic and it is
currently DEAD for this form: `_resolve`'s digit-immediate branch is entered for
`("alu_ri32:add_reg", "alu_ri32:and", "alu_ri8:cmp")` (line 824) and its final
`else` computes exactly the `sub` shape —

    res = "(%s - %s)" % (a, imm)
    extra_succ["$fs"] = "x86_flags_sub $s %s %s %s" % (a, imm, res)

— which is why `alu_ri8:cmp` (digit 7, the register-discarding `cmp`) can use
it. Adding the name to that tuple's first element is a one-token change, and it
is the evidence that `sub` was anticipated and only the row was missed.

So:

1. `lib/X86.lean`: `x86_step_sub_ri32`, the `81 /5` general form — the exact
   sibling of `x86_step_add_ri32` with `x86_flags_sub` in place of
   `x86_flags_add`, and `x86_flags_sub` already exists (digit 7 uses it). **This
   is the part that needs `lean` and must not be a `sorry`.**
2. `_FORMS`: `"alu_ri32:sub_reg": ("x86_step_sub_ri32", False, ["rip", "b0",
   "b1", "b2", "rex", "w", "mod", "digit", "rm"])` — the same list
   `alu_ri32:add_reg` carries, since it is the same encoding.
3. `_SUCCS`: the `alu_ri32:add_reg` row with `- $imm` and `($fs)` in place of
   `+ $imm` and `($fa)`.
4. `_resolve`: add `"alu_ri32:sub_reg"` to the tuple at line 824.

**`lea_r64_rip`.** The decoder already splits it (`formal/x86_64_decode.py:268`,
`"lea_r64_rip" if rip else "lea_r64_rm64"`, with `rip_rel=disp`), so the form is
named and its displacement is carried. What the successor has to say is the one
thing the `lea_r64_rm64_disp32` row does not: with `mod=00 rm=101` the address is
**`endAddr + disp`, not `base + disp`** — the displacement counts from the end of
the instruction, which is the same reason `formal/x86_64.py::encode_lea_r64_rip`
documents its own `disp` that way.

1. `lib/X86.lean`: `x86_step_lea_r64_rip` — the `lea_r64_rm64_disp32` lemma with
   the base replaced by the model's end address. Again: real, and no `sorry`.
2. `_FORMS`: `"lea_r64_rip": ("x86_step_lea_r64_rip", False, [...])`. It is a
   LOAD-shaped form (a `lea` writes a register) with NO `dst` argument beyond
   the REX-derived one, so it belongs in `_LOAD_MEMORY_FORMS` (line 1115)
   alongside `lea_r64_rm64_disp32` — that tuple's docstring says the two are
   derived from each other so they cannot drift, and adding a load mode to
   `_MEMORY_FORMS` without adding it there has already produced one arity error.
3. `_SUCCS`: the `lea_r64_rm64_disp32` row with `x86_mem_addr`'s RIP-relative
   base.
4. `_resolve`: a branch reading `rip_rel` and building the `$disp` /
   successor base from the end address.

Then `_plan` stops refusing and the six cases emit. Whether they PROVE is the
second half of the work and cannot be answered without `lean`: the guard's
`sub r10, budget` writes a register the rest of the chain reads
(`cmp r11, r10` / `jcc`), so a wrong successor here is a proof about a machine
that does not exist — the failure mode `_FORMS`' own header calls out ("a new
form needs both, and a mismatch between them is a proof failure rather than a
silent gap").

## Re-verify with

    python3 tools/memslot.py --gb 8 --label fst -- python3 test_formal_sweep_truth.py

then the x86-64 proof steps themselves — `formal-x86-model` ("every byte the
x86-64 emitter can produce is a step the model can step") and
`formal-x86-endtoend` ("x86-64 whole run, every input, no sorry"), i.e.

    python3 tools/suite.py formal-x86-model formal-x86-endtoend

which is where a wrong successor shows up as a `sorry` or a `Type mismatch` in
the generated file.
