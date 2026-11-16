# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

## Done when

The red is three stdlib modules whose generated C called a suffix-less dunder
symbol that no overload defines (`implicit declaration of function`), because
`_emit_struct_method_prototypes` stopped declaring the bare dunder symbol for
an overloaded method. The three call-site paths must name a concrete overload:

- `BinaryHeap[Int](copy=heap)` — the implicit copy constructor;
- `StringDict[StringSpan, Int][StringSpan("fruit")]` — two same-arity
  `__getitem__` overloads that erase to the same C signature;
- `with TempEnvWithCleanup(...)` — the one-argument `__exit__(error)`.

Quick test:

    python3 test_stdlib_syntax_dunder_overloads.py

It transpiles exactly those three stdlib modules through `transpile_file` (the
same stage `stdlib-syntax` runs) and fails before the fix with the gate's own
`implicit declaration of function` errors.

## Gate ledger

- **Last known working:** `46ef25daa9` integrate fix-replan-compile-fail-tools-c-analyzer-c-analyzer
- **First known not working:** `b0910af726` codegen: call the real `_eval_const_int`, not a name GimpleGen never had
- **Seen red in the full gate at:** `bec49b8101` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-bec49b81.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-stdlib-syntax.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
