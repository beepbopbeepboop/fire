# COMPILE_FAIL: Tools/cases_generator/parsing.py

## Status (2026-09-30, branch work/compile-fail-stdlib-misc — THIS DOC'S CENTRAL CLAIM IS NOW FALSE: the 12 own-file errors are GONE and the file BUILDS. But it is SILENTLY WRONG, which is worse, and the cause is `lexer.py`'s `globals()`, not `parsing.py`)

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Tools/cases_generator/parsing.py`:

```
Built: /Users/mrs/net/chatgpt/claude/work-95/.tmp/out/parsing     (exit 0, 12 s)
```

**Zero `error:` lines.** None of the twelve polymorphic
`yield from self.<field>.tokens()` dispatch errors that every entry below
records reproduces — `_struct_method_csym` evidently resolves those now (or
the shape is refused at a level above gcc without failing the build). The
doc's whole "12 own-file `parsing_gen.cpp` errors" premise is stale, and
it has been for long enough that every entry below should be read as
history rather than as a current description.

### What replaces it is NOT a fix

Run both, same arguments (none):

```
$ python3 /Users/mrs/net/Python-3.14.6/Tools/cases_generator/parsing.py ; echo rc=$?
rc=0                                   # no output at all
$ .tmp/out/parsing ; echo rc=$?
globals: unavailable in compiled moderc=0
```

CPython prints nothing and exits 0. The compiled binary exits 0 and prints
a codegen diagnostic **into its own stdout**. That is the
silent-wrong-output class: a program's observable output now contains a
compiler message.

Root-caused from the generated closure `.ci` — the weak stub is

```c
__attribute__((weak)) int64_t globals (...) {
    mojo_print ((char *)"globals: unavailable in compiled mode"); return (int64_t)0; }
```

and it has exactly two call sites, both in `_lexer_toplevel`, from
`Tools/cases_generator/lexer.py:76,78`:

```python
operators = {op: pattern for op, pattern in globals().items() if op == op.upper()}
for op in operators:
    globals()[op] = op
```

So `lexer.py`'s `globals()` — the module-dictionary builtin — lowers to
the generic unresolved-name weak stub, returns 0, prints into stdout, and
`operators` / `opmap` become garbage. `parsing.py` itself is innocent: it
merely imports `lexer`.

This is the same "a weak stub prints into the program's stdout and
returns a wrong value" failure `test_link_mode.py` and
`test_comptime_parity.py` already guard against for other names, and it
belongs to the `construct:compiled-silent-wrong-values` family, which is
another worker's claim. Filed for the record in this doc rather than as a
new doc, because the doc that claims this file does not compile is the one
that has to record that it now compiles and misbehaves.

### What a fix needs

`globals()` (and `locals()` / `vars()`) is not an unresolved external: it
is a builtin with a well-defined compiled meaning in this codegen — the
module's own globals struct, which already exists per module
(`_lexer_globals`, `_root_globals`, …). So the fix is to lower
`globals()` to that struct's address rather than to fall through to the
unresolved-name stub, and to make sure a weak stub can never print into a
program's stdout (that half is a separate, general improvement worth its
own doc).

Until then this file is a **false green**: exit 0 with wrong output is
harder to notice than the loud refusal it used to produce, and nothing in
`make check` builds this file. If a sweep over `Tools/` starts reporting
"built, exit 0" for these `cases_generator` files, it should be
cross-checked against CPython's output, not trusted.

Doc kept open — but the reason has completely changed, and the entry
below about "12 own-file errors" should no longer be used as the current
state.

Source file: `/Users/mrs/net/Python-3.14.6/Tools/cases_generator/parsing.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, worktree-agent-a01a24fff53233531 @ master `43fb291`): unchanged, same 12 own-file errors

Fresh `python3 fire.py build .../Tools/cases_generator/parsing.py`
against this worktree (fast-forwarded to master `43fb291`): exit 1,
exactly 12 own-file `parsing_gen.cpp` errors, byte-equivalent to the
entries below — the polymorphic `yield from self.<field>.tokens()`
static-dispatch class (`request for member 'tokens' in
'self->IfStmt::body'`/`ForStmt::body`/`WhileStmt::body` etc., plus the
matching int64_t→char*/Stmt* conversion errors). Still squarely the
excluded hard-doc polymorphic-dispatch cluster; not attempted.

