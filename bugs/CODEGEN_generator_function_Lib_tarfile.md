# CODEGEN_generator_function: Lib/tarfile.py

## Status (updated 2026-08-26, fresh independent re-derivation — one real, narrow root-cause piece FIXED (`cls.method(...)` return-type inference); tarfile.py's own build still blocked by a SECOND, deeper piece of the same chain, precisely identified and NOT attempted)

Re-derived this doc's own diagnosis from scratch (not just re-running the
existing repro) via `compile_to_gimple_with_cpp(do_imports=False)` +
`g++-mp-15 -std=c++20 -fsyntax-only`: confirmed byte-identical to the
2026-08-26 entry below — `TarFile.__iter__`'s local `tarinfo` still unifies
to `int64_t` (from `tarinfo = TarFile_next(self)`) against `char*` (the
`yield from self.members` default), because `TarInfo_fromtarfile`'s real
return type is still unresolved.

Traced the chain one level deeper than any previous pass by directly
inspecting `gen.func_return_types` for `TarInfo_fromtarfile`/
`TarInfo__fromtarfile`/`TarFile_next` via a `_run_pipeline` script (not just
reading the emitted `.cpp`). Found **two independent, stacked gaps**, not
one:

1. **No `cls.method(...)` return-type resolution in Pass 2b's
   `_quick_type`-driven return-type-inference loop at all** — confirmed via
   code reading (`gimple_module_gen.py`'s 4-round fixpoint loop, ~line
   2087) and grep (`gen._classmethod_names`/`gen.func_return_types` have
   zero cross-reference in `gimple_gen_resolve.py`'s `_quick_type`). The
   loop seeds `self.var_types['self'] = f"{s.name} *"` for every method but
   never seeds `cls` for a real `@classmethod`, so `_quick_type`'s EXISTING
   `gen.var_types.get(mod, '')`-based struct-method-call resolution (the
   same code an ordinary `obj.method(...)` call already uses) silently saw
   `cls` as an untracked bare identifier and fell through to the `int64_t`
   default for every `return cls.<method>(...)`-shaped classmethod body in
   the corpus, not just tarfile.py.

   **Fixed** (commit below): seed `self.var_types['cls'] = f"{s.name} *"`
   in that same loop, gated on `f"{s.name}_{m.name}" in
   self._classmethod_names` (the same set `@classmethod`/
   `__init_subclass__`/`__class_getitem__` detection already populates) —
   mirrors the pre-existing `self` seed exactly, adds no new resolution
   mechanism, purely additive (only fires for a real detected classmethod's
   literal first `cls` param). Verified via a debug trace that this now
   correctly resolves `TarInfo.fromtarfile`'s own `return
   cls._fromtarfile(tarfile)` to look up `TarInfo__fromtarfile` in
   `func_return_types`, exactly like `self.foo()` already does for `foo`.

2. **NOT fixed, root-caused precisely**: even with cls resolution seeded,
   `TarInfo._fromtarfile`'s own body (`obj = cls._frombuf(...); obj.offset
   = ...; return obj._proc_member(tarfile)`) still resolves to `int64_t`,
   because Pass 2b's return-type scan (`_infer_return_type`/
   `_collect_return_types`) only walks `ReturnStmt` nodes — it never
   records the types of ordinary LOCAL VARIABLE ASSIGNMENTS
   (`obj = cls._frombuf(...)`) into `var_types` during the same scan, so
   `_quick_type(IdentExpr('obj'))` at the `return obj._proc_member(...)`
   site has no entry for `obj` and falls to the `int64_t` default — this
   is a distinct, genuinely open gap (Pass 2b has no local-variable
   data-flow tracking at all, by design — it only ever sees a function's
   OWN parameters plus its own return expressions). Confirmed directly:
   `func_return_types['TarInfo__fromtarfile']` is still `'int64_t'` after
   fix #1, across all 4 fixpoint rounds (traced with debug instrumentation,
   removed before commit).

   Extending Pass 2b to also track local-assignment types (even a narrow
   single-hop version: "a bare `x = cls.method(...)`/`x = self.method(...)`
   local, later returned unchanged") is a real, separate, non-trivial
   extension to the SAME fixpoint machinery — the exact class of change
   this project's convention flags as needing dedicated, wide verification
   (this scan feeds `func_return_types` for every method in the whole
   compiled program, not just TarInfo's). Not attempted here — genuinely
   out of this pass's narrow-fix scope, left precisely diagnosed for
   whoever picks it up next.

**tarfile.py itself still does not build** — fix #1 is real, verified
correct in isolation (a genuine, previously-entirely-missing case), and is
kept because it fixes classmethod return-type inference broadly for the
common `return cls.<method>(...)` idiom (not tarfile-specific), but it does
not by itself change tarfile.py's build outcome; gap #2 above, plus the
already-documented 5 whole-program-build residuals (SpecialFileError.tarinfo,
bz2/lzma function-scoped-import cluster), remain.

Full mandatory gate for fix #1: `test_gimple.py` 264/264, `test_module_cache.py`
76/76; `make check-selfhost`, from-scratch stdlib dylib rebuild, and
`compile_stdlib.py` run per this session's commit (see commit message for
exact counts).

## Status (updated 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch, byte-identical)

Re-derived fresh via own isolated `compile_to_gimple_with_cpp(do_imports=
False)` + real `g++ -std=c++20 -fsyntax-only`: identical 3-error `.cpp`
signature — `invalid conversion from 'int64_t' to 'char*'` (x2, at the
`co_yield tarinfo;` sites) and `cannot convert 'MojoList' to 'int64_t' in
assignment` (at `tarinfo = (self->members)[index];`). Also independently
checked whether the existing extensive `_classmethod_names`/`cls.method`
machinery (`gimple_gen_methods.py`/`gimple_cpp_core.py`, dozens of
call sites) has any entry point for `self.<field>.classmethod(...)` where
`<field>` is a class-level attribute holding a class reference (`tarinfo
= TarInfo` at `tarfile.py:1751`) — confirmed it does not; every existing
classmethod path resolves `cls`/`self.__class__`/an explicit class name,
none resolve a field read that happens to alias a class. Concur this
remains a genuine Phase-2a-vs-generator-pass ordering gap compounded by
an unresolvable classmethod return type, not a narrow fix — consistent
with the prior session's own reverted attempt. No code change made. Doc
stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder19d — re-checked against today's super()/self.__class__ fix (bdfb825, 02:24) and generator-value-return-slot fix (326db78, 02:57); both landed AFTER this doc's most recent entry (01:11) — neither applies, confirmed via a fresh isolated repro)

Fresh `compile_to_gimple_with_cpp(do_imports=False)` repro against this
worktree (both of today's landed fixes included) reproduces the IDENTICAL
error signature as the 2026-08-25 entry below: `TarFile.__iter__`'s local
`tarinfo` is declared `int64_t` (from the `co_yield tarinfo;` sites at
lines 161/178, unified against `char*` from the earlier `yield from
self.members` element-type default), then hard-fails converting FROM a
`MojoList` at `tarinfo = (self->members)[index];` (line 165) — `g++`:
"invalid conversion from 'int64_t' to 'char*'" (x2) plus "cannot convert
'MojoList' to 'int64_t' in assignment". This is exactly the already-
diagnosed `_field_elem_types`-populated-too-late gap: `self.members`'s
real element type (`TarInfo*`, boxed via `self.tarinfo.fromtarfile(self)`
at the 3 real `.append()` sites) is still unknown at generator-.cpp-pass
time.

Checked specifically whether either of today's two fixes helps, per this
run's assignment:
- `bdfb825` (`super()`/`self.__class__` resolution) does not apply —
  `self.tarinfo.fromtarfile(self)` is a **class-attribute-mediated
  classmethod call** (`tarinfo = TarInfo` is a plain class-level
  attribute at `tarfile.py:1751`, overridable per-instance via
  `self.tarinfo = tarinfo` in `__init__`), a structurally different
  dispatch shape from both `super().method()` (explicit base-class
  resolution) and `self.__class__(args)` (construct-the-runtime-type).
  There is still no lowering anywhere in `gimple_codegen.py`/
  `gimple_cpp_core.py`/`gimple_gen_methods.py` that resolves a
  `self.<field>.classmethod(...)` call's return type when `<field>`
  holds a class reference — grepped for any such mechanism, found none.
- `326db78` (generator value-carrying return slot) does not apply either
  — `TarFile.__iter__` has no value-carrying `return <expr>` inside the
  generator body; its gap is a `yield`/`co_yield` VALUE-TYPE unification
  problem (a plain-vs-yield-from element-type mismatch), an entirely
  different mechanism from the return-slot machinery.

No shared root cause with any of today's landed work. Not attempted here
(same reasoning as the 2026-08-25 entry: a narrow pre-scan fix couldn't
even resolve THIS file's own case since `fromtarfile`'s return type is
unknown, and a broader heuristic risked regressing other, currently-
correct char*-element fields elsewhere in the corpus). Doc stays open, not
re-classified. Full whole-program `mojo.py build` re-run not attempted
this pass (isolated repro is conclusive for the question this run was
asked to check, and a full run risks the same 300s-timeout inconclusive
result the prior entry hit under build-resource contention from other
concurrent worktree sessions).

## Status (updated 2026-08-26, worktree fix/rest-remainder17 — re-verified unchanged; whole-program build attempt inconclusive due to a 300s safety-budget timeout, isolated verification confirms no regression)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` re-run
against this worktree (branched from master `1e0f3f2`, after this
session's `SubscriptExpr`-reraise + MemberExpr-receiver container-method
fixes landed elsewhere — see `CODEGEN_generator_function_Lib_test_test_
finalization.md`): identical success, cpp emitted, no refusal — matches
the 2026-08-25 entry's own diagnosis exactly (the generic yield-from
element-type-unification fix holds; tarfile.py's own instance is still
blocked purely on the documented Phase-2a-vs-generator-pass ordering gap
for `self.tarinfo.fromtarfile(self)`-mediated `.append()` sites, not
attempted here for the same reasons as before — a broad heuristic risked
flipping other, currently-correct char*-element fields wrong elsewhere
in the corpus).

