# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. First seen red when branch `work/bug-codegen-int-into-pointer-return-anno` (task `bug-codegen-int-into-pointer-return-anno`) was integrated; that branch is retired (archived at `refs/archive/work/bug-codegen-int-into-pointer-return-anno`), but its commit `5ccd8aa18` ("codegen: refuse int/bool return arms in an annotated pointer function", merged by the integrator in `73f237132`) is on master.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on master: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.
`stdlib-syntax` is OFF for the backlog in `tools/gates.json`; the landing gate is refused while every landing job is OFF. Re-enable it with `python3 tools/control.py gate on '^(stdlib\-syntax)$'` once this is green.

Failing files at the time:
- `std/builtin/bool.mojo`