## Status (re-verified 2026-08-26, worktree-agent-a21934cd6fb7c6509 @ master `e60b9cd`): unchanged, same 12 own-file errors

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Tools/
cases_generator/parsing.py` against this worktree (fast-forwarded to
master `e60b9cd`): exit 1, exactly 12 own-file `parsing_gen.cpp`
errors, same polymorphic `yield from self.<field>.tokens()`
static-dispatch class (`request for member 'tokens' in
'self->IfStmt::body'`/`ForStmt::body`/`WhileStmt::body` etc.). Still
squarely the excluded hard-doc polymorphic-dispatch cluster; per this
session's mandate, not attempted.

## Status (re-verified 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb` — unchanged, same 12 own-file errors)

Fresh safety-wrapped `python3 fire.py build .../parsing.py` against
this worktree (includes this session's dict-keyed %-formatting landing,
commit `e1e12bb` — unrelated): exit 1 with exactly 12 own-file
parsing_gen.cpp errors, byte-equivalent to the entries below — the
polymorphic `yield from self.<field>.tokens()` static-dispatch class
(`request for member 'tokens' in 'self->IfStmt::body'` etc., plus the
matching int64_t→char* conversion errors), at fresh line numbers
(179/184/189/192/254/259/...). Cross-cutting confirmation from this
session: these refused generator shapes also dangle REFERENCES when
parsing.py is inline-compiled into a larger whole-program closure
(analyzer.py's forced-inline build fails at LINK time on undefined
`__mojogen_BlockStmt_tokens_*`, see analyzer.py's doc 2026-08-26
entry) — same excluded hard-doc cluster, one mechanism, two visible
symptoms. Real vtable/type-tag dispatch in the coroutine path remains
a genuine feature project; not attempted. No code change.

## Status (re-verified 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825, 02:24) and generator-value-return-slot fix (326db78, 02:57); both landed AFTER this doc's most recent entry (00:27) — neither applies, unchanged)

Fresh `compile_to_gimple_with_cpp(do_imports=False)` repro against this
worktree (both of today's landed fixes included) reproduces the IDENTICAL
error class as every prior entry: `request for member 'tokens' in
'self->IfStmt::body'` (`Stmt*`), same for `ForStmt::body`/`WhileStmt::
body`/`IfStmt::else_body` (`MojoList*`), plus the matching int64_t<->char*/
Stmt* conversion errors at every sibling `co_yield`/`yield from` site
(`IfStmt.tokens`/`ForStmt.tokens`/`WhileStmt.tokens`/`MacroIfStmt.tokens`/
`BlockStmt.tokens`). Confirmed this is genuinely the same static-symbol-
resolution mechanism as always: `self.body.tokens()` where `body: Stmt` is
a base-typed field holding a concrete subclass (`IfStmt`, `ForStmt`, ...)
at runtime — the coroutine emitter's `_struct_method_csym` still resolves
purely by the field's STATICALLY DECLARED struct name, with no vtable/
runtime-type-tag dispatch anywhere in this path.

Checked specifically whether either of today's two fixes helps, per this
run's assignment: neither does, and for a clean structural reason — both
`bdfb825` and `326db78` are about resolving WHICH CONCRETE METHOD BODY a
call site should statically bind to when the receiver's STATIC type is
already known (`super()`: pick the first base in MRO that defines the
method; `self.__class__(...)`: construct the RUNTIME type). Neither adds
or touches any RUNTIME dispatch mechanism for a call through a
statically-base-typed field/variable holding a subclass instance — that is
precisely what this file's blocker needs (`self.body.tokens()` where
`self.body`'s declared type is `Stmt` but its runtime type varies). Still
squarely the excluded polymorphic-dispatch hard-doc cluster
(`CODEGEN_generator_recursive_yield_from_no_arg_forwarding`/
`CODEGEN_generator_classmethod_first_param_must_be_self.md`). Not
attempted — real vtable/type-tag dispatch in the coroutine codegen path is
a genuine feature project, not a narrow fix. No code change.

## Status (re-verified 2026-08-26, branch fix/rest-remainder15 — unchanged)

Direct source re-check confirms this is still structural, not narrow:
`gimple_cpp_core.py`'s struct-method call dispatch
(`_struct_method_csym(struct_name, e.member, '')`, used at every
`self.<method>(...)`/`<struct-ptr>.<method>(...)` call site in the
coroutine emitter — ~9 call sites checked) always resolves the target
method by the field's STATIC declared struct name, compiled to a fixed
C symbol at codegen time — there is no vtable/runtime-type-tag dispatch
mechanism anywhere in this coroutine path for a base-typed field (e.g.
`IfStmt.body: Stmt`) holding a concrete subclass instance at runtime.
`yield from self.<field>.tokens()` on such a field can therefore only
ever resolve to `Stmt`'s own (missing/wrong) `tokens` method, not the
real subclass's. Matches the doc's own diagnosis exactly; still
squarely the excluded polymorphic-dispatch hard-doc cluster. No shared
fix from this campaign's other recent landings touches static struct-
method symbol resolution. Not attempted. No code change (full rebuild
not re-run this pass — the mechanism-level source confirmation is
conclusive and this file's line numbers are already known to shift
cosmetically between rebuilds without changing the actual blocker).

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1)

