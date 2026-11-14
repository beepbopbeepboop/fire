# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/fix-merge-bug-mid-diagnostics-binding-deferrals-pa-3` (task `fix-merge-bug-mid-diagnostics-binding-deferrals-pa-3`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/fix-merge-bug-mid-diagnostics-binding-deferrals-pa-3`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/memory/owned_pointer.mojo`
- `std/runtime/_asyncrt.mojo`
