# COMPILE_FAIL: Tools/cases_generator/analyzer.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/cases_generator/analyzer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-25)

Re-ran fresh against `fix/rest-remainder9` — identical to the 2026-08-23
finding below, byte-for-byte (`analyzer.py:386:8` "request for member
'peek'"/"'used' in something not a structure or union", 3 diagnostics).
Confirmed via source inspection (`inputs`/`outputs` are `list[StackItem]`,
populated via a `[convert_stack_item(i, ...) for i in ...]` comprehension
that DOES carry real `StackItem*` element typing) that the gap is
specifically `itertools.zip_longest`: unlike `zip()` (mapped to a
`mojo_zip` runtime call, itself only genuinely typed for the common
2-list case) and `itertools.repeat`'s already-modeled finite 2-arg form
(`gimple_exprtypes._is_itertools_repeat2_call`), `itertools.zip_longest`
has NO model anywhere in this codegen — no entry in `_KNOWN_SIGS`, no
special-cased for-loop-iterable dispatch (`_gen_stmt_ForStmt` only
special-cases `range`/`enumerate`, falling through to the generic
`_gen_for_iter` for everything else, including `zip`/`zip_longest`
alike). Its call therefore lowers as an unresolved/opaque call, so the
for-loop's `input, output` tuple-unpack targets default to opaque
`int64_t`, and the later chained `input.peek = output.peek = True`
attribute-assignment emits raw struct-member writes into a non-struct.

A real fix needs a new stdlib-call element-type PASS-THROUGH model for
`itertools.zip_longest(a, b)`'s for-loop tuple targets (propagate `a`'s
and `b`'s own list element types onto the two loop variables, same as a
correctly-modeled `zip()` would), which touches the same general
"element-typing contracts for unmodeled stdlib calls" machinery flagged
below as having a documented regression history (Pass-1.3d). Given this
round's guidance to avoid large/speculative feature work and the explicit
regression-risk note already on record for this exact machinery, left
untouched. No code change; doc re-verified with the precise gap
identified (previously only "not previously tracked" — now root-caused
to `itertools.zip_longest` specifically, distinct from bare `zip()`).

## Status (2026-08-23): no longer blocked by cwriter.py at all; now blocked by
## analyzer.py's OWN new-shape error. Still open, root-caused.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`). The
transitively-imported `cwriter.py` ICE documented below is long gone and
`cwriter.py` itself now fails only on its own separate item — this file's build
gets all the way to its own client `.c` and fails with exactly one distinct
error site (3 GCC diagnostics):

```
analyzer.py:386:8: error: request for member 'peek' in something not a
structure or union   (×2, for the two chained targets)
analyzer.py:386:8: error: request for member 'used' in ... (1 more site)
```

Source (line 377–386): `for input, output in itertools.zip_longest(inputs,
outputs):` ... `input.peek = output.peek = True`. `itertools.zip_longest` is
unmodeled, so its element values default to opaque `int64_t`; a CHAINED
attribute assignment (`a.peek = b.peek = True`) on those opaque values then
emits raw struct-member writes into a non-struct. Root cause class: unmodeled
stdlib iterator element typing + attribute-assignment-target lowering on
opaque values — same "opaque receiver" family as wasi `__main__.py`'s surviving
`invalid call to non-function`, not previously tracked for this file. Not
attempted here (element-typing contracts for unmodeled stdlib calls are the
shared Pass-1.3d machinery with this project's documented regression history);
recorded honestly as this file's own next blocker.

## Status (re-verified 2026-08-09, historical — superseded by 2026-08-23 above): unchanged, still blocked on sibling cwriter.py ICE

Re-ran on current `master` (`python3 mojo.py build .../cases_generator/analyzer.py`,
exit 1). Single error, identical to 2026-08-07:
`Tools/cases_generator/cwriter.py:35:3: internal compiler error: in
build2, at tree.cc:5204`. This file (`analyzer.py`) itself is not
directly implicated — the failure is entirely in the transitively-
imported `cwriter.py` (`import lexer`/`from cwriter import CWriter`
chain). `bugs/COMPILE_FAIL_Tools_cases_generator_cwriter.md` (checked
the same session) confirms this GCC ICE is still open there too, and
is a genuinely different/deeper bug than the field-typing gap (task
#143) that used to mask it — not a generator/coroutine yield-type
issue at all, an actual `-fgimple` frontend crash on some emitted
GIMPLE shape. Not investigated further here (this is `cwriter.py`'s
bug to root-cause, not `analyzer.py`'s); this file's own doc kept only
to record that it's still blocked, with no code change made.

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

Root-caused in `bugs/COMPILE_FAIL_Tools_cases_generator_cwriter.md` (a
comprehension-assigned struct field defaulting to `int` instead of
`MojoList *` — new sibling gap added to
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`).
`analyzer.py` imports `lexer`/`cwriter` transitively; nothing specific
to `analyzer.py` itself was found. Not fixed here — see that doc.

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
... (11898 more lines)
```

Exit code: 1
Elapsed: 15.44s
