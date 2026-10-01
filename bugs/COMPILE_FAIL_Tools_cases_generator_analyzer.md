# COMPILE_FAIL: Tools/cases_generator/analyzer.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/cases_generator/analyzer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, worktree-agent-a01a24fff53233531 @ master `43fb291`): unchanged, build still exits 0

Fresh `python3 fire.py build .../Tools/cases_generator/analyzer.py`
against this worktree (fast-forwarded to master `43fb291`): `Built:
.../analyzer`, exit 0, 0 `error:` lines — same outcome as every prior
entry. Both open architectural blockers (link-mode sibling-module
resolution stubbing parser/lexer access; the inline fallback's own
block on parsing.py's polymorphic `BlockStmt.tokens` generator ABI)
are unchanged; not attempted.

## Status (re-verified 2026-08-26, worktree-agent-a21934cd6fb7c6509 @ master `e60b9cd`): build still exits 0, same two-blocker state

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Tools/
cases_generator/analyzer.py` against this worktree (fast-forwarded to
master `e60b9cd`): `Built: .../analyzer`, exit 0, 0 `error:` lines —
same outcome as the entry directly below. Both open architectural
blockers (link-mode sibling-module resolution stubbing parser/lexer
access; the inline fallback's own separate block on parsing.py's
polymorphic `BlockStmt.tokens` generator ABI) are unchanged; per this
session's mandate, not attempted.

## Status (re-verified + next blockers sharpened, 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb` — mut-capture fix confirmed present in this tree; link-mode stubbing reproduced; NEW: the inline fallback is itself blocked, by parsing.py's BlockStmt.tokens dangling generator references at LINK time)

Fresh `python3 fire.py build .../analyzer.py` (safety-wrapped): exits
0; binary runs, exit 0, but prints ONLY the four section headers —
reproducing the previous entry's end-to-end state exactly (the
`_emit_mut_local_box_allocs` fix, commit `46a7a91`, IS in this worktree;
`git merge-base --is-ancestor` verified). Re-investigation this pass:

1. **Link-mode sibling stubbing re-confirmed**: `parser.parse_files(...)`
   lowers as `_t7 = _t2; /* int64_t.parse_files() stubbed */`; the built
   binary contains no real parser/lexer symbols.
2. **NEW finding — the "inline pipeline resolves everything correctly"
   assumption below is no longer true on this tree.** Forcing the inline
   path (`build_executable`, do_imports=True) FAILS AT LINK TIME:
   `Undefined symbols: __mojogen_BlockStmt_tokens_{start,resume,value,
   destroy}` — all four generator ABI functions for parsing.py's
   `BlockStmt.tokens` are REFERENCED (by consuming sites in the closure)
   but never DEFINED, because BlockStmt.tokens is one of parsing.py's
   polymorphic-`yield from self.body.tokens()` generators that the C++
   coroutine emitter refuses/rolls back (the excluded hard-doc cluster
   documented in bugs/COMPILE_FAIL_Tools_cases_generator_parsing.md).
   So analyzer.py currently has NO working end-to-end path: link mode
   silently stubs siblings; inline mode dies on parsing.py's refused
   generator shapes.

Closing either gap remains architectural: link-mode sibling support /
driver fallback policy (option (c) below), or the polymorphic-dispatch
feature. Neither attempted. Doc stays open with the two-blocker state
now precisely recorded.

## Status (updated 2026-08-26, branch fix/opencode-analyzer2 — the documented segfault residual is ROOT-CAUSED AND FIXED in shared source; doc stays OPEN on the now-precisely-root-caused next blocker: link-mode sibling-module resolution stubs every `parser.*`/`lexer.*` access)

**The residual (2026-08-25 entry below) is fixed.** Root cause was NOT
exit-time cleanup and not coroutine machinery at all:

