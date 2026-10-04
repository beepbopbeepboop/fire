# COMPILE_FAIL: Lib/importlib/resources/readers.py

## Status (2026-10-01 — this file contributes ZERO `error:` lines; all five of the 2026-09-30 errors below are gone, and a simpler refusal replaced them)

```
python3 tools/memslot.py --gb 8 --label readers -- \
  python3 fire.py build -o .tmp/out/readers/readers \
  /Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py
→ exit 1, 0 `error:` lines
```

All five errors the 2026-09-30 entry below records for `readers.py`
itself are gone — the `operator_attrgetter___init__` implicit declaration,
the `_itertools_only_37bd8e` vs `_15e7c2` suffix mismatch, both
`pathlib_Path___init__` arity errors, and `re_finditer`. What is left is a
single module-level generator refusal, in a **closure member** rather
than in this file:

```
cannot compile module: `next(...)` on next(IdentExpr) has no lowering in
this codegen ...
```

at `Lib/importlib/resources/_common.py:105`'s
`return next(callers).frame`, where `callers` comes from
`itertools.filterfalse(...)`. That builtin has no lowering at all, so the
operand's type is unmodelled and `next()` over it has no honest answer.
Root-caused to six lines and filed as
the `itertools.filterfalse`-has-no-lowering gap, which also records the
two measurements that show the refusal's *diagnosis* is misleading — the
builtin `filter` IS modelled and `next(it)` over its result already works,
as does `next(iter(it))` — and the trap that makes "just support
`next(<list>)`" the wrong fix (it would turn two CPython `TypeError`s into
values, because a list and a set have no `__next__`).

