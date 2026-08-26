# CODEGEN_generator_function: Lib/codecs.py

## Status (updated 2026-08-26 — implemented real loop-as-expression codegen in the coroutine-body C++ emitter; UNAFFECTED for this file specifically (its own blocker is `**kwargs`-to-dynamic-callee), but the mechanism itself is a genuine widening — see the cross-references below for where it DID move the needle)

A prior session's triage of this cluster found the single widest
recurring blocker: `gimple_cpp_core.py`'s `_cpp_expr` (the compiled-
generator/coroutine-body C++ expression emitter) had NO codegen for
loop-as-expression constructs — `list(<iterable-expr>)`,
`set(<iterable-expr>)`, and comprehensions (`[x for x in y]`/
`{x for x in y}`) all either hit the generic "unresolved callee" honest
refusal (for the `list()`/`set()` spellings) or silently lowered to an
honest-but-always-EMPTY `mojo_list_new ()` stub (for a bare
`Comprehension` node used as a value) — because every other call site in
this emitter expects `_cpp_expr` to return one inline C++ expression
string, and a real loop needs statements, which an expression slot can't
directly hold.

**Implemented this session** (`gimple_cpp_core.py`):
- `_cpp_build_container_from_iterable(gen, kind, iter_node, target_name,
  elem_node, cond_nodes)` — builds a real `MojoList *`/`MojoSet *` as an
  immediately-invoked C++ lambda (`[&]() -> T { T *acc = ...; <loop>;
  return acc; }()`) wrapping a genuine loop. The loop itself is built by
  handing a SYNTHETIC `ForStmt` (target/iterable from the comprehension,
  body = an `<acc>.append(<elem>)`/`<acc>.add(<elem>)` call, wrapped in
  `IfStmt`s for any `if` clauses) to the EXISTING `_cpp_for_stmt` — this
  reuses that function's already-broad iterable-shape dispatch (range/
  reversed-range/a declared `MojoList *`/`MojoSet *` local or
  `self.<field>`/a `MojoDict *`'s `.keys()`/`.values()`/`.items()`/a
  sibling already-compiled generator's call/itertools.repeat/...) rather
  than re-implementing iteration a third, narrower time. Any iterable
  shape `_cpp_for_stmt` doesn't recognize propagates its existing
  `_UnsupportedGeneratorShape` refusal unchanged.
- `_cpp_rename_ident`/`_cpp_rename_ident_container` — a generic
  dataclass-field-walking deep-copy-and-rename helper, used to give a
  comprehension's own loop variable a FRESH, collision-proof C++ name
  before building the synthetic `ForStmt` (a comprehension has its own
  scope in real Python; this emitter's `declared` dict is function-
  scoped, so reusing an outer variable's bare name would silently
  alias/clobber it).
- Wired into `_cpp_expr`'s `Comprehension` case (list/set kinds, single
  `for`-clause only — dict/generator kinds and multi-clause
  comprehensions still fall back to the old empty-stub behavior, no
  confirmed real occurrence needing them) and a new `CallExpr`
  `fname in ('list', 'set')` single-arg case (synthesizes the equivalent
  `{x for x in <arg>}`/`[x for x in <arg>]` shape, mirroring the
  ordinary non-coroutine GIMPLE path's own `_lower_ctor_from_iterable`,
  `gimple_gen_calls.py`).
- `gimple_exprtypes.py`'s `_infer_simple_expr_ctype` (the separate
  type-estimator used to declare a first-assigned local's C++ type)
  widened to match: `list(x)`/`set(x)` single-arg calls now infer
  `MojoList *`/`MojoSet *` (previously fell through to the `int64_t`
  default, so `_cpp_stmt`'s `AssignStmt` case declared the wrong C++
  type — "invalid conversion ... to int64_t"), and a `set`-kind
  `Comprehension` now infers `MojoSet *` (previously ALL comprehension
  kinds inferred `MojoList *`, harmless while the codegen only ever
  produced an empty `MojoList *` stub regardless of kind, but a real
  mismatch now that a set comprehension genuinely builds a `MojoSet *`).
