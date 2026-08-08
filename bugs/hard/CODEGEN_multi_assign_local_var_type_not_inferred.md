# HARD BUG: `a = b = expr` (chained/multi-assignment) never infers its LOCAL variable targets' real C type — always defaults to `int64_t`

## Status (updated 2026-08-07, Track A continuation session): FIXED (both the local-function AND module-global sibling gaps)

Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_Modules_getpath.md`. Fixed 2026-08-07: added a
`MultiAssignStmt` case to `_infer_local_var_types`'s `collect_assigned_types`
(gimple_codegen.py, ~line 7364) — infers the RHS's type once via
`_quick_type` (mirroring the plain-`AssignStmt` case immediately above
it) and records that SAME type for every `IdentExpr` target, matching
real Python chained-assignment semantics (every target binds to the
identical value).

While fixing this, found and fixed a SIBLING gap in the same file: the
completely separate "Phase 1.7" MODULE-GLOBAL pre-scan (`gen_module`,
~line 30332) had the *identical* blind spot — it only ever matched
plain single-target `AssignStmt`, so a chained assignment at MODULE
scope (`a = b = expr`, as opposed to inside a function body) was
invisible to it too, and every such global fell back to whatever
`_global_var_types` leaves undeclared (int64_t, via the "globals are
boxed int64_t at the C storage level" default). Factored the existing
AssignStmt branch's value-type-inference logic (DictExpr/ListExpr/
SetExpr/literal/CallExpr/fallback cases, previously ~85 lines inline)
out into a shared nested helper, `_phase17_infer_global_type(_gname,
_value)`, and added a new `MultiAssignStmt` branch that calls it once
per target — same "all targets get the identical inferred type"
semantics as the local-variable fix, and zero behavior change for the
existing single-target `AssignStmt` path (verified: the extracted
helper's body is byte-for-byte the same logic, just parameterized).

### Minimal repro (now passes, both compile AND runtime value verified)

```python
def f(value: String) -> String:
    a = b = value.strip()
    return a + "|" + b

def main():
    print(f("  hello  "))       # -> "hello|hello"
    prefix = exec_prefix = "x"  # module-level-style chained assign
    print(prefix + exec_prefix) # -> "xx"
