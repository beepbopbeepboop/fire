# Gate: `native-dumpfull` is red because the native compiler's output differs from the reference's

**Job:** `native-dumpfull`. Filed 2026-11-25 by the full gate at `ec1c68c09` (165 passed, 5 failed; the other three were fixed the same day).
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green.

The self-hosted `mojoc` now builds, starts and writes valid text (`selfhost` and `mojoc` pass), but its `.ci` is not the
reference's, so this job fails: see `bugs/hard/GIR_selfhost_compiled_output_diverges.md` for the measured divergences, the
debugging method (`tools/selfhost_probe.py`, `lldb` with ASLR on) and the next step. This job was green on 2026-10-25, when the
bootstrap chain last passed; the changes since that touch what the compiled compiler does are the presence bits (11-01), the IR
(11-13..11-21), stage 5c tagged parameters (11-20..) and the solver (11-24).

Not disabled on purpose: the gate should keep saying it is red. Reproduce: `python3 tools/suite.py native-dumpfull`.
