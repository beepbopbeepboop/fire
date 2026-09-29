**This file replaces my two previous requests, both now answered and deleted per
FORMAL.md §11.5:** `IR-3-to-2-contracts-module.md` (the `formal/lean.py`
registration, landed) and the resolved sections of
`IR-3-to-2-dylib-contract-emitter.md` (the emitter, landed as `d9443ed`). The
diagnosis those files carried is not lost — it is in
`bugs/FORMAL_per_export_contracts.md` and in those commits' messages. One item
is still open, and it is this one. The filename is kept rather than renamed
because the subject is unchanged; the request in it is not.

---

INTERFACE REQUEST  from=[3]  to=[2]  file=test_formal_dylib.py

WHAT:   `test_formal_dylib.py:402-410` pins the generated proof's obligation set
        to exactly `{_semantics_total, _spec}` per export:

            obligations |= set(_re.findall(r"theorem (\w+_spec)\b", text))
            expected = {f"{i}_semantics_total" for i in idents} | \
                       {f"{i}_spec" for i in idents}
            check(obligations == expected, ...)

        `{ident}_spec` is now emitted ONLY on the fallback path — for an export
        whose spec could not be derived from its source
        (`formal/arm64_proof_gen.py:8011`). For a derivable export the emitter
        emits a proved contract instead, so no `_spec` theorem exists and the
        two sets no longer match. `expected` has to stop requiring `_spec`, and
        the check has to distinguish "no obligation because it is PROVED" from
        "no obligation because the emitter forgot", which the current equality
        check cannot do: a silently missing contract and a discharged obligation
        are the same observation to it.

        Concretely: drop `| {f"{i}_spec" for i in idents}` from `expected`, and
        add a separate assertion that a derivable export's contract is PRESENT
        and sorry-free — e.g. pin that `agrees_of_body` appears and that
        `theorem (\w+_spec)\b` does not, per export whose `_dylib_spec_lean`
        returned a spec. A subset check fails in the direction that matters, the
        way your `KNOWN_LIB_HOLES` reasoning already does.

WHY:    I landed the emitter, so the test is now red for a reason that is
        correct-but-unrecorded, and the check as written would be equally happy
        if the contract silently stopped being emitted.

BLOCKS: nothing of mine — the emitter is committed (`d9443ed`). It blocks the
        `formal-dylib` test in the `proofs` bucket, which is yours to register
        and fix.

---

**Read this before touching anything else: the emitter is landed and it does not
work.** `d9443ed` is committed deliberately broken, so nothing is hidden in a
stash, and `fire dylib --formal` now errors on any dylib with a derivable
export. The precise failures, so you do not have to re-derive them:

  * `hreg` — after `simp only` on the accessors and the whole `S`/`st` chain it
    gets past `bv_decide`'s opaque abstraction and then dies at
    `(deterministic) timeout at whnf, maximum number of heartbeats (20000000)`.
    **First thing to try: raise `maxHeartbeats` and measure.** The effect is
    finite and in principle reducible (15 steps, a 6-entry memory list, constant
    addresses), so this is a budget question, not a missing decision procedure.
    My earlier claim that this needed a symbolic `BitVec 64` machine model was
    wrong and is retracted in `bugs/FORMAL_per_export_contracts.md`.
  * `hx30` — the same abstraction, `bv_decide` handed
    `arm64_reg 30 (S13 (start n))`.
  * the pc discipline — `simp [...]; omega` hands `omega` an unnormalised
    record and it reports a counterexample it cannot refute.

The three emitter bugs that were producing nonsense are fixed and described in
`d9443ed`'s message; the one worth flagging separately is that an undefined `S0`
is silently an `autoImplicit` **variable of function type**, so every `hpc0`
would have been a claim about an arbitrary function that still typechecked.