main()
```
Compiles clean via `python3 mojo.py build`; runs and prints the
expected values (confirms `_safe_coerce_emit`'s general RHS coercion
handles the newly-correct `char *` declared type correctly, not just
the GIMPLE type-check).

### Real-world instance: only PARTIALLY unblocks `Modules/getpath.py`

`Modules/getpath.py`'s own two `a = b = expr` sites (`executable_dir =
real_executable_dir = value.strip()` at line 379, `prefix = exec_prefix
= ''` at line 556) are FIXED by this change — confirmed via the
generated `.ci`: `real_executable_dir`/`exec_prefix` are now correctly
declared `char *` (previously `int64_t`) at their own local-variable
declaration site. `getpath.py` STILL does not compile clean, but for a
GENUINELY DIFFERENT, NOT-fixed-here reason: see the "NEW, DISTINCT
finding" section in `bugs/COMPILE_FAIL_Modules_getpath.md` — `_gen_
toplevel` (the codegen path for a module's top-level/script statements,
as opposed to an ordinary `def`'s body) never runs an `_infer_local_
var_types`-style whole-body pre-pass at all; it declares each local's C
type from whichever assignment it happens to reach FIRST during a
single top-to-bottom pass, so `executable_dir`'s *first* assignment
(`executable_dir = abspath('.')`, where `abspath` is an unresolved
external stub returning `int64_t`) permanently locks its declared type
to `int64_t` before line 379's now-correctly-typed `char *` chained
assignment is ever reached — the exact same *symptom*
("assignment to 'int64_t' from 'char *'") but a completely different,
NOT chained-assignment-specific mechanism. `real_executable_dir`
doesn't hit this because its own first-ever assignment (`real_
executable_dir = None` at module scope, line 237) doesn't lock a
conflicting type the same way. Not fixed here — this `_gen_toplevel`
gap is a substantial, separate, high-risk fix (would need to extend
`_gen_toplevel` with its own whole-body type-unification pre-pass,
mirroring `_infer_local_var_types`, across literally every compiled
module's top-level code) and is out of scope for this narrow chained-
assignment fix. Worth its own dedicated hard-bug doc if picked up.

### Third sibling gap found via spot-check regression, also fixed: `_gen_stmt_MultiAssignStmt` never routed an `IdentExpr` target to the GLOBAL struct-field write path at all

Spot-checking `Lib/csv.py` (which transitively imports `Lib/codecs.py`,
`Lib/enum.py`, `Lib/copy.py`) after the two type-inference fixes above
turned up a THIRD, genuinely distinct bug in the same family, this
time in actual runtime CODEGEN rather than type inference:
`_gen_stmt_MultiAssignStmt` (gimple_codegen.py, ~line 18119) always
treated every `IdentExpr` target as a plain local variable
(`self.var_types`/`self._declare_var`/`self._write_dest`) — it never
checked whether the target was actually a tracked GLOBAL the way
`_gen_stmt_AssignStmt`'s single-target path already does (its
`tname in self._func_declared_globals` and `self._in_toplevel_gen`
branches, which route the write to `_<module>_globals.<field>` with
the correct boxed-C-type coercion). This was invisible before this
session's fixes above because a chained-assignment-only global was
ALSO invisible to Phase 1.7/the struct-field scan, so nothing else
expected it to be a global either — accidentally self-consistent, but
silently wrong (any OTHER function reading that name as a global never
saw the real value; e.g. `Lib/copy.py`'s `deepcopy()` reading the
module-level `_deepcopy_dispatch = d = {}` dict populated elsewhere).
Once the type-inference fixes above made such globals visible, this
gap surfaced as a LOUD compile error instead of a silent miscompile:
`error: assignment to 'int64_t' from 'MojoDict *' makes integer from
pointer without a cast` at `Lib/copy.py:169` (`_deepcopy_dispatch = d
= {}`) — the target was now correctly pre-declared as a boxed-int64_t
global field, but the write still went through the local-variable path
with no boxing cast.

**Fix**: added the identical two global-write branches
`_gen_stmt_AssignStmt` already has (func-declared-`global`, and
`_in_toplevel_gen` module-scope) to `_gen_stmt_MultiAssignStmt`'s
`IdentExpr` target handling, falling back to the existing local-
variable path only when neither applies. Same field-ref construction,
same `_global_c_decl_types` coercion, same dict/list/actual-type
propagation as the single-target case.

**Verification**: minimal repro —
```python
_dispatch = d = {}
_dispatch["a"] = 1
_dispatch["b"] = 2

def reader() -> Int:
    return _dispatch.get("a", 0) + _dispatch.get("b", 0)

def main():
    print(reader())   # -> 3 (cross-function global read, was invisible/wrong before)
    print(len(d))      # -> 2 ('d' aliases the SAME global dict as '_dispatch')
```
Compiles clean and both printed values are correct — confirms both
chained names alias the identical real global, correctly visible
across functions, not just a compile-error fix.

**Corpus regression check**: `Lib/csv.py`'s full transitive-closure
build (which was already failing for many unrelated, pre-existing
reasons before ANY of this session's changes) was diffed error-by-error
before vs. after all three fixes: zero new errors, two pre-existing
`Lib/codecs.py` errors (BOM_LE/BOM_UTF16_LE-related) now GONE as a
side effect, and one harmless line-number shift on an unrelated
pre-existing `tokenize.py` error (390→396, the known "#line
misattribution" display artifact, not a semantic change). No
regressions found.

## Quality gate (2026-08-07, final — all three fixes together)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (1 passed, 0 failed).
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).
6. Corpus spot-check (`Lib/csv.py`'s full transitive closure, ~30
   files) — error-by-error diff before/after: 0 regressions, 2 fewer
   pre-existing errors as a side effect.

## Original root-cause writeup (2026-08-06, still accurate for the local-var half)

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