- `_cpp_for_stmt` gained a new dedicated single-name `for x in
  <MojoSet*-typed expr>:` case (`mojo_set_iter_new`/`_next`/`_val_int`/
  `_free`, mirroring the ordinary GIMPLE path's own `_gen_for_set`,
  `gimple_gen_loops.py`) — needed so `list(<a declared set local>)`
  round-trips through the new mechanism (previously only a declared
  `MojoList *` local had an indexed-loop iteration case here; a bare
  `MojoSet *` fell to the generic `for (auto x : ...)` range-for, which
  can't compile against a raw pointer with no ADL `begin`/`end`).

**Verification**: hand-written repros (`list(range(n))`, `[i*2 for i in
range(n)]`, `set(range(n))`, `[v for v in <declared list> if v > k]`,
`{v for v in <declared list> if v > k}`, `list(<dict>.keys())`,
`set(<dict>.values())`, `list(<declared set local>)`,
`list(<declared list local>)`) all g++-fsyntax-only-clean, added as a
new `test_gimple.py` regression case
(`generator_list_set_ctor_and_comprehension_loop_as_expr_compiles_via_
cpp_path`).

Re-verified the 9 docs the prior triage flagged as hitting this
mechanism, each via a fresh isolated `compile_to_gimple_with_cpp
(do_imports=False)` strict-mode repro AND a relaxed-mode `.cpp`
syntax-check, both `git stash`-A/B'd against the pre-fix tree:

- **ADVANCED** (real, concrete progress, not closed): `bugs/CODEGEN_
  generator_function_Lib_ipaddress.md` (`_collapse_addresses_internal`'s
  `list(...)` refusal fully eliminated, strict refused-generator count
  4→3; a deeper `.pop()` gap now blocks it), `bugs/COMPILE_FAIL_Tools_
  c-analyzer_c_analyzer___init__.md` (`analyze_decls`'s `list(...)` and
  `iter_decls`'s `set(...)` refusals both eliminated, each now blocked
  by a different, deeper, separately-tracked gap), `bugs/COMPILE_FAIL_
  Tools_c-analyzer_c_analyzer___main__.md` (`fmt_summary`'s `list(...)`
  refusal fully eliminated, strict refused-generator count 2→1).
- **UNAFFECTED** (confirmed byte-identical before/after, blocker is a
  genuinely different shape — `map()`/`getattr`/`reversed()`/a
  callable-parameter for-loop/`**kwargs`-to-dynamic-callee, all
  deliberately out of this fix's scope): `bugs/CODEGEN_generator_
  function_Lib_pkgutil.md`, `bugs/COMPILE_FAIL_Tools_c-analyzer_
  c_common_tables.md`, `bugs/COMPILE_FAIL_importlib_metadata___init__.md`,
  `bugs/COMPILE_FAIL_collections___init__.md`, and this file (`iterdecode`/
  `iterencode`'s own blocker is a `**kwargs`-to-dynamic-callee spread —
  `getincrementalencoder(encoding)(errors, **kwargs)` — not a `list()`/
  `set()`/comprehension shape at all).
- **Bonus correctness fix, no doc of its own blocker was closed**:
  `bugs/CODEGEN_generator_function_Lib_dis.md` — a DIFFERENT generator
  in the same file (`_find_imports`) previously silently compiled a
  real comprehension-over-a-sub-generator-with-a-filter shape to an
  honest-but-WRONG always-empty-list stub (a real correctness bug, not a
  compile failure); now compiles to the correct loop. See that doc's own
  entry for detail.

None of the 9 fully CLOSE (each file has additional, separately-tracked
gaps stacked behind or alongside its `list()`/`set()`/comprehension
blocker), but 3 of them show genuine, verifiable forward movement from
this specific fix, plus one confirmed real correctness improvement in a
tenth generator outside the original 9. Full mandatory gate: `test_
gimple.py` 264/264 (263 + 1 new regression test), `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild 0
skip lines (unchanged from baseline).

This file's OWN blocker (`iterdecode`/`iterencode`'s `**kwargs`-to-
dynamic-callee spread) remains exactly as documented below — genuinely
structural, not attempted. Doc stays open.

## Status (re-verified 2026-08-26, worktree agent-aac0d33be914873b5 — independent re-verify, byte-identical, no change)

Independent fresh isolated `compile_to_gimple_with_cpp(do_imports=False,
MOJO_DEBUG=1)` repro on the real file: byte-identical refusal —
`iterdecode, iterencode` on "a `*`/`**`-unpack call argument is not
supported in a compiled generator/coroutine body" at
`getincrementalencoder(encoding)(errors, **kwargs)`. Confirms the
opencode-genlib2 entry immediately below with a completely separate
harness run. Per this campaign's explicit mandate, not attempting the
underlying dynamic-callee kwargs-spread feature (large, already assessed
repeatedly). No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/opencode-genlib2 — re-verified fresh; refusal byte-identical, classification re-confirmed from the current guard code)

