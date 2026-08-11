# CODEGEN_generator_function: Lib/tarfile.py

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