- lldb on the produced binary: `EXC_BAD_ACCESS (code=1, address=0x0)` — a
  WRITE to NULL in `assign_opcodes_…` at analyzer.py:1066 (`next_opcode = 1`),
  called `analyze_forest → analyze_files → _toplevel`. Since `dump_analysis`
  only runs AFTER `analyze_files` returns, the earlier session's "full
  byte-identical output, THEN segfault at exit" was undefined behavior, not
  a second crash site: the boxed cell for `next_opcode` was never allocated,
  so every `*next_opcode = …` wrote through an UNINITIALIZED `int64_t *`
  local — with a writable stack-garbage value the run "worked" (output
  appeared; some later write or teardown hit bad memory), with NULL it
  crashed instantly before any output. Same bug, nondeterministic symptom.
- Mechanism: a local captured BY REFERENCE by a nested closure
  (`ClosureInfo.mut_names`, the `{mut}`/nonlocal family) is pre-declared as
  a heap-boxed pointer (`{ctype} * name;`) by `_seed_mut_captured_local_
  types`, but its cell was malloc'd ONLY by `_gen_stmt_VarDecl` — i.e. only
  when the first binding is a Mojo-style `var x = …`. Real PYTHON source's
  first binding is a plain `AssignStmt` (`next_opcode = 1`), which never
  reaches that handler, while every read/write still dereferences the
  pointer (`*name`). Every existing test used Mojo-source `var` shapes;
  the Python shape had zero coverage.
