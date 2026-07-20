# PARSE_FAIL: `case pattern if condition:` match-case guard clause unsupported

## Status
Fixed 2026-07-20.

## Root cause and fix

Two independent bugs, both required for the repro in this doc to work:

1. **Parser (`mojo_compiler.py`, `_parse_match_case`).** The guard-parsing
   code (`if self._is_kw("if"): guard = self._parse_expr(0)`) already
   existed and `MatchCase` already had a `guard` field — but it was dead
   code. The pattern itself was parsed with `self._parse_expr(0)`, and
   `_parse_expr`'s `min_prec == 0` branch treats a top-level `if` as the
   start of a Python ternary conditional expression (`X if COND else Y`),
   so it greedily consumed the guard's `if` expecting a matching `else`,
   producing `Expected KW got COLON` at the `:` that ends the case. Fixed
   by parsing patterns at `min_prec=1` instead (`self._parse_expr(1)`,
   both the first pattern and the comma-separated or-pattern loop) — the
   same trick already used for comprehension `for`/`if` clauses elsewhere
   in the same file, which leaves a top-level `if` untouched for the
   caller to handle.

2. **Interpreter (`myinterpreter.py`, `execute_MatchStmt`).** Even with
   the parser fixed, `case n if n > 0:` failed with `NameError: name 'n'
   is not defined`. This codebase's `match` is deliberately switch-style
   equality dispatch, not full PEP 634 structural matching (see
   `MatchStmt`'s docstring in `mojo_compiler.py`) — bare names in patterns
   were always looked up as existing variables/constants, never bound.
   But a guard clause is meaningless without something to guard on, and
   the bug's own repro (`case n if n > 0:`) requires `n` to capture the
   subject's value. Added a narrow, additive capture: in
   `execute_MatchStmt`, a bare-name pattern that is **not already bound
   anywhere in scope** (checked via a new `Scope.has()` method) is now
   treated as a PEP 634 capture pattern — it always matches and binds the
   subject's value via `Scope.define()` (current scope only, not
   `Scope.set()`, which would walk up and leak the binding into the
   global scope on first use and corrupt every later call). Every
   pre-existing use of `match`/`case` in this codebase referenced already
   *bound* constants (e.g. `case NODE_FUNCTION_DECL:`), so this is
   purely additive and doesn't change dispatch for any previously-working
   case.

### Files changed
- `mojo_compiler.py`: `_parse_match_case` (pattern parsing at `min_prec=1`
  instead of `0`); `MatchStmt`'s docstring updated to describe the new
  narrow capture exception.
- `myinterpreter.py`: `Scope.has()` added; `execute_MatchStmt` extended
  with the capture-pattern branch described above.

### Compiled path (`gimple_codegen.py`)
`_gen_stmt_MatchStmt` already had `MatchCase.guard` lowering wired up
(pre-existing, apparently added when the `guard` field was added but
before the parser bug blocked reaching it) — it correctly lowers a guard
combined with an equality-dispatch pattern (an already-bound constant) or
the wildcard `_`. It does **not** implement the new bare-name
capture-pattern semantics added to the interpreter above: it always
lowers a pattern via `subject == pattern`, which requires the pattern to
already be a valid, defined C expression — a bare undefined name would
need a new declared/assigned C temp and type inference, which the
gimple lowering has no machinery for. Left as a follow-up rather than
expanding this fix's scope; `case n if cond:`-style capture-with-guard
only works in the interpreter (`mojo.py run`) for now, not the compiled
path.

### Verification (this worktree, commit `1b22f11` base)
- Repro from this doc: `f(5)` → `"positive"`, `f(-5)` → `"other"`. Pass.
- Guard referencing a captured name with a boolean-chain guard
  (`case x if x > 0 and x < 10:`), multiple guarded cases where an
  earlier guard is false and a later one true, and a guard combined with
  a wildcard fallback after it: all pass. (A true chained comparison,
  `0 < x < 10`, hit a **separate, pre-existing** bug — chained
  comparisons evaluate incorrectly in this interpreter — so guard tests
  used explicit `and` instead; not touched here, out of scope.)
  Tuple/sequence patterns (`case (a, b):`) are not implemented by this
  codebase's match at all (deliberately, per `MatchStmt`'s docstring), so
  that combination wasn't tested, per the original work order.
- `python3 test_gimple.py`: 159 passed, 0 failed, both before and after
  (this worktree's baseline is 159/0, not 161/0 — it's on an older base
  commit than assumed; no regression either way).
- `python3 test_module_cache.py`: 58 passed, 0 failed, both before and
  after (baseline 58/0 in this worktree, not 64/0; no regression).
- `make check-selfhost`: passes (1 passed, 0 failed) after the change.
- From-scratch stdlib dylib build skip count: `0` before, `0` after
  (`rm -f build/libmojostdlib.dylib && python3 -c "import
  build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" | grep -c '^
  skip'`) — no regression.

## Original report

Found 2026-07-20, re-testing the backlog for still-live parser bugs.

## Reproduction
```mojo
def f(x):
    match x:
        case n if n > 0:
            return "positive"
        case _:
            return "other"
print(f(5))
print(f(-5))
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:3:15: Expected KW got COLON(':')
```
The parser's `case` clause handling parses a pattern, then evidently tries to
continue parsing whatever comes after `if` as a ternary/conditional
expression (expecting a matching `else`), rather than recognizing `if` in
this position as a match-case **guard clause** (a boolean expression that
must also hold for the case to match, terminated by `:` — not a ternary
expression at all).

## Expected Behavior
`f(5)` should print `"positive"`, `f(-5)` should print `"other"` — the guard
clause should be evaluated (in the scope where the pattern's bindings are
already bound) after a successful pattern match, and only proceed into that
case's body if the guard is also truthy; a false guard should fall through
to the next `case`.

## Relationship to prior work
This codebase already has real `match`/`case` support (see BUG-2026-002/003
in the sibling mojolib project's bug tracker: "mojo.py does not support
match/case pattern matching" — fixed). This is a narrower gap in that
existing support: the *guard clause* form specifically (`case PATTERN if
CONDITION:`), which is valid, commonly-used Python/Mojo match syntax (seen
in the CPython 3.14 stdlib scan that populated this `bugs/` directory, e.g.
`dataclasses.py`'s `case iterable if not hasattr(iterable, '__next__'):`).

## Files Likely Affected
- `mojo_compiler.py` — wherever `case` clauses are parsed (search for
  `match`/`case` handling, likely something like `_parse_match_stmt`/
  `_parse_case`). Needs to recognize an optional `if <expr>` after the
  pattern and before the `:`, storing it as a guard condition on the case
  AST node.
- `myinterpreter.py` — wherever `match`/`case` execution happens (evaluate
  the guard expression, with pattern bindings already in scope, after a
  successful structural match, before committing to that case's body).
- Check whether `gimple_codegen.py` (the compiled path) has separate
  match/case lowering that also needs the guard-clause case — if the
  interpreter fix doesn't naturally cover it, note it as a follow-up rather
  than expanding scope (this report is about `mojo.py run`, per this
  session's default `bugs/` triage — see `PARSE_FAIL_case_guard_clause`'s
  sibling reports for the established pattern of interpreter-first, compiled
  path noted separately if broken).
