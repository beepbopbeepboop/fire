# INTERP: starred name in a for-loop unpacking target fails to parse

## Status
Fixed (2026-07-20)

## Fix
Two changes, both consolidating with existing shared machinery rather than
adding a parallel implementation:

1. `mojo_compiler.py`'s `_parse_for` — the inner `_parse_for_target()`
   helper now accepts a leading `*NAME` (an `OP("*")` token followed by a
   name) as one element of the comma-list, alongside the existing plain-name
   and parenthesized-nested-tuple cases. It's represented the same way the
   rest of this function represents targets: as a string, with the starred
   element written as `"*rest"` inside the comma-joined `"(first, *rest)"`.
   The function also collapsed two near-identical top-level branches (one
   for `for (a, b) in ...`, one for `for a, b in ...`) into a single call to
   `_parse_for_target()` followed by the same comma-list loop, since the
   nested helper already handles the `LPAREN` case — removing a duplicated
   `target = "(" + ", ".join(names) + ")"` line left over from a copy-paste
   in the process.

2. `myinterpreter.py`'s `execute_ForStmt` — on this branch it turned out to
   predate the `_bind_comprehension_target` helper that `eval_Comprehension`
   already uses for its `for`-clause targets. It had its own ad hoc
   `target`/`targets` binding logic that only ever handled a *single* target
   name (a comma-list target like `"(a, b)"` was bound as one variable
   literally named `"(a, b)"`, never split up) — so on this branch, plain
   tuple-target for-loops (`for a, b in pairs:`) were **also** broken, not
   just the starred case; the bug doc's "plain tuple targets already work"
   premise held on `master` but not on the commit this worktree forked
   from. Rather than patch the ad hoc logic to also handle starred names
   (a second, parallel implementation of unpacking), `execute_ForStmt` now
   just calls `self._bind_comprehension_target(node.target, value)`, same
   as `eval_Comprehension` and `execute_ComptimeForStmt` already do.

`_bind_comprehension_target` itself (also in `myinterpreter.py`) was
extended to recognize one `*name`-prefixed entry in the comma-list: it
splits the list into "before"/"after" the starred entry, requires at least
`len(before) + len(after)` values, binds `before`/`after` positionally, and
binds the starred name to whatever's left over in the middle (including the
"leading-name + trailing-star" shape from the repro, where `after` is
empty).

## Verified
- `for first, *rest in lines:` (the repro): prints `1`/`[2, 3]` then
  `4`/`[5]`, as expected.
- Plain tuple target `for a, b in pairs:` — now also fixed on this branch
  (was broken pre-fix, see above).
- Single-name target `for x in [1,2,3]:` — still works.
- Middle-star form `for a, *mid, b in rows:` — works (e.g. `[1,2,3,4]` ->
  `a=1, mid=[2,3], b=4`).
- Full `test_gimple.py` suite: 159 passed, 0 failed (unchanged from
  baseline).
- `test_module_cache.py`: 58 passed, 0 failed.
- `test_selfhost.py`: 1 passed, 0 failed (self-host compile/link clean).
- `test_myinterpreter.py`, `test_myinterpreter_simple.py`,
  `test_myinterpreter_validation.py`, `test_phase2_parser.py`,
  `test_phase2_parser_simple.py` all fail to even import on this branch
  (`ModuleNotFoundError: No module named 'parser'` /
  `FileNotFoundError: mojo/ast_nodes.mojo`) — confirmed via `git stash`
  that this is pre-existing breakage, unrelated to and unaffected by this
  fix.

Not covered: nested-tuple-in-a-for-target combined with a starred element
(e.g. `for a, (b, *c) in ...:`) — `_bind_comprehension_target`'s comma
split is not paren-aware for nested tuples in general (a pre-existing,
separate limitation, not introduced by this fix), so that combination
wasn't in scope here.

## Reproduction
```mojo
def f():
    var lines = [[1, 2, 3], [4, 5]]
    for first, *rest in lines:
        print(first)
        print(rest)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:3:12: Expected KW got NAME('rest')
```
(`_parse_for` in `mojo_compiler.py` expects the `in` keyword right after the
first target name — it doesn't know how to parse a comma-separated target
list at all, let alone one containing a starred name.)

## Expected Behavior
Should bind `first = 1, rest = [2, 3]` on the first iteration, matching
Python's extended-unpacking-in-for-target semantics.

## Notes
Confirmed: plain (non-starred) tuple targets already work fine —
`for a, b in pairs:` runs correctly today. So this is specifically about the
starred-name case, not comma-list targets in general. It's most likely
parser-only (the fix belongs in `mojo_compiler.py`'s `_parse_for`'s
target-list parsing, adding a starred-name case the way it's presumably
already handled for plain names), but verify the interpreter's per-iteration
target-binding code also handles a starred element once the parser produces
one — don't assume runtime support is free just because the plain-tuple case
already works (see `INTERP_dict_double_star_unpack_runtime.md` in this
directory for why "parses now" and "runs now" must both be verified
independently for star/spread-related syntax in this codebase).

## Files Likely Affected
- `mojo_compiler.py` — `_parse_for` (target-list parsing).
- `myinterpreter.py` — wherever for-loop targets get bound each iteration
  (the plain-tuple case already works; extend for a starred element).
