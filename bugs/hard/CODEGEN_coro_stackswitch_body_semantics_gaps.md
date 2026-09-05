# CODEGEN (A3 stack-switch): 4 further generator-body semantic gaps found
via the §5.5 cutover's real behavioral test suite

## Status

**Partially fixed 2026-09-05** (see per-issue markers below):

- **#1 (`finally` in a loop over-runs its counter) — FIXED.**
- **#2 (`finally` after a `yield` following an early consumer `break`) — FIXED.**
  Both had the same single root cause in `gimple_gen_stmts.py`'s
  `_gen_stmt_TryStmt` (NOT in `gimple_gen_coro.py` or the A3 runtime —
  the try/finally lowering is plain ordinary codegen that the
  stack-switch model runs verbatim on the coroutine's own real stack).
  On the normal (no-exception, no-early-return) fall-through out of a
  `try` body, control fell straight through the `bb_finally:` label
  (running the finally body once) and THEN hit the `elif not
  _had_terminal:` branch that re-ran the finally body inline — so every
  plain `try: … finally: …` that fell off the end of its try body ran
  its `finally` **twice**. Standalone that just double-counts whatever
  the finally mutates (#1: `cleanups` 3→5); wrapped in a `while` loop
  whose loop variable is bumped in the finally it also **skips loop
  iterations** (#2: `i` jumps 0→2 in one pass, so the consumer's
  `break` at `x == 2` fires before `1` is ever yielded). A
  `try/else/finally` fall-through ran the finally **three** times
  (fall-through into `bb_finally`, inline re-run, then again at the end
  of the `else` block). Fixed by giving the normal path an explicit
  jump over the early-return `finally` block to a single dedicated
  normal-path `finally` landing pad (or straight to `bb_else`, which
  runs the finally itself), so `finally` now runs exactly once on every
  path. Regression tests: `generator_try_except_finally_runs_every_time`,
  `generator_try_finally_survives_early_break` (the two repros below),
  plus new `generator_try_else_finally_counts_once` and
  `generator_try_finally_early_return_runs_once` in
  `test_gimple_generator_runner.py`. Full CLAUDE.md gate (0–4) re-run
  green; stdlib dylib skip count 0→0, `compile_stdlib.py` U-count
  unchanged.

- **#3 — NARROWED 2026-09-05.** The *lambda* half is fixed: the ordinary
  codegen path lifts a `lambda` to a top-level C function, so a lambda
  value stored in a local and called later now works for 0-/1-/2-param
  lambdas, a lambda re-bound per if/else branch, and a lambda passed as
  an argument (see `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.
  md`'s 2026-09-05 status + the new `generator_*_lambda_*` regression
  tests). What remains is a **bound-method value** stored in a local
  then called (`getpos = self.tell; ... getpos()`) — this is
  codegen-wide (reproduces in a plain non-generator method, prints only
  the lambda-branch result and silently drops the bound-method branch),
  not generator-specific. Needs a real first-class bound-method-value
  representation in the ordinary codegen path. `MOJO_CORO=cpp` remains a
  correct fallback for that shape.

- **#4 (heterogeneous `.pop()` + `isinstance` re-read each iteration) —
  STILL OPEN.** Not attempted here (a narrower, likely single-site
  `isinstance`/`.pop()` type-tag re-read bug — good next target).

`MOJO_CORO=cpp` (escape hatch) remains a correct implementation for #3
and #4; §5.6 (deleting the cpp emitter) should still wait on those two.

--- original filing (2026-09-05) ---

New, found 2026-09-05 running `test_gimple_generator_runner.py` against
the §5.5 cutover (doc/COROUTINE.html — `MOJO_CORO=stackswitch` now
default). `MOJO_CORO=cpp` (escape hatch) unaffected — all four were
real, previously-passing tests under the old cpp-path emitter.

## 1. `finally` inside a loop over-runs its own counter  — FIXED 2026-09-05

```mojo
def gen_with_cleanup():
    cleanups = 0
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise KeyError("x")
            yield i
        except KeyError:
            yield -1
        finally:
            cleanups = cleanups + 1
        i = i + 1
    yield cleanups

def main():
    for x in gen_with_cleanup():
        print(x)
```
Expected `0\n-1\n2\n3\n` (`cleanups` incremented exactly once per loop
iteration, 3 total). Got `0\n-1\n2\n5\n` — `cleanups` ends at 5, meaning
the `finally` block runs (or its assignment applies) MORE than once per
iteration for at least one iteration. Likely interacts with the
real-stack setjmp/longjmp exception mechanism + the coroutine suspend/
resume boundary landing INSIDE the `try` (a `yield` mid-try, per A3's own
design goal that `try/finally` "just works" across a real suspend) —
something about resuming back into the `try` after a `yield` appears to
re-enter (or double-count) the `finally` on a later loop pass.

## 2. `finally` after a `yield`, following an early consumer `break`  — FIXED 2026-09-05

```mojo
def gen_finally_early_exit():
    i = 0
    while i < 100:
        try:
            yield i
        finally:
            i = i + 1

def main():
    for x in gen_finally_early_exit():
        if x == 2:
            break
        print(x)
```
Expected `0\n1\n` (yields 0, prints it; yields 1, prints it; yields 2,
consumer breaks without printing — generator's own `destroy()` then runs
`finally` once more as cleanup, but that's after the loop, doesn't affect
this stdout). Got only `0\n` — the SECOND resume (to get from the `finally`
after yielding 0, back around the loop, to yielding 1) never produces
output. Either the generator's `.resume()` call after the first `.value()`
read isn't correctly continuing execution past the `finally`, or the
loop's own re-entry into `try` on the second pass silently exits early.

## 3. A lambda / bound-method value assigned to a local, then called,
   inside a generator body

```mojo
class Ticker:
    def __init__(self, start: Int):
        self.value = start
    def tell(self):
        return self.value
    def run(self, use_lambda: Int):
        if use_lambda:
            getpos = lambda: 42
        else:
            getpos = self.tell
        pos = getpos()
        yield pos

def main():
    tk = Ticker(7)
    for x in tk.run(1):
        print(x)
    for x in tk.run(0):
        print(x)
```
Expected `42\n7\n` (first call takes the lambda branch, second the bound-
method branch). Only `42\n` printed — the second call (`tk.run(0)`,
`getpos = self.tell` then `getpos()`) produces nothing, suggesting the
bound-method-as-value branch either crashes silently, yields no value, or
the whole second generator instance never runs to its `yield`. Assigning
a closure/bound-method VALUE to a local inside a coroutine body, then
calling it later through that local, is the specific shape at fault —
calling `self.tell()` directly (no intermediate variable) is a
structurally different, already-working shape elsewhere in this suite.

## 4. Heterogeneous-typed values popped off a shared stack lose their
   per-pop identity

```mojo
def walker():
    stack = [(1, 2)]
    stack.append("leaf")
    stack.append((3, 4))
    while stack:
        top = stack.pop()
        if isinstance(top, tuple):
            a, b = top
            yield a + b
        else:
            yield 99

def main():
    for x in walker():
        print(x)
```
Expected `7\n99\n3\n` (pop `(3,4)`→7, pop `"leaf"`→99, pop `(1,2)`→3 —
LIFO order). Got `99\n99\n99\n` — every iteration takes the `else` branch
regardless of what was actually popped, as if `isinstance(top, tuple)`
(or `top`'s own re-read after each `.pop()`) is stuck evaluating against
whichever type answered `True`/`False` first, rather than the CURRENT
popped value each iteration.

## Impact

All four are real generator-body semantic regressions specific to the
stack-switch backend that became the default in §5.5 — none of these
constructs are exotic (loop + try/finally, a lambda assigned to a local,
a heterogeneous list + `isinstance`), and all four passed under the old
cpp-path emitter. `MOJO_CORO=cpp` remains a fully correct escape hatch
for any Mojo program hitting one of these shapes today; per this
session's broader finding (see the sibling yield-kind-inference and
iterator-protocol docs), §5.6 (deleting the cpp-path emitter) should
wait until this cluster of real behavioral gaps is closed, since cpp
is currently the only CORRECT implementation for all four shapes above.

## Not attempted here

None of the four were root-caused to a specific `gimple_gen_coro.py`/
ordinary-codegen line in this pass — this doc is a capture-and-flag from
running the real test suite, not a diagnosis. Whoever picks this up
should start from #4 (heterogeneous stack pop) as the most likely to
have a narrow, single-site root cause (probably a `MojoList.pop()`
result's type-tag not being re-read fresh each loop iteration, or
`isinstance()`'s own lowering caching a stale check), then #1/#2 (both
point at the same `try`/`finally`-across-suspend mechanism, likely
sharing a root cause), then #3 (closure-value-as-local, likely a
narrower, unrelated gap in how a captured callable's identity survives
being stored in and re-read from a local variable).
