# CODEGEN_generator_function: Lib/codecs.py

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree (branched from master post-integration,
c46bf5d). `iterdecode`/`iterencode` still refuse at the exact same
`*`/`**`-unpack-call-argument guard (`getincrementalencoder(encoding)
(errors, **kwargs)`, a dynamically-obtained callee). None of the
mechanisms landed since the 2026-08-24 pass (struct-method extern-decl
param typing, generator-consumption ordering, `**kwargs`-forward slot
alignment, `int()`/`float()` in coroutine bodies, weak variadic stubs,
`cls.attr` writes, classmethod-generator receiver passing, mixed-yield
refusal, chained-assignment type-hint propagation) touch this shape —
none of them address dynamic-callee kwargs-spread. Genuinely unfixable
without the same large dynamic-kwargs-dispatch feature already assessed
repeatedly. No change; doc stays open.

## Status (updated 2026-08-24 — re-verified unchanged)

`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/codecs.py` still
refuses at the module gate exactly as documented:
`iterdecode, iterencode` refused for "a `*`/`**`-unpack call argument is
not supported" — `getincrementalencoder(encoding)(errors, **kwargs)`,
a dynamically-obtained callee whose real parameter names aren't known
at compile time. Genuinely unfixable without a much larger dynamic-
kwargs-dispatch feature (as already assessed). No change; doc stays open.


## Status (updated 2026-08-23 — re-verified unchanged; honest-refusal state confirmed still correct)

Re-ran the repro against current code (this session landed three generic
generator-codegen fixes, none touching this shape): isolated compile of
Lib/codecs.py still fails with the exact same honest refusal —
`RuntimeError: cannot compile module: function(s) iterdecode, iterencode
(generator function(s), contain a yield/yield from)` — raised by the
`*`/`**`-unpack-call-argument guard in the coroutine-body emitter, never
reaching any C emission. The underlying feature gap (kwargs-spread against
a dynamically-obtained callee) remains genuinely unimplemented and
feature-sized, exactly as the 2026-08-10 entry concluded. No change; no
new investigation warranted.


## Status (updated 2026-08-10, later same session — the `**kwargs`-unpack MISCOMPILE fixed into an honest refusal)

The `**kwargs`-call-argument miscompile documented below (`_cpp_expr`
emitting the literal, invalid `(**kwargs)` for a `getincrementalencoder
(encoding)(errors, **kwargs)`-shaped call) is **fixed**, but not by
implementing real dynamic-callee/kwargs-spread support — that remains a
genuine, much larger feature (the callee here is a dynamically-obtained
class; even a correct implementation would need to know ITS real
parameter names at compile time, which this scalar coroutine-body model
has no way to discover at all). Instead, `_cpp_expr`'s `CallExpr` case
now detects ANY `*`/`**`-unpack call argument (a `UnaryOp(op='*'/'**',
...)` node, this project's parser convention — see `CLAUDE.md`) up front
and raises `_UnsupportedGeneratorShape` immediately, before reaching any
of the several call-argument-lowering sites that previously fell through
to the generic (wrong) `UnaryOp` case. This converts the bug from a
silent MISCOMPILE (invalid C++ that happened to still look plausible
enough to reach `g++`) into the same honest, graceful "generator not
eligible, fall back to interpreting the module from source" refusal
every other unsupported generator shape in this codegen already gets —
the same family as `bugs/hard/CODEGEN_generator_lambda_expr_
unsupported.md`'s existing `LambdaExpr`-argument refusal (which this doc
previously classified this bug alongside as a "sibling gap", per the
2026-08-09 status below).

