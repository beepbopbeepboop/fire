# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/info.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-26, wtOpencode_canalyzer2 — one of two blockers FIXED
## in shared source; the four c_parser/info.py errors are gone; remaining
## errors are the previously-masked generator-body type-inference family)

Fresh bounded build reproduced a REDUCED failure set vs the entries
below: only ONE error remained — `_toplevel`'s `UNKNOWN =
_misc.Labeled('UNKNOWN')` emitting `(char *)` coercion into the
root-globals struct's `int64_t UNKNOWN` field (the four c_parser/info.py
`:179/:247` `_fix_filename` pointer-from-integer errors from the
2026-08-25 signature-race analysis no longer reproduce).

Root-caused and FIXED this session (commit `4b24623`, shared source):
a cross-module same-bare-name GLOBAL homonym. `c_common/tables.py`
declares its own string global `UNKNOWN = '???'`; both modules compile
into one whole-program unit sharing `_global_c_decl_types`. Empirically
(instrumented): root's globals-struct fields freeze from a CLEAN cdecl
(`int64_t UNKNOWN`), then the imported modules' compiles land tables'
`char *` into the SHARED cdecl dict, then root's body emission consults
`_global_dst_ctype` — whose pointer-shaped-cdecl exception (added for
the compiler's own dispatch tables) let the FOREIGN `char *` beat root's
own scalar Phase-1.7 conclusion → RHS coerced to `char *` against an
`int64_t` field. Fix: new `GimpleGen._own_overlay_global_ctype()` is now
the single type resolution used by BOTH the assignment sites
(`_global_dst_ctype`) and gen_module_impl's field-decl loop — container-
pointer cdecls (`MojoDict *`/`MojoList *`/`MojoSet *`, the dispatch-
table/boxing family) still outrank scalar own-freezes; every other
foreign non-container pointer cdecl no longer beats this module's own
scalar conclusion; the two sides can therefore never disagree regardless
of cross-module compile ordering.

Full mandatory gate after the change: `test_gimple.py` 256/256,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild EXIT=0 with **0 skip lines** (baseline held).

The fix exposed (rather than left masked) the NEXT blocker — exactly the
generator-body type-inference family this doc's 2026-08-23 entry already
documented, now reached again:

```
info_gen.cpp:138: request for member 'render' in 'self->Analyzed::item',
                  which is of non-class type 'int64_t'
info_gen.cpp:146: void value not ignored as it ought to be
info_gen.cpp:236: invalid conversion from 'int64_t' to 'char*'
```

`Analyzed.render`/`_render_extra` are generators; `self.item = item`
(unannotated init param → int64_t default) makes `.render(fmt)` a
member call on int64_t, etc. The `self.item` half is squarely the
HIGH-RISK unannotated-init-param-type family
(bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md)
this session is instructed NOT to attempt; the rest is the same
coroutine-path inference-parity gap tracked below. Doc stays open on
that family.

## Status (re-verified 2026-08-26)

Fresh repro against this session's tree (`fix/rest-remainder18`)
reproduces the identical five errors byte-for-byte (`c_parser/info.py`
:179:45/:179:50/:247:45/:247:50 `_fix_filename` pointer-from-integer, plus
`c_analyzer/info.py:18:25` `int64_t`-from-`char*`). Confirmed still the
same caller/callee signature-race (stale placeholder param types raced
against later body-usage inference) documented in the 2026-08-25 entry
below. A general fix requires a forward-declaration-only type-resolution
prepass across the whole two-pass compilation model — correctly assessed
as out of scope for a narrow per-doc pass; not attempted. No code change;
doc re-verified only.

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1)

Fresh repro: same failure family as the 2026-08-25 entry below — the
build fails in the ordinary compiled-C stage on transitively-imported
`c_parser/info.py` (`:179:45/:179:50/:247:45/:247:50 passing argument
1/2 of 'c_parser_info__fix_filename_5c8044' makes pointer from integer`,
plus `c_analyzer/info.py:18:25 assignment to 'int64_t' from 'char *'`)
— i.e. the stale-placeholder-signature-vs-inference race documented
there, now with two ADDITIONAL call sites (:247) showing the same
`_fix_filename` coercion mismatch. Re-examined this round per the
doc's own analysis: the general fix is a forward-declaration-only
prepass resolving every free function's real parameter types before
any caller compiles — a materially larger change to the shared two-pass
model than this round's scope, and the `cls`-parameter variant at :825
is the same family. No code change; doc re-verified with the new call
sites recorded. Still open.

## Status (re-verified 2026-08-25)

Re-ran fresh against `fix/rest-remainder9`. The specific errors quoted by
the 2026-08-23 entry (`info_gen.cpp` coroutine-path errors) no longer
occur — this file no longer routes through the C++20-coroutine generator
path at all for its current blocker. Fresh repro instead fails during the
ordinary compiled-C build, pulling in a SIBLING file this module imports
(`Tools/c-analyzer/c_parser/info.py`, not `c_analyzer/info.py` itself):

```
c_parser/info.py:179:45: error: passing argument 1 of
  'c_parser_info__fix_filename_5c8044' makes pointer from integer without
  a cast
