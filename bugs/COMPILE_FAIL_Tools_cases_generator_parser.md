# COMPILE_FAIL: Tools/cases_generator/parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/cases_generator/parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-23): ALREADY-FIXED end-to-end at the compile/link level.

`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Tools/cases_generator/parser.py`
now exits 0 and produces a real arm64 Mach-O executable ("Built: parser") on
branch `fix/tools-misc`. Both of the doc's historical blockers are resolved:
the client-`.c` `'Parser' undeclared` errors no longer reproduce (master's
absorbed struct-emission fixes), and the `__mojogen_lexer_tokenize_*`
undefined-symbol link failure is gone — this branch's landed commit `736b349`
("Fix build_executable dropping sibling-module coroutine units from the link
line") is precisely the build_executable-path counterpart of the
`_compile_imported_module` capture gap described in the 2026-08-20 entry below,
and with it the full inline pipeline links lexer.py's coroutine unit.

Runtime caveat (not a compile issue, recorded for completeness): executing the
built binary prints `globals: unavailable in compiled mode` and then dies with
`Unhandled exception: AttributeError: Token` — a separate, runtime-level gap in
this codegen, out of scope for this COMPILE_FAIL doc. Compile+link status:
fixed; doc can be closed once its sibling docs' shared context is no longer
needed.

## Status (2026-08-20): the documented link-time gap (4th coroutine-code
## source) is FIXED at the mechanism level. `parser.py` itself is STILL
## blocked end-to-end, now by a DIFFERENT, earlier (compile-time, not
## link-time), apparently-regressed blocker — see below.

**The fix.** `gimple_codegen.py`'s `_compile_imported_module` (the
routine link mode's `_link_inline_modules` fallback AND the plain
`do_imports=True` Phase 0 pass both call to compile a transitively-
imported sibling module) now also captures that module's own
`temp_gen.generated_cpp` — the self-contained C++20 coroutine
translation unit `temp_gen.gen_module(stmts)` already independently
computes for a plain top-level generator/async function defined in that
module (e.g. `lexer.py`'s `tokenize()`) — and compiles it to its own
CAS-cached object via the new `_compile_link_inline_cpp_unit` method
(mirrors `driver.py`'s `_build_client_cpp_object` / `monomorphize.
instantiate`'s identical per-instantiation cpp build: same operation, a
third call site for it). The object is appended onto `_link_objects`
and its need for a C++-aware final link is recorded — both now SHARED
BY REFERENCE down through every nested `_compile_imported_module`
temp_gen (`_link_objects`, `_link_dylibs`, and a new single-element-list
`_link_needs_cxx_box`, alongside the already-shared `_generator_api`),
not just the outermost `link_imports=True` root's own instance. This
last part mattered concretely for this file's own real import chain:
`lexer` is never imported directly by `parser.py` or even by
`parsing.py`'s `from parsing import (...)` — it's `parsing.py`'s OWN
`import lexer as lx`, discovered only from INSIDE the nested,
`do_imports=True`-only (not `link_imports=True`) temp_gen that compiles
`parsing.py`. A per-instance `self.link_imports` gate (the first,
narrower version of this fix) missed that case entirely; sharing the
accumulators by reference down the whole nested-temp_gen chain (the
same convention already used for `_generator_api`/`_imported_struct_
home`/etc.) fixes it generally, at any nesting depth.

**Verification of the fix itself:** a minimal, hand-built two-file
repro (`gensib.mojo`: `def make_items(n: Int): ... yield i * 10`;
`mainmod.mojo`: `from gensib import make_items` / `for it in
make_items(5): print(it)`) — confirmed to fail with the exact
documented symptom (`__mojogen_gensib_make_items_start/_resume/_value/
_destroy` undefined at link time) on unmodified master, and to link AND
run correctly (`0/10/20/30/40`) with this fix applied. Also confirmed,
via a pristine-HEAD side-by-side (symlinked source tree, HEAD's own
`gimple_codegen.py`) `compile_linked()` call directly against
`parser.py`, that the exact behavior described below (client `.c`
compile fails before ever reaching the link stage) is unchanged from
before this fix — i.e. this fix strictly adds the missing coroutine-
object capture/link and changes nothing else observable.

**`parser.py` itself, still blocked — different blocker, pre-existing.**
Confirmed via a direct `gimple_codegen.compile_linked()` call (bypassing
`mojo.py build`'s silent fallback to the separate, unrelated `build_
executable` inline pipeline — see below) that `parser.py`'s own client
`.c` currently fails to even gcc-compile, well before the link stage
this fix addresses:
```
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/parser.py:48:10: error: 'Parser' undeclared (first use in this function)
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/parser.py:55:3: error: unknown type name 'Parser'
```
i.e. the `Parser` struct's own C typedef is entirely missing from the
compiled output (not merely a wrong-guessed field type — the earlier,
narrower class of bug the 2026-08-09 entry below describes as fixed).
Reproduced identically on a pristine, unmodified master checkout (no
changes from this session or any other), so this is a genuine pre-
existing/regressed blocker independent of this fix — not investigated
or fixed here (out of this task's scope; flagged honestly rather than
glossed over, per this repo's own stated convention). Because of this,
`mojo.py build .../parser.py`'s end-to-end behavior is UNCHANGED by
this fix: `driver.compile_program`/`compile_linked` still throws before
producing a binary (swallowed by `mojo.py`'s own `except Exception: rc
= None`), so the build silently falls back to `build_executable` (a
separate, independent inline pipeline, NOT `compile_linked` — the one
this task's fix targets), whose own separate linking logic still fails
with the same `__mojogen_lexer_tokenize_*` undefined-symbol error as
before. This doc is kept open (not deleted) — see the new blocker above
— rather than falsely closed.

`bugs/COMPILE_FAIL_Tools_cases_generator_cwriter.md`/`_analyzer.md`/
`_parsing.md` (same directory, same `lexer.py`/`parsing.py` dependency
chain) were checked: all three still fail earlier than the link stage
(cwriter.py's own GCC ICE / struct-field-typing gaps), so this fix does
not change their status either — not updated.

## Status (2026-08-09): both prior blockers (cwriter.py's ICE, and this
## file's own struct-field-type corruption) are FIXED. Now blocked on a
## separate, structural, newly-exposed link-time gap.

Re-verified fresh. `cwriter.py`'s ICE (see that file's own doc) is fixed
this session, so `parser.py` gets past it. That surfaced this file's OWN
next blocker, previously masked: `gimple_codegen.py`'s struct-field-type
inheritance heuristic ("assume all struct fields on unknown types are
pointers to the same struct", added for genuinely-unknown-type
self-referential fields like `Scope.parent: Scope`) was firing on
`class Parser(PLexer): ...` — `Parser` has no `__init__` of its own,
only ever using `PLexer`'s inherited one, and EVERY one of its inherited
fields (`pos`, `src`, `filename`, `tokens` — correctly `int64_t`/
`char *`/`char *`/`MojoList *` on `PLexer` itself) got redeclared
`struct Parser *` (a self-referential pointer never actually assigned a
`Parser *` value anywhere real). Root cause: `_merge_struct_inheritance`
copies a base class's already-resolved fields into the subclass as
placeholder `VarDecl(type_ann=None)` nodes (the real type lives
separately, in `struct_field_types[base_name]`, not in the VarDecl
itself) — the heuristic loop couldn't distinguish "genuinely unknown
field" from "known field, inherited, just not yet re-resolved for this
subclass" and defaulted both to the same-struct-pointer guess. This is
the SAME class of gap driving `cwriter.py`'s own GCC ICE for a
different reason (an uncalled bound-method value), not the field-typing
issue documented in `bugs/hard/CODEGEN_unannotated_init_param_field_
type_defaults_int64.md` (that one is about unannotated CONSTRUCTOR
PARAMETERS, not cross-module INHERITED fields — a distinct root cause,
despite the superficially similar symptom).

**Fixed** (narrow, not structural): before falling back to the
same-struct-pointer guess, the heuristic now checks each of the struct's
base classes (`s.bases`, in the same order `_merge_struct_inheritance`
walks them) for an already-known type for that field name in
`self.struct_field_types[base_name]`, and uses that if found —
gimple_codegen.py, the "for now, assume all struct fields on unknown
types..." loop just after `_merge_struct_inheritance`'s call site.
Verified with a minimal, hand-built two-file cross-module repro
(`class Base: def __init__(self, s: str): self.s = s; self.pos = 0` /
`class Derived(Base): ...`, imported across two `.py` files exactly
like `plexer.py`'s `PLexer`/`parsing.py`'s `Parser`) — before the fix,
`Derived`'s inherited `s`/`pos` fields were declared `struct Derived *`;
after, they're the correct `char *`/`int64_t`, matching `Base`'s own.

**Still does not build**, for a NEW, separate reason exposed once the
above got out of the way — a link-time failure, not a compile error:

```
Linking failed: Undefined symbols for architecture arm64:
  "__mojogen_lexer_tokenize_destroy", referenced from:
      __lexer_toplevel in parser.o
      __lexer_toplevel in parser.o
  "__mojogen_lexer_tokenize_resume", referenced from:
      __lexer_toplevel in parser.o
  "__mojogen_lexer_tokenize_start", referenced from:
      __lexer_toplevel in parser.o
  "__mojogen_lexer_tokenize_value", referenced from:
      __lexer_toplevel in parser.o
ld: symbol(s) not found for architecture arm64
```

`lexer.py`'s `tokenize()` (a plain, non-generic, module-level generator
function — `yield Token(...)`, `lexer.py:294`) compiles fine on the `.c`
side (it's only ever referenced via `extern`-declared coroutine-handle
functions there) but its actual C++20-coroutine IMPLEMENTATION never
makes it into the link. `driver.py`'s `compile_linked` distinguishes
exactly three sources of C++ coroutine code to link in: (1) the ROOT
file's OWN top-level generators (`gen.generated_cpp`), (2) an elaborated
GENERIC's own coroutine unit (`monomorphize.instantiate`'s
`cpp_object`), and (3) dylib-resident stdlib generators (already linked
into `libmojostdlib.dylib`). `lexer.py` here is none of those: it's a
plain (non-generic) generator in a TRANSITIVELY IMPORTED SIBLING file
(inlined via `link_imports=True`'s "inline modules" mechanism, not the
stdlib dylib), and no code path captures ITS `.cpp` companion into
either `gen.generated_cpp` or the elaboration-object list. **Not
investigated further / not fixed here** — this is a new, distinct
category of gap in the C++ coroutine linking machinery (a third source
of coroutine code the existing three-source model doesn't cover), not a
narrow accidental bug; per this task's guidance around avoiding
speculative changes to shared linking machinery with a documented
history of causing broad silent regressions, this needs its own
directly-supervised investigation rather than an opportunistic fix
here.

### Quality gate (2026-08-09, struct-field-inheritance heuristic fix)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`Results: 1 passed, 0 failed`).
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected (same
   baseline as before the change).
6. `parser.py` itself: both the ICE (via cwriter.py) and this file's own
   struct-field corruption are gone; build now fails only at the new,
   separate, structural link-time gap described above.

## Status (2026-08-07)

Re-ran after this session's `_compr_range_loop` fix (see `bugs/
COMPILE_FAIL_Tools_cases_generator_cwriter.md` for the fix itself) — the
2026-08-06 error below is GONE, but this file (via the same
transitively-imported `cwriter.py`) now hits a different, deeper,
unfixed bug in that same sibling file: `cwriter.py:35:3: internal
compiler error: in build2, at tree.cc:5204`. Still failing overall; see
`cwriter.py`'s own doc for the full remaining-issue breakdown (a real
GCC ICE plus the still-excluded task #143 field-typing gap). Not
independently investigated further here.

## Status (updated 2026-08-06, historical)

Re-ran; current error is entirely in a transitively-imported sibling,
not this file's own code:

```
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/cwriter.py:20:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/cwriter.py:20:1: error: type mismatch in binary expression
```

Same root cause as `bugs/COMPILE_FAIL_Tools_cases_generator_cwriter.md`
(comprehension-assigned struct field defaulting to `int` — see
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`).
Nothing specific to `parser.py` itself was found. Not fixed here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py: In function '_alloc_Token':
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:273:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  273 |     @property
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py: In function 'choice':
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:464:11: warning: variable 'opt' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:463:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py: In function 'lexer_Token_line':
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:261:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  261 |     @property
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:259:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  259 |     end: tuple[int, int]
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:258:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  258 |     begin: tuple[int, int]
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:257:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  257 |     text: str
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:256:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  256 |     kind: str
      |              ^  
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:255:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  255 |     filename: str
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py: In function 'lexer_Token_column':
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:274:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  274 |     def end_column(self) -> int:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:272:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  272 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:271:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  271 |         return self.end[0]
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:270:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  270 |     def end_line(self) -> int:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:269:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  269 |     @property
      |              ^  
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:268:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  268 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py: In function 'lexer_Token_end_line':
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/lexer.py:278:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  278 |     def width(self) -> int:
      | ^   
... (8765 more lines)
```

Exit code: 1
Elapsed: 14.23s
