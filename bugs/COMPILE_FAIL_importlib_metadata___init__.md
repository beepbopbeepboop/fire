# COMPILE_FAIL: Lib/importlib/metadata/__init__.py

## Status (re-verified 2026-08-26 — checked against this session's new loop-as-expression codegen; UNAFFECTED)

This session implemented real loop-as-expression codegen for `list(x)`/
`set(x)`/comprehension-as-value inside a compiled generator/coroutine
body (see `bugs/CODEGEN_generator_function_Lib_codecs.md`'s entry of the
same date for the implementation writeup). This file's own two refusals
are `_convert_egg_info_reqs_to_simple_reqs` (nested-`def`-as-callee,
`url_req_space(...)`) and `Sectioned.read` (`map(...)`, categorically
unsupported — out of this session's scope per the task's own framing:
"if map()/filter() with a genuinely dynamic/runtime callable value turns
out to need a different, harder mechanism ... it's fine to leave those
refused") — neither is a `list()`/`set()`/comprehension shape.

A/B'd via `git stash`: strict-mode `compile_to_gimple_with_cpp(do_imports
=False)` refusal is byte-identical (`_convert_egg_info_reqs_to_simple_
reqs`/`read`, same reasons), and the relaxed-mode `.cpp` for the
surviving generators is ALSO byte-identical (0 g++ syntax errors both
before and after — this file's other generators were already clean).
Confirmed unaffected; doc stays open.

## Status (updated 2026-08-26 — re-verified fresh against current branch head; unchanged, still three feature-sized gaps)

Re-ran the isolated `compile_to_gimple_with_cpp` probe fresh. Refusal
byte-for-byte identical to the 2026-08-25 entry: `_convert_egg_info_
reqs_to_simple_reqs` refuses on unresolved callee `url_req_space(...)`
(nested def called from its loop), `Sectioned.read` on unresolved
callee `map(...)`. None of the very recent shared machinery
(generator return slots, cls-receiver work, etc.) touches these
shapes. Re-assessed each of the three documented gaps against today's
tree before concluding:

1. **Nested-def/closures in coroutine bodies** (`make_condition`/
   `quoted_marker`/`url_req_space`) — still no lifting mechanism. Note
   the individual scalar ingredients the nested bodies need have been
   landing one by one (f-string interpolation, str.partition, str.join,
   string-repeat `*`), so the remaining work really is just the
   lift-to-capturing-lambda/static-local-function step — but that step
   itself is the subsystem addition (parameter passing, recursion into
   `_gen_cpp_generator_unit`-style shape checks per nested body), still
   not a narrow fix. Also worth recording: `quoted_marker`'s own body
   contains `list(filter(None, [markers, make_condition(extra)]))` — a
   filter-with-None-predicate AND a call to a sibling nested def — so
   gaps 1 and 2 are coupled inside one function; closing either alone
   leaves `_convert_egg_info_reqs_to_simple_reqs` refused.
2. **map/filter/callable-valued builtins** — `Sectioned.read`'s
   `filter(filter_, map(str.strip, text.splitlines()))` needs BOTH a
   lazy-iterable representation AND calling an arbitrary runtime value
   (`filter_` is a plain parameter that may be None or any callable).
   No boxed-callable convention exists in the scalar coroutine model;
   a fused/special-case lowering cannot be honest here precisely
   because `filter_` is not statically known. Unchanged.
3. **Foreign-module struct construction** (`Pair(name, value)`) —
   re-verified what ACTUALLY happens today with the closest analogous
   shape: an isolated probe of `yield pathlib.Path(path_str)` in a
   generator body now COMPILES — but only because the module-stub
   convention lowers the whole constructor call to literal `0`
   (verified in the emitted C++: `co_yield 0;`). That is the documented
   silent-degrade path, not support: wiring `Pair` through it would
   compile while yielding garbage, exactly what this campaign's
   end-to-end standard forbids counting as resolution. Real support
   still needs imported structs registered into `struct_field_types`/
   `_struct_has_init` plus the foreign typedef re-emitted into the .cpp
   preamble. Unchanged.

All three remain genuine subsystem additions to the coroutine-body
emitter; not attempted, per the no-half-landing rule. Doc kept open.

## Status (updated 2026-08-25 -- re-verified against fix/rest-remainder12, unchanged)

Re-ran an isolated `compile_to_gimple_with_cpp` check fresh, after
this session's 4 coroutine-emitter fixes landed for
COMPILE_FAIL_Apple___main__.md (`mojo_c_getenv`/platform/subprocess
runtime-call whitelist, zero-arg `print()`, string-repeat `*`,
f-string interpolation in `_cpp_expr`'s `StringLiteral` case — none of
which are the shapes this file's remaining blocker needs). Confirmed
byte-for-byte identical refusal: `_convert_egg_info_reqs_to_simple_
reqs, read (generator function(s)...)`, `Unsupported shape(s):
_convert_egg_info_reqs_to_simple_reqs: a call to unresolved callee
'url_req_space(...)'...`. The three remaining feature-sized gaps
(nested-def/closure compilation inside coroutine bodies; `map`/
`filter`/callable-valued builtins; foreign-module struct construction
for `Pair(...)`) are unchanged and still not attempted — each is a
real subsystem addition to the scalar coroutine-body emitter, not a
narrow fix. Doc kept open.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. The three remaining feature-sized gaps (nested-def/closure compilation inside coroutine bodies; map/filter and other first-class-callable builtins; foreign-module struct construction) are unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies -- this file's own blockers are a different shape). Still feature-sized; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py`