So this file's own compile unit is clean and the closure it needs has one
remaining unmodelled builtin in a sibling module. Two open items in this
closure are not this file's: the `_common.py` refusal above, and
`shutil.py`, which no longer stops at the `'open'` ambiguity (fixed and
removed — see `bugs/COMPILE_FAIL_zipfile___init__.md`'s 2026-10-01 entry)
and now contributes its own errors.

Doc kept open on the closure, with the blocker in a named sibling module
rather than in this file.

## Status (2026-09-30, branch work/compile-fail-stdlib-misc — the crash that blocked the whole closure is FIXED; 7 modules in it now compile and report their own errors; readers.py's own 5 errors unchanged and all now precisely located)

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py`
(129 s). Exit 1, 145 `error:` lines, 5 of them in `readers.py`:

```
readers.py:82:3:   implicit declaration of function 'operator_attrgetter___init__'
readers.py:118:10: implicit declaration of function '_itertools_only_37bd8e'; did you mean '_itertools_only_15e7c2'?
readers.py:171:9:  implicit declaration of function 're_finditer_37bd8e'
readers.py:174:3:  too many arguments to function 'pathlib_Path___init__'; expected 2, have 3
readers.py:203:3:  too many arguments to function 'pathlib_Path___init__'; expected 2, have 3
```

### FIXED this session: `AttributeError: 'IdentExpr' object has no attribute 'value'` (commit `b501954c`)

This was NOT one of the two blockers the 2026-09-27 entry listed, and it
took out seven modules of this closure before gcc ever ran:

```
# ERROR: compiling imported module 'zipfile'      ... : 'IdentExpr' object has no attribute 'value'
# ERROR: compiling imported module 'shutil'       ... : 'IdentExpr' object has no attribute 'value'
# ERROR: compiling imported module 'tempfile'     ... : 'IdentExpr' object has no attribute 'value'
# ERROR: compiling imported module '._common'     ... : 'IdentExpr' object has no attribute 'value'
# ERROR: compiling imported module '._functional' ... : 'IdentExpr' object has no attribute 'value'
# ERROR: compiling imported module '.'            ... : 'IdentExpr' object has no attribute 'value'
# ERROR: compiling imported module '._itertools'   ... : 'IdentExpr' object has no attribute 'value'
Error building: 'IdentExpr' object has no attribute 'value'
```

`_returns_kinds_valued` (`mojo/backend_gimple/module_gen.py`) read
`node.args[0].value` on any `struct.unpack*` call — an attribute only a
string-literal node has — so `struct.unpack(fmt, buf)` with a VARIABLE
format, i.e. every module that forwards a caller-supplied format, killed
the build. Its own docstring already said "only literal formats answer";
the code did not. The literal test existed only in `_struct_ctor_format`,
which has its own inline copy of "is this node a plain non-bytes string
literal"; that reading is now the one shared `_struct_literal_format`, so
there is no second copy left to omit the guard from. Two regression tests
(`struct_unpack_computed_format_compiles`,
`struct_unpack_computed_format_keeps_literal_half`), the second asserting
the LITERAL half still answers True so the fix cannot have silently
disabled the per-slot-kinds feature.

Measured on this build: the `AttributeError` appears **0** times.
`zipfile`, `importlib/resources/{__init__,_common,_functional,_itertools}`
now compile (they are in the closure's compiled file list) instead of
crashing; `shutil` used to stop at the `'open' is ambiguous` refusal,
which is now FIXED (the doc that filed it is removed — see
`bugs/COMPILE_FAIL_zipfile___init__.md`'s 2026-10-01 entry for the root
cause and the fix), so `shutil` now reaches gcc and contributes its own
errors; `tempfile` contributes 3 real gcc errors.

### Still blocking, unchanged, all four located

1. **`re_finditer`** (171) — no compiled representation of CPython's
   C-extension `_sre` objects. Feature-sized, as recorded.
2. **`_itertools_only_37bd8e` vs `_itertools_only_15e7c2`** (118) — the
   2026-09-27 entry's `lstrip('.')` fix corrected the PREFIX but not the
   SUFFIX. The two halves of a mangled symbol are `<qualifier>_<name>_<hash>`
   where the hash is `overload_suffix_for(_effective_param_types(...))`,
   and here the DEFINITION is `_itertools_only_15e7c2` (types
   `(MojoList *, MojoList *, int64_t)`) while the CALL is `_37bd8e` — the
   call site typed the imported function's parameters differently from
   `only()`'s own signature, because `only(one_dir)`'s only argument comes
   from `itertools.tee(children, 3)` whose return type is unknown. So this
   is the BUG-2026-024 param-type-snapshot family, one step further on than
   the entry above recorded. NOT attempted: `_effective_param_types` is the
   machinery that a wrong change to silently calls the wrong overload.
3. **`pathlib_Path___init__` arity** (174, 203) — cross-module struct
   constructor called with 3 args where the registered signature has 2;
   `MultiPlug`/`_adapters` pass extra positionals to a foreign struct's
   `__init__`. Same defaults/arity-padding family as (2).
4. **`operator_attrgetter___init__`** (82) — `operator.attrgetter` is a C
   type; its `__init__` has no compiled declaration here.

Closure error distribution for scale: `pathlib` 43,
`importlib/_bootstrap_external` 15, `statistics` 14,
`importlib/resources/_itertools` 11, `pathlib/_os` 10, `glob` 10,
`tokenize` 9, `random` 6, `readers.py` 5.

Doc kept open. **Not closable on this file's account** — items 2-4 are
shared-machinery gaps whose own blast radius is every module in the tree.

## Status (2026-09-27, latest — blocker #1, the cross-module symbol-name mismatch, is FIXED and verified on the real file)

The first of the two remaining `readers.py`-specific errors is closed. It was
a shared-machinery naming bug, exactly as the previous entry predicted, and
it is now a separate, landed fix.

### The bug

`from ._itertools import only` (CPython's
`Lib/importlib/resources/readers.py:15`) produced, in ONE generated unit:

```
#ifndef _MOJO_STUB__itertools_only_37bd8e
int64_t _itertools_only_37bd8e (int64_t, int64_t, int64_t);      /* decl    */
int64_t _itertools_only_37bd8e (int64_t, int64_t, int64_t) {...} /* def     */
  _t51 = __itertools_only_37bd8e (one_dir, _t52, _t53);          /* CALL    */
```

A relative import's leading depth dot is **not** part of the module's name,
but `_register_sym` (`mojo/middle/module_shared.py`) turned that dot into an
underscore like any other dot, so the CALL site's prefix gained an underscore
the DEFINITION side never had. The module's own leading `_` is what made the
two spellings differ by exactly one character — which is why a sibling named
`base3` (as `test_root_module_circular_import_symbol` uses) was always fine
and `_helper`/`_itertools` never was, and why no pre-existing test could have
caught it.

This function was the **only one of five** sites that mangle a module string
into a C symbol prefix and omitted the `lstrip('.')` the other four already
had (`funcs_shared.py:376`, `:602`, `:830`, and `_compile_imported_module`'s
`_module_key` in `emit_resolve.py`). The same class was already found and
fixed for the STRUCT side at `funcs_shared.py:830`
(`“CODEGEN (link-mode): `from SUBMODULE import SYMBOL`, symbol bound to a”`);
this was that same fix simply missed on the free-function side. The comment
immediately below the fixed line states the requirement the old code
violated: "the qualifier half and suffix half of one mangled symbol always
mean the same binding ... the DEFINITION side's exact resolver".

### The fix

One token: `s.module` -> `s.module.lstrip('.')`.

### Verified

- **The real file.** `python3 fire.py build
  /Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py` — the
  call site at `readers.ci:322744` changed from
  `__itertools_only_37bd8e` to `_itertools_only_37bd8e`, matching the
  definition. Diffed the whole generated `.ci` before/after: that one line
  is the only difference.
- **A minimal fails-before regression**, `test_module_cache.py`'s
  `test_underscore_prefixed_sibling_import_symbol`. It asserts the invariant
  rather than a link result, and that distinction is load-bearing: in the
  minimal shape the sibling is ALSO compiled to its own translation unit,
  whose separately-derived symbol happens to satisfy the mismatched call, so
  the binary links and prints the right answer even while the unit's own
  call site names something it does not define. A link/exit-code assertion
  therefore passes on the broken tree. The real failure needs a closure where
  nothing else supplies the name — which is why `readers.py` (one 10 MB
  `.ci` for the whole closure) is the shape that actually broke. The test
  counts distinct C identifier spellings for the imported symbol across its
  declaration, definition and call site, excluding the `_MOJO_STUB_` guard
  namespace. Measured: 2 spellings before the fix, 1 after.

### What still blocks this file (unchanged)

1. **`re_finditer`** — no compiled representation of CPython's C-extension
   `_sre` objects anywhere in this pipeline. Feature-sized, not a quick fix.
2. **Fifteen sibling modules** in the closure: `pathlib` (19 errors),
   `importlib/_bootstrap_external` (15), `pathlib/_os` (10), `tokenize` (8),
   `glob` (7), `statistics` (6), `importlib/resources/_common` (6),
   `random` (4), `numbers` (4), `importlib/resources/_functional` (4),
   `tempfile` (2), `importlib/resources/_adapters` (2),
   `importlib/_bootstrap` (1), `fractions` (1), plus the `shutil`
   `'open' is ambiguous` module-level refusal. Also newly visible now that
   this file gets further: `re_compile` unresolved in `tokenize.py`, and
   `non-trivial conversion in 'component_ref' / 'var_decl'` in
   `tokenize.py` / `_bootstrap_external.py`.

**This doc is NOT closable on item 2's account.** The doc stays, tracking
`re_finditer` and the sibling-module corpus.

## Status (2026-09-27, later — the `@staticmethod`-generator blocker is FIXED on both backends; the file now gets all the way to gcc and fails on two DIFFERENT things)

The feature the previous entry identified as this file's first blocker — a
`@staticmethod` generator method — is implemented, on both coroutine backends,
and the delegation machinery from the entry before it keeps working. The
compilation no longer refuses this module at all.

### The feature, and the three places that had to agree

A generator METHOD with no receiver is a shape all three layers disagreed
about, and each disagreed in a way that made the *unit* wrong rather than
refusing it:

1. **`fire_compiler.method_receiver_kind(m)` — new, and now the single rule.**
   `'self'` / `'cls'` / `''`, decorator FIRST and the first parameter's name
   second. The name-only rule every consumer used is what let a
   `@staticmethod def gen(n)` through as receiver-less: its first parameter
   is a REAL argument, so the old test read "not a method".
2. **`module_gen.py`'s free-function generator loops** (the initial pass and
   the fixed-point retry pass) skipped a generator whose `params[0][0]` was
   `self`/`cls` — a proxy for "is a method" that a `@staticmethod` does not
   satisfy. The method's coroutine unit was therefore emitted under the
   **free-function** symbol `_mojogen_<name>` and registered in
   `_generator_api` under its BARE name, while the real call sites
   (`MP.candidate_paths(...)`, and the consumer path that looks the callee up
   in `_generator_method_api` under a `(struct, name)` key) never found it.
   `C.gen(5)` was not a generator call at all: it lowered to an ordinary
   int64_t call, and the `for` loop over its "result" raised
   `mojo_unsupported_iter` at run time. Both loops now skip by **membership**
   (`_struct_method_ids`, collected next to `_generator_fns` from
   `_walk_ast`), which is the honest test.
3. **`coro.py`'s A3 eligibility and `_lower_one`**: `@classmethod` was
   special-cased and everything else was an instance method, so a
   `@staticmethod` got a `{Struct} *` self the caller never passed *and* had
   its first real parameter stripped from `real_params`. Both read
   `method_receiver_kind` now.
4. **`emit_methods.py`'s generator-method call site**: it unconditionally
   prepended the receiver. It now reads the api entry's `receiver` key (which
   `_cpp_method_receiver_name` records, and which a MISSING key refuses
   rather than guesses) and prepends nothing for `''`. The
   `yield from cls.<gen>(...)` path in `cpp_core.py` already handled `''`.

Regression: three new compile-AND-RUN cases in
`test_gimple_generator_runner.py` (now registered as `gimplegenerators`) —
`staticmethod_generator_method`, `staticmethod_generator_multi_param` (two
parameters, so a still-prepended receiver shifts both and cannot accidentally
come out right), and
`classmethod_generator_yield_from_staticmethod_generator`, which is this
file's exact shape. All three fail at `435cc71` with the refusals above.

### What the file fails on NOW (measured, not inferred)

`python3 fire.py build .../Lib/importlib/resources/readers.py` now runs the
whole closure through codegen and into gcc. `readers.py` itself has exactly
**two** remaining errors, and neither is a generator problem any more:

```
readers.py:118:10: error: implicit declaration of function '__itertools_only_37bd8e';
                               did you mean '_itertools_only_37bd8e'?
readers.py:172:9:  error: implicit declaration of function 're_finditer_37bd8e'
```

1. **A cross-module symbol-name mismatch** for an imported `itertools`
   function: the definition is emitted as `_itertools_only_<hash>` and the
   call site as `__itertools_only_<hash>` — a leading-underscore
   disagreement between the two naming conventions. Small and worth its own
   bug doc; it is a shared-machinery naming bug, not a `readers.py` shape.
2. **`re_finditer`** — the `re` module falls back to source interpretation
   during the build, so `re.finditer(...)` inside a coroutine body has no
   compiled symbol. Same class as the previously documented `re.Match` gap:
   there is no compiled representation of CPython's C-extension `_sre`
   objects anywhere in this pipeline, and the scalar-only coroutine value
   model has no place to put one.

`_resolve_zip_path`'s own body — the one the previous entry called out as
refusing independently — now compiles. The `with contextlib.suppress(...)`
body is still ELIDED by the plain-generator path (documented convention).

The rest of the closure fails too, in fifteen other modules, so the file is
**not** close to building: `pathlib` (19 errors), `importlib/_bootstrap_external`
(15), `pathlib/_os` (10), `tokenize` (8), `glob` (7), `statistics` (6),
`importlib/resources/_common` (6), `random` (4), `numbers` (4),
`importlib/resources/_functional` (4), `tempfile` (2),
`importlib/resources/_adapters` (2), `importlib/_bootstrap` (1),
`fractions` (1) — plus one module-level refusal upstream of all of them
(`shutil`: `'open' is ambiguous`). None of those is this doc's subject; they
are listed so the next session does not re-derive that "the generator
machinery is done" does not mean "the file builds".

**Do not read this file as green.** The two generator gaps this doc was
opened for are closed and covered; what remains is a naming bug, a
`re`-module fallback, and fifteen sibling modules.

## Status (2026-09-27 — the `yield from cls.<generator>` gap is FIXED with synthetic coverage; the file is still open, on a DIFFERENT and now-better-characterised blocker)

The `cls`-receiver/delegation gap this doc's headline blocker named is
closed. `test_gimple_generator_runner.py`'s new
`yield_from_cls_generator_method_delegation` compiles and RUNS a
`@classmethod` generator doing `yield from cls.<sibling generator>(...)`
and asserts CPython's own stdout; it fails at HEAD with exactly the
refusal message below. Four pieces were needed, and none existed:

1. **`_cls_refs_supported` accepted a `cls.<generator method>(...)` call.**
   It deliberately excluded *every* compiled generator method, because
   the ORDINARY-call lowering has no receiver convention for one — a
   correct exclusion for a call that is genuinely ordinary, and the wrong
   test for a `yield from` DELEGATION, which supplies its own.
2. **`_cpp_yield_from` resolved the callee** through
   `_generator_method_api` (the same dict the `for ... in self.<method>
   (...)` consuming path uses, so the two forms of the same callee
   cannot drift) and passed the `cls` receiver positionally. `cls` in a
   compiled `@classmethod` generator body is an opaque, never-dereferenced
   `int64_t` placeholder, so nothing reads it — the receiver is threaded
   purely to keep the arity right, exactly as the ordinary
   `cls.method(...)` lowering already does.
3. **`_yield_from_delegate_ctype` resolved the same callee for TYPE
   inference.** Without it the delegation fell through to a `char *`
   default, so a delegating generator that also does `yield 1` was
   refused for "yields conflicting types" — a refusal for a shape the
   emitter can compile.
4. **A forward declaration of the callee's four `extern "C"` wrappers.**
   `readers.py` defines `_candidate_paths` BEFORE
   `_resolve_zip_path`, so the two-pass method retry makes the callee
   *registered* in time but its `.cpp` unit is still emitted after the
   delegating one — g++ reported all four names as undeclared. Same
   problem `_cpp_gen_self_recursed` already solved for self-recursion,
   generalised here to any delegated-to generator (a repeated matching
   declaration is legal C++, and a disagreement is a hard error rather
   than a silent miscompile).

The receiver arity itself comes from a new `receiver` key on the
registered generator-method api entry (`'self'` / `'cls'` / `''`), read
from the callee's own first source parameter at registration by
`_cpp_method_receiver_name` — the registered `params` are bare ctype
strings with the names stripped, so a consumer cannot recover it from
them, and a MISSING key is refused rather than guessed.

### The file itself is still open, and the remaining blocker is now precise

`readers.py` still fails with the identical refusal message. The reason
has changed, and the change is worth recording because it is a NEW,
separately-fixable gap this investigation surfaced:

- **`_resolve_zip_path` is a `@staticmethod` generator, and staticmethod
  generators do not compile at all** — on either backend. It is not the
  only blocker, but it is the FIRST one, and it is what keeps
  `_candidate_paths` refused: the delegation branch correctly requires a
  callee this compile has actually translated, and this one never is.
  `_gen_cpp_generator_unit`'s method path opens with `if not fn_params or
  fn_params[0][0] not in ('self', 'cls')` → refuse, which a
  `@staticmethod` (first parameter is the real first argument) cannot
  satisfy. The A3 path accepts it and then the CALL SITE does not treat
  it as a generator at all — a `C.inner(5)` call lowered to an ordinary
  int64_t call, and consuming its result raised
  `mojo_unsupported_iter` at runtime. The fix is the same shape as the
  `receiver` key already added: let a method whose first parameter is
  neither `self` nor `cls` compile with NO receiver, on both backends, and
  teach the call sites to route `Class.static_gen(...)` through the
  generator-start convention.
- **`_resolve_zip_path`'s own body still refuses**, independently:
  `for match in reversed(list(re.finditer(r'[\\/]', path_str)))` is a
  `CallExpr` for-loop iterable, and beneath that `match.end()` /
  `match.start()` are calls on `re.Match` objects produced by CPython's
  C-extension `_sre` engine — there is no compiled representation of them
  anywhere in this pipeline. The `with contextlib.suppress(...)` body is
  ELIDED by the plain-generator path (documented convention), acceptable
  only because nothing there can represent the suppressed exceptions
  anyway.

So: **do not read this file as green.** The `cls` delegation machinery
works; this file needs the staticmethod-generator feature and then the
`re.Match` / `reversed(list(...))` work on top of it.

### A second, smaller gap this work uncovered

`test_gimple_generator_runner.py`'s build helper gated on
`'__mgco_' in c_code`, which is the A3 stack-switch marker, and sent
the whole module down the pure-A3 link — never compiling `prog_gen.cpp`.
A module whose generators are split across the two backends (the new
`cls` case is the first) therefore had one backend's bodies silently
dropped and failed to link with undefined symbols. The two body kinds
are now detected SEPARATELY (`'__mgco_'` vs `'_mojogen_'`) and the
link gets exactly the runtimes each needs: the `.cpp` is compiled
whenever either kind is present, the A3 runtime objects are linked for
an A3 body and `fire_runtime.c` otherwise, and the link driver is g++
whenever a cpp body is present. One path now covers pure-A3, pure-cpp
and mixed modules.

## Status (updated 2026-08-26 — fresh deep-dive per task request; doc remains OPEN, but the documented blocker text is now substantially stale and the remaining gap is precisely characterized)

Fresh investigation this session, as explicitly requested (the recent
generator value-carrying-return work prompted a re-check of whether
cross-generator `yield from` delegation is now plausibly tractable).
Reproduced today's isolated refusal — same two shapes, byte-for-byte:

```
Unsupported shape(s): _candidate_paths: _candidate_paths: a
@classmethod generator that references `cls` in its body in an
unsupported way (...); _resolve_zip_path: unsupported for-loop
iterable type: CallExpr.
```

### What changed since the 2026-08-25 write-up (stale-text corrections)

1. **Cross-generator delegation is NO LONGER "a real, separate,
   not-yet-built mechanism" in general.** The old text's premise is now
   only ~half true. Verified fresh via minimal repros against current
   master:
   - `yield from <plain-name>(...)` delegating to another compiled
     free-function generator WORKS (`_generator_api` + fixed-point
     retry passes for forward references);
   - `for x in self.<genmethod>(...)` / generator-METHOD delegation
     WORKS (`_generator_method_api`, receiver passed as literal
     `self`);
   - @classmethod generators with receiver passing WORK; and,
     notably discovered this session: **@staticmethod generators are
     silently routed through the FREE-FUNCTION generator path**
     (gimple_module_gen.py's free-fn loop skips only first-param-
     self/cls functions), compiling to a module-unqualified
     `_mojogen_<name>_*` unit registered under their bare name. A
     minimal repro confirms `_resolve_zip_path`'s trivially-reduced
     body (plain string yields) compiles fine standalone.
2. **The "plain `yield` of a foreign-module constructor" half of the
   old blocker is GONE.** `yield pathlib.Path(path_str)` inside a
   generator body now compiles (verified with an isolated probe).

### What ACTUALLY remains missing for `_candidate_paths`

Exactly one narrow thing: `_cls_refs_supported` deliberately excludes
`cls.<method>(...)` when `<method>` is a generator method of the
enclosing struct, and `_cpp_yield_from`'s delegation dispatcher has no
branch resolving a `cls.` receiver (it handles bare IdentExpr callees
and literal-self receivers only). A minimal two-method repro (classmethod
generator doing `yield from cls.<staticmethod-gen>(...)`) refuses at
eligibility even though the staticmethod callee itself fully compiles.
Extending it would be: relax the exclusion for generator methods that
have (or, via the existing retry passes, will get) an api entry, plus a
`cls.`-receiver branch in the yield-from/for-consumption emitters
(staticmethod callee → no receiver arg; classmethod callee → opaque
int64_t placeholder, mirroring `_gen_cpp_generator_unit`'s own `('cls',
'int64_t')` convention). Plausibly a small, mechanical change.

### Why it was nevertheless NOT attempted, and why this doc stays open

Fixing delegation alone cannot close this file, because
`_resolve_zip_path` independently refuses on shapes that are genuinely
feature-sized:
- `for match in reversed(list(re.finditer(r'[\\/]', path_str)))` —
  CallExpr iterable still refused (re-probed fresh); and beneath that,
- `match.end()`/`match.start()` are calls on `re.Match` objects
  produced by the CPython C-extension `_sre` engine — there is no
  compiled representation of them anywhere in this pipeline (re itself
  falls back to source interpretation during the build), so consuming
  them inside a coroutine frame would need a foreign/interpreted-object
  model the scalar-only coroutine codegen deliberately does not have;
- the guarded body runs under `with contextlib.suppress(...)` whose
  exception-suppression semantics the plain-generator path currently
  ELIDES entirely (documented convention) — acceptable only because
  nothing here can represent the suppressed exceptions anyway.

Also relevant to the cost/benefit: `grep -rn "yield from cls\."`
across the entire Lib/ tree hits exactly ONE site — this file's line
162. The narrow delegation extension would have zero other consumers
today, and it edits shared coroutine eligibility/emission machinery
(the exact class of change CLAUDE.md's regression history warns
about). Per the campaign's risk policy — don't touch shared machinery
without end-to-end payoff — deferred until some real consumer can
actually compile end-to-end once it exists.

## Status (updated 2026-08-25 -- re-verified against fix/rest-remainder12, unchanged, root cause pinned down precisely)

Re-ran an isolated `compile_to_gimple_with_cpp` check fresh (post this
session's coroutine-emitter fixes for COMPILE_FAIL_Apple___main__.md
— none relevant to this file's shape). The refusal message is more
detailed than the 2026-08-23 entry recorded (this file was evidently
last checked before `fd909e9`'s per-function refusal-reason reporting
landed), and pins down the exact mechanism:

```
Unsupported shape(s): _candidate_paths: _candidate_paths: a
@classmethod generator that references `cls` in its body in an
unsupported way is not supported (only a class-level-attribute read,
or a call to a real compiled classmethod/static method of the
enclosing class, are supported for `cls.<...>` access in a compiled
generator); _resolve_zip_path: unsupported for-loop iterable type:
CallExpr.
```

Read `gimple_cpp_core.py`'s `_cls_refs_supported` (the check that
produces this message): its own docstring/inline comment explicitly
and deliberately excludes a `cls.<method>(...)` call when `<method>`
is ANOTHER COMPILED GENERATOR (checked via `gen.
_struct_generator_method_names`) — exactly `_candidate_paths`' own
`yield from cls._resolve_zip_path(path_str)` shape (`_resolve_zip_path`
is itself a generator, a `@staticmethod`). The comment states plainly
this needs "its own coroutine-construction call convention this fix
does not add" — i.e. composing/delegating into another already-
compiled coroutine from inside a coroutine body is a real, separate,
not-yet-built mechanism, not a missing case in an existing dispatcher.
Separately, `_resolve_zip_path` itself additionally fails the for-loop
iterable check (`for match in reversed(list(re.finditer(...))):` —
`reversed(list(...))` as a for-target has no coroutine-body for-loop
lowering). Even fixing the for-loop gap alone would leave
`_candidate_paths` still refused by the `yield from`-into-another-
generator gap. Both genuinely feature-sized (coroutine-to-coroutine
delegation, a new call convention); not attempted. Doc kept open.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. The blocker (`_candidate_paths`: a plain `yield` of a foreign-module constructor followed by `yield from` delegating to another classmethod generator) is unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still structural; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-23 against master 626f3f0 — unchanged, STILL-OPEN structural)

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
importlib/resources/readers.py` fresh: still fails with the IDENTICAL
up-front refusal, byte-for-byte the 2026-08-09 message —
`cannot compile module: function(s) _candidate_paths (generator
function(s), contain a yield/yield from)`. Although the compiled-
generator project landed substantial coroutine-body support since the
last pass (C++20-coroutine units for many shapes; this cluster's own
fd909e9 tightened its refusal contract), `_candidate_paths` remains
outside every supported shape and is refused by the module-level
pre-pass before any per-function codegen. The gap is exactly as the
2026-08-09 analysis below describes: a plain `yield` of a constructed
value (`yield pathlib.Path(path_str)` — a foreign-module constructor,
itself unsupported in the scalar body model) followed by `yield from`
delegating to another generator METHOD (`cls._resolve_zip_path`, a
@classmethod generator call needing the classmethod-generator
call-convention machinery). Feature-sized, not attempted; see that
write-up for the full shape requirements.

## Status (re-verified 2026-08-09 — historical): blocker changed, now a confirmed structural gap

Re-ran `python3 fire.py build .../readers.py` fresh against current
master. The 2026-08-06 blocker below (the `NamespaceReader.__init__`
unannotated-param `int64_t` mistype) no longer surfaces — presumably
fixed as a side effect of other recent type-inference work on sibling
importlib files this session — but the module still fails to build,
now on an earlier, module-wide pre-pass:

```
Error building: cannot compile module: function(s) _candidate_paths
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ... falling
back to interpreting this module from source instead
```

Confirmed real: `MultiplexedPath._candidate_paths` (line 160) is a
genuine generator —
```python
@classmethod
def _candidate_paths(cls, path_str: str) -> Iterator[abc.Traversable]:
    yield pathlib.Path(path_str)
    yield from cls._resolve_zip_path(path_str)
```
`gimple_codegen.py`'s `gen_module` (`gimple_codegen.py` around line
30564) does an upfront, whole-module scan for any function containing
`yield`/`yield from` or declared `async def`, and — when not running
under `relaxed_imports` (stdlib-build fallback mode; `fire.py build`
on a direct entry file always runs strict) — raises immediately,
before any per-function codegen (including whatever
`NamespaceReader.__init__` now does) is even attempted. This is the
same well-known, deliberate limitation noted in this project's
generator/coroutine codegen history: only specific, narrow generator
shapes have a real suspend/resume state-machine lowering implemented
(see `test_generators.py`/the compiled-generator-codegen project in
git log); arbitrary generator shapes like this one (plain `yield` +
`yield from` delegating to another generator method) are not among
them. This is a genuinely structural gap, not a narrow bug — no fix
attempted here, per the task's explicit scope (generator support is
feature-sized, not a narrow fix).

