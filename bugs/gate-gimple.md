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
gap. A standalone `fire.py build` repro of the exact source does NOT reach it --
it dies earlier on the unrelated `FormatStruct` blocker in the stdlib, so the
suite's dylib path is what gets far enough. The job was re-disabled (switch
restored) because it still fails; delete it only when all three are fixed.


- **Last known working:** `128bc1eb82` integrate fix-proof-fix-gate-type-string-ratchet
- **First known not working:** `8bc7bb14af` integrate bug-codegen-per-file-from-import-calls-m
- **Seen red in the full gate at:** `8bc7bb14af` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8bc7bb14.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-gimple.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
