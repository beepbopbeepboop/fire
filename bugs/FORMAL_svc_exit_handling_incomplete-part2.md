# FORMAL: `svc` exit handling — part 2: a run certificate admits a dynamic write `svc` under `svc_write_assumed`

Part 2 of 5 of `bugs/hard/FORMAL_svc_exit_handling_incomplete.md`. It is the
first half of the parent's remaining design item 4: the dynamic `svc` is
assumed, not guessed. Part 3 does the halt certificate; part 4 threads the
assumption through the universal walk; part 5 exposes it on the dylib
termination theorem.

## Goal

Teach `formal/arm64_proof_gen.py::_gen_run_cert` to compose a straight-line run
through a write `svc` whose x16 is **not** statically known, instead of
returning `None`, when the run satisfies the two conditions that make the
write form sound:

* the fall-through rewrites `x0` before anything reads the byte count the
  model does not model (`_x0_reassigned_after_write`); and
* the caller supplies the named hypothesis that the write form needs:
  `svc_write_assumed : ¬ arm64_reg 16 s = 1` at that svc's state.

The assumption is a binder on the emitted `{S}_runs` theorem and is used to
discharge `work_step_svc_write`'s `hx`. It is never invented inside the
certificate, and the certificate never proves that x16 is not 1. With no
assumption supplied, the behaviour is exactly today's: `None` (a refusal).

## Current state

`_gen_run_cert` already has the right halves:

* the write provenance check reads x16 only from a `movz` that is one of the
  run's own preceding instructions, and refuses when it is absent:
  `if x16 is None or x16 == 1: return None`;
* `_x0_reassigned_after_write(words, pc)` is the other admission condition;
* `_gen_step_result_lemmas` already emits a per-word lemma for a dynamic `svc`
  as `work_step_svc_write` under `hx : ¬ arm64_reg 16 s = 1` (the `idx == 35`
  branch), so the lemma side exists. What is missing is the run certificate's
  use of it when no chain is available.

## Acceptance

* `_gen_run_cert("f", words, base, "b0", [svc, movz_x0_0, ret])` (the svc is
  the run's first instruction, so no preceding `movz` is in the run) still
  returns `None` when no assumption is supplied.
* The same call with the named assumption supplied returns a certificate whose
  `{S}_runs` theorem carries a binder visibly named `svc_write_assumed` (or the
  caller-supplied name) and whose `hx{k}` for the dynamic svc is that
  hypothesis applied at the run's own pre-svc state — **not** a chain from a
  `movz` that is not in the run.
* The step is the write form (`some { s with pc := s.pc + 4 }`), never the
  exit form. No `arm64_go_exit_step_jump_at` is introduced by this function.
* Controls, unchanged:
  * a static write run (`movz x16, #4; svc; movz x0, #0; ret`) still
    discharges `hx` from its own reg-16 chain and does not mention
    `svc_write_assumed`;
  * a static exit run (`movz x16, #1; svc; …`) is still refused;
  * a dynamic write whose fall-through reads `x0` before rewriting it is still
    refused, assumption or not.
* The optional argument defaults to "no assumption", so every existing caller
  (`_gen_universal_e2e_cfg`, `_gen_halt_cert`) keeps its current behaviour
  until part 4 passes one.

## Done when

```
python3 test_formal_call_proof_gen.py TestSvcWriteAssumedRunCertificate
```

exits 0. It is a text test over hand-built word dictionaries — no Lean, no
dylib, no compile. Expected cost under 5 s.

## Approach

1. Add an optional keyword to `_gen_run_cert`, e.g.
   `svc_assumed: dict[int, str] | None = None`, mapping the dynamic svc's pc
   to the Lean term that proves `¬ arm64_reg 16 ({S}_qS{k} st) = 1`.
2. In the svc-admission loop, when `x16 is None`: refuse unless the pc is in
   `svc_assumed` and `_x0_reassigned_after_write(words, pc)`; record the site
   as dynamic rather than in `svc_write`.
3. In the `hx_facts` emission, a dynamic site emits
   `have hx{k} : ¬ arm64_reg 16 ({S}_qS{k} st) = 1 := <the supplied term>`
   instead of the chain-based `h16`/`hx` pair. The `_sr_i` application is the
   same as the static write case.
4. The `{S}_runs` theorem gets one binder per dynamic site (the exact binder
   spelling is the caller's; part 4 uses the name `svc_write_assumed`). State
   it as a binder, not a `have` with a proof: this part assumes, it does not
   prove.

## Out of scope

* The halt certificate (`_gen_halt_cert`, part 3).
* Choosing and exposing the assumption on the universal theorem (part 4), and
  the dylib termination theorem (part 5).
* Any change to the Lean model or `lib/`.