## Status (updated 2026-08-06, historical — superseded above)

Re-ran; current error:

```
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:142:1: error: non-trivial conversion in 'mem_ref'
```
at `NamespaceReader.__init__`'s `self.path =
MultiplexedPath(*filter(bool, map(self._resolve, namespace_path)))`.

Root-caused: this is a confirmed real-world instance of the
already-documented hard bug
`“the constructor-call-site field-typing pass understood only scalars”` (which
supersedes the removed
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`)
— `__init__(self, namespace_path)`'s unannotated `namespace_path`
parameter defaults to `int64_t` regardless of the real (iterable)
argument type. Confirmed via the generated `.ci`: the parameter is
declared `int64_t`, and an unrelated use of it a few lines earlier
(`if 'NamespacePath' not in str(namespace_path)`) lowers `str(
namespace_path)` as `mojo_str_from_int(namespace_path)` — the same
"real value is a container/string, field typed int64_t" signature the
hard bug doc's own minimal repro produces. `map(self._resolve,
namespace_path)` then tries to iterate the wrongly-int64_t-typed
param, producing the GIMPLE `mem_ref` conversion error. Added as a new
confirmed instance to that hard-bug doc. Not fixed here, per that
doc's own risk assessment (shared call-site/parameter type-inference
machinery, high risk, not attempted this session).

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function '_alloc_MultiplexedPath':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:73:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   73 |         self._paths = list(map(_ensure_traversable, remove_duplicates(paths)))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'remove_duplicates_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:260:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader___init__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:34:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   34 |     def files(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:32:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   32 |         return str(self.path.joinpath(resource))
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:31:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   31 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:30:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   30 |         copy.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:29:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   29 |         `resources.path()` from creating a temporary
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:28:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   28 |         Return the file system path to prevent
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:27:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   27 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:26:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   26 |     def resource_path(self, resource):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:25:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   25 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:24:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   24 |         self.path = pathlib.Path(loader.path).parent
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader_resource_path':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 | class ZipReader(abc.TraversableResources):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:31:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   31 |         """
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:29:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   29 |         `resources.path()` from creating a temporary
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader_files':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (1120 more lines)
```

Exit code: 1
Elapsed: 10.35s
