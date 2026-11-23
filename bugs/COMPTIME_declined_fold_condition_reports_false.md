# COMPTIME: a foldable-shaped condition whose fold DECLINES is compiled as FALSE

**Area:** `mojo/middle/comptime.py` (`eval_const`, `eval_const_bool`,
`eval_const_bool_state`, `_const_foldable`).
**Where the branch shows:** a module-level `if <expr>:` (and every other
`eval_const_bool_state` caller) takes its **else** arm when `<expr>` is a
constant the folder declines to evaluate, deleting the then-arm before
emission. CPython prints the then-arm.

This is the residual of the class the `not` and signed/arithmetic-float fixes
closed: `eval_const_bool_state` is tri-state, but it derives
"false" from two different situations — a value that folded to falsy, and a
shape `_const_foldable` calls foldable whose fold answered `None`. The second
is read as CONST_FALSE, so **every operator the folder does not implement is a
silent wrong branch** on a constant expression. `eval_const` now agrees with
CPython for `not`, unary `+`/`-` and arithmetic on floats (see
`gimple_module_constant_not_condition` and
`gimple_module_constant_float_condition` in `test_gimple_runner.py`), but
container/text operations are still unimplemented, so they still miscompile.

## Measured (this tree, `python3 test_gimple_runner.py` helpers)

Each shape below is the sole condition of a module-level `if`/`else` that
prints `THEN`/`ELSE`; `compiled` is the gimple executable, `cpython` is the
oracle on the same source.

| condition | CPython | compiled |
|---|---|---|
| `[1] + [2]` | THEN | ELSE |
| `[1] + []` | THEN | ELSE |
| `(1,) + (2,)` | THEN | ELSE |
| `(1,) * 2` | THEN | ELSE |
| `"ab" * 2` | THEN | ELSE |
| `{1: 2} \| {3: 4}` | THEN | ELSE |
| `{1: 2} \| {}` | THEN | ELSE |

Controls that already agree, and show the boundary is exactly "operator not in
the folder": `[] + []`, `() * 2`, `"ab" * 0` (the empty results happen to be
falsy, so a declined fold and the right answer coincide), `{1} | {2}` and
`{1} - {1}` (those are *not* folded at all — `_const_foldable` has no
set-literal arm, so they answer CONST_UNKNOWN and run at runtime), and
`1 if True else 0`, `abs(-1)`, `min(1, 2)`, `int(0.5)`, `"a".upper()`,
`len([1, 2])`.

## Why the shape is foldable

`_const_foldable` says "yes" from the SHAPE: a list/tuple/dict literal of
foldable elements is foldable (`comptime.py`, the `TupleExpr`/`ListExpr`/
`DictExpr` arms), and a `BinaryOp` is foldable when both operands are
(`comptime.py`, the `BinaryOp` arm). `[1] + [2]` therefore enters
`eval_const_bool_state` as foldable, `eval_const` has no list `+` arm, the fold
answers `None`, and `eval_const_bool_state`'s last two lines turn that into
`CONST_FALSE`.

## Two ways to close it, and why neither is landed with this doc

1. **Teach `eval_const` the operators** (the shape the `not`/float fixes took):
   list/tuple `+`, sequence `*` int, dict `|`, then any further operator
   found the same way. Correct values, no change in what is reported when the
   folder genuinely cannot decide — but it is one arm per operator forever,
   and the next Python operation anyone writes reopens the class.

2. **Stop deriving FALSE from a declined fold** — the root cause. In
   `eval_const_bool_state`, `eval_const_bool(...) is None` should answer
   `CONST_UNKNOWN`, leaving CONST_FALSE for a value that actually folded
   falsy. One place, whole class closed at once. The risk is exactly what
   CONST_FALSE currently buys: a module-level condition the folder declines
   today emits ONE arm, and under CONST_UNKNOWN it emits BOTH, so any arm with
   host-specific names that "worked" by being pruned would start to compile.
   The docstring's `1 // 0` rationale ("a condition that divides by zero at
   compile time has no meaningful branch either way") is the one behaviour
   change to decide on: at runtime CPython raises, so UNKNOWN would raise
   there instead of silently choosing the else arm.

   This is the option to take, but it changes what the compiled path emits for
   every declinable condition, so it needs the stdlib compile (`skip <module>:`
   count and `FAILED: N (E expected, U unexpected)`) compared before/after —
   the exact silent verdicts `CLAUDE.md` says a type/fold change can regress
   without failing anything.

## Status 2026-11-22: option 2 measured, and it is blocked by 8 stdlib modules

