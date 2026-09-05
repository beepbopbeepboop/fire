# CODEGEN (A3 stack-switch): ordinary-codegen `next()`/`enumerate()` don't
recognize a `MojoGenerator *` handle as an iterable source

## Status

New, found 2026-09-05 running `test_gimple_generator_runner.py`'s real
compile+link+run suite against the §5.5 cutover (doc/COROUTINE.html —
`MOJO_CORO=stackswitch` now default). Traced to root cause; not fixed.
`MOJO_CORO=cpp` (escape hatch) unaffected — these are real, previously-
passing tests under the old cpp-path coroutine emitter.

## Repro 1 — `next()` on a list iterator inside a generator body

```mojo
def scan(xs):
    it = iter(xs)
    first = next(it)
    yield first
    for x in it:
        yield x
    yield next(it, -1)

def main():
    for v in scan([10, 20, 30]):
        print(v)
```
Under `MOJO_CORO=stackswitch`: **hard link failure**, `Undefined symbols
... "_next"`. The generated C emits a bare, undeclared call to `_next`.

Root cause: `next(it)`/`next(it, <default>)` was never really supported
by the **ordinary** (non-generator) codegen either — a standalone,
non-generator repro (`it = iter(xs); print(next(it))`) compiles and
RUNS today, but only via the generic "unknown name" weak-stub fallback
(prints `next: unavailable in compiled mode` and returns `0` — not a
real value, but at least not a link failure). Inside a stack-switch-
lowered `__mgco_scan_body`, that same weak-stub safety net doesn't apply
— the call reaches gcc as a raw, wholly undeclared `_next(...)`, so the
*same* missing feature manifests as a much worse failure mode (link
error, or in a production build, presumably the same
`__attribute__((weak))`-stub treatment other unknown names get if the
stub-emission gate is reached at all — not confirmed either way here).

The deeper point: **there has never been a real Python iterator-protocol
implementation (`iter()`/`next()`, with real cursor state and
`StopIteration`) in the ordinary codegen** — only the old cpp-path
coroutine promise/awaiter machinery implemented anything like it, scoped
to ITS OWN generator consumption. Since doc/COROUTINE.html's whole A3
design deliberately routes a stack-switch generator's BODY through the
ordinary codegen (the point of the design — near-full language coverage
for free), any real Python source using `next()`/`iter()` on a general
iterable inside a generator body now depends on a feature the ordinary
codegen never actually had.

## Repro 2 — `enumerate()` over a generator (not a list)

```mojo
def days(n):
    yield from range(1, n + 1)

def numbered(n, start):
    for i, d in enumerate(days(n), start):
        yield d * 100 + i

def main():
    for v in numbered(3, 10):
        print(v)
```
Expected `110\n211\n312\n`. Produces garbage: multi-megabyte runaway
output of what look like uninitialized-memory reads reinterpreted as loop
bounds/values (`440686985610`, `27852813`, ...) — i.e. NOT a clean
failure, an actual wrong-answer miscompile.

A structurally similar 2-generator-method composition
(`enumerate(self.iterdays(n), self.firstweekday)`, `bugs/hard/` doc
`Cal.iterdaynum` shape) is **worse**: the compiled program **hangs**
(10s timeout in the test harness, presumably a genuine infinite loop, not
merely slow) — a real product-facing hazard, not just wrong output.

Root cause (not fully traced to a single line, but the shape is clear):
`enumerate(<iterable>, start)`'s ordinary-codegen lowering (wherever it
resolves the iterable's length/cursor-advance mechanism) evidently
assumes a concrete container (`MojoList *`/similar) with a known
`len`/index-based access pattern, and has no case for a `MojoGenerator *`
handle (`_generator_var_api`-tracked) as the enumerated source — reading
whatever raw bytes happen to sit at the address it computes as if they
were valid loop-bound/element data, hence garbage output or (when the
garbage read happens to look like an always-true continue condition) an
outright hang.

## Impact

Both are the same underlying category as the sibling default-argument-
padding doc (fixed this session) and the identifier-yield-kind doc (filed
alongside this one): a stack-switch generator's body genuinely depends on
ordinary-codegen features the old cpp-path coroutine emitter happened to
implement independently, and which the ordinary path either never had
(`next()`/`iter()` real semantics) or never extended to cover a
`MojoGenerator *` source (`enumerate()`). The **hang** case (Repro 2's
2-generator-method composition) is the more urgent of the two — a
correctness bug that manifests as wrong output is bad; one that
manifests as a non-terminating compiled program is worse, and worth
prioritizing over the printf-truncation-style bugs in the sibling doc.
`MOJO_CORO=cpp` remains a fully correct escape hatch for any Mojo program
hitting either shape today.

## Not attempted here

Real `iter()`/`next()`/`enumerate()`-over-a-generator support in the
ordinary codegen is a genuine feature (real cursor state, `StopIteration`
semantics, `MojoGenerator *` as a first-class enumerable source) — not a
narrow fix, and out of scope for this investigation pass, which was
scoped to finding+documenting (with a few in-scope narrow fixes already
landed — see the default-argument-padding doc, FIXED) what the §5.5
cutover exposes, not building new iterator-protocol infrastructure.
