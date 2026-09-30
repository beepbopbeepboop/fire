# FORMAL: nested comprehension exits nondeterministically (wrong value, or SIGSEGV)

## Status — OPEN. `x86-containers`' `nested-comprehension` case is marked
`expect=` for this and nothing else.

Four runs of the same binary, same input, from one build:

```
run 0 rc= -11      (SIGSEGV)
run 1 rc= 58
run 2 rc= 58
run 3 rc= 58
```

`58` where the answer is `100`. The exit code IS the program's return value
(this harness reports the return as the status), so the value itself is
wrong, and sometimes the process dies instead. Nothing in the output
distinguishes the two.

Verified **pre-existing** at commit `12336514` with the multi-clause
comprehension fix stashed, so it is not a regression from that work.

## Why this is its own bug, not the comprehension bug

The gimple path (`python3 fire.py --jit`) gets this case **right** and gets
it right stably: `[i + j for i in range(5) for j in range(5)]` yields
`len == 25` and `sum == 100` on every run, matching the interpreter.

This test does not use the gimple path. `test_x86_64_containers.py` calls
`formal.build.compile_formal(..., arch="x86_64")`, which is a **separate
proof-oriented backend** — it emits its own code carrying `base_addr`,
`labels` and `cond_branches` for the proof path, and does not share
`gimple_codegen`'s emitter. So the two engines can disagree here without
either being wrong about the other, and a fix in `mojo/backend_gimple/`
cannot reach this failure.

That is also why the previous `expect=` reason was misleading: it blamed
nested comprehension, which pointed at a bug doc that has since been
deleted, and which never described this backend.

## Scope

Only this one case is unstable; the other 44 in the file pass. So it is not
a blanket formal-backend breakage — something about this shape (a nested
comprehension materialised into a list, then iterated, then accumulated)
trips uninitialised memory or a bad frame in the formal emitter.

## Next step

Build the case with `prove=False` and read `result["code"]` from
`compile_formal`'s return (it is the formal backend's C, bytes) for the
nested-comprehension shape, and diff it against the same shape without the
second `for` clause. Nondeterminism across runs of one binary means
uninitialised or out-of-range memory, so run the build under
`-fsanitize=address,undefined` if the backend's compiler invocation can take
it — that names the read directly instead of by inspection.

Once it is fixed, drop the `expect=` marker on `x86-containers` in
`tools/suite.py`; the suite's anti-rot rule will otherwise report the test as
a failure for PASSING, which is the intended way a marker retires.
