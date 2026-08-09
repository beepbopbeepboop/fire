# HARD BUG: a generator with a struct/class-typed parameter is refused outright, hard-failing the WHOLE top-level module (not a graceful per-function fallback)

## Status (FIXED 2026-08-08, this doc's own title case only)

Fixed the exact case this doc's title and root-cause section describe —
a struct-typed generator PARAMETER — for all three coroutine-codegen
units (`_gen_cpp_generator_unit`, `_gen_cpp_async_unit`,
`_gen_cpp_async_generator_unit`, which the doc's own "Scope note"
already established share one byte-for-byte-identical allow-list). The
OTHER two families that scope note also names (non-scalar yielded
values; `*args`/`**kwargs` parameters) are NOT addressed by this
change — separate, still-open docs.

### What was fixed

1. **Parameter acceptance**: widened all 3 allow-list checks to also
   accept a pointer to any struct this compile already knows about
   (`ctype.endswith(' *') and ctype[:-2] in self.struct_field_types`) —
   exactly the "mechanically straightforward, zero additional plumbing"
   acceptance step this doc's own "What a fix would need" section
   predicted.
2. **Body-side struct-pointer access** (the doc's own predicted hard
   part): a struct-typed generator parameter needs `->` for field
   reads, not `.` — `_cpp_expr`'s non-self `MemberExpr` case now checks
   a new `_cpp_struct_ptr_local(name)` helper (looks up the name's
   declared C++ type in `self._cpp_declared`, resolves to the bare
   struct name if it's a known struct pointer) and picks the correct
   operator.
3. **Method calls on a struct-typed value** (the doc's own flagged
   "real work" — and, discovered while implementing this, NOT limited
   to non-self parameters): this codegen's structs are plain C structs
   with no real C++ member functions — confirmed via a direct repro
   that even the PRE-EXISTING `self.method()` call path
   (`gimple_codegen.py`'s `self->{member}(args)` emission, already
   present in the code before this fix) was actually BROKEN, not just
   narrow-scoped as its own docstring claimed ("method calls on self
   ... refuse naturally") — a real repro hit `'Counter' has no member
   named 'bump'` at the g++ compile step, since no member function
   named `bump` exists on the plain C struct typedef. Fixed BOTH the
   self case and the new non-self case together: a method call now
   goes through the method's own mangled C symbol
   (`_struct_method_csym`) as an ordinary free-function-style call
   (`mangled_sym(obj_ptr, args...)`), not C++ member-call syntax. Which
   `(struct, method)` pairs actually get called is tracked in a new
   `self._cpp_struct_method_refs` set and declared `extern "C"` in the
   .cpp preamble (mirroring the existing `_cpp_module_func_refs`
   pattern for free functions called from a generator body).
4. **Struct-typedef visibility for parameter types**: the .cpp
   preamble only re-emitted a struct's C layout for the `self` struct
   of a generator METHOD (`_supported_generator_methods`). A struct
   accepted only via a generator/async function's own PARAMETER type
   (not `self`) had no typedef in the .cpp TU at all, producing
   `'Resolver' was not declared in this scope`. Fixed by tracking every
   struct name accepted this way in a new `self._cpp_param_struct_names`
   set and merging it into the same typedef-emission loop
   `_supported_generator_methods` already drives.

### Verification

- The doc's own minimal-repro sketch (`Resolver.__init__(self, base)` /
  `resolve(self, x): return x + self.base`, `def gen_vals(r: Resolver,
  n): ... yield r.resolve(i) ...`) — needed an explicit `r: Resolver`
  annotation to actually exercise struct-typed PARAMETER inference (an
  unannotated free-function generator parameter has no equivalent of
  #143's constructor-call-site scalar inference; noted as a real,
  separate, narrower gap, not fixed here). Compiles and runs correctly:
  `Resolver(10)`'s generator prints `10, 11, 12`.
- A companion self-method repro (`Counter.gen_vals(self, n): yield
  self.bump(i)`) — confirmed BROKEN before this fix (direct repro:
  `'Counter' has no member named 'bump'`), fixed and verified: prints
  `10, 11, 12`.
- Real-world trigger re-tested: `MOJO_DEBUG=1 python3 mojo.py build
  .../Lib/dis.py` — this doc's own exact documented symptom
  (`_get_instructions_bytes: generator parameter 'arg_resolver' has
  unsupported type 'ArgResolver *'`) no longer appears ANYWHERE in the
  build output; `_get_instructions_bytes` is no longer refused. The
  file as a WHOLE still can't build — `_find_imports`/`_unpack_opargs`/
  `findlinestarts` still refuse, but for the entirely separate,
  explicitly-out-of-scope "non-scalar yielded value" reason this doc's
  own Scope note already names (`bugs/COMPILE_FAIL_pathlib___init__.md`
  /`bugs/CODEGEN_generator_function_Lib_ftplib.md`'s family) — not a
  new/different symptom, and not something this change touches or
  regresses.
- Full 5-part gate: `compile_stdlib.py -j8` run FIRST (fail-fast,
  matching every other high-risk item's verification order this
  session) — 664/664, 0 unexpected, unchanged from baseline, both
  times this was run during development. `test_gimple.py` 247/247,
  `test_module_cache.py` 76/76, `make check-selfhost` clean,
  from-scratch stdlib dylib rebuild 0 skips. `test_gimple_runner.py`
  (compiled-AND-RUN suite) 17/18 — the 1 failure is the
  already-documented, confirmed pre-existing (unmodified-master)
  failure from earlier this session, unrelated to this change.

### Known, honest limitations (not attempted)

- The non-scalar-yielded-value and `*args`/`**kwargs`-parameter
  families this doc's own "Scope note" section already named are
  UNTOUCHED — separate docs, separate root causes.
- An UNANNOTATED struct-typed generator/async parameter still defaults
  to `int64_t` (no equivalent of #143's constructor-call-site scalar
  inference exists for generator/async free-function parameters) —
  only an EXPLICITLY annotated struct-typed parameter is accepted.
- A struct-typed LOCAL VARIABLE (not a parameter) inside a generator
  body was not specifically exercised — `_cpp_struct_ptr_local` reads
  from `self._cpp_declared`, which the existing body-compile loop
  already updates for locals assigned a known type, so this should work
  by the same mechanism, but wasn't separately repro'd.
- A NESTED struct method call whose OWN parameters include ANOTHER
  struct pointer, deep `self.x.y.method()` chains, and generic/
  parametrized structs were not exercised — this fix targets exactly
  the shape the doc's own repro and the real `dis.py` trigger use (a
  direct `local_or_param.method(args)` call), not the fully general
  case.

## Scope note (2026-08-07): this is a whole FAMILY of refusals, not just struct-typed parameters

This doc's title names the parameter-type case specifically (the
original finding), but the SAME underlying architecture — a fixed
scalar/container allow-list in `_gen_cpp_generator_unit`/
`_gen_cpp_async_unit`/`_gen_cpp_async_generator_unit`, refusal
escalating to a fatal whole-module `RuntimeError` for the CLI's
`mojo.py build` root file — has now been independently confirmed
hitting THREE more real stdlib files via two OTHER trigger shapes, not
just struct-typed parameters:

- **Non-scalar YIELDED VALUE** (a tuple, where "every `yield` must
  carry a value, and all values must agree on one scalar type" is
  violated): `Lib/pathlib/__init__.py`'s `Path.walk()` (`yield path,
  dirnames, filenames`) and `Lib/ftplib.py`'s `FTP.mlsd()` (`yield
  (name, entry)`). See `bugs/COMPILE_FAIL_pathlib___init__.md` and
  `bugs/CODEGEN_generator_function_Lib_ftplib.md`.
- **`*args`/`**kwargs` parameters refused unconditionally**:
  `Lib/test/_code_definitions.py`'s `asyncgen_spam(*args)`. See
  `bugs/CODEGEN_generator_function_Lib_test__code_definitions.md`.

All three are the same class of finding as this doc's original
struct-typed-parameter case: a real, documented, INTENTIONAL scope
limit in the C++20-coroutine codegen subsystem, not an accidental
bug — and per this session's assignment, this whole family is held
back from further attempts (feature-sized: widening the coroutine
promise type to carry non-scalar yielded values, or to accept
`*args`/`**kwargs`, are both real features, not narrow fixes). Left
here as a consolidated pointer so a future session doesn't have to
re-discover the connection between these docs from scratch.

## Status (re-verified 2026-08-07, still unfixed)

Re-confirmed still reproducing identically against current master
(after tasks #146/#149/#150/#151/#138/#145 all landed) — none of those
6 fixes touch the parameter-type allow-list. `MOJO_DEBUG=1 python3
mojo.py build .../Lib/dis.py` still shows the exact same refusal:
`_get_instructions_bytes: generator parameter 'arg_resolver' has
unsupported type 'ArgResolver *'`. Considered for this session's item
3 (only-if-time-remains); NOT attempted — the analysis below already
correctly scopes this as genuinely feature-sized (parameter-acceptance
AND body-side struct-method-call support need to land together, or the
failure just moves one step later per the "What a fix would need"
section), not a narrow fix suitable for the remaining time budget in
this pass. Left for a dedicated future session with a real time budget,
per this project's guidance for tasks explicitly marked this way.

## Status (original)

Unfixed / not attempted — this is a deliberate, documented scope boundary
in `_gen_cpp_generator_unit`/`_gen_cpp_async_unit`, not an accidental bug
in the usual sense (see "Root cause"), so fixing it means genuinely
widening the coroutine codegen's parameter-passing story, not patching a
mistake. Root-caused 2026-08-06 while classifying the
`CODEGEN_generator_function_Lib_*.md` cluster (tasks #95-135). Confirmed
live on current master (`2b0c4c5`) via `Lib/dis.py`'s real build.

## Symptom

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py
[gimple_codegen] generator '_get_instructions_bytes' not eligible for C++ coroutine path, falling back to honest refusal: _get_instructions_bytes: generator parameter 'arg_resolver' has unsupported type 'ArgResolver *' (only int64_t/double/_Bool/char*/MojoList*/MojoDict*/MojoSet* parameters are supported for compiled generators)
[... repeated for passes 2-4 ...]
[gimple_codegen] relaxed_imports: skipping unsupported functions: _get_instructions_bytes (generator function(s), contain a `yield`/`yield from`)
Error building: cannot compile module: function(s) _get_instructions_bytes (generator function(s), contain a `yield`/`yield from`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead
RuntimeError: cannot compile module: function(s) _get_instructions_bytes (...)
```

`mojo.py build`'s exit is a hard failure (RC=1, no object file produced)
DESPITE the error text claiming "falling back to interpreting this
module from source instead" — that fallback behavior is real for
**imported** modules (`gen_module`'s "relaxed imports" degrade-gracefully
path — see the `[gimple_codegen] relaxed_imports: skipping unsupported
functions` debug line right above, which IS a graceful per-function skip
for a module reached via import), but is NOT honored for the **top-level
file actually passed to `mojo.py build`** — `build_executable` treats
`gen_module`'s `RuntimeError` as fatal for that one file, full stop. This
exact "message promises graceful fallback, CLI path doesn't actually take
it" mismatch is independently corroborated by
`bugs/hard/CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`'s
own Symptom section, so it's a recurring, general characteristic of this
failure mode across this whole cluster, not unique to `dis.py`.

## Root cause

`_gen_cpp_generator_unit`'s parameter-support step (`gimple_codegen.py`)
only accepts parameters whose resolved C type is one of `int64_t`,
`double`, `_Bool`, `char *`, `MojoList *`, `MojoDict *`, `MojoSet *` — any
OTHER resolved type (concretely: a pointer to a user-defined
`struct`/`class`, e.g. `dis.py`'s own `ArgResolver` class) raises
`_UnsupportedGeneratorShape` and the whole function is refused. This is
an explicit, documented, INTENTIONAL scope limit — the method's own
docstring says: *"string/struct/pointer parameters cross the C++/C
boundary with lifetime and ownership questions this narrow step
deliberately defers"* — not a bug where the type was supposed to work and
doesn't; the coroutine codegen project simply never widened past scalar/
container types for parameters. The identical restriction (byte-for-byte
same allow-list) is independently duplicated in `_gen_cpp_async_unit`
(plain async functions) and the async-generator step, so this is a
project-wide policy of the whole C++20-coroutine codegen subsystem, not a
one-off omission in the plain-generator path alone.

`_get_instructions_bytes(code, linestarts=None, line_offset=0,
co_positions=None, original_code=None, arg_resolver=None)` in `dis.py`
takes `arg_resolver: ArgResolver = None` — a real, explicitly-typed
(via the object actually passed at every real call site, resolved through
this codegen's own usage-based inference) parameter of a user-defined
class. This is a categorically different situation from the already-
documented "untyped param defaults to int64_t" gap
(`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s bullet 1): the type here
IS correctly known/inferred (`ArgResolver *`) — it's being explicitly
REFUSED, not silently mistyped.

## Why this is a distinct, high-value finding for this cluster

Because the refusal escalates to a WHOLE-MODULE `RuntimeError` for the
top-level file (see Symptom), a single generator function ANYWHERE with
one struct-typed parameter is enough to hard-fail `mojo.py build` for
that entire file, even if every other function in the file (generator or
not) would otherwise compile cleanly. This makes it a much higher-impact
gap per occurrence than the "gets past eligibility but hits a narrower
.cpp-level type bug" cluster (dyld.py's 5 bullets) — those degrade to
"this one generator's body has a bug", not "the whole file refuses to
build at all".

## What a fix would need

Passing an opaque struct pointer as an ordinary by-value C++20 coroutine
parameter is mechanically straightforward (the compiler-generated
coroutine frame already copies scalar/`MojoList *`/`MojoDict *`/
`MojoSet *` parameters into itself by value today — the same copy
semantics work for any trivially-copyable pointer type, including a
struct pointer, with ZERO additional plumbing beyond widening the
allow-list check). The real work implied by the docstring's own caveat
("lifetime and ownership questions") is likely about what happens
INSIDE the generator body once such a param is in scope — e.g. does
`_cpp_expr`'s `MemberExpr` case support `arg_resolver.get_argval_argrepr
(...)` (a METHOD CALL on a struct-typed generator parameter, not just a
scalar SELF field read, which `_gen_cpp_generator_unit`'s own docstring
already flags as "method calls on self ... are out of this step's scope
and refuse naturally" for the `self` case) — so simply widening the
allow-list would very likely just convert this hard hand-off-time
refusal into a DIFFERENT `_UnsupportedGeneratorShape`/C++ compile error
the first time the body actually USES the struct parameter (calls a
method on it, as `_get_instructions_bytes` does:
`arg_resolver.get_argval_argrepr(op, arg, offset)`). Any real fix should
be scoped to cover both the parameter-acceptance AND the body-side
struct-method-call support together, or it will just move the failure
one step later without actually unblocking the file.

## Repro

Real: `MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py` — `_get_instructions_bytes`'s `arg_resolver: ArgResolver`
parameter.

Minimal repro sketch (not yet hand-verified in isolation):

```python
class Resolver:
    def __init__(self, base):
        self.base = base
    def resolve(self, x):
        return x + self.base

def gen_vals(r, n):
    i = 0
    while i < n:
        yield r.resolve(i)
        i += 1

def main():
    r = Resolver(10)
    for v in gen_vals(r, 3):
        print(v)
main()
```
Expected (per root cause above): refused at the parameter-type check
(`r`'s resolved type `Resolver *` not in the scalar/container allow-list)
before ever reaching the `r.resolve(i)` method-call question.
