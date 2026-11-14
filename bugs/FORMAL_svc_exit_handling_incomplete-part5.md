# FORMAL: `svc` exit handling — part 5: the dylib termination theorem exposes `svc_write_assumed`

Part 5 of 5 of `bugs/hard/FORMAL_svc_exit_handling_incomplete.md`. It closes
the "every caller of the dylib contract sees it" half of the parent's design:
the assumption is not discharged inside a private certificate and then dropped
on the way out.

Depends on part 4 (the universal walk carries the hypothesis). Do not start
until part 4 has landed and its test is green.

## Goal

Make `formal/arm64_proof_gen.py::_dylib_total_proof` account for a dynamic
write `svc` on an export's walked path instead of silently losing the
assumption:

* when the export's `{ident}_halts` theorem carries `svc_write_assumed`, state
  `{ident}_semantics_total` under the same named hypothesis and pass it through
  to `DylibExport.total_of_halts` — so the export's public termination claim
  says "terminates **if** x16 at those pcs is never 1";
* never emit the plain `DylibExport.total_of_halts dylib_image {ident}
  {ident}_halts` application when `{ident}_halts` needs the assumption: that is
  a type error at best, and a silently dropped premise at worst;
* if the assumption cannot be stated for this export, keep the existing named
  obligation (`sorry` with the docstring) and make its text name the dynamic
  `svc` pc — do not emit an unconditional `Total`, and do not swallow the
  reason.

The dylib **contract** path (`_dylib_contract_proof`, which reads the executed
normal path with `_overflow_normal_path`) is not changed by this part; it is a
separate guarded route and already refuses a path it cannot state.

## Current state

`_dylib_total_proof` calls

```
_gen_universal_e2e_cfg(..., thm=f"{ident}_halts", prop="True",
                       halt_only=True, fuel=_EXPORT_FUEL_BASE, ...)
```

and, on success, emits

```
theorem {ident}_semantics_total :
    DylibExport.Total dylib_image {ident} :=
  DylibExport.total_of_halts dylib_image {ident} {ident}_halts
```

On `walk is None` it emits a named `sorry` obligation. A dynamic write `svc`
currently makes the walk `None`, so the export gets the obligation (measured
with a three-word synthetic image: `[svc, movz x0,#0, ret]` produced
`theorem f_semantics_total := sorry`). After part 4 the walk returns a
`{ident}_halts` with an extra binder, and this call site is the one that must
render the consequence.

## Acceptance

* On the synthetic image `[svc, movz x0,#0, ret]` at `base`, with export
  `{"name": "f", "entry": base}`, `_dylib_total_proof("f", code, base, base,
  exports)`:
  * contains `svc_write_assumed` in the `{ident}_semantics_total` statement;
  * applies `DylibExport.total_of_halts` to `{ident}_halts` **with** that
    assumption (the exact application may be `fun n => {ident}_halts n
    svc_write_assumed` or another well-typed spelling, but the binder must
    reach `total_of_halts`);
  * does not contain a bare `sorry` for `semantics_total`.
* On a control image with no dynamic `svc` (e.g. `[movz x0,#5, ret]`), the
  emitted text is the old shape byte-for-byte where it matters: no
  `svc_write_assumed` binder, and `DylibExport.total_of_halts … {ident}_halts`
  applied directly.
* If the export is refused for another reason (a loop, a call, a dynamic exit
  `svc`), the obligation text names the dynamic `svc` pc rather than claiming
  an unconditional `Total`.
* No `sorry` is introduced in `lib/`; this part edits the generator only.

## Done when

```
python3 test_formal_call_proof_gen.py TestSvcWriteAssumedDylibTotal
```

exits 0. It is a text test over hand-built bytes calling `_dylib_total_proof`
directly. No Lean, no dylib build, no `proofs` bucket. Expected cost under 10 s.

The `formal-dylib` gate row is a separate, heavier measurement (`proofs`
bucket); the integrator runs it after the series, not this part's Done-when.

## Approach

1. After the walk, detect whether its theorem needs `svc_write_assumed`. The
   cleanest source is the same helper part 4 added for the assumption sites;
   do not re-scan the image in a second, slightly different way.
2. If it does, emit the theorem header with the same binder and pass it
   through the `total_of_halts` application with a lambda that supplies `n`
   first (the walk's theorem puts `n` before the assumption).
3. If the assumption set is empty, keep the current text exactly. The control
   row is there so the common case cannot regress.
4. Keep the `walk is None` obligation branch, but extend its docstring to name
   the dynamic `svc` pc when `_cfg_decomposition_refusal` returned one. A
   reader must be able to tell "no proof because dynamic svc at 0x…" from
   "no proof because a loop".

## Out of scope

* The universal walk and refusal classifier (part 4).
* `_dylib_contract_proof` and the per-export functional contract.
* Removing or changing the `formal-dylib` `expect=` marker. The marker's
  remaining rows include the wrong-spec teeth checks and the guarded contract
  rows, which are not caused by the dynamic-svc slot; measure them separately
  rather than attributing them to this part.