Fresh repro: same structural class as both entries below — the
generated `parsing_gen.cpp` still fails on polymorphic
`yield from self.<field>.tokens()` dispatch (`request for member
'tokens' in 'self->IfStmt::body'` where body is `Stmt *`,
`'self->IfStmt::else_body'`/`'self->ForStmt::body'` where MojoList*,
plus the int64_t→char*/Stmt* conversions), at fresh line numbers
(179/184/189/192/254/259/320/325/386/397/461/470). None of this
round's landed shared fixes (zip_longest per-slot typing, opaque-
handle write mirror, WithStmt generator driving, cpp string escaping)
touch runtime-polymorphic receiver dispatch on base-typed struct
fields — still squarely the excluded hard-doc cluster below. No code
change; doc re-verified with current line numbers. Still open.

## Status (re-verified 2026-08-25)

Re-ran fresh against `fix/rest-remainder9`: same structural class of
error as 2026-08-23 (polymorphic `self.<field>.tokens()` dispatch in the
C++ coroutine path — `request for member 'tokens' in 'self->IfStmt::body'`
etc., plus `int64_t`→`char*`/`Stmt*` conversions), though the specific
line numbers in `parsing_gen.cpp` shifted slightly (179/184/189/192/254/
259/320/325/386/397/461/470 vs the previous 159/164/.../366/367). No
regression, no fix — same deliberately-excluded polymorphic-dispatch gap
(`CODEGEN_generator_recursive_yield_from_no_arg_forwarding`/
`CODEGEN_generator_classmethod_first_param_must_be_self.md` cluster). Not
attempted, per this round's guidance against speculative changes to this
shared, regression-prone machinery.

## Status (2026-08-23): re-verified — STILL-OPEN on the same documented blocker.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`; parser.py, the
sibling that shared the struct-inheritance and link-stage blockers, now builds
end-to-end — see its doc). `parsing.py` still fails in its own generated
coroutine companion with the SAME polymorphic-field shape documented in the
2026-08-09 entry below: `request for member 'tokens' in 'self->IfStmt::body'`
(`Stmt *`), `'self->ForStmt::body'`/`WhileStmt::body`/`IfStmt::else_body`
(`MojoList *`) — i.e. `yield from self.<field>.tokens()` on fields whose
declared type is base `Stmt` (or list-of-`Stmt`), where the concrete subclass's
generator method must be dispatched at runtime. The error set also gained 7×
`invalid conversion from 'int64_t' to 'char*'` and one
`int64_t → Stmt*` in the same functions (`IfStmt.tokens`/`ForStmt.tokens`/
`WhileStmt.tokens`/...), same underlying typing gap. Structural per the
existing analysis (needs polymorphic receiver dispatch in the coroutine path);
not attempted here. Note: sibling `parser.py` is now compile-clean, so this
file's remaining errors are purely its own — no transitive masking remains.

## Status (2026-08-09, historical — superseded header only; body below unchanged): both prior blockers

Re-verified fresh. `cwriter.py`'s ICE is fixed this session (see that
file's own doc), so `parsing.py` gets past it. That surfaced the SAME
struct-field-type-inheritance corruption documented in `bugs/
COMPILE_FAIL_Tools_cases_generator_parser.md` (`class Parser(PLexer)`,
defined right in this file, inherits `PLexer`'s `pos`/`src`/`filename`/
`tokens` fields, which the buggy heuristic redeclared `struct Parser *`)
— also now fixed by the same `gimple_codegen.py` change (see that doc
for the full root-cause writeup; not repeated here).

