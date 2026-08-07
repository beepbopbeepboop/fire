# HARD BUG: module-level global prescan (Phase 1.7) is blind to `try/except`-only assignment and to bare (unassigned) annotations, and falls back to a garbage literal

## Status

Unfixed. Root-caused 2026-08-06 while investigating
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
