# COMPILE_FAIL: Tools/cases_generator/cwriter.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/cases_generator/cwriter.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-23): re-verified — STILL-OPEN, unchanged, on item 3 only.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`). The build
now fails with exactly the two diagnostics of the already-documented structural
item 3 below and nothing else:

```
error: request for member 'write' in 'self->CWriter::out', which is of
non-class type 'int64_t'   (×2)
```

i.e. `CWriter.header_guard`'s `@contextlib.contextmanager` bare-`yield`
generator's companion `.cpp` calling `.write()` on `self.out`, whose real type
(TextIO) boxes to `int64_t`. No new issues; no regression; not attempted (still
out of scope per `bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`).
Sibling note: with parser.py now building end-to-end and analyzer.py blocked on
its own unrelated error, cwriter.py is no longer on any other file's blocking
path.

## Status (2026-08-09, historical — superseded header only): the ICE from 2026-08-07 is FIXED. File still doesn't
## fully build, for the separate, already-documented, structural reason
## (item 3 below) — that part is unchanged and left open.

Re-verified the 2026-08-07 ICE fresh (`internal compiler error: in build2,
at tree.cc:5204` in `CWriter_set_position`, line 35, `self.out.write(" " *
gap)`). Confirmed it still reproduced on current master. Root-caused via
the transitive-closure `.ci` (`mojo.py --dump-full`, not the standalone
`--dump`, which never hit this — see below for why): `gap = tkn.column -
self.last_token.end_column` (`cwriter.py` line 34), where `Token.column`/
`Token.end_column` are `@property`s (`lexer.py`).

Once `Token` becomes a real, statically-known struct (only true when
`lexer.py` is compiled into the same translation unit as `cwriter.py` —
the standalone single-file `--dump` of `cwriter.py` alone never resolves
`Token` and falls back to fully-dynamic `_mojo_dispatch_getattr`, which
happens to work), `tkn.column` (no call syntax) lowers via
`_lower_bound_method_value` to a deferred, uncalled `MojoBoundMethod *`
value — correct when the value is itself being called or passed around as
a callable, but here it's an *operand of a binary operator*
(`BinaryOp.left` in `-`). `gimple_codegen.py`'s `_lower_binary`
(generic/fallback path, after all the special-cased operators) had no
handling for a `MojoBoundMethod *` operand at all, so `_is_raw_ptr()`
treated the bound-method pointer as a genuine raw C buffer pointer and
routed the subtraction through the generic scaled-pointer-arithmetic
helper (`_mojo_at_MojoBoundMethod(ptr, -offset)`, i.e. `ptr + n` — real
pointer arithmetic on a struct with no such element shape). That's a
GIMPLE shape GCC's own `-fgimple` frontend crashes building internally
(ICE) rather than gracefully rejecting — hence "internal compiler error
in build2", not an ordinary type-mismatch diagnostic. Comparison
operators hit the exact same uncalled-bound-method value but took a
*different*, non-crashing wrong path: they just cast the raw
`MojoBoundMethod *` pointer to `int64_t` and compared THAT — silently
wrong runtime values, not a compile failure (e.g. `self.last_token.
end_line < tkn.line` a few lines above the crash site).