- Fix (shared compiler source): new `_emit_mut_local_box_allocs`
  (gimple_gen_infra.py) allocates EVERY boxed local's cell ONCE in the
  function prologue; called from both plain-function generation
  (gimple_gen_funcs.py gen_func) and struct-method generation immediately
  after seeding. `_gen_stmt_VarDecl`'s boxed branch now only stores the
  initial value through the already-allocated cell. This gives exactly-once,
  call-scoped cells (Python's own per-call cell model) and also fixes two
  latent hazards of the per-statement scheme: a VarDecl re-executed by its
  loop re-malloc'd a FRESH cell per iteration while the nested closure's env
  kept the stale one (splitting the nonlocal binding), and a first binding
  lexically inside one branch left the box unallocated on other paths.
- Causality proven BOTH ways: the same minimal repro built from the pre-fix
  tree SEGFAULTS (exit 139); with the fix it prints the CPython-verified
  result on both compiled paths (link mode AND the inline
  `build_executable` pipeline), exit 0. New regression suite
  `test_python_source_mut_capture.py` (3 tests, expectations verified
  against real CPython 3.14) fails with a deterministic SIGSEGV without the
  fix and passes with it.

Quality gate: test_gimple.py 256/256, test_module_cache.py 76/76,
make check-selfhost clean, from-scratch stdlib dylib rebuild with 0
`skip <module>:` lines. All pre-existing closure suites re-run green:
test_general_mutable_closure_capture 6/6, test_transitive_closure_capture
2/2, test_closure_capture_comptime_func_params 4/4,
test_mutable_async_capture 2/2.

**End-to-end state after the fix:** `python3 fire.py build …/analyzer.py`
exits 0; the binary runs deterministically with exit 0 (3/3 runs, no crash
under repeated runs or lldb). Output is currently the four section headers
only — because of the separate, precisely-root-caused gap below (NOT a
regression of this fix; verified present at the previously-"verified"
8dfd12f as well).

**Next blocker, root-caused (architectural; deliberately not forced here):
link-mode resolution does nothing for plain project-sibling modules.**
In link mode (driver.compile_program — `fire.py build`'s primary path),
`import parser` registers the module ALIAS but nothing registers parser.py's
functions (`parse_files` never enters `func_return_types`; the reflection/
dylib resolver finds no dylib for a bare sibling .py), so every
module-qualified access lowers against the `(int64_t)0` module-marker
global: `parser.parse_files(filenames)` emits
`_t7 = _t2; /* int64_t.parse_files() stubbed */` (returns receiver garbage),
and analyze_files consequently iterates a garbage "list" → empty forest →
empty sections. Minimal repro (two-file sibling project):
`import helper; print(helper.f())` builds clean and silently prints `0`;
the `from helper import f` form at least degrades LOUDLY (`f: unavailable
in compiled mode (imported from an unresolved external/relative module)`
then 0). The INLINE pipeline (`compile_to_gimple(do_imports=True)` /
fire.py's build_executable fallback) fully inlines sibling sources and
resolves everything correctly — which is how the 2026-08-25 entry's
byte-identical 2892-line run must have been produced (link mode failing
loudly back then, triggering the inline fallback; today link mode
"succeeds" while silently stubbing, so no fallback fires). Closing this
needs real link-mode sibling support (on-demand sibling dylibs, or
registering sibling exports into `_register_link_imports`, or a driver
policy that falls back to inline compilation whenever unresolved LOCAL
siblings exist) — squarely the shared import-seam machinery with this
campaign's documented regression history; recorded here with repros rather
than forced.

## Status (updated 2026-08-25, branch fix/opencode-group1 — FIXED: the zip_longest blocker is resolved; build exits 0 and real-input output is byte-identical to CPython's; one unrelated pre-existing exit-time crash documented below)

The `itertools.zip_longest` gap root-caused in the 2026-08-25 entry below is
now fixed in shared source (commit `8dfd12f` on fix/opencode-group1):
`for (a, b) in itertools.zip_longest(sa, sb)` lowers as a plain index loop
over max(len_a, len_b) — each tuple-target slot assigned from its OWN
sequence's element i (that sequence's tracked element-type accessor), or
the fill value past its length (default 0 = this model's None, so the
body's `x is None` guards test a genuine 0/NULL). Per-slot element typing
propagates from each sequence's own `_elem_types` entry, so
analyzer.py's `list[StackItem]` inputs/outputs give genuinely struct-typed
loop variables (fixing BOTH error sites: line 386's chained member writes
AND line 401's `input.used = True`, which was poisoned by first-decl-wins
off the same mistyped loop). The dispatch is transactional: any unprovable
shape (non-2-arity, non-tuple target, non-list sequence, non-literal
fillvalue) rolls back and falls through to the old generic path unchanged.

**End-to-end verification (beyond "compiles"):**
- `python3 fire.py build .../cases_generator/analyzer.py` exits 0.
- Standalone equal/unequal-length repros (struct-typed sequences,
  `is None` padding guards, attribute writes on loop vars) produce output
  byte-identical to python3 on both paths.
- The compiled binary run on REAL input (`analyzer Python/bytecodes.c`)
  produces output byte-identical to CPython's own run of the same command
  (all 2892 lines — Uops/Instructions/Families/Pseudos), exercising
  analyze_stack's zip_longest loop for real. (CPython itself refuses
  interpreter_definition.md — wrong input format, same on the Python side.)

**Residual (pre-existing, NOT this fix's scope):** after printing its full
byte-identical output the process segfaults at exit; lldb attributes it to
`assign_opcodes`'s `nonlocal next_opcode` mutable-closure site
(analyzer.py:1066) — the boxed-mutable-capture family, untouched by and
unreachable-from the loop lowering (which allocates nothing). Two further
pre-existing quirks observed while isolating that: a struct-field read of
an int64_t-boxed field in a str-concat context can stringify via
`mojo_str_from_int` (pointer printed as decimal; reproduces with a plain
hand-written index loop, no zip_longest involved — root family is the
excluded HIGH-RISK unannotated-init-param/field-type doc), and bools print
as 0/1. None affect analyzer.py's own analyzed output above.

Quality gate: test_gimple.py 256/256, test_module_cache.py 76/76,
make check-selfhost clean, from-scratch stdlib dylib rebuild with 0
`skip <module>:` lines.

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

Re-ran on current `master` (`python3 fire.py build .../cases_generator/analyzer.py`,
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
`MojoList *` — new sibling gap originally recorded in
`bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md`, the doc that
supersedes the removed
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`).
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