**Still does not build**, for a THIRD, separate reason exposed once both
of the above got out of the way — this one specific to `parsing.py`
itself, not a transitively-imported sibling:

```
parsing_gen.cpp:159:20: error: invalid conversion from 'int64_t' {aka 'long long int'} to 'char*' [-fpermissive]
parsing_gen.cpp:164:49: error: request for member 'tokens' in 'self->IfStmt::body', which is of non-class type 'int64_t' {aka 'long long int'}
parsing_gen.cpp:169:24: error: invalid conversion from 'int64_t' {aka 'long long int'} to 'char*' [-fpermissive]
parsing_gen.cpp:172:58: error: request for member 'tokens' in 'self->IfStmt::else_body', which is of pointer type 'MojoList*' (maybe you meant to use '->' ?)
parsing_gen.cpp:234:20: error: invalid conversion from 'int64_t' {aka 'long long int'} to 'char*' [-fpermissive]
parsing_gen.cpp:239:49: error: request for member 'tokens' in 'self->ForStmt::body', which is of pointer type 'MojoList*' (maybe you meant to use '->' ?)
...
parsing_gen.cpp:366:20: error: invalid conversion from 'int64_t' {aka 'long long int'} to 'char*' [-fpermissive]
parsing_gen.cpp:367:28: error: 'begin' was not declared in this scope
parsing_gen.cpp:367:28: error: 'end' was not declared in this scope
```

This is the C++ coroutine companion for `parsing.py`'s own `Stmt`
subclasses' `tokens()` generator methods (`IfStmt.tokens`,
`ForStmt.tokens`, `WhileStmt.tokens`, `MacroIfStmt.tokens`,
`BlockStmt.tokens`, ...), e.g.:

```python
class IfStmt(Stmt):
    body: Stmt          # polymorphic — a Stmt SUBCLASS instance at runtime
    ...
    def tokens(self) -> Iterator[lx.Token]:
        yield self.if_
        yield from self.condition
        yield from self.body.tokens()   # <- generator method call on a
                                         #    POLYMORPHIC field, itself
                                         #    ANOTHER generator
        ...
```

Every failing site is a `yield from self.<field>.tokens()` where
`<field>`'s declared type is the abstract base `Stmt`, but the actual
runtime value is one of several concrete subclasses (`IfStmt`,
`ForStmt`, ...) — the C++ coroutine codegen path emits a direct,
statically-typed `self->body->tokens()`-style call/member access
against `Stmt`'s own (or a wrongly-inferred scalar) layout rather than
going through the polymorphic dispatch the plain-C generator path uses
elsewhere, and (separately) loses track of the `begin`/`end` locals
used inside at least one of these methods' bodies entirely (`'begin'
was not declared in this scope`). **Not investigated further / not
fixed here** — this looks like the same general class of gap as the
already-documented, deliberately-excluded `bugs/hard/
CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`/
`CODEGEN_generator_classmethod_first_param_must_be_self.md` cluster
(polymorphic/chained `yield from` shapes the C++ coroutine codegen
project never fully covered), not a narrow, safe, one-line fix — per
this task's guidance to avoid speculative changes to shared generator-
codegen machinery with a documented history of broad regressions from
exactly this kind of "looks narrow" fix.

### Quality gate (2026-08-09): N/A for this file specifically — the
only code change this session (the struct-field-inheritance heuristic
fix) is documented, verified, and committed against `bugs/
COMPILE_FAIL_Tools_cases_generator_parser.md`; see that doc for the
full 5-part gate results (247/247 test_gimple.py, 76/76
test_module_cache.py, clean check-selfhost, 0-skip stdlib dylib
rebuild, 664/664 compile_stdlib.py). No `parsing.py`-specific code
change was made.

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

Same root cause as `“COMPILE_FAIL: Tools/cases_generator/cwriter.py”`
(comprehension-assigned struct field defaulting to `int` — see
`“the constructor-call-site field-typing pass understood only scalars”`).
Nothing specific to `parsing.py` itself was found. Not fixed here.

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
... (8719 more lines)
```

Exit code: 1
Elapsed: 14.76s