Fresh strict isolated `compile_to_gimple_with_cpp(do_imports=False)`:
byte-for-byte identical refusal — `iterdecode, iterencode` on
"a `*`/`**`-unpack call argument is not supported in a compiled
generator/coroutine body" at `getincrementalencoder(encoding)(errors,
**kwargs)`. Also re-derived the classification directly from the CURRENT
guard site (`gimple_cpp_core.py`'s coroutine-body CallExpr case): the one
narrow kwargs-spread exception that exists (`_cpp_try_kwargs_forward_call`)
requires a STATICALLY-KNOWN `IdentExpr` callee whose real parameter
names/defaults are compile-time visible — this shape's callee is the
dynamically-obtained class returned by `getincrementalencoder(encoding)`,
which that helper provably returns None for, falling through to the
honest refusal. Nothing landed since the last pass touches dynamic-callee
dispatch; genuinely unfixable without the large dynamic-kwargs-dispatch
feature already assessed repeatedly. No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825) and generator-value-return-slot fix (326db78); neither applies, unchanged)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` repro:
byte-identical refusal — `iterdecode, iterencode` on the `*`/`**`-unpack
call-argument guard at `getincrementalencoder(encoding)(errors,
**kwargs)`. Neither of today's two landed fixes is relevant: this
blocker is a dynamically-obtained-callee kwargs-spread shape, unrelated
to `super()`/`self.__class__` resolution or to a generator's own
value-carrying `return`. No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder16 — re-verified unchanged)

Fresh re-verify against this worktree (branched from master `a913ab8`,
post self-host-bootstrap-divergence fix). Ran a direct isolated
`gimple_codegen.compile_to_gimple_with_cpp(..., do_imports=False)` call
(equivalent to, but faster/safer than, a full `mojo.py build`) under the
RAM-safety watcher. Byte-for-byte identical refusal to the 2026-08-25
entry: `iterdecode, iterencode` refused for "a `*`/`**`-unpack call
argument is not supported in a compiled generator/coroutine body" at
`getincrementalencoder(encoding)(errors, **kwargs)`. No shared mechanism
landed since the last pass (self-host bootstrap divergence fix touches
flow-insensitive field inference + boxed-handle typing, unrelated to
dynamic-callee kwargs-spread). Genuinely unfixable without the same
large dynamic-kwargs-dispatch feature already assessed repeatedly. No
change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified unchanged)

Fresh re-verify against this worktree (branched from master at `f65502d`,
post-integration of the opencode-ctables/perf5/gdb merges). Ran
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/codecs.py` under
the safety-rule watcher (finished in well under a minute, no runaway).
Identical refusal, byte-for-byte the same shape as every prior pass:
`iterdecode, iterencode` refused with "a `*`/`**`-unpack call argument is
not supported in a compiled generator/coroutine body" — the
`getincrementalencoder(encoding)(errors, **kwargs)` dynamically-obtained-
callee kwargs-spread shape. None of the mechanisms that landed in the
interim (module-cache/link-mode fixes, opencode-ctables/perf5/gdb merges)
touch dynamic-callee kwargs-spread lowering. Still genuinely unfixable
without the same large dynamic-kwargs-dispatch feature already assessed
repeatedly across many prior passes. No change; doc stays open.

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
