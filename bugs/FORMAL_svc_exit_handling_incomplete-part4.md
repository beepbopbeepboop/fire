# FORMAL: `svc` exit handling — part 4: the universal theorem carries the `svc_write_assumed` hypothesis

Part 4 of 5 of `bugs/hard/FORMAL_svc_exit_handling_incomplete.md`. It is the
piece that makes the parent's design sentence true: "The assumption is a named
hypothesis (`svc_write_assumed`) on the generated theorem, so every caller of
the dylib contract sees it. A dynamic `svc` with no such assumption available
is refused, not guessed."

Depends on part 2 (run certificate) and part 3 (halt certificate). Do not start
this part until both have landed: it passes their assumption channel, it does
not reimplement it.

## Goal

Thread the dynamic write-`svc` assumption through
`formal/arm64_proof_gen.py::_gen_universal_e2e_cfg`:

* collect every dynamic write `svc` site on the blocks the walk actually
  certifies (those that pass `_x0_reassigned_after_write`);
* add ONE binder to the universal theorem, named `svc_write_assumed`, stating
  the fact the write form needs:
  `∀ s, s.pc ∈ [<the dynamic pcs>] → ¬ arm64_reg 16 s = 1` (the exact Lean
  spelling may follow the `frame`/`_fr["hyps"]` channel, but the name and the
  content are fixed);
* pass the per-site discharge (the binder applied at the certificate's own
  pre-svc state) into `_gen_run_cert` and `_gen_halt_cert`;
* leave the cell refused when the assumption is unavailable — a dynamic svc
  whose fall-through reads `x0` before rewriting it, or a dynamic `svc` at a
  reachable point with no `x0` provenance. Name it; do not guess.

## Current state

`_gen_universal_e2e_cfg` builds each block's certificate with a call to
`_gen_run_cert(...)` / `_gen_halt_cert(...)` and returns `None` if either
refuses. Both functions refuse a dynamic `svc`, so a synthetic image whose only
defect is a dynamic write `svc` makes the whole universal theorem `None`.

The theorem's binder list already supports caller-supplied hypotheses through
`_fr["hyps"]` (`(name, type, proof_or_None)` entries rendered as theorem
binders). That is the channel to use; do not add a second, parallel binder
mechanism.

`_cfg_decomposition_refusal`'s second (`svc`) search currently reports every
dynamic x16 as the reason the walk refused. Once an admissible dynamic write is
assumed, that search must skip it and continue; only an actually-unassumable
dynamic `svc` is the cause of a refusal.

## Acceptance

* A synthetic image

  ```
  <base>       svc                 # dynamic x16, write form assumed
  base + 4     movz x0, #0         # rewrites the byte count
  base + 8     ret
  ```

  passed to `_gen_universal_e2e_cfg` no longer returns `None`. Its emitted
  universal theorem (`<name>_compiles_correctly_universal`, or the `thm` the
  caller supplies) has a binder visibly named `svc_write_assumed`, and the
  block certificate inside the text uses that binder as the dynamic svc's
  `hx` — not a chain from a `movz` that is not there, and not a proved fact.
* The same image with `add x1, x0, x2` in place of `movz x0, #0` still returns
  `None`: the fall-through reads the unmodelled byte count, so no assumption is
  available. `_cfg_decomposition_refusal` on that image names the write `svc`,
  its pc and `x0` (the existing rows in
  `TestTheRefusalNamesTheSvcItRefuses` stay green).
* A dynamic **final** `svc` (the block's tail) is still refused with the
  dynamic-svc message. A halt cannot be assumed.
* A program with no dynamic `svc` changes its emitted universal theorem in no
  way: no `svc_write_assumed` binder appears, and the corpus's ordinary
  straight-line/guard cases keep their current text (pin this with the existing
  `plain` stack-floor case or an equally small control).
* One implementation of "which dynamic sites are admissible": a helper used by
  the walk and by the refusal classifier, not two copies of the three-call
  rule (`_is_svc` + `_svc_static_x16 is None` + `_x0_reassigned_after_write`).

## Done when

```
python3 test_formal_call_proof_gen.py TestSvcWriteAssumedUniversalWalk
```

exits 0. Text-only: it calls `_gen_universal_e2e_cfg` on hand-built bytes and
asserts on the returned text. No Lean, no dylib, no compile. Expected cost
under 10 s.

## Approach

1. Add a helper, e.g. `_svc_write_assumed_sites(blocks, words, leaders)`,
   returning the sorted pcs of dynamic write `svc`s that satisfy
   `_x0_reassigned_after_write`. Use it wherever the walk needs the set and in
   `_cfg_decomposition_refusal`'s svc search.
2. Build the binder type with the pcs list (the same `∀ p ∈ [...]` list shape
   the generator already uses for `_mid`'s exit set), append it to
   `_fr["hyps"]` with no proof, and keep the hypothesis name
   `svc_write_assumed`.
3. For a block certificate, pass `{pc: f"svc_write_assumed ({S}_qS{k} st)
   (by simp [hpc{k}])"}`-style terms — the exact state and pc proof are the
   certificate's own, so the helper belongs at the call site, not inside the
   certificate builders.
4. Update the refusal classifier to skip admissible dynamic writes. The old
   sentence for a genuinely dynamic svc stays, with the same "refused rather
   than guessed" reading; do not reword it into a generic failure.
5. Control on a plain corpus program: assert its universal text contains no
   `svc_write_assumed`. The census in part 1 says every corpus `svc` is
   static, so this is true today and must stay true.

## Out of scope

* The certificate builders themselves (parts 2 and 3).
* The dylib termination theorem and `_dylib_total_proof` (part 5).
* `_dylib_contract_proof`'s normal-path contract, which is a separate guarded
  route and already refuses the shapes it cannot state.
