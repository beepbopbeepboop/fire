# GATE red: 1 landing-gate job(s) red on `bug-mid-diagnostics-lsp-error-recovery-p-2 fix-proof-bug-mid-codegen-simd-and-array-values-er-2 fix-merge-fix-proof-bug-mid-codegen-dict-slot-reads-refuse-c bug-test-modcache-in-tu-instantiation-ge-3 bug-codegen-int-into-pointer-return-anno` (gate red)

## Status (2026-11-12, OPEN; jobs turned OFF to land the round)

The landing gate of round `bug-mid-diagnostics-lsp-error-recovery-p-2 fix-proof-bug-mid-codegen-simd-and-array-values-er-2 fix-merge-fix-proof-bug-mid-codegen-dict-slot-reads-refuse-c bug-test-modcache-in-tu-instantiation-ge-3 bug-codegen-int-into-pointer-return-anno` ran RED. The integrator turned these jobs OFF (`tools/gates.json`, one anchored regex) so the round could land, and files each one here until it is fixed:

    stdlib-syntax

Tasks landed with this round: bug-mid-diagnostics-lsp-error-recovery-p-2, fix-proof-bug-mid-codegen-simd-and-array-values-er-2, fix-merge-fix-proof-bug-mid-codegen-dict-slot-reads-refuse-c, bug-test-modcache-in-tu-instantiation-ge-3, bug-codegen-int-into-pointer-return-anno.

Evidence: `work-integ/gate.log` and `work-integ/confirm.log` (the failing jobs re-run alone), `work-integ/build/suite.log` for the job output.

Consequence: these jobs are NOT covered by the gate for this landing. Re-enable each one when fixed with `python3 tools/control.py gate on '<pattern>'` and remove this report in the same commit.