## Status (updated 2026-08-23 — compiler-side emission bug FIXED (fd909e9); module itself STILL does not compile, blocker now precisely characterized)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
importlib/metadata/__init__.py` fresh against master `626f3f0`. The
2026-08-09 "invalid conversion in return statement" cluster below is
GONE — both former problem functions (`Sectioned.read`,
`Distribution._convert_egg_info_reqs_to_simple_reqs`) are generators
and now take the C++20-coroutine path implemented by the
compiled-generator project, which sidesteps the ordinary-path return
type inference entirely.

The build then failed with SIX g++ errors in the two generated
coroutine impl bodies (`__init___gen.cpp:110/120/183/184`), all one
class:

```
error: 'map' was not declared in this scope          (Sectioned.read: filter(map(str.strip, ...)))
error: 'filter' was not declared in this scope       (Sectioned.read)
error: 'str' was not declared in this scope          (str.strip as a first-class callable argument)
error: 'Pair' was not declared in this scope         (yield Pair(name, value) — Pair lives in importlib.metadata._collections)
error: 'url_req_space' was not declared in this scope  (nested def called inside the generator body)
error: 'quoted_marker' was not declared in this scope  (same)
```

Root cause: `_cpp_expr`'s final CallExpr fallback
(gimple_cpp_core.py, the IdentExpr-callee tail of the CallExpr case)
emitted ANY callee it couldn't resolve as a bare, undeclared C++
identifier call. The three real shapes landing there:

1. **Nested `def`s local to the generator body** (`quoted_marker`,
   `url_req_space`, defined inside
   `_convert_egg_info_reqs_to_simple_reqs` and called from its loop) —
   this scalar coroutine-body model has no closure/nested-def
   compilation at all.
2. **Python builtins with no coroutine-body lowering** (`map`,
   `filter`, plus `str.strip` used as a first-class callable VALUE
   passed to `map`) — every other builtin (len/str/repr/range/sorted/
   enumerate/iter/next/isinstance/hasattr/callable/object/getattr)
   has an explicit lower-or-refuse case; these did not.
3. **A foreign-module struct constructor** (`Pair(name, value)` —
   `Pair` is imported from `importlib.metadata._collections`, so it
   isn't in THIS module's `struct_field_types` and the existing
   same-module ctor branch can't fire).

**Fixed this session (commit fd909e9)** — measured-regression-safe:
instrumentation first confirmed the bare-name fallback fires ZERO
times across test_gimple.py, test_module_cache.py, check-selfhost,
and a full stdlib dylib rebuild, i.e. every current reach was broken
emission. The fallback now (a) keeps emitting bare-name calls ONLY
for the one shape where that's valid C++ — a declared callable-value
local of `_CPP_CALLABLE_CTYPE`/`_CPP_CALLABLE_CTYPE_1ARG`
(`getpos = lambda: ...; getpos()`, std::function `operator()`), now
covered by its own regression test
(`test_generator_callable_local_call_compiles_via_cpp_path`), and
(b) raises `_UnsupportedGeneratorShape("a call to unresolved callee
'X(...)' is not supported...")` for everything else
(`test_generator_unresolved_callee_honest_refusal`). Additionally,
every generator/async catch site in gen_module now records its refusal
reason into `GimpleGen._cpp_refusal_reasons`, and the strict-mode
whole-module RuntimeError appends them — so the failure now reads
`Unsupported shape(s): _convert_egg_info_reqs_to_simple_reqs: a call
to unresolved callee 'url_req_space(...)' ...; read: ... 'map(...)'
...` instead of six opaque g++ errors. Full gate verified clean:
test_gimple.py 252/252, test_module_cache.py 76/76, check-selfhost
clean, from-scratch dylib rebuild exit 0 with 0 `skip <module>:`
lines.

**The module still does NOT compile**, and closing the remaining gap
is feature-sized work on the coroutine-body emitter, deliberately not
attempted here (per the no-half-landing rule):

1. Nested-def/closure compilation inside coroutine bodies (the
   `quoted_marker`/`url_req_space`/`make_condition` trio needs f-string
   formatting, `str.partition`, `' and '.join(...)`, `'@' in req`,
   string multiplication — none of which the scalar body model has).
   Design shape: lift each nested def to either a capturing C++ lambda
   (the model already emits those for LambdaExpr values) or a static
   local function, after its own body clears the scalar-shape checks.
2. `map`/`filter` (and callable-valued builtins like `str.strip`)
   producing iterable/callable first-class values — needs a lazy-
   iterable representation plus a calling convention for arbitrary
   boxed callables in the scalar model (the existing fnptr/lambda
   machinery covers only statically-known callees).
3. Foreign-module struct construction (`Pair(...)`) — needs imported
   structs registered into `struct_field_types`/`_struct_has_init` for
   the importing module so the existing inline-calloc+`_init` ctor
   branch can fire, plus the foreign typedef re-emitted into the .cpp
   preamble (the `_struct_typedef_texts` plumbing already exists).

## Status (updated 2026-08-10 — historical)

This session implemented real tuple-valued-`yield` support in the
compiled-generator coroutine codegen (`gimple_codegen.py`'s
`_cpp_yield_tuple`/`_generator_tuple_yield_slot_ctypes`). Checked this
file against it: **this file has no tuple-valued `yield` anywhere** —
its only two `yield` sites (`yield Pair(name, value)` and `yield
section.value + space + quoted_marker(section.name)`) are both plain
scalar values. Issue #1's `name, sep, rest = filename.partition('-')`
is a tuple-UNPACK assignment (a completely different mechanism,
`_infer_local_var_types`/`_assign_target`, in the ORDINARY
non-generator GIMPLE path), not a generator `yield`. This doc was
evidently included in this session's initial file list by a keyword
match on "tuple" in its own text, not because tuple-valued `yield` is
its blocker. No change to this doc's classification or content below;
unaffected by this session's fix.

## Status (updated 2026-08-09)

Re-verified fresh against current master. A NEW issue (not present in
the 2026-08-07 write-up, so presumably introduced or exposed by
unrelated codegen work in between) was found and fixed this session:
`distributions(**kwargs)` called with no arguments (`distributions()`,
lines 1009/1044) failed to LINK with "too many arguments to function
'distributions_08efcc'; expected 1, have 2" — see "4. FIXED" below.

Still blocked on the same, unchanged, already-documented structural
type-inference gap from the prior session (issue #1/#3, "invalid
conversion in return statement" — bare `return` vs. a real value in
the same function): now 2 remaining sites (`_read_files_egginfo_
installed`'s `text and text.splitlines()`/`map(...)`, and
`PathDistribution._name_from_stem`'s tuple-unpack-from-call case; the
2026-08-07 write-up's "3 remaining sites" count included a third that
no longer reproduces). Not attempted here either — same architectural
area flagged as high-regression-risk in issue #1's own writeup below
(unchanged from the prior session).

## Status (updated 2026-08-06)

Three issues found. One (str.partition()) has a real runtime fix landed;
the other two are documented but not fixed.

### 1. FIXED (commit 1584798): `str.partition()`/`str.rpartition()` were unimplemented

```
error: invalid conversion in return statement
```
at (`PathDistribution._name_from_stem`):
```python
name, sep, rest = filename.partition('-')
return name
```

`str.partition()`/`str.rpartition()` had NO codegen lowering at all —
any call fell to the generic "unknown char* method" stub, unconditionally
returning `int64_t 0`. Implemented both as real runtime helpers
(`mojo_str_partition`/`mojo_str_rpartition`, mirroring the existing
`mojo_str_split`/`mojo_str_rsplit` shape: build a 3-element `MojoList *`
of strings) and wired the method names into the char* method-call
dispatch. Full quality gate verified clean.

**Not fully resolved by this fix** — a SEPARATE, deeper gap remains for
this exact call shape (`a, b, c = <call>()`, not a literal tuple RHS):
`_infer_local_var_types` (gimple_codegen.py:6933), a pre-pass that scans
a function body BEFORE the real per-statement compilation to seed
`_inferred_var_types`, has a documented, DELIBERATE limitation:

```python
if (isinstance(node.value, TupleExpr) and len(node.value.elements) == len(targets)):
    elem_types = [self._quick_type(e) for e in node.value.elements]
else:
    # Unpacking a single iterable: per-element type is unknown
    # here; use the int64_t storage default, not the container.
    elem_types = ['int64_t'] * len(targets)
```

Whenever the RHS isn't a literal tuple (e.g. any function/method call
returning a tuple, including `partition()` now that it's implemented),
EVERY unpack target gets pre-seeded `int64_t`, unconditionally. This
hint later WINS over the correctly-computed type at the real
compilation site (`_assign_target`'s `hint or et`, gimple_codegen.py:
16418-16421 — `hint` takes priority whenever present). So even with
`partition()` now correctly implemented and correctly TYPE-INFERRED at
its own call site (`_tuple_elem_value` resolves `char *` correctly via
`_elem_types`), the unpack target `name` still ends up C-declared
`int64_t` — `_track_pointer_actual_type` DOES still correctly record
the real type in `_actual_types['name'] = 'char *'` (so some consumers,
e.g. a binary op, recover correctly via that side-table), but a bare
`return name` doesn't consult `_actual_types` (`_lower_IdentExpr`'s
generic fallback and `_infer_return_type`'s own shallow scan both only
look at `var_types`, i.e. the DECLARED type) — hence the function's own
inferred return type stays `int64_t`, producing "invalid conversion in
return statement" at its `-> str`-shaped real usage (or, absent an
annotation, a return-type mismatch at the CALLER).