c_parser/info.py:179:50: error: passing argument 2 of
  'c_parser_info__fix_filename_5c8044' makes pointer from integer without
  a cast
c_parser/info.py:825:1: error: non-trivial conversion in 'parm_decl'
c_analyzer/info.py:18:25: error: assignment to 'int64_t' from 'char *'
  makes integer from pointer without a cast
```

Root-caused the FIRST of these two independent bugs precisely (found via
targeted debug instrumentation of `_lower_named_call`'s kwargs-padding
loop, gimple_gen_calls.py): `c_parser/info.py`'s `FileInfo.fix_filename`
calls `_fix_filename(self.filename, relroot, **kwargs)`, forwarding a
`**kwargs` SPREAD (not literal kwargs) to a callee, `_fix_filename(filename,
relroot, *, formatted=True, **kwargs)`, that has a keyword-only parameter
(`formatted`) BETWEEN the last fixed positional and its own trailing
`**kwargs` slot. The forwarded dict landed in `arg_pairs` as the LAST
lowered argument (`_lower_UnaryOp`'s `**` spread pass-through), but the
missing-argument padding loop treated it as filling the NEXT missing
positional slot (silently binding the real forwarded dict to `formatted`
instead of `kwargs`) and then fabricated a brand-new EMPTY dict for the
real `**kwargs` slot — losing every forwarded override and shifting the
whole argument tail by one. FIXED in `gimple_gen_calls.py`'s
`_lower_named_call` (~line 2469): when a `**`-spread call's forwarded
dict already sits in `arg_pairs` at a position strictly before its real
`_func_kwargs_slot` index (i.e. there's a real keyword-only param with a
default in between), the dict is now popped aside and re-inserted at its
correct slot once the loop reaches it, instead of a fresh empty dict.
Verified via targeted debug output that this fix engages correctly on
this exact repro (`_fwd_kw_pair` now correctly re-lands at index 3).

This fix did NOT, however, make the file build clean — it exposed
(rather than caused) a SEPARATE, deeper, genuinely structural bug it sits
in front of: `_fix_filename`'s `func_param_types` entry, as seen by THIS
particular caller, is still `[int64_t, int64_t, int64_t, MojoDict *]` — a
PLACEHOLDER signature registered before `_fix_filename`'s own body-usage
type inference (which later concludes `char *, char *, _Bool, MojoDict *`
from its `fix(filename, relroot=relroot, **kwargs)` forwarding into
`fsutil.format_filename`/`fsutil.fix_filename`) has run. Because
`FileInfo.fix_filename` is compiled and its call site's C args committed
BEFORE `_fix_filename`'s real signature is finalized, the caller coerces
its arguments down to the STALE int64_t placeholder types, while the
callee's own `-fgimple` definition (compiled later, using the resolved
`char *` types) ends up with a different, incompatible real C signature —
exactly the class of two-pass "sentinel gets overwritten... every OTHER
call site compiled afterwards sees the concrete signature" hazard this
codegen's own comments already document elsewhere (see
`_emit_call`/`_pack_vararg_trailing_params`'s docstrings), but here it's
the SIGNATURE ITSELF racing its own inference, not just the varargs-
packing sentinel. Fixing this class of ordering bug in general (e.g. a
forward-declaration-only prepass that always resolves every free
function's real parameter types before any CALLER is compiled) is a
materially larger, riskier change to the shared two-pass compilation
model than this round's per-doc scope — not attempted further. The
second independent blocker (`_parse_data`/`_format_data` classmethods'
`cls` parameter inferred as `struct KIND *` in one spot vs `int64_t` in
another — likely the same class of caller/callee signature-race, for a
`cls` param rather than an ordinary one) was also root-caused to the same
family but not fixed, for the same reason. Neither is the coroutine-path
generator/async gap the earlier updates below focused on — doc's
blocker has moved twice now; kept open with today's precise findings.
Quality gate after the `_lower_named_call` fix: `test_gimple.py` 253/253,
`test_module_cache.py` 76/76 (see the top-level session report for
`make check-selfhost`/stdlib-dylib results, run once for the whole
day's change set).

## Status (re-verified 2026-08-23)

Re-ran against current master tip (`626f3f0`): still fails, still in the
generated `info_gen.cpp`, with the SAME error shapes the 2026-08-09
root-cause below identified (unannotated generator-body params
`item`/`fmt` falling back to naive types):

```
info_gen.cpp:138:27: error: request for member 'render' in
    'self->Analyzed::item', which is of non-class type 'int64_t'