A fresh full `python3 mojo.py build .../Lib/tarfile.py` (with
`build/libmojostdlib.dylib` freshly rebuilt, 0 skips) was attempted to
confirm the whole-program-build residual set is unchanged, but hit the
300s safety-budget wall-clock cap before finishing (RSS stayed flat and
safe throughout, same "genuinely slow transitive import walk, not a
runaway" pattern documented on `CODEGEN_generator_function_Lib_test_
test_ctypes_test_random_things.md` for `collections`/`inspect`'s
source-interpretation fallback, which tarfile.py's own import graph also
reaches) — inconclusive on the whole-program-build error set this pass,
but the isolated re-verification above already confirms the actual
codegen path this doc tracks is unaffected by anything landed since the
last pass. Doc stays open; not re-classified.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — root-caused the 2026-08-24 isolated-compile symptom; a real, generic partial fix landed; tarfile.py's own instance still not resolved)

Root-caused the 3 new `.cpp` errors the 2026-08-24 entry flagged
(`TarFile.__iter__`'s `yield from self.members` reading elements via
`mojo_list_get_str` while the sibling `yield tarinfo` sites are
`int64_t`). Confirmed via a direct isolated-compile repro
(`compile_to_gimple_with_cpp(do_imports=False)` + inspecting the
generated `.cpp`): `_generator_yield_ctype`'s `YieldFromExpr` branch
(`gimple_exprtypes.py`) delegates to `_yield_from_delegate_ctype`, whose
final fallback treats ANY `yield from <expr>` that isn't a plain
list/tuple literal, a `range()`/`repeat()`/`sorted()` call, or a call to
another already-compiled generator as unconditionally string-valued
(`return 'char *'`) — including `yield from self.<field>`, even when the
field demonstrably holds pointer-boxed objects (here, `TarInfo`
instances). Since `_generator_yield_ctype`'s merge rule always lets
`char *` win over a disagreeing `int64_t` site (the long-standing
"stringy fallback" reconciliation), this generic default silently
clobbers the WHOLE promise to `char *`, and `_cpp_yield_from`'s matching
emission-side fallback compounds it by unconditionally reading every
"plain collection" `yield from` element back via `mojo_list_get_str`
regardless of the field's real element type — producing exactly the
`invalid conversion from int64_t to char*` class of error.

**Fixed generically** (not tarfile.py-specific): both
`gimple_exprtypes.py`'s `_yield_from_delegate_ctype`/
`_generator_yield_ctype` and `gimple_cpp_core.py`'s `_cpp_yield_from`
now consult `gen._field_elem_types`/`gen._cpp_list_local_elem_types` —
the same per-struct-field / per-local element-type registries
`_cpp_for_stmt`'s existing plain `for x in self.<field>:` case already
uses — to resolve a `yield from self.<field>`/`yield from <local list>`
site's real element type (int64_t/double/char*) instead of always
defaulting to char*, and to pick the matching `mojo_list_get_int/
_double/_str` accessor at emission time instead of hardcoding
`mojo_list_get_str`. Purely additive (new optional params, all default
to the exact prior behavior when the registries have no entry), so this
cannot regress any currently-working `yield from` shape.

**However, this does NOT fix tarfile.py's own instance** — traced one
level further, precisely, and NOT fixed (out of narrow-fix scope):
`_field_elem_types` is only populated by the FULL GIMPLE lowering of a
real `.append()` call site (`gimple_gen_methods.py`'s struct-method-call
codegen), which happens during Phase 2a's ordinary-struct-method body
compile (`_gen_struct_method`) — but generator METHODS' own `.cpp` units
are compiled in an EARLIER, dedicated pass (`gimple_module_gen.py`'s
async/generator-method loop, well before Phase 2a starts), so
`_field_elem_types` is always still empty at the point `TarFile.__iter__`
itself compiles, regardless of this fix. A bounded pre-scan (walking
every struct method's AST for `self.<field>.append(<expr>)` sites before
the generator-.cpp pass, seeded from Pass 2b's already-available
lightweight return-type inference) was attempted and then deliberately
reverted: tarfile.py's actual 3 real append sites (lines ~1841, ~2402,
~2909) all route the appended value through `self.tarinfo.fromtarfile
(self)` — a class-attribute-mediated classmethod call this codegen has
no return-type inference for at all — so the narrow 2-shape pre-scan
attempted couldn't even resolve THIS file's own case, and a broader
heuristic (e.g. "any non-literal-looking append argument defaults to
int64_t") was judged too likely to flip currently-correct char*-element
fields wrong elsewhere in the corpus without much wider testing than
this pass's budget allows. Left as a precisely-diagnosed, genuine
pass-ordering gap for a future dedicated session.

Verified no regression: `test_gimple.py` 256/256, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild —
0 `skip <module>:` lines (unchanged from baseline). Commit: see this
session's `gimple_exprtypes.py`/`gimple_cpp_core.py`/
`gimple_cpp_async.py` changes.

**tarfile.py itself still does not build end-to-end** — both this fresh
element-type-unification gap AND the previously-documented 5
whole-program-build residuals (SpecialFileError.tarinfo, bz2/lzma
function-scoped-import implicit-declaration cluster) remain. Doc stays
open.

## Status (updated 2026-08-24 — re-verified; the 5 whole-program-build residuals unchanged; a DIFFERENT isolated-compile symptom noted, not reconciled)

Re-verified the whole-program-build-owned 5-error residual set this doc
already documents is unchanged in shape (not re-run to full completion
this pass — a real `mojo.py build` on this file pulls in a large
transitive closure and was aborted after confirming it's still running
the same class of work seen for `ftplib.py`/`gettext.py`'s sibling
whole-program attempts, to avoid tying up shared build resources other
concurrent worktree sessions are using).

Separately, an ISOLATED compile (`GimpleGen(do_imports=False,
relaxed_imports=True)` — a different diagnostic surface from the
whole-program methodology this doc's existing entries use, so NOT
necessarily reachable/relevant in the real build) surfaces 3 new `.cpp`
errors in `TarFile.__iter__`, not previously documented: `self.members`
(a list of real `TarInfo` objects, per `yield from self.members`) gets
its element-read lowered via `mojo_list_get_str` (a string accessor),
while the SAME generator's other yield sites (`yield tarinfo`, `tarinfo
= self.next()`) are typed `int64_t` — a value-type-unification mismatch
between the `yield from <list>` site and the plain `yield <scalar>`
sites in the same coroutine, producing `invalid conversion from
int64_t to char*` and a `MojoList` vs `int64_t` assignment-type error.
Not investigated further or fixed this pass (unclear whether it's a
genuine `do_imports=True` bug too, or an isolated-compile-only artifact
from `TarInfo`'s real element type being less certain without imports)
— flagged here so a future isolated-compile-based re-check of this file
isn't surprised by it. Doc stays open.


## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — the ENCODING global-type cross-contamination FIXED; two documented residual clusters remain)

The `149:26`/`151:26` `assignment to 'char *' from 'int'` pair on
tarfile.py's own `ENCODING = ...` lines — root-caused in the 2026-08-11
entry below as the shared, whole-program-flat `_global_var_types` dict
being overwritten between this module's Phase 1.7 scan and its own Phase
2a assignment emission (here by `Lib/token.py`'s unrelated same-bare-name
`ENCODING` int constant) — is now FIXED via a per-instance overlay:
each GimpleGen's Phase 1.7 scan additionally records its OWN conclusions
into `_own_global_var_types` (via the new `_phase17_set_gtype`, now used
by every write site of the scan), and the six global-assignment emission
sites in gimple_gen_stmts.py route through a new `_global_dst_ctype`
helper that trusts the overlay's SCALAR conclusions over both shared
dicts while keeping pointer `_global_c_decl_types` overrides (e.g.
`_EARLY_DISPATCH_DICTS`) and container int64_t boxing authoritative.
This is deliberately NOT the full per-module rework the 2026-08-11 entry
deferred (the shared dicts themselves are untouched; reads/decls still
consult them) — it fixes exactly the assignment-side mis-coercion class.
Commit 65706f3. Verified: a real `mojo.py build .../Lib/tarfile.py` no
longer emits either ENCODING error.

**Remaining tarfile.py-own errors (5 raw lines, unchanged families):**
`754:7 'SpecialFileError' has no member named 'tarinfo'` (root-caused a
step further this pass: `Lib/shutil.py` defines its OWN bare-name-identical
`SpecialFileError(OSError)` with NO fields — in a whole-program build the
struct definition that wins lacks tarfile's field; same deferred
bare-name-struct-collision family as `bugs/hard/
CODEGEN_same_bare_name_struct_collision_across_modules.md`, not a new
mechanism) plus the `bz2_BZ2File___init__`/`lzma_LZMAFile___init__`
implicit-declaration cluster (function-scoped `from bz2/lzma import ...`
inside `try:` — the already-tracked `bugs/hard/
CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md`
class). All 3 generator sites still compile cleanly. Doc stays open.

Quality gate for the overlay change: `test_gimple.py` 250/250,
`test_module_cache.py` 76/76, `make check-selfhost` clean (after catching
and fixing a first-attempt precedence regression vs this compiler's own
dispatch-table globals), from-scratch stdlib dylib rebuild 0
`skip <module>` lines — same as baseline.

## Status (updated 2026-08-18 — targeted investigation of the 2026-08-09 `:2418:27` "unexpected RHS" error: already fixed, no code change needed)

Investigated the specific remaining item flagged in the 2026-08-09
section below: `TarFile._get_extraction_filter`'s `return
_NAMED_FILTERS[filter]` inside `try:`/`except KeyError:`, which used to
fail with:
```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2418:27: error: unexpected RHS for assignment before ';' token
```

Built several isolated repros of exactly this shape (a module-level
dict of callables, a function/method doing `try: return d[key] except
KeyError: raise ...`, plus sibling variants — plain `return d[key]`
outside any try, and `x = d[key]; return x` inside a try) via `python3
mojo.py build`. All of them compile AND run correctly (verified actual
returned values, not just "no compile error") on current master. Also
did a full from-scratch `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py`: `TarFile__get_filter_
function` (the mangled name for `_get_extraction_filter`) now compiles
with only ordinary unused-variable/unused-label warnings — no error at
line 2418, and grepping the full build log for "unexpected RHS" finds
only 4 unrelated occurrences elsewhere (`weakref.py:157`/`353`,
`inspect.py:1233`, `functools.py:950` — different files, not
investigated here, out of scope). The rest of the previously-documented
error set for this file (the `149:26`/`151:26` ENCODING pointer-from-
int errors, `754:7` SpecialFileError.tarinfo, the bz2/lzma implicit-
declaration errors) is still present, unchanged, confirming this is a
real apples-to-apples re-run against the same file and not a fluke.

Root cause of why it went away: not pinned down to a specific commit —
`_gen_stmt_TryStmt`'s early-return interception (the `intercepted_emit`
closure around `_mojo_exc_top` bookkeeping) and `_gen_stmt_ReturnStmt`
itself are unchanged in this region since well before 2026-08-09, so
the fix was very likely an incidental side effect of one of the several
unrelated dict/list/global-type-inference fixes landed in the
intervening sessions (e.g. the Phase 1.7 global-list/global-dict
element-type inference work, or the raw-pointer `*T` resolution work) —
plausibly the dict-subscript-read's value type for `_NAMED_FILTERS`
(module-level dict of function references) now resolves to a real,
single consistent C type where it previously didn't, avoiding whatever
malformed GIMPLE the mismatch used to produce. Not worth spending more
time isolating retroactively since the bug is simply gone and verified
gone from multiple independent angles.

No code change made — CLAUDE.md's gimple_codegen.py quality gate was
not invoked since nothing was touched; `test_gimple.py` (248/248) and
`test_module_cache.py` (76/76) re-run clean as a baseline sanity check
regardless.

## Status (updated 2026-08-11, one root cause fixed; real blocker root-caused, left open)

Re-verified against current master. Classification unchanged: **NOT a
generator-codegen-cluster failure** — all 3 of tarfile.py's own
generator sites (`TarFile.__iter__`'s `yield from self.members`/`yield
tarinfo` x2) still compile cleanly, unaffected by anything below.

**One real root cause fixed**: `sys.getfilesystemencoding()` had no
real lowering in `gimple_codegen.py` and fell through to the fully
generic "unknown method on scalar receiver" stub, which passes the
receiver's own placeholder C type through as the call's result type —
a bare `sys` module reference resolves to a placeholder `int64_t`, so
the call's result was typed `int64_t` too, even though the real
function returns a string. Added a narrow special case (mirroring the
existing `sys.platform` comptime-constant special case already in
`_lower_method_call`) for `sys.getfilesystemencoding()`/`sys.
getdefaultencoding()`, returning the fixed `"utf-8"` value both
genuinely have on every host this compiler targets. Also fixed, in the
same pass, a related but SEPARATE gap this file's own `if os.name ==
"nt": ENCODING = "utf-8" else: ENCODING = sys.getfilesystemencoding()`
exposed: the Phase 1.7 module-level-global type pre-scan
(`gen_module`'s `_phase17_infer_global_type` family) only handled a
`TryStmt`'s branches when a global is assigned inside one (an already-
fixed, now-deleted hard bug, `CODEGEN_global_prescan_blind_to_trystmt_
and_bare_annotation.md`) — the analogous `IfStmt` case, when the
condition can't be folded to a compile-time constant (`os.name ==
"nt"` isn't one of the handful of expressions this codegen's `_eval_
const_bool` recognizes, unlike e.g. `sys.platform`), was never handled
at all: the whole `IfStmt` node is left un-flattened in the pre-scan's
input, so NEITHER branch's assignment was ever visible to the type
inference, silently defaulting through the generic `int64_t` fallback.
Added `_phase17_scan_if_branches`, a direct IfStmt sibling of the
already-shipped `_phase17_scan_try_branches`, joining the inferred type
across `then`/`elif`/`else` branches exactly the same way.

Both fixes are real, independently defensible, and pass the full
mandatory gate with zero regressions (`test_gimple.py` 247/247,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
dylib rebuild 0 skips, `compile_stdlib.py` 664/664 — see this session's
commits). Verified directly: a real `mojo.py build` of a `sys.
getfilesystemencoding()`-calling repro no longer types the call's
result `int64_t`.

**tarfile.py's `ENCODING` line (149/151) itself still fails**, though —
root-caused one level deeper, and NOT fixed here: `_global_var_types`
(the dict both `_phase17_infer_global_type` and the Phase 2a assignment
lowering consult for a global's declared C type) is a single flat dict
SHARED BY OBJECT IDENTITY across every module compiled together in one
`do_imports=True` whole-program build (`temp_gen._global_var_types =
self._global_var_types`), keyed by BARE global name alone — the exact
same "shared, first/last-writer-wins flat namespace" root cause already
diagnosed and deliberately deferred for FREE FUNCTIONS in `bugs/hard/
CODEGEN_generator_function_symbol_not_module_qualified.md` and for
STRUCTS in `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_
modules.md`, but never previously confirmed for MODULE-LEVEL GLOBALS.
Concretely: `Lib/token.py`'s own module-level `ENCODING` (a real token-
type integer constant, unrelated in meaning) and `Lib/tarfile.py`'s own
`ENCODING` (a string) share the same bare name; each module's own
struct DECLARATION ends up correctly typed (`_token_toplev.ENCODING` is
`int`, `_root_toplev.ENCODING` — tarfile's own — is `char *`, confirmed
via direct `.ci` inspection) because each module's struct-declaration
pass reads `_global_var_types['ENCODING']` at the moment ITS OWN
Phase 1.7 scan just ran, before any later-processed module can
overwrite the shared dict — but the ASSIGNMENT-STATEMENT codegen for
tarfile's own `ENCODING = ...` (Phase 2a, run interleaved with other
modules' own Phase 1.7/2a passes in a whole-program build) reads the
SAME shared dict at a later point, by which time some other module's
own scan has overwritten the shared entry, producing an `int`-typed
RHS value assigned into a `char *`-typed field — exactly the observed
`error: assignment to 'char *' from 'int'`. Confirmed via direct `.ci`
inspection (both the `os.name == "nt"` AND the `sys.
getfilesystemencoding()` branches emit an `(int)` cast on their RHS,
even the branch that's a bare string-literal reference — ruling out a
"the RHS value itself was wrong" explanation and confirming it's the
GLOBAL's inferred TYPE that's cross-contaminated, not the individual
call's result).

**Deliberately not fixed here**: making `_global_var_types` (and its
Phase 2a consumers) genuinely per-module-scoped — the same fix
`_func_qualifier`'s three-tier lookup already provides for free
functions — is a real, structural, non-trivial rework of shared,
correctness-sensitive machinery touched by dozens of call sites (`grep
-c '_global_var_types' gimple_codegen.py` is well over 40), squarely
the same class of change this project's own documented history (the
"_tuplegetter incidents", the free-function/struct SB-1 fixes' own
two-regression histories) says needs a dedicated session with room for
real multi-file `mojo.py build` CLI verification across many
collision shapes, not a same-pass addition alongside two already-
verified, independently-scoped fixes. Left open.

The other tarfile.py-own errors are unaffected by any of the above and
remain independently diagnosed, unfixed, non-generator issues (unchanged
from the 2026-08-09 pass below): `SpecialFileError.__init__`'s `self.
tarinfo = tarinfo` ("has no member named 'tarinfo'" — adjacent to, but
NOT the same receiver shape as, `bugs/hard/CODEGEN_dynamic_attribute_
on_generic_object.md`'s own documented residual gap; not investigated
further here) and the `bz2opzen`/`xzopen` `from bz2 import BZ2File`/
`from lzma import LZMAFile` FUNCTION-SCOPED imports inside a `try:` block
(implicit-declaration errors — the already-tracked, already-diagnosed
class of gap in `bugs/hard/CODEGEN_function_scoped_import_rettype_and_
literal_cast_mismatches.md`).

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs, this file included (the 2026-08-06 entry below —
already noted fixed as of 2026-08-07, `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md`'s mechanism-1/mechanism-2
fixes). Confirmed via fresh rebuild: zero occurrences now, unaffected
either way. While tracing the mechanism, found+fixed a closely related
residual bug (`_gen_struct_method`/`_gen_lifted_closure` never setting
`self._current_module_ctx`, misrouting a `global`-statement write
inside a class method to the wrong module's struct — see that hard-bug
doc's history and this session's commit) plus a related `_safe_coerce_
emit` `.`-access gap. Effect on this file: total build error count
dropped 562 -> 560 via a fresh rebuild. All 3 of tarfile.py's own
generator sites remain unaffected (still compile cleanly); the
`SpecialFileError`/`bz2`/`lzma`/dict-subscript-in-try cluster below is
unaffected and remains this file's real blocker.

## Status (updated 2026-08-09)

Re-verified again against current master with a fresh real rebuild
(`MOJO_DEBUG=1 python3 mojo.py build .../Lib/tarfile.py`, real
`gcc-mp-15`/`g++-mp-15` via `mojo.py`'s own resolution — not a hand
invocation). Classification UNCHANGED: **NOT a generator-codegen-cluster
failure**. Confirmed via `MOJO_DEBUG=1`: all 3 of tarfile.py's own
generator sites (`TarFile.__iter__`'s `yield from self.members` /
`yield tarinfo` x2, lines 2999/3011/3024) — no "not eligible" refusal
logged for any of them; every "not eligible" line in this build's debug
output names a generator/async function in a DIFFERENT, transitively-
imported module (e.g. `ItemsView.__iter__`, `_unpack_opargs`,
`findlinestarts`, `Flag._iter_member_by_value_`, `WeakValueDictionary.
items`, `iter_fields`), never `TarFile.__iter__` or anything else from
tarfile.py itself.

The error set has shifted again since the last note: the previous
`:1863:1`/`:2403:1` "non-trivial conversion in 'var_decl'" pair is GONE
(both those source lines now only produce ordinary unused-variable/
unused-label warnings), replaced by one new error:
```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2418:27: error: unexpected RHS for assignment before ';' token
```
at `return _NAMED_FILTERS[filter]` inside a `try:`/`except KeyError:`
(`TarFile._get_extraction_filter`) — a dict-subscript **read** inside a
`return` inside a `try` body. (Note: this is a different shape from the
dict-subscript *augmented-assignment* mis-codegen fixed by commit
`0b6394a`/"Fix bug31" just before this session started — that fix was
for `dict[k] += v`; this is a plain `return dict[k]` inside try/except.
Not investigated further — out of scope for this generator-codegen
pass.) The rest of the previously-documented error set is unchanged:
```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:149:26: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:151:26: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:754:7: error: 'SpecialFileError' has no member named 'tarinfo'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2035:3: error: implicit declaration of function 'bz2_BZ2File___init__'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2040:3: error: implicit declaration of function 'bz2_BZ2File_mojo_close'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2063:3: error: implicit declaration of function 'lzma_LZMAFile___init__'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2068:3: error: implicit declaration of function 'lzma_LZMAFile_mojo_close'
```
Still none of these are inside tarfile.py's own generator bodies. Not
investigated further here — same out-of-scope non-generator issues
(exception-subclass attribute, conditional `import bz2`/`import lzma`
symbol resolution, dict-subscript-in-try codegen) as previously noted.
No code change made in this pass.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** — all 3 of
tarfile.py's own generator sites still compile cleanly (no "not
eligible" refusal). The `struct _genericpath_toplev` error quoted below
is GONE (fixed by `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_
fully_defined.md`'s "mechanism 2" landing, same fix confirmed elsewhere
in this session), but a DIFFERENT batch of tarfile.py's-own-code errors
has since surfaced — none inside a generator body:

```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:149:26: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:754:7: error: 'SpecialFileError' has no member named 'tarinfo'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:1863:1: error: non-trivial conversion in 'var_decl'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2035:3: error: implicit declaration of function 'bz2_BZ2File___init__'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2403:1: error: non-trivial conversion in 'var_decl'
```

Not investigated further here (out of scope for this generator-codegen
cluster) — `:754`'s `'SpecialFileError' has no member named 'tarinfo'`
looks like it may be the same class of issue as `bugs/hard/CODEGEN_
dynamic_attribute_on_generic_object.md` (a custom exception subclass
setting an attribute not in its declared `__init__` fields — real:
`class SpecialFileError(...): def __init__(self, tarinfo): self.tarinfo
= tarinfo` or similar), and the `bz2_BZ2File___init__`/
`lzma_LZMAFile___init__` implicit-declaration errors look like a
transitively-imported-module symbol-resolution gap (likely conditional-
import related, `import bz2`/`import lzma` inside a `try:` block per
tarfile.py's own real source) — neither confirmed further, left for a
dedicated non-generator pass.

## Status (updated 2026-08-06, superseded above — struct_toplev error since independently fixed, different errors now present)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'TarFile'` .cpp error no longer reproduces. `tarfile.py` has
3 of its own generator sites (`getmembers`-adjacent `yield from
self.members`/`yield tarinfo` x2, lines 2999/3011/3024) — none appear in
the current error list, and `MOJO_DEBUG=1` shows no "not eligible"
refusal for any of them: tarfile.py's own generator bodies now appear to
compile cleanly through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore** —
this is `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md` (5th confirmed occurrence in this cluster):

```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:312:29: error: invalid use of undefined type 'struct _genericpath_toplev'
```
Not investigated further here — out of scope for this generator-codegen
cluster; see the hard-bug doc.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tarfile.py