Verified: an isolated compile of `codecs.py` alone (`do_imports=False`)
now raises the standard `RuntimeError: cannot compile module: function(s)
iterdecode, iterencode ...` refusal — the exact same message shape
`calendar.py`/`dis.py` produce for THEIR still-unsupported generators —
instead of ever reaching the broken `(**kwargs)` emission site. A fresh
`MOJO_DEBUG=1 python3 mojo.py build .../Lib/codecs.py` confirms the same:
both generators are refused at "not eligible for C++ coroutine path"
with the new, precise message, and the whole build fails with the
standard fatal `Error building: cannot compile module: ...` (same
"escalates to a fatal RuntimeError for the root build target" behavior
this family's other docs already document — not a new inconsistency).
Commit: `dbe97ee`.

**`codecs.py` still does not compile natively** — it never could (the
`**kwargs`-against-a-dynamic-callee shape is a real, unimplemented
feature, not a narrow bug), but it now fails the SAME honest way every
other out-of-scope generator shape does, instead of via a miscompile.
Doc kept open (the underlying feature gap is real and unresolved), status
updated to reflect the miscompile is gone.

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs, this file included (the `struct _opcode_toplev`
error in the 2026-08-06 section below, already noted there as stale/
from-the-wrong-gcc-binary). Confirmed via fresh rebuild: zero
occurrences of that error now regardless (already fixed by the
mechanism-1/mechanism-2 fixes, `bugs/hard/COMPILE_FAIL_module_toplev_
struct_never_fully_defined.md`, deleted as resolved). Not this file's
live blocker (that's the `**kwargs` coroutine-arg-lowering miscompile
below, unrelated).

While tracing the mechanism, found+fixed one closely related residual
bug (`_gen_struct_method`/`_gen_lifted_closure` never setting `self.
_current_module_ctx`, misrouting a `global`-statement write inside a
class method to the wrong module's struct — full writeup in the
module_toplev_struct_never_fully_defined doc's history and this
session's commit) plus a related `_safe_coerce_emit` gap (`.`-accessed
struct-field LHS not recognized, only `->`-accessed). Effect on this
file: total build error count dropped 645 -> 643 via a fresh rebuild.
The `**kwargs`-unpack blocker below is unaffected.

## Status (updated 2026-08-09)

Re-verified against current master (`3d36ccd`). `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/codecs.py` still fails, but the failure
is NOT the collection of unrelated errors listed in the 2026-08-06
status below — those turned out to be a red herring from testing with
the wrong `gcc`/`g++` binary in this session's own investigation
(`gcc-15`/`g++-15` aren't actually on `PATH` in this environment; the
project's real compiler is `/opt/local/bin/gcc-mp-15` /
`/opt/local/bin/g++-mp-15`, per `build_config.find_gcc()`/`find_gxx()`
— a plain `gcc-15 ...` silently no-ops as "command not found" and a
naive `grep -c error` on its empty output reads as "0 errors", a false
negative). Once re-tested with the correct binaries,
`codecs.py`'s own generated `.ci` (plain-C part) compiles 100% clean —
confirming the "not a generator-codegen-cluster failure" conclusion
below WAS right about the `.ci` side.

**However, `codecs.py` DOES still fail, for a real, still-open,
generator-codegen reason** that the 2026-08-06 pass never actually
reached (it was looking at the wrong error output). Root-caused via
`driver.compile_program` directly (`mojo.py build`'s primary,
module-cache/link-mode path — a DIFFERENT codegen invocation from the
plain `compile_to_gimple_with_cpp(do_imports=True)` path
`build_executable`, its fallback, uses): the companion `.cpp`
(coroutine-translation unit for `codecs.py`'s own 2 generators,
`iterencode`/`iterdecode`) fails to compile with g++:

```
client_async.cpp: In function '_mojogen_iterencode_Task _mojogen_iterencode_impl(MojoList*, int64_t, int64_t, MojoDict*)':
client_async.cpp:113:65: error: no match for 'operator*' (operand type is 'MojoDict')
  113 |     encoder = (getincrementalencoder_0c85c9(encoding))(errors, (**kwargs));
      |                                                                 ^~~~~~~~
client_async.cpp:113:74: error: expression cannot be used as a function
client_async.cpp:117:26: error: request for member 'encode' in 'encoder', which is of non-class type 'int64_t'
```
(identical pair for `iterdecode`/`decoder` at :185/:189).

**Root cause, precisely identified:** `codecs.py`'s real source, line
1052 (`iterencode`, a generator — contains `yield output`):
```python
encoder = getincrementalencoder(encoding)(errors, **kwargs)
```
a `**kwargs`-unpack used as a CALL ARGUMENT (`iterdecode`'s sibling
line 185/`getincrementaldecoder` is identical). `gimple_codegen.py`'s
coroutine `.cpp` expression emitter (`_cpp_expr`, ~line 23418) lowers
every call argument via a flat `', '.join(self._cpp_expr(a) for a in
e.args)` (repeated at every `CallExpr` call site in that function, e.g.
~23712/23716) with NO special case for a `**kwargs`/`*args`-unpack
argument (a `UnaryOp` node per this project's `*`/`**` call-argument AST
convention — see this repo's own `CLAUDE.md`). Such a `UnaryOp` instead
falls through to `_cpp_expr`'s generic `UnaryOp` case (~line 23512):
```python
if isinstance(e, UnaryOp):
    op = {'not': '!'}.get(e.op, e.op)
    return f"({op}{self._cpp_expr(e.operand)})"
```
which for `op == '**'` literally emits `(**kwargs)` — C++ parses that as
a double pointer-dereference of the `MojoDict *` local, not an argument-
unpack — hence "no match for operator*". This is a silent MISCOMPILE
class bug (produces syntactically-plausible-looking but wrong C++,
rather than an honest refusal), not a graceful "unsupported shape"
refusal — worse than most of this family's other gaps in that respect,
though the end effect (this module can't compile through the coroutine
path) is the same.

**Classification: same structural bucket as the already-documented,
explicitly-not-attempted `bugs/hard/CODEGEN_generator_lambda_expr_
unsupported.md`** (a sibling gap in the exact same `_cpp_expr`
call-argument-lowering machinery — that doc covers a `LambdaExpr`
argument falling through to a dispatcher with no case for it; this is a
`*`/`**`-unpack argument falling through to the wrong generic case
instead). Both are instances of "the coroutine-body expression emitter's
call-argument handling is narrower than the ordinary (non-generator)
function path's," which is this session's stated out-of-scope
generator/coroutine structural gap. Not attempted here, per this
session's explicit mandate to confirm-and-document rather than extend
this family's codegen. A minimal, purely-defensive narrower fix (making
this ONE shape raise `_UnsupportedGeneratorShape` instead of emitting
invalid C++, so it fails soft — falls back to interpreting the module —
instead of hard) was considered but also not attempted, to keep this
pass's footprint on shared `_cpp_expr` machinery at zero, matching the
lambda doc's own precedent.

## Status (updated 2026-08-06, superseded above — see note on wrong
compiler binary; the specific errors below were never actually
codecs.py's real blocker)

**STILL FAILING**, but re-diagnosed against current master (`2b0c4c5`) —
the 2026-07-30 `getincrementalencoder` .cpp error no longer reproduces.
`codecs.py` has exactly 2 generators of its own
(`StreamReaderWriter`/similar `__getattr__`-adjacent helpers around
lines 1056/1074, both simple `yield output` shapes) — **neither shows up
anywhere in the current error list**, and `MOJO_DEBUG=1` shows no "not
eligible"/refusal note naming either of them, so codecs.py's OWN
generator bodies now appear to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
codecs.py currently fails to build for a large number of severe,
apparently unrelated pre-existing bugs that have nothing to do with
`yield`/coroutines — dominant ones seen in the current error list:

```
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:685:10: error: expected '=' before '*' token
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:686:3: error: expected expression before 'MojoList'
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:704:3: error: '_t3' undeclared (first use in this function); did you mean '_t2'?
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:710:3: error: implicit declaration of function 'io_Reader_mojo_read'; did you mean 'StreamReader_mojo_read'? [-Wimplicit-function-declaration]
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:923:25: error: invalid use of undefined type 'struct _opcode_toplev'
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:75:26: error: assignment to 'char *' from 'int64_t' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:1362:46: error: stray '\' in program
/Users/mrs/net/Python-3.14.6/Lib/codecs.py:1362:47: error: missing terminating ' character
```

(the 685-789-range block looks like a garbled multi-variable declaration
statement emitted with the wrong syntax entirely — likely a class-field/
tuple-unpack codegen bug; the `:1362` stray-backslash error looks like a
raw-string/escape-handling tokenizer bug; neither is generator-related.)

Not investigated further — genuinely out of scope for this generator-
codegen cluster's mandate. If picked up, these look like they'd need
their own dedicated `COMPILE_FAIL_Lib_codecs.md`-style investigation
(unrelated to `bugs/hard/CODEGEN_*` generator docs), starting with the
malformed declaration block around lines 685-789.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/codecs.py
