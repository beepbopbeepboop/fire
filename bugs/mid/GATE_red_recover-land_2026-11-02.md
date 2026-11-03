# GATE red: 4 landing-gate job(s) red on `recover-land` (gate red)

## Status (2026-11-02, OPEN; jobs turned OFF to land the round)

The landing gate of round `recover-land` ran RED. The integrator turned these jobs OFF (`tools/gates.json`, one anchored regex) so the round could land, and files each one here until it is fixed:

    bootstrap-stage1-transitive
    bootstrap-stage2-dumps
    bootstrap-stage3-dumps
    mojoc

Tasks landed with this round: recover-land.

Evidence: `work-integ/gate.log` and `work-integ/confirm.log` (the failing jobs re-run alone), `work-integ/build/suite.log` for the job output.

Consequence: these jobs are NOT covered by the gate for this landing. Re-enable each one when fixed with `python3 tools/control.py gate on '<pattern>'` and remove this report in the same commit.