Not fixed: `hint or et`'s priority exists for OTHER good reasons this
session hasn't fully mapped (forward-reference cases where the live
`et` isn't yet reliable) — flipping it blindly risks the same class of
broad regression already hit twice this session in adjacent shared
type-inference code. A real fix likely needs `_infer_local_var_types`
to attempt real container-element-type inference for the CALL-RETURN
case too (mirroring what `_tuple_elem_value` already knows how to do at
the real compilation site, e.g. via `self._elem_types`/`_return_elem_
types` if that pre-pass can see them yet) rather than just widening
`_assign_target`'s priority.

### 2. FIXED (2026-08-07): `self.metadata['Name']` — subscript on an un-invoked bound-method/property value

```
error: cannot convert to a pointer type
```
at:
```python
@property
def name(self) -> str:
    """Return the 'Name' metadata for the distribution package."""
    return self.metadata['Name']
```
where `metadata` (line 448-449) is a `@property` defined on the BASE
class `Distribution`, inherited (not overridden) by `PathDistribution`.

**Root cause (confirmed via the generated `.ci`)**: `self.metadata`
(accessed WITHOUT call syntax) lowers via `_lower_MemberExpr` /
`_lower_bound_method_value` (gimple_codegen.py) to a deferred, un-called
`MojoBoundMethod *` value — correct when the consuming context is itself
a call (`self.metadata()`), and this codegen has no `@property`-specific
handling anywhere (confirmed: zero hits for `'property'` in
`gimple_codegen.py`/`mojo_compiler.py` — bare 0-arg attribute access is
generically deferred to a `MojoBoundMethod`, with auto-invocation only
happening at whatever consumes it). `_lower_subscript` (gimple_codegen.py,
`_lower_subscript`) had no case at all for a `MojoBoundMethod *` base:
the generated `.ci` showed `self.metadata` boxed into a
`MojoBoundMethod *` via `mojo_bound_method_new`, and the subscript then
fell through to the generic "opaque/unknown pointer type" fallback,
which:
1. treated the un-called `MojoBoundMethod *` itself as an array base
   pointer via the generic `_mojo_at_<Type>` GIMPLE pointer-arithmetic
   helper (`_mojo_at_MojoBoundMethod`, a struct with no such element
   shape) — the actual "cannot convert to a pointer type" GCC error, and
