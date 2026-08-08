# HARD BUG: module-level global prescan (Phase 1.7) is blind to `try/except`-only assignment and to bare (unassigned) annotations, and falls back to a garbage literal

## Status (updated 2026-08-07) — ALL THREE PARTS FIXED

**Fully fixed**, landed as two commits (part 1 alone, then parts 2+3
together — see below for why 2 and 3 turned out to be inseparable).
Both the minimal repro and the real motivating file now build AND RUN
correctly end-to-end: `bugs/COMPILE_FAIL__pyrepl_main.md`'s
`Lib/_pyrepl/main.py` now compiles clean via `python3 mojo.py build`
(previously 3 `-Wint-conversion` errors) and produces a working binary.
That bug's own file has been updated to reflect this.

**Revised understanding of parts 2 and 3, found while landing part 3**:
this doc's earlier "Part 2 already implemented, no work needed" note
(written right after Part 1 landed) was only half right — Phase 1.7's
existing `VarDecl`/`type_ann` handling (predates this doc) DOES resolve
the annotation, but its own boxing decision (which C storage
representation to advertise via `_global_c_decl_types`) had a real,
independent, latent bug: it boxed EVERY pointer-typed annotation
(including `char *`) to `int64_t`, when the actual rest-of-file
convention (`_lower_IdentExpr`'s read side, `_gscan_declare_global`'s
own sibling `AssignStmt` branches) only ever boxes `MojoDict
*`/`MojoList *`/`MojoSet *` — a `char *` or other struct-pointer global
is stored and read DIRECTLY, unboxed. This mismatch was invisible
before because, for the common case (a `VarDecl` WITH a value, or any
`AssignStmt`), a LATER pass always re-derives and overwrites both
`_global_var_types`/`_global_c_decl_types` from the real value shape,
silently correcting Phase 1.7's over-eager boxing. Only the bare-
annotation-only case (Part 3's territory — nothing ever overwrites
Phase 1.7's decision except the also-broken-until-now Part 3 code)
actually depended on Phase 1.7 getting the boxing right, which is what
finally exposed it. Fixing Part 3 alone (declaring the struct field
correctly, unboxed) without ALSO fixing Phase 1.7's over-eager boxing
just moved the type mismatch from the read site to the WRITE sites
inside the `try`/`except`/`else` bodies (`_gen_stmt_AssignStmt`, which
runs during Phase 2a — BEFORE Part 3's struct-declaration pass even
executes — consults `_global_c_decl_types` as Phase 1.7 left it). The
two fixes are not actually separable pieces of work; they had to land
together as one coherent, gate-verified change. See "Part 2" and "Part
3" sections below for the exact code changes.

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

### Part 2: bare-annotation VarDecl → type_ann fallback — FIXED (had a latent boxing bug)

Phase 1.7's `VarDecl` branch (`gimple_codegen.py`, the `elif
isinstance(_scan_stmt, VarDecl) and _scan_stmt.name not in
_pre_declared_globals:` case) has, since commit `8c00e57` (predates
this doc entirely), always checked `_scan_stmt.type_ann` first and
mapped it through `self._resolve_type(...)` — so the ANNOTATION itself
was already being resolved to a real C type; this doc's original
"what a real fix needs" item 2 was already substantially done. BUT its
decision for `self._global_c_decl_types` (which C type to actually
declare/read/write the global's STORAGE as) was wrong for any
pointer-typed annotation other than dict/list/set: `if _resolved.
endswith(' *'): self._global_c_decl_types[name] = 'int64_t'` boxed
`char *` (and any custom struct pointer) to `int64_t` too. The rest of
this file's actual, load-bearing convention (`_lower_IdentExpr`'s read
side: `if gtype in ('MojoDict *', 'MojoList *', 'MojoSet *'): ctype =
'int64_t' else: ctype = gtype`; `_gscan_declare_global`'s own sibling
`AssignStmt`/`StringLiteral` branch: `global_decls.append(f"char *
{gname};")`, NOT boxed) only boxes those three container types —
everything else (`char *`, any struct pointer) is stored and read
DIRECTLY, unboxed. Narrowed the condition to `if _resolved in
('MojoDict *', 'MojoList *', 'MojoSet *'):` to match. This bug was
invisible before because, for a `VarDecl` WITH a value or any ordinary
`AssignStmt`, `_gscan_declare_global`'s own struct-declaration pass
(Part 3, below) always re-derives and overwrites both `_global_var_
types`/`_global_c_decl_types` from the real RHS value shape, silently
correcting whatever Phase 1.7 guessed. Only a bare-annotation-only
global (no `AssignStmt`/`VarDecl`-with-value ever reaches
`_gscan_declare_global`'s existing branches for it) actually depended
on Phase 1.7's `_global_c_decl_types` decision surviving unmodified —
which is also exactly Part 3's territory, which is why these two had
to be fixed together (see Part 3).

### Part 3: the untracked "third fallback" — FOUND AND FIXED (two separate bugs)

Tracked down the "third, more permissive fallback ... producing a
type-incoherent placeholder value" this doc originally flagged as
unlocated. Two independent bugs, both in the SAME pass (a few hundred
lines further down `gen_module`, past Phase 1.7 — the loop that
actually emits the module's `_<mod>_toplev` struct FIELD DECLARATIONS
and the struct-literal initializer, `_gscan_declare_global`/its `for
stmt in _collect_global_stmts(all_global_scan):` consumer loop):

1. **Bug A — the `VarDecl` branch never consulted `stmt.type_ann`.**
   It read `stmt.value` directly; for a bare annotation (`FAIL_REASON:
   str`, `stmt.value is None`), every `isinstance(_gv, ...)` check
   failed and it fell through to the final `else`: `global_decls.
   append(f"int {gname};")` — silently OVERWRITING the correct type
   Phase 1.7 had already recorded, with plain `'int'`. This is what
   produced the observed `int FAIL_REASON;` struct field. **Fixed**:
   added an `if stmt.type_ann and stmt.value is None:` branch ahead of
   the existing value-inference chain, resolving the annotation via
   `self._resolve_type(...)` exactly like Phase 1.7's own (now-
   corrected, see Part 2) `VarDecl` branch, using the SAME dict/list/
   set-only boxing convention.

2. **Bug B — the struct-literal initializer's own value-extraction
   pass (a separate loop further down, `for gname in sorted(
   _declared_globals): ... init_code = _extract_init_expr(stmt.value)`)
   treated an f-string's raw, UNDECODED `StringLiteral.value` (which
   keeps its `f`/`t` prefix and quotes — real interpolation only
   happens later, at actual codegen time, in `_lower_StringLiteral`)
   as an ordinary compile-time string constant.** This is what produced
   the garbage `.FAIL_REASON = "f\"warning: {e}\""` initializer — the
   literal, uninterpolated SOURCE TEXT of the f-string, quoted as a C
   string. `_extract_init_expr`'s `elif isinstance(stmt_value,
   StringLiteral): return f'"{_c_escape(stmt_value.value)}"'` had no
   f-string special case at all. **Fixed**: added a new free-function
   helper `_str_literal_value_is_fstring(val)` (module-level, next to
   `_extract_init_expr`) that mirrors `GimpleGen._decode_str_literal_
   text`'s own prefix-detection (deliberately NOT refactored to share
   code with that hot, 4-call-site instance method — out of scope,
   unrelated risk); `_extract_init_expr`'s `StringLiteral` branch now
   returns `'0'` (the same "can't static-initialize, defer to runtime"
   sentinel already used for `CallExpr`/`IdentExpr`) for an f/t-string
   instead of treating its raw text as a real constant.

Confirmed via direct testing that these are genuinely two independent,
additive bugs: fixing Bug A alone got the struct field type right
(`int64_t FAIL_REASON;` — correctly boxed at the time, before Part 2's
fix; see below) but with the SAME garbage initializer (`.FAIL_REASON =
"f\"warning: {e}\""`) until Bug B was also fixed. And fixing Part 3
(Bugs A+B) alone, without ALSO narrowing Phase 1.7's own boxing
decision (Part 2), produced a struct field boxed as `int64_t` (Part 3
mirrored Phase 1.7's — at that point still-wrong — "any pointer type"
boxing convention) while `_lower_IdentExpr`'s read side (which only
boxes dict/list/set) read it straight into an unboxed `char *` temp
with no cast: `assignment to 'char *' from 'int64_t'` at the READ site
(`print(FAIL_REASON)`). Narrowing Part 3's own boxing condition to
match `_lower_IdentExpr`/`_gscan_declare_global`'s real dict/list/set-
only convention fixed the read site, but then EXPOSED that Phase 1.7's
own boxing decision (which the WRITE-side codegen inside the try/
except bodies — `_gen_stmt_AssignStmt`, running during Phase 2a,
BEFORE Part 3's struct-declaration pass even executes — actually reads
via `_global_c_decl_types`) was itself still wrong, producing
`assignment to 'char *' from 'int64_t'` at the WRITE sites instead.
Only after fixing BOTH Phase 1.7's boxing decision (Part 2) AND Part
3's struct-declaration boxing decision, consistently, did every site
(read, write, struct declaration, struct initializer) agree. This is
why Parts 2 and 3 landed together as one commit rather than separately
— they are not actually independent pieces of work once you trace the
full data flow; the doc's original "don't land all three in one shot"
caution was right in spirit (verify incrementally, don't rush), but
the natural unit of "one part" turned out to be {Part 1} and {Parts 2
+ 3 together}, not three separate units.

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

## Risk (historical — kept for context; see "Status" at top for the outcome)

Same class of risk as the already-fixed `IfStmt` gap in this same pass
(that fix WAS made safely, gate-verified — see `fd29316`), but this one
is bigger in scope (three sub-fixes, one of which — the join-across-all-
branches semantics — is a genuinely different algorithm shape from the
existing "resolve to one branch" `IfStmt` logic, and another — the
untracked third fallback — needs real spelunking before it can even be
described precisely). Do the `TryStmt`-descent piece first and re-run
the full quality gate before attempting the annotation-fallback or
placeholder-fallback pieces; don't land all three in one shot.

## Final verification (2026-08-07)

Full 5-part mandated gate clean on the combined Part 2+3 commit:
`test_gimple.py` 247/247, `test_module_cache.py` 76/76, `make
check-selfhost` clean, from-scratch stdlib dylib rebuild 0 skips,
`compile_stdlib.py -j8` 664/664 0 unexpected. Before/after spot-check
of 12 diverse corpus files (`importlib/_bootstrap_external.py`,
`typing.py`, `tokenize.py`, `json/__init__.py`, `difflib.py`,
`configparser.py`, `textwrap.py`, `shutil.py`, `argparse.py`,
`dataclasses.py`, `enum.py`, `_pyrepl/main.py`) via isolated
(`do_imports=False`) compile + `gcc -fgimple -fsyntax-only`: byte-
identical output before and after, 0 regressions (4 of the 12 hit the
pre-existing, unrelated "generator function, honest fallback"
exception both before and after — not this bug's territory).

End-to-end (`python3 mojo.py build`, the real CLI path, not the
isolated proxy above): the minimal repro compiles clean and RUNS,
printing the correct `warning: x`. `Lib/_pyrepl/main.py`
(`bugs/COMPILE_FAIL__pyrepl_main.md`'s file) now builds to a working
executable with exit code 0 (previously 3 `-Wint-conversion` errors).
`bugs/COMPILE_FAIL__pyrepl_main.md` has been updated to reflect this.
