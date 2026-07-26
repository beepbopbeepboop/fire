# CODEGEN: compiled `async def` calls eagerly run to completion instead of returning an awaitable, unlike real Python and the interpreter

## Discovery context

Found via independent hand-verification of Step B of the compiled-path
async/await codegen project (commit `9db1713`, "Compile the simplest real
async def to C++20 coroutines"). This is a real semantic correctness issue,
not just an out-of-scope refusal — worth fixing before Step C (real
`await`) builds further on top of the current design.

## Repro

```python
async def f():
    return 42

def main():
    x = f()   # in real Python: x is a coroutine OBJECT, NOT 42
    print(x)

main()
```

- **Real CPython** (confirmed directly, not assumed):
  ```python
  >>> async def f(): return 42
  >>> async def main():
  ...     x = f()
  ...     print(type(x)); print(x)
  >>> asyncio.run(main())
  <class 'coroutine'>
  <coroutine object f at 0x...>
  ```
  Calling an async function never runs its body immediately and never
  produces the result directly — it returns a coroutine object. Getting
  the actual value requires `await f()` (inside an `async def`) or driving
  it explicitly via something like `asyncio.run(f())`.
- **This project's interpreter** (`myinterpreter.py`'s `MojoCoroutine`,
  from the earlier interpreter-side async milestones) already matches
  this correctly: `python3 mojo.py run repro.py` prints
  `<myinterpreter.MojoCoroutine object at 0x...>` for `x`, exactly
  mirroring real Python's "you get a coroutine object back" semantics.
- **The compiled path** (`python3 mojo.py build repro.py -o out && ./out`)
  prints `42` directly — `x = f()` is compiled as construct→schedule→run
  the whole coroutine to completion→read its result, all fused into the
  assignment's own lowering, with no `await` involved anywhere.

## Root cause

Commit `9db1713`'s own design (quoting its report): "Calling convention:
... deliberately no `<base>_resume` ... any value-consuming call site
(`x = f()`, `print(f())`) gets construct→schedule→run→read→destroy fused
into one expression's lowering." This was a deliberate choice for this
step's narrow scope (no `await` exists yet to give the "run it" signal),
but it conflates two DIFFERENT things that must stay distinct once real
`await` support (Step C+) exists: "I have a reference to a not-yet-started
computation" (calling `f()` alone) vs. "actually run this to completion and
give me the value" (`await f()`, or an explicit top-level driver).

## Impact

This is a foundational correctness issue for every later step in this
project. If `f()` alone already runs the coroutine to completion, then:
- `await f()` (Step C+) would have nothing meaningful left to await on —
  the work is already done by the time `await` sees it, defeating the
  entire point of suspension/composition.
- Real code that intentionally holds a coroutine WITHOUT running it yet
  (e.g. to pass to a future `gather`-equivalent, or to schedule as a
  task) cannot be expressed at all — every reference to an async call's
  result forces immediate, eager execution.
- This diverges from the interpreter's own already-correct behavior,
  meaning identical source code behaves differently (and, worse,
  *plausibly* differently — `42` looks like a completely reasonable
  result, making this the kind of mismatch that's easy to miss without
  deliberately comparing against real Python/the interpreter, exactly as
  happened here).

## Suggested fix

`f()` alone (any reference to it — assignment, argument, etc.) must
construct the coroutine WITHOUT scheduling/running it — mirroring the
interpreter's `MojoCoroutine` (calling doesn't run the body) and the
already-correct generator convention (`<base>_start()` doesn't run
anything either, matching `initial_suspend()==suspend_always`). The
"actually run this to completion" step needs to be a SEPARATE, explicit
operation — likely deferred to Step C+ once `await`/a top-level run
driver exists to provide that signal. For THIS step's own narrow target
(no `await` anywhere yet), the right fix is probably: since there's
genuinely no way to observe/consume an async function's result without
either `await` (not yet built) or an explicit top-level driver (not yet
built), correctly narrow the accepted shape further — a module is only
eligible for this step's compilation path if the async function's result
is either (a) never consumed at all (matching the interpreter — `f()`
alone as a bare statement, already correctly not running, per the report),
or (b) refuse-and-honestly-fall-back for any shape that tries to consume
the result without an actual mechanism (`await`/top-level driver) to do so
correctly, rather than fusing eager execution in as a substitute. Given
this may substantially narrow what Step B can usefully demonstrate on its
own, it's reasonable to fold "how do you actually get a value out of an
async function you called" into Step C itself (which is building real
`await` anyway) rather than solving it awkwardly in Step B — use judgment
on the cleanest way to restructure, but the eager-execution-on-consumption
behavior must not ship as-is.
