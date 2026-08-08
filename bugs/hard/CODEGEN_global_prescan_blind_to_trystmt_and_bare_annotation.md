# HARD BUG: module-level global prescan (Phase 1.7) is blind to `try/except`-only assignment and to bare (unassigned) annotations, and falls back to a garbage literal

## Status (updated 2026-08-07)

**Part 1 of 3 FIXED** (this session, incremental/one-at-a-time per this
doc's own earlier caution). **Part 2 found to be ALREADY IMPLEMENTED**
(pre-dates this doc — see below). **Part 3 precisely located** (this
session tracked down the "untracked third fallback" flagged as
unresolved below) but **NOT YET FIXED** — see "Part 3" section at the
bottom; that is the actual blocker for `bugs/COMPILE_FAIL__pyrepl_main.md`
and is being picked up as an independent next step, gated separately.

### Part 1: TryStmt-descent in Phase 1.7 — FIXED

`gen_module`'s Phase 1.7 pre-scan (`gimple_codegen.py`) now descends
into a top-level `TryStmt`'s `body`, every handler's `body`, `else_body`,
and `finally_body`, collecting `AssignStmt`/`MultiAssignStmt` targets
from ALL of them and `TypeLattice.join`-ing the type across every
branch that assigns the same name (added `_phase17_scan_try_branches`,
which reuses a new pure `_phase17_value_type` helper factored out of
the pre-existing `_phase17_infer_global_type` so both stay in sync by
construction rather than by convention). Hooked in as a new
`elif isinstance(_scan_stmt, TryStmt):` branch in the main Phase 1.7
loop, deferring to any name already resolved by a preceding VarDecl/
AssignStmt (explicit annotation or plain assignment always wins over a
type merely inferred from try/except branches).

Deliberately NOT self-recursive for nested `TryStmt`s (a `TryStmt`
nested inside another `TryStmt`'s branch is left unscanned) — mirrors
`_flatten_resolved_conditionals`'s own documented constraint: a nested
function calling itself doesn't survive this file's own self-host
build. No real-world instance found that needs the nested case; flagged
as an explicit non-goal in the new helper's docstring rather than
silently omitted.

Verified: the minimal repro's `_root_globals.FAIL_REASON` type is now
correctly joined from the try/except/else branches (previously entirely
invisible — TryStmt wasn't even checked). Full 5-part mandated gate
clean (test_gimple.py 247/247, test_module_cache.py 76/76,
check-selfhost clean, from-scratch stdlib dylib rebuild 0 skips,
compile_stdlib.py -j8 664/664 0 unexpected). Spot-checked, before vs.
after this change, isolated (`do_imports=False`) compile + `gcc
-fgimple -fsyntax-only` of 6 diverse non-generator corpus files
(`importlib/_bootstrap_external.py`, `typing.py`, `tokenize.py`,
`json/__init__.py`, `configparser.py`, `textwrap.py`) plus confirming
`difflib.py`'s pre-existing (unrelated, generator-support) fallback
exception is unchanged: **byte-identical output before and after**, 0
regressions.

Note: this fix alone does NOT unblock the `_pyrepl/main.py` motivating
case — that file's globals ARE preceded by a bare `X: T` VarDecl (see
Part 2), so Part 1's TryStmt-join branch never even fires for them (it
defers to the VarDecl-resolved type, by design). Part 1 matters for the
different, ALSO-real shape of a global with NO preceding annotation
that is only ever assigned inside try/except — not exercised by the
`_pyrepl/main.py` repro itself, but a distinct, independently-real gap
this pass had.

### Part 2: bare-annotation VarDecl → type_ann fallback — ALREADY IMPLEMENTED, not new work

Re-investigating this from scratch (per this session's "read the doc in
full first" instruction) found that Phase 1.7's `VarDecl` branch
(`gimple_codegen.py`, the `elif isinstance(_scan_stmt, VarDecl) and
_scan_stmt.name not in _pre_declared_globals:` case) has, since commit
`8c00e57` (predates this doc entirely), always checked `_scan_stmt.
type_ann` first and mapped it through `self._resolve_type(...)` before
ever falling back to inferring from `_scan_stmt.value` — i.e. exactly
what this doc's "What a real fix needs" item 2 asked for. This doc's
original root-cause writeup did not notice this pre-existing branch
(likely because it focused on the `AssignStmt`-only blindness of the
loop's FIRST branch and didn't re-check the separate `VarDecl` `elif`
a few dozen lines down). No code change was needed or made for this
part. Confirmed via `git log -S` that the `type_ann` handling predates
this doc's 2026-08-06 root-cause date.

### Part 3: the untracked "third fallback" — LOCATED, not yet fixed

Tracked down the "third, more permissive fallback ... producing a
type-incoherent placeholder value" this doc originally flagged as
unlocated. It is NOT in Phase 1.7 at all — it's a completely separate,
independently-maintained pass a few hundred lines further down
`gen_module` that actually emits the module's `_<mod>_toplev` struct
FIELD DECLARATIONS and the struct-literal initializer: the loop `for
stmt in _collect_global_stmts(all_global_scan): ... elif isinstance(
stmt, VarDecl): ...` (search `_gscan_declare_global`). This second
pass's `VarDecl` branch reads `stmt.value` directly and NEVER consults
`stmt.type_ann` at all — for a bare annotation (`FAIL_REASON: str`,
`stmt.value is None`), every `isinstance(_gv, ...)` check in that
branch fails and it falls through to the final `else`:
`global_decls.append(f"int {gname};")` / `self._global_var_types[gname]
= 'int'` — silently OVERWRITING the correct `'char *'` that Phase 1.7
(the OTHER pass, confirmed already correct per Part 2 above) had
already recorded, with `'int'`. This is exactly what produces the
observed `int FAIL_REASON;` struct field and the garbage
`.FAIL_REASON = "f\"warning: {e}\""` initializer (a completely
separate, unrelated fallback elsewhere handles stringifying an
unresolved initializer expression's source text when asked to
initialize a field whose recorded type doesn't match its value's
shape — not investigated further, since fixing the type resolution
here should mean that fallback stops being reached for this case at
all).

Confirmed via direct testing: Part 1 (already landed) does not change
this struct's field type at all (`int FAIL_REASON;` unchanged before/
after) — proving Part 3 is a genuinely separate bug in a separate pass,
not a downstream consequence of Phase 1.7. This pass's `_collect_
global_stmts` helper ALREADY recurses into `TryStmt`/`IfStmt` bodies
(added independently, predates this doc) — so unlike Phase 1.7, this
pass's gap is ONLY the missing `type_ann` consultation for bare
annotations, not TryStmt-blindness.

**Proposed fix** (not yet implemented — picking this up as the next
incremental step, gated and spot-checked separately per this doc's own
"don't land all three in one shot" caution, now generalized to "don't
land Part 3 in the same step as anything else either"): in that
`VarDecl` branch, check `stmt.type_ann` first (mirroring Phase 1.7's
already-correct handling) and only fall back to inferring from `stmt.
value` when there is no annotation — and, symmetrically, still allow a
LATER real assignment (if `_gscan_declare_global` ever needs to
reconcile with a value-inferred type) to be joined/preferred over a
too-generic annotation the same way Part 1 above joins across try/
except branches. Must keep `self._global_c_decl_types` in sync with
Phase 1.7's existing pointer-boxing convention (`'int64_t'` storage for
any pointer-typed global) — see the `_resolved.endswith(' *')` handling
in Phase 1.7's own `VarDecl` branch — since this pass's `_gscan_declare_
global`-style branches already do this consistently for the AssignStmt/
MultiAssignStmt cases just below it in the same loop.

## Original root-cause writeup (2026-08-06, kept for history)

Root-caused 2026-08-06 while investigating
bugs/COMPILE_FAIL__pyrepl_main.md. This is the same `gen_module` "Phase
1.7: pre-scan global variable declarations" pass whose `IfStmt`-blindness
was already found and fixed once (see
bugs/COMPILE_FAIL_importlib__bootstrap_external.md, commit `fd29316`) —
this is a sibling gap in the same pass, for a different statement shape
(`TryStmt` instead of `IfStmt`), plus a second, compounding issue for
bare type-annotated globals. Not attempted: extending Phase 1.7 further
is global-variable type-inference machinery, immediately adjacent to the
areas CLAUDE.md flags as high-risk (this exact pass already produced one
real regression-shaped scare earlier this session — see the "two real
regressions" note in `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`),
and here the fix isn't a simple "add one more branch to flatten" the way
the `IfStmt` fix was — see "What a real fix needs" below.

## Symptom

```
error: assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
```
(or `from 'int'`, depending on which RHS literal triggers it) at every
assignment site of a module-level global that is declared with a bare
type annotation and then ONLY ever assigned inside a `try`/`except`/
`else` block — never via a plain top-level `AssignStmt`.

## Minimal repro

```python
FAIL_REASON: str
try:
    raise RuntimeError("x")
except Exception as e:
    FAIL_REASON = f"warning: {e}"
else:
    FAIL_REASON = ""

def main():
    print(FAIL_REASON)

main()
```
Confirmed with `python3 mojo.py build`:
```
error: initialization of 'int' from 'char *' makes integer from pointer without a cast [-Wint-conversion]
error: initializer element is not computable at load time
error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
```

Real-world instance: `Lib/_pyrepl/main.py` lines 7-21:
```python
CAN_USE_PYREPL: bool
FAIL_REASON: str
try:
    ...
    from .simple_interact import check
    if err := check():
        raise RuntimeError(err)
except Exception as e:
    CAN_USE_PYREPL = False
    FAIL_REASON = f"warning: can't use pyrepl: {e}"
else:
    CAN_USE_PYREPL = True
    FAIL_REASON = ""
```
— the exact same shape: a bare-annotated global (feature-detection
style, a common real-Python idiom) assigned only inside `try`/`except`/
`else`.

## Root cause

`gen_module`'s Phase 1.7 pre-scan (`gimple_codegen.py`, search for
`Phase 1.7: pre-scan global variable declarations`) walks a
`_flatten_resolved_conditionals`-flattened top-level statement list and
only matches `isinstance(_scan_stmt, AssignStmt)` — see the loop
`for _scan_stmt in _phase17_stmts: if isinstance(_scan_stmt, AssignStmt)
and isinstance(_scan_stmt.target, IdentExpr): ...`. `_flatten_resolved_
conditionals` only descends into (and picks one branch of) `IfStmt`
nodes — a `TryStmt` at top level is left as-is (appended to `_out`
unchanged, since it isn't an `IfStmt`), so it is never matched by the
`isinstance(_scan_stmt, AssignStmt)` check at all: every `AssignStmt`
living inside a `TryStmt`'s `try`/`except`/`else`/`finally` bodies is
completely invisible to Phase 1.7. (Unlike the `IfStmt` case, this can't
just reuse "flatten to the one platform-correct branch" logic either —
a `try/except` isn't a compile-time-resolvable branch a la
`sys.platform`; ALL branches can genuinely execute at runtime, so a real
fix needs to visit every branch and unify (`TypeLattice.join`) the
types found across all of them, not pick one.)

Separately: `FAIL_REASON: str` (a bare type annotation with no value)
parses to a `VarDecl(name='FAIL_REASON', type_ann='str', value=None)`
node, not an `AssignStmt` — so even a `TryStmt`-aware Phase 1.7 fix
would still need a second, independent fix to make the pass consult a
top-level `VarDecl`'s own `type_ann` (honoring the ANNOTATION as the
type of record, when present) as a fallback when no assignment is ever
found for that name. Currently NEITHER mechanism sees this shape, and
the observed generated C (`int FAIL_REASON;` field type, with initial
struct-literal value `.FAIL_REASON = "f\"warning: {e}\""` — the literal
SOURCE TEXT of the f-string expression, string-repr'd, stuffed in as an
`int`-typed struct initializer) shows there is a THIRD, more permissive
fallback mechanism elsewhere in the globals-struct-literal emission path
that produces a type-incoherent placeholder value for a global Phase 1.7
never resolved, rather than honestly refusing or defaulting sanely. That
fallback's exact location was not tracked down (out of scope for this
investigation — flagging its existence for whoever picks this up, since
whatever fixes the two gaps above will also need to confirm this third
fallback stops firing / degrades gracefully once real values are found).

## What a real fix needs

1. Extend Phase 1.7's statement walk to also descend into `TryStmt.body`,
   each handler's body (`TryStmt.handlers[*].body`), `TryStmt.else_body`,
   and `TryStmt.finally_body`, collecting `AssignStmt` targets from ALL
   of them (not picking one, unlike the `IfStmt` flattening) and
   `TypeLattice.join`-ing the type across every branch that assigns the
   same name — mirroring how the pass already joins element types across
   a list literal's own elements.
2. When a top-level name has a `VarDecl` with a real `type_ann` but is
   never resolved to a concrete C type via the above (e.g. an annotation
   like some exotic `Optional[...]`/`Callable[...]` this pass doesn't
   map to a C type), map the ANNOTATION itself through the same
   ann-to-C-type table `_gen_stmt_VarDecl` already uses for local
   variables (see `gimple_codegen.py`'s handling of `VarDecl.type_ann`
   inside function bodies) rather than leaving it unresolved.
3. Track down and fix (or remove) the third fallback that is currently
   producing the garbage source-text-literal initializer, so a
   still-unresolved global fails loudly (falls back to source, per this
   codebase's own "never emit silently-wrong C" convention) instead of
   compiling to a type-incoherent placeholder.

## Risk

Same class of risk as the already-fixed `IfStmt` gap in this same pass
(that fix WAS made safely, gate-verified — see `fd29316`), but this one
is bigger in scope (three sub-fixes, one of which — the join-across-all-
branches semantics — is a genuinely different algorithm shape from the
existing "resolve to one branch" `IfStmt` logic, and another — the
untracked third fallback — needs real spelunking before it can even be
described precisely). Do the `TryStmt`-descent piece first and re-run
the full quality gate before attempting the annotation-fallback or
placeholder-fallback pieces; don't land all three in one shot.