2. even set up to reinterpret the subscript's STRING key (`'Name'`) as a
   raw INTEGER byte offset (`_t6 = (int64_t) _t5;` where `_t5` was the
   string literal's pointer) — a silent miscompile, not just a compile
   error, had the arity happened to align instead.

**Fix**: `_lower_subscript` (gimple_codegen.py) now checks for
`ot == 'MojoBoundMethod *'` immediately after lowering the subscript's
object expression, and if so, calls the bound method with 0 args first
(via `mojo_bound_method_call_0`, using `_bound_method_ret_types` — keyed
by the bound-method value's own C temp name, already populated by
`_lower_bound_method_value` — to recover its real return type), THEN
proceeds with the existing subscript dispatch logic on the ACTUAL
returned value/type. This generically fixes `self.prop[key]` for any
0-arg property/method (inherited or not) followed by a subscript,
without touching `_signature_ctypes`/call-argument-packing machinery at
all (a deliberately different, narrower code path from the held-back
`bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
task #142 — NOT the same fix, NOT touching the same function).

Verification: both `Distribution.name`/`Distribution.version`'s
`self.metadata['Name']`/`self.metadata['Version']` sites now compile
(the "cannot convert to a pointer type" errors are gone; this file's
build now fails only on the separate, pre-existing issue #1/#3 "invalid
conversion in return statement" cluster below). Full quality gate run
clean: `test_gimple.py` (247/247), `test_module_cache.py` (76/76),
`make check-selfhost`, from-scratch stdlib dylib rebuild (0 `skip`
lines), `compile_stdlib.py -j8` (664/664, 0 unexpected). Corpus spot-
check (collections/__init__.py, weakref.py, zipfile/__init__.py) showed
no change in error signature/count vs. before the fix — all still fail
on their own separate, already-documented issues.

### 3. Not investigated: other "invalid conversion in return statement" (line 575)

Not yet looked at — a third, separate site with the same class of error
as issue #1's symptom but not confirmed to share the same root cause.
(2026-08-09: re-verified — line 575 is `_read_files_egginfo_installed`'s
`return map('"{}"'.format, paths)`, which mixes a bare `return` (line
563, `if not text or not subdir: return`) with this real-value return in
the same function — the exact same "single inferred return type across
a bare-`return`-mixed-with-real-`return`" shape issue #1 already
describes, just a different function. Not a separate root cause.)

### 4. FIXED (2026-08-09): `def f(**kwargs): ...` called with no `*args` slot passed 2 C args against a 1-param C signature

```
error: too many arguments to function 'distributions_08efcc'; expected 1, have 2
```
at both call sites of:
```python
def distributions(**kwargs) -> Iterable[Distribution]:
    ...
```
called as plain `distributions()` (lines 1009, 1044 — inside
`entry_points()`'s `_unique(distributions())` and
`packages_distributions()`'s `for dist in distributions():`).

**Root cause (confirmed via the generated `.ci`)**: `distributions`'s C
signature is correctly declared with exactly ONE parameter
(`int64_t distributions_08efcc (MojoDict *);` — `_signature_ctypes`, the
DEF-side signature builder, only emits a `MojoList *` slot for `*args`
when the function ALSO has a real `*args` parameter before `**kwargs`;
`distributions` has none). But `_lower_named_call`'s `**kwargs`-packing
logic (gimple_codegen.py, the block keyed off `_func_kwargs_slot`)
unconditionally assumed the `f(self, *args, **kwargs)` forwarding
pattern — i.e. that a `*args` slot ALWAYS immediately precedes
`**kwargs` — and built BOTH a fresh empty `MojoList *` (meant to
represent the nonexistent `*args`) AND a `MojoDict *`, passing both to
every `**kwargs`-taking callee regardless of whether it actually
declared `*args` too. For a genuinely kwargs-ONLY function like
`distributions(**kwargs)`, that's 2 arguments against the correctly
1-parameter real C declaration — "too many arguments."

This is a general bug, not specific to this file: ANY plain
`def f(**kwargs): ...` (no `*args`) called with zero positional
arguments and reached through this packing path would hit it.

**Fix**: added `GimpleGen._func_kwargs_has_vararg: dict[str, bool]`
(gimple_codegen.py, declared next to `_func_kwargs_slot`), populated at
the same registration site (`gen_module`'s FunctionDef pre-scan) from
the SAME `_seen_star` flag that loop already computes internally but
previously discarded. The call-site packing logic
(`_lower_named_call`) now checks this flag: when the callee genuinely
has a preceding `*args`, behavior is unchanged (build both a
`MojoList *` and `MojoDict *`, exactly as before); when it doesn't, only
the single `MojoDict *` is built and appended, matching the real 1-slot
C signature. Any stray positional arguments passed to a kwargs-only
call site (a real Python-level `TypeError` this codegen has no
type-checker to catch earlier) are passed through unchanged rather than
silently dropped, ahead of the dict — an honest degrade for a call that
was already invalid Mojo/Python, not a new failure mode.

Verification: both `distributions()` call sites in this file now
compile+link past this point (the "too many arguments" errors are
gone; the file's build now fails only on the separate, pre-existing
issue #1/#3 "invalid conversion in return statement" cluster). Full
quality gate run clean: `test_gimple.py` (247/247), `test_module_
cache.py` (76/76), `make check-selfhost` clean, from-scratch stdlib
dylib rebuild (0 `skip <module>:` lines), `compile_stdlib.py -j8`
(664/664 passed, 0 unexpected).
