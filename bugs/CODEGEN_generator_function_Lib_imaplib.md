# CODEGEN_generator_function: Lib/imaplib.py

## Status (updated 2026-08-11 — 3 of the 4 documented `Idler.burst` gaps FIXED; 2 blockers remain, both precisely diagnosed, neither fixed)

Re-verified with a fresh direct minimal repro (`Idler`/`IMAP4` reduced
to just the shapes `burst()` touches, same methodology as the
2026-08-09 entry below). Of the 4 previously-documented gaps, 3 are
FIXED this pass (all in `gimple_codegen.py`, all generic — not
imaplib.py-specific):

1. **`self._imap.sock` (a 2-level `self.<field>.<field>` chain)** —
   `_cpp_expr`'s `MemberExpr` case only ever recognized a single-level
   `self.<field>` read; a chain through an INTERMEDIATE struct-pointer
   field fell to the generic non-self fallback, emitting `self->_imap
   .sock` (`.`, not `->`) on a field this narrow model's own boxing
   convention stores as a raw `int64_t` in the C++ typedef regardless
   of its real pointer type — g++: "member reference base type
   'int64_t' is not a structure or union". Fixed by adding a case that
   recognizes `self.<field1>.<field2>` when `field1`'s type (already
   known via `struct_field_types`) is a registered struct pointer,
   casting through it explicitly: `((Inner *)(self->field1))->field2`.
   Also had to register the INNER struct name (`IMAP4`) into
   `_cpp_param_struct_names` — gen_module's existing "struct layout(s)
   needed by this module's compiled generator method(s)" .cpp-preamble
   typedef collection only knew about a generator method's own
   `self`-struct and a generator's declared parameter structs, neither
   of which covers a struct reached only indirectly through a field's
   pointer type.
