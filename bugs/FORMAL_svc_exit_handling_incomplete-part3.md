# FORMAL: `svc` exit handling — part 3: a halt certificate admits a dynamic write `svc` under `svc_write_assumed`

Part 3 of 5 of `bugs/hard/FORMAL_svc_exit_handling_incomplete.md`. It is the
second half of the parent's remaining design item 4, for the certificate that
proves a block **halts** at an exit `svc`. Part 2 does the `some`-returning run
certificate; part 4 threads both through the universal walk.

## Goal

Teach `formal/arm64_proof_gen.py::_gen_halt_cert` to accept an **earlier**
write `svc` whose x16 is not statically known, under the same named hypothesis
as part 2, instead of refusing the whole halt block. The final `svc` must still
be a statically-known exit: a halt certificate cannot assume the halt it is
proving.

The emitted `{S}_halts` theorem carries the `svc_write_assumed` binder and uses
it to discharge `work_step_svc_write`'s `hx` for the dynamic write, then
continues to the static x16 chain and the exit `svc` as it does today. No
assumption is invented; with no caller-supplied assumption the function still
returns `None`.

## Current state

`_gen_halt_cert` refuses a dynamic `svc` twice:

* its first loop does `x = _svc_static_x16(words, pc, leaders); if x is None:
  return None` for every `svc` in the block;
* in the segment walk, an `svc` with `prev_run is None` (no preceding run
  segment from which to build a reg-16 chain) returns `None`, and the comment
  says "Refuse rather than assume."

Everything else is already in place: the split at `svc`s, the
`arm64_go_exit_step_jump_at` write step, the final exit step's `none`, and the
`_x0_reassigned_after_write` rule used by `_gen_run_cert`. Only the "assume
the dynamic write form" path is missing.

## Acceptance

* `_gen_halt_cert("f", words, base, "b0", pcs, exit_pc)` on the image

  ```
  <base>       svc                 # no movz immediately before: x16 dynamic
  base + 4     movz x0, #0         # rewrites the write's byte count
  base + 8     movz x16, #1
  base + 12    svc                 # static exit
  ```

  still returns `None` with no assumption.
* With the named assumption supplied, it returns a `({defs}, "{S}_halts", n)`
  triple whose theorem carries a binder visibly named `svc_write_assumed` and
  whose `hx_svc_j` for the dynamic write is that binder applied at the
  pre-svc state. The write still steps to `some { … pc := pc + 4 }` through
  `arm64_go_exit_step_jump_at`; the final static exit still steps to `none`.
* Controls, unchanged:
  * a block whose only `svc` is the static exit (`movz x16, #1; svc`) produces
    no `svc_write_assumed` binder;
  * a **final** `svc` whose x16 is dynamic is still refused, assumption or not
    (the halt being proved cannot be assumed);
  * an earlier dynamic write whose fall-through reads `x0` before rewriting it
    is still refused (`_x0_reassigned_after_write`).

## Done when

```
python3 test_formal_call_proof_gen.py TestSvcWriteAssumedHaltCertificate
```

exits 0. Text only: hand-built word dictionaries, no Lean and no compile.
Expected cost under 5 s.

## Approach

1. Add the same optional assumption channel as part 2, e.g.
   `svc_assumed: dict[int, str] | None = None`, keyed by the dynamic svc's pc.
2. In the first `svc` scan, keep refusing `x is None` for the **final** pc;
   for an earlier pc, accept it only when it is in `svc_assumed` and
   `_x0_reassigned_after_write(words, pc)`. Record it as a dynamic write, not
   in `svc_x16`.
3. In the segment walk, when `prev_run is None` and the current svc is a
   dynamic write with an assumption, emit
   `have hx_svc_j : ¬ arm64_reg 16 (<cur state>) = 1 := <the supplied term>`
   instead of building a chain, then take the existing `arm64_go_exit_step_jump_at`
   write branch.
4. Add the binder to the `{S}_halts` theorem header. Reuse part 2's binder
   spelling so the universal caller can pass one assumption family to both
   certificate builders; do not introduce a second name for the same fact.

## Out of scope

* The `some`-returning run certificate (part 2).
* Threading the assumption from `_gen_universal_e2e_cfg` (part 4), and the
  dylib termination theorem (part 5).
* A dynamic **exit** `svc`. It is still a refusal: proving a halt cannot be a
  hypothesis.
