# a REGISTER READ out of `x86_shift_post` has no projection fact, so every program with a shift leaves the closing read admitted

**Area:** FORMAL (the x86-64 end-to-end prover, `formal/x86_64_endtoend_test.py`).
Found 2026-10-05 on `work/formal69-docs`, while fixing the stale `shl`/`shr`/`sar`
successor rows (`bugs/FORMAL_x86_64_end_to_end_proof.md`'s B35).

**Status: the `Type mismatch` is gone and one admission remains, named here.**

## What I ran, and what it says

```console
$ python3 formal/x86_64_endtoend_test.py formal/examples/shiftlr.mojo
shiftlr  terminates: proved, 1 live hole (hrip's own admission, line 964), 242 guarded
$ python3 formal/x86_64_endtoend_test.py formal/examples/shift_by_var.mojo
shift_by_var  terminates: proved, 1 live hole (hrip's own admission, line 1212), 322 guarded
```

Both were `FAIL lean exited 1: error: Type mismatch | x86_step_shl_imm8 s16` before
B35 — a hard failure, not a hole — so this is the second half of that fix and it
is smaller.

## What is missing

The closing read is `mem_read_bytes s_k.mem (s_k.rsp.toNat) 8`, and `_concrete_read`
makes it CLOSED by `simp only`-ing the path's successor equations and letting
`native_decide` evaluate the result. Every wrapper it goes through needs a
projection fact or a definition, or the projection stops and the term is not
closed:

* `x86_set_reg_mem`, `x86_set_reg_narrow_mem`, `x86_set_flag4_mem`,
  `x86_shift_post_mem` — the MEMORY side, all present (B35 added the last two);
* `x86_shift_post_rip` — the `rip` side, present (B35);
* **`s_k.rsp` — and there is no fact for it.** A shift's successor is
  `{ x86_shift_post s i digit a k with rip := … }` and the read's address is a
  register read out of it, so the term needs `(x86_shift_post …).rsp = s.rsp`.
  `x86_shift_post_rip` does not help: it is a statement about one field, and the
  simplifier does not turn `s.rsp` into `s.rip`.

Naming the `def` instead is worse, and that is measured rather than argued: with
`x86_shift_post` in `_WRAPPER_DEFS` the simplifier unfolds the `if k = 0` and the
memory read lands INSIDE the `if`, so the evaluation is refused for a different
reason. `shiftlr` reported the same single hole with it named and without it —
which is why the entry is "a fact is needed", not "a definition is needed".

## The next step

**One pair of facts, with the hypotheses they need, and they are not both true.**

A shift writes its destination and its four flags, so

```lean
theorem x86_shift_post_rsp (s : X86State) (i digit : Nat) (a : UInt64) (k : Nat)
    (h : i ≠ 4) : (x86_shift_post s i digit a k).rsp = s.rsp
theorem x86_shift_post_rbp (s : X86State) (i digit : Nat) (a : UInt64) (k : Nat)
    (h : i ≠ 5) : (x86_shift_post s i digit a k).rbp = s.rbp
```

are what the two frame registers need — `4` and `5` are RSP and RBP in
`X86State`'s field order, and **the hypotheses are load-bearing**: `shl rsp, 1` is
a legal encoding, so the unconditional statement is FALSE. Proved by
`unfold x86_shift_post; split` and then `x86_set_reg`'s `match` with the index
excluded, which is the same shape as `x86_set_reg_rip`.

Then `_RIP_LEMMAS` becomes a second tuple — or this one, since it is the same kind
of statement — and `_tracked`'s docstring already says why RSP and RBP are the two
that matter whatever else is tracked: "they are what the prologue moves and what
every frame store is addressed through".

**The honest alternative, if that pair turns out to be awkward to discharge:** the
per-step `hval` facts already state `s_k.rsp` as a LITERAL for every step that has
one (`_tracked` puts RSP in the set unconditionally), so the closing read could
read the address from `hval{k}` rather than from the chain. That is the same
"one cheap fact per step" shape
`bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md` argues for,
and it fixes this hole and the `_MAX_UNFOLD` wall in the same direction — but it
is the bigger of the two, and the pair of projection facts is 10 lines.

## Reproducing

```console
$ python3 formal/x86_64_endtoend_test.py formal/examples/shiftlr.mojo
```

`formal/x86_64_model_coverage_test.py`'s `shift_cases` (21 rows) is what says the
SHIFT ARITHMETIC is right — it is not what is missing here; what is missing is a
projection the emitter asks for.