info_gen.cpp:134:14 / 158:19 / 161:19: error: ISO C++ forbids comparison
    between pointer and integer   (fmt == "raw" / "summary" / "full")
info_gen.cpp:159:48: error: invalid conversion from 'int64_t' to 'char*'
info_gen.cpp:146:35: error: void value not ignored as it ought to be
```

Byte-for-byte the same mechanism (coroutine-path type inference lacks
the ordinary path's param/field inference; same tracked generator/async
codegen project, tasks #95-135). Structural; unchanged; no code change —
doc re-verified only.

## Status (updated 2026-08-09)

Re-verified against current master (fast-forwarded to `bf1ead2`, after
several sibling `Tools/c-analyzer/` bugs got fixed this session): still
fails, same shape and (for the errors quoted in the 2026-08-06 note)
byte-identical text — errors are all in the generated C++ file
(`info_gen.cpp`), confirming this module still routes through the
separate C++20-coroutine generator lowering path (`info.py`'s `render`
method does `yield repr(self)` / `yield from rendered`, etc.).

Root-caused precisely this time (the 2026-08-06 note hadn't traced past
the gcc error text): `Analyzed.__init__`'s `item`/`typedecl` parameters
and the `render(self, fmt='line', ...)` method's `fmt` parameter are
both unannotated. The ORDINARY (non-coroutine) function-lowering path
infers such parameters' real C types from call-site/body usage; the
C++20-coroutine generator-body lowering (`_gen_cpp_generator_unit` and
its statement-emission helpers) is a separate, independently-maintained
type-inference pass that does not do this — it falls back to the naive
`int64_t` default for both `self.item` (a struct-typed field, assigned
from the `item` constructor param) and `fmt` (a string, compared against
string literals `'raw'`/`'summary'`/`'full'` in `render`'s body). This
produces exactly the observed errors:
- `self->item.render(fmt)` — `.render` looked up on `int64_t` because
  `item`'s field type was never resolved to the real `Analyzed`/
  `TypeDeclaration`-shaped struct pointer.
- `(fmt == "raw")` / `(fmt == "summary")` / `(fmt == "full")` — `fmt`
  compared against a C string literal while typed `int64_t`: "ISO C++
  forbids comparison between pointer and integer".
- `throw _MojoCppExc{ (int64_t)108472663, fmt, (void *)fmt }` — the
  exception-message slot expects `char*` but receives `fmt` typed as
  `int64_t`.
- `Analyzed__render_extra(self, fmt)` used in a value context while its
  inferred return type is `void` — likely the same self/param
  mistyping cascading into `_render_extra`'s own inferred signature.

This is the same "untyped/misresolved generator-body member-access"
category the 2026-08-06 note already pointed at, now traced to its
actual mechanism: the coroutine-body lowering pass needs its own
parameter/field type-inference pass brought up to parity with the
ordinary function-lowering path's (a real, nontrivial feature — not a
missing single case), and touches the same separately-maintained
generator/async codegen subsystem the tracked project (tasks #95-135)
already covers. Structural; not attempted here, per CLAUDE.md's
guidance against forcing narrow fixes onto shared/incomplete inference
machinery. No code change — doc corrected with the precise mechanism.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |             return resolved, None
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         if extra:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |         elif typedeps in (None, UNKNOWN):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         elif item.kind is KIND.STRUCT or item.kind is KIND.UNION:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:101:13: warning: unused variable '_tag' [-Wunused-variable]
  101 |         elif typedecl and not isinstance(typedecl, TypeDeclaration):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function 'SystemType___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:227:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  227 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:225:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  225 |         self.item.fix_filename(relroot, **kwargs)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function 'Analyzed_is_target':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:38:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   38 |     def from_raw(cls, raw, **extra):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:36:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   36 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:47:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   47 |             return cls(raw, **extra)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 |     def from_raw(cls, raw, **extra):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:36:9: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   36 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:35:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   35 |             return False
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:34:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   34 |         else:
      |           ^~~
... (2301 more lines)
```

Exit code: 1
Elapsed: 13.82s
