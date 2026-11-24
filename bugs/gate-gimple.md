# Gate: gimple is red on master

**Job:** `gimple`. Filed by the full gate at `8bc7bb14af`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py gimple`), then fix the cause.

## Gate ledger

### 2026-11-23: enabled, run, 4 -> 3 failures; switch restored

Dropped `disabled='bugs/gate-gimple.md'` from `tools/suite.py` and ran the job:
it FAILED with 4 cases. Fixed one -- the walk-memo census flagged four
`cpp_core.py` CONSTRUCTORS (`_field_ex`, `_un_ex`, `_cpp_call_ex`,
`_cpp_call_line`) that set fields on freshly built `Ex`/`Instr` nodes no walk has
seen; allowlisted with that reason in `db8357455`. Re-running: that case PASSES,
so 3 remain:

    FAIL a_mixed_iterated_parameter_with_a_str_variable_runs_correctly
       the compiled program exited -11 printing '4\n5\n'
    FAIL test_module_level_mixed_iterated_parameter_with_a_str_variable_runs_correctly
       same
    FAIL a_str_returned_in_a_tuple_slot_runs_correctly_beside_a_list
       RuntimeError: parameter 'xs' of 'each' is passed a container at one call
       site and a str or number at another ... (the per-kind clone pass only
       covers literal arguments)

The first two are a live SIGSEGV in the word-dispatch loop arm: the test's own
docstring claims that shape was fixed ("the caller here is a function, where the
binding is seen"), so this is a REGRESSION or an uncovered variant, not a known
gap.

STANDALONE REPRO (verified): the exact source

    def each(xs):
        for x in xs:
            print(x)

    def main():
        ys = "de"
        each([4, 5])
        each(ys)

    main()

builds clean (`fire.py build` exit 0), prints `4`, `5`, and then dies with
SIGSEGV -- shell reports 139. Repro file:
`/Users/mrs/.hermes/cache/scratch/iter_mixed.mojo`.

**Root cause, pinned by lldb.** The crash frame is not the word-dispatch arm:

    frame #0: libmojostdlib.arm64.dylib`mojo_list_get_boxed + 324
       ->  ldr  x1, [x0, x6]
    EXC_BAD_ACCESS, address=0x6564

`0x6564` is the ASCII bytes of `"de"`. So the loop ran the `MojoList *` arm with
the STRING's own bytes as the list pointer -- i.e. `xs` was typed `MojoList *`,
exactly the guess the test's docstring says was fixed. Confirmed the trigger is
the MIXED call sites, not the string: the same def called ONLY with the str
variable (`/Users/mrs/.hermes/cache/scratch/iter_str_only.mojo`) builds, prints
`d` and `e`, and exits 0. Adding `each([4, 5])` beside it turns the second call
into a segfault.

That matches the mechanism in `_gmi_apply_call_site_param_evidence`
(`module_gen.py:246`): it overrides a use-derived container type only when the
call sites are UNANIMOUS, and "one ambiguous or absent call site leaves the
inference exactly as it was". With a list and a str both passed, the evidence is
ambiguous, so `_infer_param_types`' `MojoList *` stands. The fix belongs there
(or in the iterable-consuming inference): list+str evidence is not "no answer",
it is proof the parameter must be the kind-neutral word, since the runtime word
dispatch iterates both.

### 2026-11-23: FIXED (2 of the 3 cases)

`_gmi_apply_call_site_param_evidence`'s not-unanimous branch now reads MIXED
container+str evidence as the answer it is: the parameter is retyped to the
kind-neutral `int64_t`, and the choice is recorded in a new
`gen._mixed_kind_params[fname]` set. Recording it matters -- writing the table
alone did nothing, because `_gmh_reconcile_param_container_kinds` runs later and
promotes any int-word slot back to its container guess; both of its loops now
skip a mixed-evidence slot.

Measured on the repro above: prints `4`, `5`, `d`, `e` and exits 0 (was SIGSEGV
139). Re-running the job with the switch off: the two SIGSEGV cases
(`a_mixed_iterated_parameter_with_a_str_variable_runs_correctly` and its
module-level twin) now PASS -- 3 failures -> 1.

The remaining one,
`a_str_returned_in_a_tuple_slot_runs_correctly_beside_a_list`, is a different
shape: its str arrives through a TUPLE-UNPACK target (`s, n = pair()`), which is
not a literal, so the mixed-evidence arm never sees a `char *` for it. It still
raises the `_gmh_refuse_mixed_container_params` refusal -- whose stated reason
("the `int64_t` box cannot tell a `MojoList *` from a `char *`") is now false,
since the word dispatch does exactly that. Next step is to extend the tuple-slot
exemption to a slot whose callee returns a str beside a scalar, or to drop the
refusal for a param the call sites prove mixed.


- **Last known working:** `128bc1eb82` integrate fix-proof-fix-gate-type-string-ratchet
- **First known not working:** `8bc7bb14af` integrate bug-codegen-per-file-from-import-calls-m
- **Seen red in the full gate at:** `8bc7bb14af` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8bc7bb14.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-gimple.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
