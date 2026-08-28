# CODEGEN_generator_function: Lib/ftplib.py

## Status (updated 2026-08-26, fresh independent re-derivation — confirmed unchanged, not just re-trusting the prior entry)

Re-derived from scratch via a fresh `compile_to_gimple_with_cpp(do_imports=
False)` + `g++-mp-15 -std=c++20 -fsyntax-only` repro (not the prior session's
own script): `.ci` 0 errors; `.cpp` exactly the same 2 errors as every prior
entry — `FTP_retrlines(self, cmd, (int64_t)(lines.append))` (gap #2,
`lines.append` read as a bare callback VALUE, not called — `mojo_fnptr_call_1`
has no context-pointer slot for a bound receiver, and unifying it with the
`MojoBoundMethod`/`mojo_bound_method_call_N` ABI would need every plain-path
callee taking a callback — including `retrlines`'s own default arg,
`print_line`, a plain free function with no `self` — to accept the new
convention: an ABI-wide change, not a self-contained one) and `(void)
(0.partition(" "))` (gap #4, downstream of #2's unknown element type).
Independently confirms this remains genuinely ABI-broad, not narrow. No code
change made against this specific gap this pass (see this session's
`gimple_module_gen.py` commit for an unrelated classmethod-return-type fix
made while investigating `Lib_tarfile.md`, which does not touch ftplib.py's
gap). Doc stays open, gaps #2-4 unchanged.

## Status (updated 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch, byte-identical)

Re-derived fresh (own isolated `compile_to_gimple_with_cpp(do_imports=False)`
+ real `g++ -std=c++20 -fsyntax-only` run, not a re-read of this doc):
`.cpp` still exactly 2 errors, byte-identical to the entry above —
`request for member 'append' in 'lines', which is of pointer type
'MojoList*'` (gap #2) and `unable to find numeric literal operator
'operator""partition'` (gap #4, the `0.partition(" ")` symptom). Concur
with the existing classification: gap #2 needs a context-carrying
callback ABI change across all four plain-path callback params
(`retrbinary`/`retrlines`/`storbinary`/`storlines`), not a self-contained
fix; gap #4 is downstream of it. No code change made. Doc stays open.

## Status (updated 2026-08-26 — gap #2 re-checked against the new generator-value-return-slot machinery; confirmed still not tractable narrowly; gaps #2-4 otherwise unchanged)

Re-ran `scripts/repro_ftplib_isolated_group3.py` fresh: `.ci` still 0
errors, `.cpp` still exactly the same 2 errors as the prior entry
(`lines.append` member-access-on-pointer at the `FTP_retrlines(self, cmd,
(int64_t)(lines.append))` call, and the downstream
`(void)(0.partition(" "))` gap-#4 symptom).

Specifically investigated whether the VERY recent generator-value-carrying
return-slot work (asyncio/futures.py's per-unit extern-C return slot for
values crossing a coroutine's suspend/return boundary) is relevant here, as
directed. It is not: that machinery widens what a C++20 coroutine can
*return* through `co_return`/the promise type; gap #2 is not a return-value
problem at all; it is `FTP.retrlines` (compiled through gimple_codegen.py's
**plain, non-coroutine** path — `retrlines` itself is not a generator) whose
`callback` parameter is consumed via `mojo_fnptr_call_1(callback, line)` —
`runtime/mojo_runtime.h`'s `int64_t (*)(int64_t)` raw function-pointer
convention with NO slot for a receiver/context. Traced all four sibling
callback params (`retrbinary`/`retrlines`/`storbinary`/`storlines`) — all
four use the identical bare `mojo_fnptr_call_1` convention, confirmed via
`grep -n "mojo_fnptr_call\b" ftplib.ci` (4 call sites, one per method).

Also checked whether the EXISTING `MojoBoundMethod`/`mojo_bound_method_call_N`
machinery (`{ void *fn; void *self; }`, already used for user-struct bound
methods referenced as values, `runtime/mojo_runtime.h:75-94`) could be
reused here. It can't apply narrowly: `lines` is a built-in `MojoList *`,
not a user-defined struct, so `_lower_bound_method_value` (which resolves a
struct's real method C symbol) has no entry point for a container's
`.append`. And even if a `MojoList`-append-as-bound-method special case were
added, `FTP_retrlines`'s *default* callback argument is `print_line`, a
plain 1-arg free function with no `self` at all — unifying the whole
`callback` parameter onto the bound-method ABI would require calling free
functions through it too (`self=nullptr`, but `mojo_bound_method_call_1`
supplies `self` as the callee's first argument, which `print_line(line)`
does not expect) — exactly the ABI-wide, every-plain-path-callee-affecting
change the doc already correctly flagged, not a self-contained fix.

Classification unchanged: gap #2 remains genuinely ABI-broad, not narrow.
Not attempted, per campaign rules. Doc stays open, gaps #2-4 unchanged.

## Status (updated 2026-08-25, wtOpencode_group3 — gap #3 (`facts_found[:-1].split(";")` as a loop iterable) FIXED; gaps #2/#4 remain)

Re-verified fresh via this doc's isolated methodology
(`scripts/repro_ftplib_isolated_group3.py`, adapted to this worktree):
`.ci` clean, `.cpp` down from 3 errors to **2**:

- **FIXED (commit `43fac2c`, shared compiler source) — gap #3.** The
  coroutine-body emitter had no `.split` case at all (the str-method
  family stopped at replace/strip/partition/join), so
  `for fact in facts_found[:-1].split(";"):` fell to the generic
  `{obj}.{member}(...)` fallback and emitted invalid C++ member-call
  syntax on a raw `char *`. Three coordinated pieces, all reusing
  existing machinery: `_cpp_expr` gained the split family
  (`split`/`rsplit`/`splitlines`, routed through the SAME
  `mojo_str_split`/`mojo_str_rsplit`/`mojo_str_splitlines` runtime
  helpers the ordinary path already uses — NULL sep IS Python's
  whitespace split, negative maxsplit IS unlimited); `_cpp_for_stmt`'s
  list-iterable branch recognizes the call shape (cached local +
  indexed loop, element type char*); `_cpp_receiver_ctype` types a
  subscript/slice rooted at a known-char* (or untracked) local as
  char* so chained dispatch fires on the `[...]-then-.split` shape,
  with the matching `MojoList *` entry in
  `_infer_simple_expr_ctype`. A fourth piece was needed for the
  general shape: `_infer_param_types` now unwraps slice/subscript
  receivers when collecting STRING_ONLY_METHODS evidence
  (`<param>[:-1].split(sep)` proves the param is a string exactly as
  strongly as `<param>.split(sep)` did — previously the indirect shape
  inferred MojoList* from the bare subscript). Verified end-to-end:
  standalone generators iterating `s.split(";")` and
  `s[:-1].split(",")` build AND print correct elements/counts.
  Full gate: test_gimple 256/256, test_module_cache 76/76,
  check-selfhost clean, stdlib dylib rebuild 0 skips.

- **Gap #2 (`FTP_retrlines(self, cmd, lines.append)` — a bound
  container method passed as a callback VALUE), re-assessed and still
  not tractable narrowly.** The callee side is compiled through the
  PLAIN path: its `callback` param is a raw int64_t consumed via
  `mojo_fnptr_call_1(callback, line)` (a real C function-pointer call,
  see runtime/mojo_runtime.h). The coroutine emitter's existing
  callable-value form is a capturing C++ lambda convertible to
  `std::function` — which has NO conversion to a raw function pointer,
  so it cannot feed `mojo_fnptr_call_1`. Materializing a real
  trampoline would need the receiver communicated out-of-band (a
  global/static cell set before the call — unsound under same-site
  reentrancy) or extending the callback ABI to carry a context
  pointer through every plain-path callee (`retrbinary`/`storbinary`/
  `storlines` share the convention) — both feature-sized/ABI-broad;
  not attempted per campaign rules.

- **Gap #4 (`(void)(0.partition(" "))`) unchanged** — upstream symptom
  of `lines`' unknown element type (populated only at runtime via the
  gap-#2 callback, so no static append evidence exists); same
  classification as before.

`ftplib.py` as a whole still does not build. Doc stays open.


## Status (updated 2026-08-25 — gap #1 (`FTP_sendcmd` extern typed its `cmd` param `int64_t`) FIXED; gaps #2-4 unchanged)

**Root cause**: `FTP.sendcmd(self, cmd)`'s body only FORWARDS `cmd` into
`self.putcmd(cmd)` — no str-method call, no concat, no subscript on the
param itself — so the usage-based `_infer_param_types` pass had zero signal
and the parameter fell to the int64_t default in
`func_param_types['FTP_sendcmd']`, which is what both the .c forward decl
and the coroutine .cpp emitter's `_cpp_struct_method_refs` extern loop read.
The module already HAD the right architecture for this — the cross-call
scalar contract (Pass 1.3d for free functions, Pass 1.3d-ctor for
constructor calls) — but neither covered plain `receiver.method(...)`
call sites.

**Fixed** (commit `20d2cb6`, shared compiler source): new Pass 1.3e in
`gen_module` (`gimple_module_gen.py`) extends the same
unanimity-over-call-sites refinement to struct methods: bare-`self` or
known-struct-pointer receivers only; unanimous `{'double'}`/`{'char *'}`
observation sets only; explicit annotations and defaulted params respected;
bounded fixpoint (≤4 rounds) so pure forwarding chains resolve one hop per
round (ftplib resolves sendcmd.cmd and voidcmd.cmd from their string-literal
call sites, then putcmd.line from those two's now-resolved params). Two
evidence extensions are deliberately scoped to THIS pass alone after each
was shown to regress free-function compiles when shared: `deep_str`
(a `'+'`/`'%'` expression with a provable string operand is sound char*
evidence — without it a method whose ONLY call site is mlsd's concat gets
no vote) and `prefer_refined_param` (a refined caller-param type outranks a
stale `_inferred_var_types` int64_t entry, un-freezing deeper forwarding
hops). Three consumers of the previously method-invisible qualified registry
were aligned so definition, .c forward decls, .cpp externs, and pre-
definition call-site argument conversions all agree: the func_param_types
registration loop and `_signature_ctypes` now consult the qualified
"Struct_method" key before `_param_ctype`'s bare-name lookup, and Pass
2b-bis's `_mangled_signature_ctypes` entries are refreshed post-pass (for a
`*args` method `_emit_call` prefers that sentinel form — without the
refresh, self-host myinterpreter.py's `Interpreter__call_dunder` failed
"makes pointer from integer"; caught by `make check-selfhost` mid-session,
fixed, re-gated).

**Verification**: isolated compile per this doc's methodology
(`GimpleGen(do_imports=False, relaxed_imports=True)` +
`g++-mp-15 -std=c++20 -fsyntax-only`, see
`scripts/repro_ftplib_isolated.py`): gap #1's
`invalid conversion from 'char*' to 'int64_t'` at the
`self.sendcmd("OPTS MLST " + ...)` line is GONE (.ci 0 errors; .cpp 4 -> 3
errors — exactly gaps #2/#3/#4 below, untouched). Real safety-wrapped
`mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py`: ftplib's OWN
code compiles clean (zero FTP_/mlsd/sendcmd errors anywhere in the log);
the 217 total errors are byte-identical to the pre-change run and all live
in transitively-imported modules (argparse/typing/os/pickle/codecs/
weakref/tracemalloc/tokenize/gettext/functools) — the documented
whole-program blockers, not this file. Runtime behavior confirmed correct,
not just compiling: a standalone generator→`sendcmd(concat)`→`putcmd`→
`putline` chain repro built via `mojo.py build` prints the intact command
strings (`OPTS MLST type;size;perm;\r\n`, `TYPE I\r\n`), where the
pre-fix tree fails to compile that shape at all.

Full mandatory gate for this fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild EXIT=0 with 0 skip lines (baseline 0, unchanged).

Gaps #2 (`lines.append` passed as a value), #3 (`.split()` chained-call
result as loop iterable), and #4 (`fact.partition(...)` on an
unannotated-param-derived string, the high-risk
`unannotated_init_param_field_type_defaults_int64` family) are UNCHANGED —
confirmed still present in the same isolated compile. Note gap #4 remains
distinct from this fix's mechanism: Pass 1.3e refines METHOD PARAMETERS
from unanimous call-site evidence; it does not touch
`_collect_self_assigns`/struct-field typing, and mlsd's own `path`/`facts`
params got no unanimous evidence anyway (their C types are still int64_t,
as before).

`ftplib.py` as a whole still does not build. Doc stays open.


## Status (updated 2026-08-24, worktree fix/rest-remainder — gap #1 (`";".join(facts)`) FIXED; a NEW, previously-masked error surfaced on the same line; gaps #2-4 unchanged)

Implemented real `str.join(...)` support in the coroutine-body expression
emitter this session (`gimple_cpp_core.py`'s `_cpp_expr` CallExpr/MemberExpr
case, plus a matching `_infer_simple_expr_ctype` entry in
`gimple_exprtypes.py` so a freshly-assigned local like `cmd = "OPTS MLST " +
";".join(facts) + ";"` gets the real `char *` declared type instead of the
int64_t default): a bare string-literal OR declared-`char *` receiver's
`.join(iterable)` now routes through the same `mojo_str_join(sep, parts)`
runtime helper the ordinary GIMPLE path already uses. Verified via a
standalone repro (`";".join(["a","b","c"])` inside a generator, yielded and
printed) — `mojo.py build` + running the binary prints `a;b;c` correctly.

Re-verified this file specifically via an isolated
`compile_to_gimple_with_cpp(do_imports=False)` + `g++-mp-15 -std=c++20
-fsyntax-only`: the previously-documented `.join()`-on-literal error at
this exact line is GONE. However, the SAME line (`self.sendcmd("OPTS MLST "
+ ";".join(facts) + ";")`) now surfaces a DIFFERENT, previously-masked
error: `FTP_sendcmd`'s own extern declaration types its `cmd` parameter
`int64_t` (not `char *`), so passing the now-correctly-`char *`-typed join
result is a hard `invalid conversion from 'char*' to 'int64_t'`. This is a
distinct, pre-existing gap (an inherited/cross-reference struct-method
extern-declaration parameter-typing issue, not a `.join()` problem) that
gap #1's own fix simply unmasked by getting past it — not investigated or
attempted this session; flagged for whoever picks up FTP's own
`sendcmd`/`retrlines` external-signature accuracy.

Full mandatory gate for this fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild EXIT=0 with 0 skip lines (baseline 0, unchanged).

Gaps #2 (`lines.append` passed as a value), #3 (`.split()` chained-call
result used as a loop iterable), and #4 (`fact.partition(...)` on an
unannotated-param-derived string, the `unannotated_init_param_field_type_
defaults_int64` hard-bug family) are UNCHANGED — none touch `.join()`,
confirmed still present in the same isolated compile.

`ftplib.py` as a whole still does not build. Doc stays open.


## Status (updated 2026-08-24 — `%`-format crash in `mlsd` FIXED; 4 unrelated errors remain, own-.cpp count 5 -> 4)

Re-verified via isolated compile (`GimpleGen(do_imports=False,
relaxed_imports=True)` + `gcc-mp-15`/`g++-mp-15 -fsyntax-only`): `.ci`
side clean. `.cpp` side, `FTP.mlsd`, previously 5 distinct errors, now 4:

**Fixed**: `cmd = "MLSD %s" % path` — the shared coroutine-body `%`-
format crash (see `bugs/CODEGEN_generator_function_Lib_ipaddress.md`'s
matching entry for the fix, `gimple_cpp_core.py`'s new
`_cpp_percent_format`). Confirmed gone from the isolated `.cpp`.

**Still open, 4 distinct, unrelated, all narrow feature gaps in the
coroutine-body expression emitter, none attempted here**:
1. `";".join(facts)` — `.join()` called on a STRING LITERAL (not a
   `MojoList *`/`MojoSet *` local) — `_cpp_expr` has no case for a
   string-literal receiver here (only a container-typed local's
   `.join`-equivalent call shapes are handled elsewhere).
2. `self.retrlines(cmd, lines.append)` — `lines.append` passed as a
   VALUE (a bound-method callback argument), not called — the same
   "compiled callable surface has no first-class value form in this
   scalar body model" class of gap `glob.py`'s doc documents for a
   generator method referenced as a plain value.
3. `facts_found[:-1].split(";")` iterated via `for fact in ...:` —
   `.split()`'s result (from a `mojo_cstr_slice(...)` char* expression)
   used directly as a `for`-loop iterable; no case recognizes a chained
   `.split()` call as a loop iterable here (only a bare declared
   `MojoList *` local is).
4. `fact.partition("=")` unpacked into `key, _, value` — same
   underlying issue as (1)/(3): `facts_found`/`fact`, sourced from an
   unannotated `path`/`facts` `FTP.mlsd(self, path="", facts=[])`
   parameter pair, get mis-typed further downstream (visible upstream
   as `(void)(0.partition(" "))` — `line.rstrip(CRLF).partition(' ')`'s
   LHS resolving to the integer literal `0` instead of a real `char *`)
   — very likely another instance of the already-tracked
   `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
   family (that hard bug's own doc explicitly flags itself as high-risk,
   shared, regression-prone machinery — NOT re-attempted here per this
   session's scope).

Full mandatory gate for the `%`-format fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skip lines. Commit `d3154a6`.

`ftplib.py` as a whole still does not build. Doc stays open.


## Status (updated 2026-08-23 — mlsd's body partially improved by shared coroutine-emitter work; remaining blockers enumerated precisely)

Re-triaged the isolated compile (ci_errors=0; cpp_errors=6 → 4 unique,
all inside `_mojogen_FTP_mlsd_impl`). Session progress that helps this
file: `lines = []` (mlsd's accumulator) now lowers to a REAL `MojoList *`
with typed appends instead of an int64_t local holding brace-init garbage
(one error gone), and defaulted-argument calls pad correctly. The four
REMAINING errors are independent, each its own narrow-but-real coroutine-
body expression-emitter gap (none generator-machinery-specific):
1. `";".join(facts)` — a str-LITERAL method call (`.join` on a
   `const char[2]`); the emitter has `.replace()` on char*-typed receivers
   but no join/split/rstrip family on literals.
2. `"MLSD %s" % path` — `%`-format-string on a literal + non-constant RHS
   (the long-standing dynamic-%-format gap, here reached via the .cpp path).
3. `FTP_retrlines(self, cmd, lines.append)` — a bound-method VALUE used as
   a callback argument (`lines.append` read without an immediate call); the
   emitter's bound-method-as-value support covers `self.<method>` and
   struct-pointer locals via `_CPP_CALLABLE_CTYPE`, not container members.
4. `line.rstrip(...)`/`fact.split(";")`/`key.lower()` — str-method calls on
   values whose element type this scalar model can't statically know
   (`line` comes from a list populated only at runtime by the callback in 3).
Each is feature-sized; fixing any one alone leaves mlsd blocked by the
others, so none was attempted piecemeal this pass. Doc kept open.


## Status (updated 2026-08-18 — the `Popen__close_pipe_fds`/`calendar.Month`/`Day` blocker below is FIXED, file still doesn't build for other unrelated reasons)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py`
after `bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_
on_ordinary_code.md` landed its fix (the over-eager "assume all
methods" `getattr(self, x)` dispatch-table fallback is now gated to
only fire when compiling this compiler's own self-hosting source, not
ordinary stdlib files like `subprocess.py`/`calendar.py`). Confirmed:
zero occurrences of `Popen__close_pipe_fds` or `calendar.Month`/`Day`
"undeclared here" errors anywhere in the build log now (grepped for
`-i undeclared` across the full output) — the exact blocker described
below is resolved.

**Still does not build end-to-end**, for other, unrelated,
already-documented-elsewhere reasons: undeclared-identifier errors in
`posixpath.py` (`_varsubb`/`_varsub`), `codecs.py` (`_t3`/`_t5`/`_t6`/
etc.), `inspect.py` (`_mojo_cb_formatannotation_repl`, several `_tNN`
temporaries), `reprlib.py` (`functools__make_key_0c85c9`), and
`functools.py` (`hits`/`misses`). None of these are the dispatch-table
mechanism this doc was blocked on; not investigated further here since
that's out of scope for this specific fix.

## Status (updated 2026-08-10, re-verified — this doc's OWN generator bug is FIXED, file still doesn't build for an unrelated reason)

Re-ran `MOJO_DEBUG=1 python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/ftplib.py` against current master
(fast-forwarded to `9d93746`, which includes this session's earlier
real tuple-valued-`yield` support, commit `a7b71a0`/merge `09008e8`).

**`FTP.mlsd`'s tuple-yield refusal is GONE.** Grepped the full
`MOJO_DEBUG=1` log for every "not eligible for C++ coroutine path" line
naming `mlsd` — zero hits. The tuple-boxing fix (`yield (name, entry)`
now boxes into a real `MojoList *`, same mechanism this session used
to fix `dis.py`/`calendar.py`/etc.) resolves exactly the gap this doc's
2026-08-09 entry (below) diagnosed. This doc's own subject is fixed.

**The file still fails to build overall, but for a completely
different, non-generator reason in a transitively-imported module.**
`ftplib.py` pulls in `ssl.py` (for `FTP_TLS`), which pulls in
`subprocess.py`; the combined-module compile fails with dozens of
`error: 'Popen__close_pipe_fds' undeclared here (not in a function);
did you mean 'subprocess_Popen__close_pipe_fds'?` (and the same shape
for several `calendar.Month`/`calendar.Day` dunder methods) — a real
struct method exists under its MODULE-QUALIFIED C symbol
(`subprocess_Popen__close_pipe_fds`), but a generated dispatch-table
struct-literal initializer references it by its UNQUALIFIED name
(`Popen__close_pipe_fds`), which was never declared.

Root-caused this precisely: it's the SAME already-tracked mechanism as
`bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_
ordinary_code.md` (the `DispatchTable`/`_plan_dispatch_tables`
"assume all methods" fallback for an unrecognized `getattr(self, x)`
pattern), just a different symptom of it than that doc's own repro. The
fallback registers callees via `self.struct_methods[stmt.name]
[method.name]` (`gimple_codegen.py:758`), which is populated as the
UNQUALIFIED `f"{stmt.name}_{method.name}"`
(`gimple_codegen.py:756`) — this call-graph/dispatch-table analysis
pass was built before/independently of the module-qualified-C-symbol
scheme (see the "SB-1 mojo_abs symbol-collision fix" work) and was
never updated to match, so any struct this heuristic mis-fires on (any
class with an unrecognized `getattr(self, x)`-shaped method, per that
doc's root-cause writeup) gets a dispatch table full of dangling
unqualified symbol references whenever that struct's real methods
live in a NON-root, imported module (root-module structs' unqualified
and qualified names coincide, masking the bug there).

Not fixed here: out of scope for this doc (it's not a generator bug,
and not even in `ftplib.py` itself), and the existing hard-bug doc
already classifies this whole mechanism as "Moderate risk... any
change here must be verified against `make check-selfhost` FIRST and
foremost" — deserves its own dedicated pass, not a piggyback fix. Left
a matching note on that doc with this new symptom for whoever picks it
up next (module-qualification gap, not the malformed-self-type gap
that doc's `option 3` already fixed).

**This doc could be deleted (its own subject, `mlsd`'s tuple-yield
gap, is fixed) except that `python3 mojo.py build
Lib/ftplib.py` still does not succeed** — keeping it open, re-pointed
at the real current blocker, rather than deleting a doc for a file
that still doesn't build (which would look like false progress to a
future pass grepping `bugs/` for "does ftplib.py build yet").

## Status (updated 2026-08-09, re-verified — reproduces identically)

**STILL FAILING**, re-confirmed against current master (fast-forwarded
to `dd7c7c6`). Identical repro to the 2026-08-07 entry below:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
[gimple_codegen] generator method FTP.'mlsd' not eligible for C++ coroutine path, falling back to honest refusal: mlsd: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) mlsd (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: tuple-valued `yield`** — the well-known,
already-catalogued C++20-coroutine-promise scope boundary (the promise
only carries a single scalar `int64_t`/`double`/`_Bool`; there is no
representation for a tuple/struct value crossing a suspend point), same
family as `bugs/CODEGEN_generator_function_Lib_dis.md`'s
`_unpack_opargs`/`findlinestarts`/`_find_imports` case. `FTP.mlsd`'s
body does `yield (name, entry)` — a 2-tuple `(str, dict)` — and
`_gen_cpp_generator_unit`'s value-type check only accepts a single
scalar type across every `yield` in the function, so a tuple-yielding
generator is refused outright. Because this is ftplib.py's only
generator and it's module-level-reachable (an `FTP` instance method),
the refusal escalates to a fatal whole-module `RuntimeError` for the
CLI's `mojo.py build` path (the error text's claimed graceful fallback
isn't actually taken for the root file being built).

(Note: the sibling struct-typed-*parameter* refusal this doc's older
entries below cross-reference — `bugs/hard/CODEGEN_generator_struct_
typed_param_refused.md`, task #147 — is now fixed, commit `5d22b29`,
and that doc has since been removed per project convention. That fix
is unrelated to `mlsd`'s failure here, which is about the yielded
VALUE's type, not a parameter's.)

The previously-reported `test.__doc__` "invalid use of void expression"
error (line 926) was real at the time but is no longer what blocks this
file — `mlsd`'s refusal happens first, before that code is ever
reached. Not re-verified whether the `__doc__` issue is separately
fixed or still latent; moot until `mlsd`'s tuple-yield limitation is
addressed.

Not fixed here — this is the same genuine, already-assessed
feature-sized coroutine-codegen scope boundary as task #147
(`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`), which
this session's assignment explicitly holds back from further attempts.
Widening the C++20 coroutine promise type to carry a tuple/struct value
across suspend points (rather than a single scalar) is a real feature,
not a narrow bug fix.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
