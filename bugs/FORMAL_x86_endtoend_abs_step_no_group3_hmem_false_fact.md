# FORMAL: the abstract walk wipes on `group3:not`, and the store after it makes `hmem` a lie

## Symptom, measured

    python3 -m formal.x86_64_endtoend_test formal/examples/unary_ops.mojo
      unary_ops  terminates: FAIL lean exited 1: error: unsolved goals

On this tree (measured 2026-11-19, full run `PASS=68 FAIL=13 of 68`) this is
the ONLY example that fails with unsolved goals; the other twelve failures are
different mechanisms (see the sibling docs filed the same day). Reproduced in
isolation (generated file `.tmp/unary_ops_proof.lean`):

    .tmp/unary_ops_proof.lean:1588:39: error: unsolved goals
    .tmp/unary_ops_proof.lean:1998:41: error: unsolved goals
    .tmp/unary_ops_proof.lean:2418:43: error: unsolved goals

each on the same goal shape:

    ⊢ mem_write_bytes s50.mem (↑s50.rsp.toNat % 18446744073709551616).toNat s50.rax 8
      = s50.mem

i.e. a `have hmem51 : s51.mem = s50.mem` whose step 51's successor is a STORE
(`{ s50 with mem := mem_write_bytes …, rip := … }`): memory invariance claimed
for a step that writes memory.

## The chain

1. `unary_ops` computes `~n`, which the backend emits as `REX.F7 /digit 2`
   (`group3:not`). `_abs_step` (formal/x86_64_endtoend_test.py, the walk-side
   constant propagation) has NO branch for `group3:not` (nor `group3:neg`): the
   walk falls through to the final `st.wipe()`, so every register — including
   RSP — becomes `None` from that point on, and every later store on the path
   is address-less. Measured on the tree walk: the state at the `group3:not`
   node and every node after it carries no register and no cell at all.
   (`_resolve` handles both digits — `x86_step_not_r64`/`x86_step_neg_r64` are
   wired in `_FORMS`/`_SUCCS` — so the MODEL steps the form; only the walk
   does not. `~n` in `unary_ops` is the first example in the corpus to reach
   it — `sign` and friends compute `-n` as `sub 0` and never emit the form,
   and `a = 0 - n` in the same example is `alu_rr:sub` on the register, which
   the walk does model.)
2. Every store afterwards addresses through the unknown RSP:
   `_Abs.store(None, …)` records NO write — it drops the whole write list and
   sets `mem_ok = False` (the comment says so: an unknown address can be
   anything). `done()` then tests `len(after.writes) > len(abs_.writes)` to
   decide whether the step stored, and a store that CLEARED the list fails
   that test, so `node.write` stays `None`.
3. `emit_terminates` reads `node.write is None` as "this step wrote only
   registers" and emits `have hmem{k+1} : s{k+1}.mem = s{k}.mem := by
   rw [hs{k+1}]; try simp […]` — for a step whose successor is a
   `mem_write_bytes`, that fact is FALSE, and the block carries NO
   `all_goals sorry` (unlike every side condition `_resolve` emits), so the
   open goal is an ELABORATION error and the whole file dies: the example
   reports `terminates: FAIL lean exited 1` instead of a counted hole.

## Why this is an emitter bug and not a harness limit

The walk refusing `group3:not` is a coverage gap in the abstract state, and
the `hmem` emission is a false fact with no admission path. Both are on this
side of the model: the model steps the form (the coverage test is green for
it), the step lemma is wired in `_resolve`/`_FORMS`/`_SUCCS`, and the
generated file's ONLY error is the emitter's own `hmem`.

## What the fix has to touch

1. `formal/x86_64_endtoend_test.py::_abs_step`: a `group3` branch — `not` is
   `res = a & ~0` (flags as `x86_flags_logic`) and `neg` is `res = 0 - a`
   with `x86_flags_sub`'s four values, both through the same
   `st.put(dst, …)`/`st.set_flags(…)` shape the other ALU rows use, reading
   the ModRM the way every other row does. Without it the walk wipes and
   every later store is address-less.
2. The `hmem` emission must not fire for a step that stores even when the
   walk cannot say where: the `len(after.writes) > len(abs_.writes)` test in
   `done()` is not a store detector — a store with an unknown address
   SHRINKS the list. Either mark the node from the FORM (the successor table
   knows which forms write memory) or give the `hmem` block the same
   `all_goals sorry` guard every other side condition has, so the worst case
   is a counted hole named `hmem` and not a file that dies.

## Done when

`unary_ops` stops failing (a `group3:not`/`group3:neg` row lands in
`formal/x86_64_model_coverage_test.py`'s walk-side check so a form that
`_abs_step` does not model is red there rather than a file that cannot
elaborate), and the full run's `terminates: FAIL` count drops from thirteen
toward the memory-ceiling cases the `formal-x86-endtoend` marker names.