2. **`next(self)` (the builtin, not a method call)** — unhandled,
   fell through to a bare undeclared C++ identifier. Fixed: `next(x)`
   now recognized when `x` is `self` or a struct-pointer local,
   dispatching to `x.__next__()` via the exact same struct-method-call
   machinery `self.<method>(...)` already uses (only the common 1-arg
   form; `next(x, default)`'s StopIteration-suppression not attempted).
3. **`self._pop(interval, None)` inside `while response := ...:`** —
   the self-method CALL itself was already correctly forwarding both
   arguments (an EARLIER fix, before this session, already closed that
   half — the doc's 2026-08-09 entry below describing "both real args
   dropped" is now stale). What was still broken: the WALRUS TARGET
   (`response`) was never declared at all — `_cpp_expr`'s `WalrusExpr`
   case only ever emits the assignment, assuming the name is already a
   declared C++ local (true for a walrus used as an ordinary
   statement's RHS, never true for one embedded directly in an `if`/
   `while` condition, which has no separate declaring statement) — g++:
   "use of undeclared identifier 'response'". Fixed with a new
   `_cpp_hoist_walrus_decls` helper, called from both `WhileStmt` and
   `IfStmt` before their condition is lowered: walks the condition
   (via the existing generic `_walk_ast`) for every `name := value`,
   declaring each with its value's inferred ctype — including a new
   special case for `self.<method>(...)`/`<struct-ptr-local>.
   <method>(...)` RHS (resolved via `func_return_types[f"{struct}_
   {method}"]`, mirroring `_quick_type`'s identical struct-method-call
   lookup), since the shared `_infer_simple_expr_ctype` free function
   has no self/struct-method-call case at all and would otherwise
   always default to `int64_t`.

Verified via a direct isolated repro (`Idler`/`IMAP4`/`burst`, all 3
shapes together) compiling clean through g++ and, separately, a real
end-to-end `mojo.py build` + run producing correct output values (not
just exit 0) for a str-returning stand-in `_pop`. Also confirmed
against the REAL `imaplib.py` inside the full transitive `mojo.py
build`: `Idler`/`burst`'s own generated code now shows ZERO gcc/g++
errors anywhere in the log (previously 4) — `MOJO_DEBUG=1` still shows
no "not eligible" refusal either.

Full mandatory gate (CLAUDE.md) re-run after all 3 fixes:
- `python3 test_gimple.py`: 247 passed, 0 failed
- `python3 test_module_cache.py`: 76 passed, 0 failed
- `make check-selfhost`: clean
- From-scratch `build/libmojostdlib.dylib` rebuild: 0 `skip <module>:` lines
- `python3 compile_stdlib.py` (no `-j`): 664/664 passed, 0 unexpected

**imaplib.py itself still does not build**, for two SEPARATE reasons,
neither attempted here:

**(a) A completely unrelated, severe, pre-existing symbol clash,
confirmed via the real full-build log** — GCC bails out ("confused by
earlier errors") partway through `ssl.py`, well before ever reaching
`imaplib.py`'s own code in this whole-program compile:
```
/Users/mrs/net/Python-3.14.6/Lib/ssl.py:6952:44: error: 'socket___enter__' undeclared here (not in a function); did you mean 'Idler___enter__'?
/Users/mrs/net/Python-3.14.6/Lib/ssl.py:6953:50: error: 'socket___exit__' undeclared here (not in a function); did you mean 'Idler___exit__'?
```
A cross-module symbol-resolution bug in `ssl.py`/`socket`-related
struct methods, unrelated to generators or to anything fixed this
session — out of scope for this doc, not investigated further (a
`ssl.py`-specific bug report would be the right place).

**(b) Even setting (a) aside, `self._imap`'s field is STILL wrong.**
`Idler.__init__(self, imap, duration=None):` (imaplib.py:1432) leaves
`imap` unannotated, so `_imap`'s registered field type defaults to
`int64_t` instead of the real `IMAP4 *` — this is the ALREADY-TRACKED
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
hard bug (re-verified unchanged earlier this same session), not
re-attempted here. Confirmed directly: fix (1) above is real and
correct — a minimal repro with `imap: IMAP4` annotated compiles and
runs `self._imap.sock` correctly end-to-end — but doesn't fully
activate for the REAL file until that separate hard bug is fixed.

**Also found, NOT fixed (a genuinely separate, pre-existing gap, not
introduced by any change this session, confirmed via a repro with NO
walrus/self-method/next() involved at all):** the coroutine-body
`_cpp_stmt`'s `if`/`while` condition lowering (`cond = self._cpp_expr
(s.condition)`) never applies Python truthiness coercion to a non-bool
condition value — a `char *`/`MojoList *` condition compiles to a raw
C++ pointer-non-null check (`if ((!s))` for `if not s:`), not
Python's real "is this string/list/tuple EMPTY" semantics. A minimal
repro (`while (s := f()):` where `f()` eventually returns `""`) hangs
forever at runtime instead of terminating, since a non-null pointer to
an empty string is still "truthy" in raw C++. This would matter for
`Idler.burst`'s own `while response := self._pop(interval, None):`
once (a) and (b) above are both resolved — `_pop`'s real return type
is a 2-tuple, which may also hit a SEPARATE representability limit in
this scalar coroutine-body model. Not investigated further or fixed —
a real, but broad, pre-existing gap (Python-truthiness coercion for
pointer/container-typed values is already solved on the ORDINARY
GIMPLE path via `_ensure_bool_cond`/`mojo_truthy_cstr`; porting the
equivalent to the coroutine-body emitter is a bigger, separate step,
not attempted here) — worth its own dedicated bug doc if it recurs
elsewhere.

## Status (updated 2026-08-09, re-verified with a direct minimal repro)

Re-verified against current master (post-merge `7df52a0`). The full
`mojo.py build` on the real `imaplib.py` is currently uninformative on
its own for this specific bug: the whole-transitive-graph build now
fails much earlier, in unrelated code (a severe `ssl.py`/`argparse`
symbol clash causing GCC to bail out early with "confused by earlier
errors") before the log gives a clean read on `Idler.burst`'s own
generated `.cpp`. So this pass isolated the method with a minimal
standalone repro (`Idler`/`IMAP4` classes reduced to just the shapes
`burst()` touches: `self._imap.sock`, `next(self)`, `self._pop(...)`)
and ran `MOJO_DEBUG=1 python3 mojo.py build` on that directly.

Result: no "not eligible" refusal (confirms the `raise self._imap.error
(...)` fix from `bugs/hard/CODEGEN_generator_raise_non_static_
exception_class.md` still holds — the generator reaches real coroutine
`.cpp` generation), and the generated `.cpp` reproduces all three
previously-documented blockers verbatim, unchanged:
```
imaplib_burst_repro_gen.cpp:120:23: error: request for member 'sock' in 'self->Idler::_imap', which is of non-class type 'int64_t' {aka 'long long int'}
imaplib_burst_repro_gen.cpp:126:18: error: 'next' was not declared in this scope
imaplib_burst_repro_gen.cpp:140:13: error: 'response' was not declared in this scope
imaplib_burst_repro_gen.cpp:140:34: error: too many arguments to function 'int64_t Idler__pop(Idler*)'
```
The 4th (`response`/arity) is one symptom, not two: `self._pop(interval,
None)` — a call to a `self`-method from inside a generator body — gets
silently codegen'd as a call to `Idler__pop(self)` (dropping both real
args, per the doc's original "self.<field> reads only, no method calls"
observation), so the `while response := ...` walrus assignment target
is left undeclared when the call shape mismatch cascades.

No change in classification or scope: these are the SAME structural
"coroutine-body expression emitter doesn't model nested struct-field
attribute chains, the `next()` builtin, or `self`-method calls" gaps as
before, not narrow, not attempted here — still worth a dedicated hard-
bug doc for `_cpp_expr`/`_cpp_stmt`'s silent-fallthrough-instead-of-
refusing behavior on unhandled generator-body constructs (a future
session's task, not this one).

## Status (updated 2026-08-07)

**Classification bug FIXED** (`bugs/hard/CODEGEN_generator_raise_
non_static_exception_class.md`, task #149) — `raise self._imap.error
(...)` no longer refuses at the eligibility gate; `_cpp_raise_stmt` now
emits a valid (untyped/lenient-match) `_MojoCppExc` throw for it.

**`Idler.burst` STILL does not compile end-to-end**, for OTHER,
unrelated pre-existing reasons in the same method body, confirmed via a
direct g++ compile of the generated `.cpp`:
- `self._imap` is itself a struct-typed field; `self._imap.sock` (a
  nested attribute chain through it) isn't representable in this
  narrow generator-body model (`self.<scalar field>` reads only) —
  g++: `request for member 'sock' in 'self->Idler::_imap', which is of
  non-class type 'int64_t'`.
- `yield next(self)` calls the builtin `next()`, not supported —
  g++: `'next' was not declared in this scope`.
- `self._pop(interval, None)` calls a method on `self` — also out of
  this narrow model's scope (self.<field> reads only, no method
  calls) — silently emitted as a call to an undeclared function rather
  than refused.

These are NOT new — they were always unsupported, just never reached
because the raise check refused `burst` FIRST. `imaplib.py`'s overall
build outcome is unchanged (still fails, same as before) — only the
internal blocker moved. Worth a dedicated hard-bug doc in a future
session on `_cpp_expr`/`_cpp_stmt`'s silent-fallthrough-instead-of-
refusing gap for unhandled generator-body constructs; not attempted as
part of the raise fix (see that hard-bug doc's own "Important finding"
section for the full analysis, including confirmation via the required
gate that this doesn't affect any currently-passing file).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/imaplib.py
[gimple_codegen] generator method Idler.'burst' not eligible (pass 2): unsupported `raise` value expression in generator body (only `raise ExcName(...)`/`raise ExcName` with a statically known exception class name is supported)
Error building: cannot compile module: function(s) burst (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Root cause:** `Idler.burst`:
```python
def burst(self, interval=0.1):
    if not self._imap.sock:
        raise self._imap.error('burst() requires a socket connection')
    try:
        yield next(self)
    except StopIteration:
        return
    while response := self._pop(interval, None):
        yield response
```
`raise self._imap.error(...)` raises an exception CLASS resolved via a
runtime member-expression (`self._imap.error`, a class stored as an
instance attribute) rather than a statically-known bare class name
(`raise ValueError(...)`). The coroutine codegen's `raise`-lowering
(Milestone D's real-C++-exceptions-in-the-generator's-own-translation-
-unit design) requires the exception class to be resolvable at compile
time to build the corresponding C++ exception object/type — a `raise
<MemberExpr>(...)` shape has no such static class name to work with, so
it's refused outright, and (same escalation pattern as
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`) a single
module-level-reachable refusal like this hard-fails the WHOLE file's
`mojo.py build`, not just this one generator method.

**Now folded into `bugs/hard/CODEGEN_generator_raise_non_static_
exception_class.md`** — confirmed recurring twice more (`test.support`'s
`run_with_locale`/`subst_drive`, found while diagnosing
`Lib/test/_test_eintr.py`), so promoted from "single instance" to a full
hard-bug doc. See that doc for the shared root cause and fix-scope
notes.

Not fixed here — same reasoning as the sibling struct-param-refusal
gap: a genuine coroutine-codegen scope boundary (exception-type
resolution needs to happen at C++ compile time), not a narrow accidental
bug.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/imaplib.py