Option 2 was implemented and measured (the `eval_const_bool_state` change:
`eval_const_bool(...) is None` -> CONST_UNKNOWN). Results:

* The doc's whole table passes -- all 7 rows now print CPython's arm, checked
  with `test_gimple_matches_cpython` (the oracle, not a hand-written
  expectation), so the class IS closed by the change.
* `test_gimple_runner.py`: 570 cases passed, 0 failed, before the run hit its
  40-minute timeout (658 total).
* `test_suite.py`: 458/0.
* `compile_stdlib.py`: **FAILED: 8 (0 expected, 8 unexpected)** -- against a
  recorded baseline of 610/0 unexpected. All 8 are `std/collections/deque.mojo`
  and `std/collections/interval.mojo`, failing with
  `error: non-trivial conversion in 'integer_cst'` (deque.mojo:798 is
  `raise "ValueError: Given element is not in deque"`).

So the change is exactly the regression the doc predicted: emitting BOTH arms
for a declinable condition compiles code that used to be pruned, and that code
does not build. **Option 2 is not landable until those 8 are understood** --
either the newly-emitted arms are fixed, or the UNKNOWN answer is narrowed to
the shapes that are safe. The change was reverted, not landed.

Option 1 (teach `eval_const` the operators) is untested and has its own risk:
`comptime.py` is compiled by the self-hosted compiler, so `l + r` on lists /
`{**l, **r}` must be constructs that backend supports, which wants a
`make bootstrap` byte-compare before it is trusted.

### The 8 are one distinct cause, and it is latent

Measured again on HEAD (which carries `dbc3a10e9`, the same CONST_UNKNOWN
semantics), `compile_stdlib.py --roots std/collections` gives
`PASSED: 25 / FAILED: 8 (0 expected, 8 unexpected)`, and all 8 are the SAME
diagnostic at the SAME column shape: `error: unknown type name 'Format…'` at
`<module>.mojo:<line>:33` -- array.mojo:588, counter.mojo:540, deque.mojo:578,
dict.mojo:648, interval.mojo:664, list.mojo:638 and two more. (An earlier
measurement with a hand-written variant of the same change instead produced
`non-trivial conversion in 'integer_cst'` at a `raise "<string>"`; the point is
unchanged -- one cause, and it only appears once the pruned arm is emitted.)

The truncation is the harness's. The name is a `Format…` type, and the only one
in the stdlib is `FormatStruct` (`std/format/_utils.mojo:287`), which
`array.mojo:41` imports as `import std.format._utils as fmt`. So the plausible
mechanism is: emitting BOTH arms compiles a `fmt.FormatStruct`-using path whose
imported module's declarations are not emitted, leaving the type undeclared.
Confirm with the generated C (`compile_stdlib.py --roots std/collections -v`
prints the refusal detail and the `.c` path) and find which module-level import
the pruned arm was suppressing. Note the reported position is unreliable: every
failure is at `:33` of a `comptime` local line (array.mojo:588 is
`comptime TRIVIAL_FAST_PATH_MAX_BYTES = 1024`), while the actual `FormatStruct`
reference in that file is line 1130, `fmt.FormatStruct(writer, "Array")` -- the
`#line` mapping in the generated C is pointing at the wrong source line.

It is NOT reachable standalone: `def f() -> Int: raise "boom"`,
`def f(): raise "boom"` and `def f() -> Int: raise ValueError("boom")` all build
(rc 0) on this tree. The failure appears only once CONST_UNKNOWN emits the
previously-pruned code.

## Done when

A module-level `if` over each row of the table above prints the CPython arm.
Pin it next to the two existing cases (`gimple_module_constant_not_condition`,
`gimple_module_constant_float_condition` in `test_gimple_runner.py`) with
`test_gimple_matches_cpython`, so the oracle, not a hand-written expectation,
decides. If option 2 is taken, the same test covers the whole class; add one
row for a *non-constant* condition (`if x:` with runtime `x`) to pin that
CONST_UNKNOWN still compiles both arms and behaves as before, and one for
`comptime if 1 // 0:` if the false-on-fold-error behaviour is kept.

## Exact next step

Reproduce it in one process, no gate: write the failing shape as a program with
`def main(): pass` and a module-level `if <row>:` printing `THEN`/`ELSE`, then
`from test_gimple_runner import compile_mojo_to_gimple_exe` and run the
executable beside `python3 <same file>` — the same comparison
`test_gimple_matches_cpython` makes. Then either add the `eval_const` container
arms (option 1) or change `eval_const_bool_state`'s final `return CONST_FALSE`
to `return CONST_UNKNOWN` and compare the stdlib compile's two verdict counts
against the same commit's parent (option 2).
