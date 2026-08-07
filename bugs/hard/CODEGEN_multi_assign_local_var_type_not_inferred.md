# HARD BUG: `a = b = expr` (chained/multi-assignment) never infers its LOCAL variable targets' real C type — always defaults to `int64_t`

## Status

Unfixed. Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_Modules_getpath.md`. Not attempted — touches local
variable type inference, immediately adjacent to (though not identical
to) the struct-field/param-type-inference machinery this session
already flagged high-risk.

## Symptom

```
error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```
at a chained assignment `a = b = <expr-of-non-scalar-type>` — both `a`
and `b` get declared `int64_t` in the generated C, regardless of the
RHS's real type.

## Minimal repro (inferred from source pattern, not independently run)

```python
def f(value):
    a = b = value.strip()
    return a
```

## Real-world instance

`Modules/getpath.py`:
```python
executable_dir = real_executable_dir = value.strip()
```
and, separately:
```python
prefix = exec_prefix = ''
```
Both trigger the identical error shape — `executable_dir`/
`real_executable_dir`/`prefix`/`exec_prefix` are all declared
`int64_t` despite their RHS clearly being `char *` (a method-call
result in the first case, a plain string literal in the second).

## Root cause

`_infer_local_var_types` (`gimple_codegen.py:6933`) is THE pre-pass
that scans a function body's assignments to determine each local
variable's real declared C type before codegen emits its declarations.
Its scan (confirmed by reading the function's body directly) only
matches `isinstance(node, AssignStmt)` — a PLAIN, single-target
assignment. It has NO case for `MultiAssignStmt` (this codebase's own
AST node for `a = b = c = expr`, per `mojo_compiler.py`) at all — such
a statement is invisible to this inference pass entirely, so every
target of a chained assignment falls through to whatever this
function's own default is (confirmed via the real-world instance:
`int64_t`).

This is a clean, narrow, single-function gap — unlike several other
findings this session, it doesn't span multiple interacting mechanisms
(no `_reset_func` wipe, no Phase-1.7 timing issue) and doesn't require
picking among multiple branches. It's simply a missing `elif
isinstance(node, MultiAssignStmt):` case in one well-contained
pre-pass function.

## What a real fix needs

1. Add a `MultiAssignStmt` case to `_infer_local_var_types`'s scan,
   inferring the RHS's type once (via the same `_quick_type`/whatever
   this function already uses for plain `AssignStmt`) and recording
   that SAME inferred type for EVERY target name in
   `node.targets` (mirroring real Python chained-assignment semantics:
   all targets receive the identical value/type).
2. Verify against the real-world instance above plus a hand-written
   minimal repro, checking BOTH successful compilation AND the actual
   runtime value (this class of bug is easy to silently "fix the
   compile error" while leaving a subtler value-boxing issue — same
   caution as this session's other struct-field-type findings).
3. Full quality gate. This pre-pass runs for every function in every
   compiled module, so even though the missing CASE is narrow, the
   function itself is extremely hot — the from-scratch stdlib dylib
   rebuild's skip-count check matters most here.

## Risk

Lower than the struct-field/global-container-type findings elsewhere
this session (this is add-a-missing-case, not restructure-existing-
logic), but `_infer_local_var_types` is called once per function
across the entire compiled corpus, so even a narrow, correct-looking
change deserves the full gate before being considered safe — chained
assignment (`a = b = expr`) is common enough (found in real stdlib code
on the FIRST file checked this session) that a subtly-wrong fix could
have broad silent-value-corruption reach.