This is the exact same class of gap as two already-fixed, already-
documented precedents in the same file (`_lower_MemberExpr`'s `self.prop.
attr` chain and `_lower_subscript`'s `self.prop[key]`, both citing
`bugs/COMPILE_FAIL_zipfile__path___init__.md`) — an uncalled 0-arg
property/method value reaching a THIRD consuming context (a binary
operator) that had no auto-invoke handling. **Narrow, not structural**:
fixed by adding the identical auto-invoke-via-`mojo_bound_method_call_0`
step to `_lower_binary`'s generic fallback (right before the final
`return self._lower_binary_tail(...)`, gimple_codegen.py), for both
operands, deliberately excluding `is`/`is not` (the one operator where
comparing the callable's *identity* rather than its *invoked value* is
the plausible intent — e.g. `self.callback is None`).

Confirmed fixed: `cwriter.py`'s `CWriter_set_position` now compiles past
line 35 with no ICE and no error there. The file still does not fully
build, for the SEPARATE, pre-existing, structural reason already
documented as item 3 below (`CWriter.header_guard`'s `@contextlib.
contextmanager` bare-`yield` generator's companion `.cpp` calling `.write
()` on `self.out`, whose real type is an unresolvable `TextIO` boxed to
`int64_t` — explicitly out of scope per `bugs/hard/
CODEGEN_generator_struct_typed_param_refused.md`, not touched here).
Items 1 (`indents` field typing) and 2 (the ICE) below are now both
resolved — item 1 turned out to already be fixed by unrelated work
between 2026-08-07 and now (`indents` is `MojoList *` in the current
struct, not the plain `int` the 2026-08-06 note describes).

### Quality gate (2026-08-09, `_lower_binary` bound-method auto-invoke fix)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`Results: 1 passed, 0 failed`).
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib` +
   `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0 `skip <module>:`
   lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected (same
   baseline count as before the change).
6. `cwriter.py` itself: the ICE is gone; build now fails only at the
   already-documented, separate, structural item 3 below.

## Status (2026-08-07): STILL FAILING, but one real bug found+fixed along the way

Re-investigated fresh. The `indents` field-typing diagnosis below (from
2026-08-06) is correct and is the documented "comprehension RHS" sibling
gap of `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_
int64.md` (task #143) — **explicitly out of scope for this session**
(task #143 is on this session's DO-NOT-TOUCH list, "held back for
separate, directly-supervised work due to prior regressions"). A fix was
drafted and verified (adding a `Comprehension` case to `_collect_self_
assigns`, gimple_codegen.py) but then DELIBERATELY REVERTED once it was
recognized as landing inside #143's excluded scope, even though it
passed the full 5-part quality gate cleanly with zero regressions and
touched a different, narrower slice of `_collect_self_assigns` than
that doc's main (IdentExpr/param_types cross-call) finding. Left for
whoever picks up #143 properly, with this session's draft available in
git history if useful (see commit that reverts it in the same session).

While investigating this file, however, a SEPARATE, genuinely narrow bug
WAS found and fixed (unrelated to #143 or `_collect_self_assigns`):
`_compr_range_loop` (the codegen for `[expr for x in range(...)]`-shaped
comprehensions) hardcoded the loop's start/step values as bare Python
string literals `'0'`/`'1'` for the 1-arg and 2-arg `range()` shapes,
instead of real `int64_t`-typed temps. Under strict `-fgimple`, a bare
integer literal defaults to C `int`, and GIMPLE has no implicit int->
int64_t widening across statements — so `{loopvar} = 0;` (the loop var
declared `int64_t`) and the increment `{loopvar} + 1` both produced
"non-trivial conversion in 'integer_cst'"/"type mismatch in binary
expression" for EVERY 1-arg/2-arg range()-based comprehension, not just
this file's. Fixed by materializing `self._new_val('int64_t',
'(int64_t)0')`/`'(int64_t)1')` temps instead (mirroring the function's
own existing pattern for the increment step further down). Confirmed via
direct `.ci` inspection and a standalone `gcc -fgimple` compile: this
specific error class is now completely gone from `cwriter.py`'s build.

**This file still does not build**, for two OTHER, unrelated reasons
exposed once the above got out of the way (neither touched):
1. The still-open `indents` field-typing issue (task #143, see above) —
   `struct CWriter { int indents; ... }` instead of `MojoList *`.
2. A real internal compiler error once the field-typing issue is
   force-worked-around: `cwriter.py: In function 'cwriter_CWriter_
   set_position': cwriter.py:35:3: internal compiler error: in build2,
   at tree.cc:5204` — not investigated, a genuinely different and
   deeper bug (this codegen emitting some GIMPLE shape GCC's own
   `-fgimple` frontend crashes on, not just rejects).
3. Separately, `CWriter.header_guard`'s `@contextlib.contextmanager`
   bare-`yield` generator routes through the C++20-coroutine codegen
   path, whose companion `.cpp` fails to compile: `self->out.write(...)`
   — `self.out`'s real type is an opaque `TextIO` (unresolvable to a
   known struct), so its field is `int64_t`-typed, and `_cpp_expr`'s
   generator-body lowering emits a direct `.write()` method call on it
   without the plain-C path's dynamic-dispatch fallback. This matches
   the already-excluded/known class of gap described in `bugs/hard/
   CODEGEN_generator_struct_typed_param_refused.md`'s scope note
   ("method calls on self ... are out of this step's scope") — not
   attempted, consistent with that doc's exclusion.

### Quality gate (2026-08-07, `_compr_range_loop` fix only)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`Results: 1 passed, 0 failed`).
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected**.
6. Spot-checks: `Lib/json/__init__.py` and `Lib/logging/handlers.py`
   (see `bugs/COMPILE_FAIL_logging_handlers.md` for that file's own,
   separate fix landed the same session) both still build clean.
   Before/after comparison via `git stash` confirmed `Lib/textwrap.py`'s
   3 pre-existing errors are unchanged (not a regression from either
   fix in this pass).

## Status (updated 2026-08-06, historical)

Re-ran; current error:

```
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/cwriter.py:20:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Tools/cases_generator/cwriter.py:20:1: error: type mismatch in binary expression
```

Root-caused via the generated `.ci`: `CWriter.__init__`'s `self.indents
= [i * 4 for i in range(indent + 1)]` (a list COMPREHENSION, not a
literal) gets its struct field `indents` declared plain `int` instead
of `MojoList *` — confirmed via the struct typedef (`int indents;`)
and the assignment site, which stores the real list pointer truncated
through `(void*)→(int64_t)→(int)` casts to fit the wrongly-narrow
field. `set_position` (line 20) then reads `self.indents` expecting a
list, producing the GIMPLE type-mismatch errors.

This is a newly-found SIBLING gap in the already-documented hard bug
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
— same function (`_collect_self_assigns`), same "unrecognized RHS
shape falls to a generic scalar default" failure mode, just triggered
by a comprehension RHS instead of a bare unannotated parameter. Added
as a new section to that doc. Not fixed here, same risk rationale as
the rest of that doc (shared struct-field-type-inference machinery).

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
... (1761 more lines)
```

Exit code: 1
Elapsed: 14.63s
