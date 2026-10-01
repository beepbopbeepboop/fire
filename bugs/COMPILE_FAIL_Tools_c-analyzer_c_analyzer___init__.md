# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-26 — the loop-as-expression codegen this doc's own history called for is now implemented; ADVANCED, not closed)

This doc's 2026-08-25 entry root-caused all three of this file's refused
generators to one shared gap and explicitly scoped a real fix: "giving
the coroutine-body expression emitter genuine loop-as-expression
codegen ... a materially new codegen capability". Implemented this
session: `gimple_cpp_core.py` gained `_cpp_build_container_from_iterable`
(a new helper building a real `MojoList *`/`MojoSet *` via an
immediately-invoked C++ lambda wrapping a genuine loop, reusing
`_cpp_for_stmt`'s existing iterable-shape dispatch) plus
`_cpp_rename_ident` (gives a comprehension's own loop variable a fresh
C++ name so its scope can't alias an outer same-named local), wired into
`_cpp_expr`'s `Comprehension` case (previously a hard-coded always-empty
stub) and a new `list(x)`/`set(x)` single-arg `CallExpr` case (mirroring
the ordinary GIMPLE path's own `_lower_ctor_from_iterable`). Matching
`_infer_simple_expr_ctype` widening in `gimple_exprtypes.py` so a
first-assigned local's declared C++ type agrees with what the new
codegen actually produces. Also added: dedicated `MojoSet *` single-name
for-loop iteration in `_cpp_for_stmt` (via `mojo_set_iter_new/_next/
_val_int/_free`, mirroring the ordinary GIMPLE path's `_gen_for_set`) —
needed so `list(<a set local>)` round-trips through the new mechanism.

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` (strict)
repro, A/B'd via `git stash`: **2 of the 3 refused generators' blocking
reason changed** —
- `analyze_decls`: was `"a call to unresolved callee 'list(...)'"`
  (from `decls = list(decls)`). Now compiles past that entirely and
  refuses on `"a call to unresolved callee 'group_by_kinds(...)'"` — a
  DIFFERENT, deeper gap this doc's own 2026-08-25 entry already
  predicted lay behind it ("`group_by_kinds`/dict-comprehension/
  nested-`def` shapes in `analyze_decls`'s body").
- `iter_decls`: was `"a call to unresolved callee 'set(...)'"` (from
  `KIND.DECLS & set(kinds)`). Now compiles past that and refuses on
  `"a `*`/`**`-unpack call argument is not supported"` — this is
  `iter_decls`'s OWN already-documented, separately-tracked blocker
  (the 2026-08-14 entry: `parse_files(filenames, **kwargs)` forwarded to
  a dynamically-obtained parameter-valued callee, genuinely structural,
  not attempted) — i.e. the `set()` fix genuinely unblocked the function
  far enough to reach the frontier this doc had already mapped out.
- `check_all`: byte-identical, `"unsupported for-loop iterable type:
  CallExpr"` (`for data, failure in check(analysis):`, a for-loop over a
  call through a loop-variable callable — not a `list()`/`set()`/
  comprehension shape, correctly untouched by this fix, matching the
  task's explicit scoping decision to leave dynamic-callable iteration
  out of scope).

**Net effect**: real progress on 2 of 3 functions (their `list()`/
`set()` blockers are fully eliminated), but each now sits behind a
different, separately-structural gap (`group_by_kinds` call resolution;
`**kwargs`-to-dynamic-callee), and `check_all` is unaffected — module
still does not build. Quality gate: `test_gimple.py` 264/264,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skip lines. Doc stays open.

## Status (re-verified 2026-08-26)

Fresh repro against this session's tree (`fix/rest-remainder18`, based on
integrated master) reproduces the EXACT same three-function refusal
verbatim (`analyze_decls`: unresolved `list(...)`; `check_all`: for-loop
iterable `CallExpr`; `iter_decls`: unresolved `set(...)`) — byte-identical
error text to the 2026-08-25 pm entry below. None of this campaign's
recently-landed shared fixes (str.split/rsplit/splitlines in coroutine
bodies, real isinstance() semantics, C++-keyword field escaping, scalar
self-field range-for, next() on cross-module generators, self-host
bootstrap fix) touch loop-as-expression codegen, so no change was
expected and none was found. Confirmed still genuinely blocked on the
same large structural gap (`_cpp_expr`'s `Comprehension` case is a hard
stub; no `list()`/`set()`/comprehension-as-value codegen in the
coroutine-body emitter). Not attempted — this is exactly the kind of
"large speculative feature project" this round's instructions say not to
take on. No code change; doc left as-is below.

Re-verified again 2026-08-26, wtOpencode_canalyzer2 (fresh-cut worktree):
isolated compile_to_gimple_with_cpp(do_imports=False) gives the identical
three-shape refusal set verbatim; still out of reach for the same reasons
(opaque-param list()/set() materialization → generator-handle parameter
wall → nested-def closure + loop-variable-callee call shapes behind it).

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1)

Fresh repro reproduces the EXACT three-function refusal set documented
below (`analyze_decls`: unresolved `list(...)`; `check_all`: for-loop
iterable CallExpr; `iter_decls`: unresolved `set(...)`) — unchanged by
any of the recent campaign fixes. Re-examined for tractability this
round and confirmed out of reach:

- Adding `list(x)`/`set(x)` construction to the coroutine-body emitter
  would not flip this file: `analyze_decls`'s `decls` parameter is fed
  AT ITS ONLY CALL SITE from `iter_analysis_results`'s
  `decls = iter_decls(filenames, **kwargs)` — a compiled-GENERATOR
  handle, which the generator-parameter type whitelist refuses outright
  — so even a perfect `list()` lowering hits the parameter wall next.
- Behind that sit `group_by_kinds`/dict-comprehension/nested-`def`
  shapes in `analyze_decls`'s body, plus `check_all`'s dynamic-callee
  loop (`check` is a loop-variable callable) — the same loop-as-
  expression / closure-compilation families already root-caused below.

No code change; doc re-verified with the parameter-typing observation
added. Still open.

## Status (re-verified 2026-08-25)

Re-ran fresh against current `fix/rest-remainder9` tip (descends from
master's `3d2c6c2`, which already includes the `_cpp_try_kwargs_forward_call`
fix this doc's 2026-08-14 entry describes, and the later generator-
consumption-ordering fix). The blocker has SHIFTED — it is no longer
`iter_decls`'s dynamic-callee `**kwargs` forward (that shape is still
correctly, safely refused, but it's no longer the first thing hit). Fresh
repro (`python3 fire.py build .../c_analyzer/__init__.py`) now reports
THREE separate ineligible generators, none of which are the kwargs-forward
case:

```
Error building: cannot compile module: function(s) analyze_decls, check_all,
iter_decls (generator function(s), contain a `yield`/`yield from`) ...
Unsupported shape(s): analyze_decls: a call to unresolved callee 'list(...)'
is not supported in a compiled generator/coroutine body (...); check_all:
unsupported for-loop iterable type: CallExpr; iter_decls: a call to
unresolved callee 'set(...)' is not supported in a compiled generator/
coroutine body (...).
```

Root-caused all three to the SAME underlying structural gap, confirmed by
reading `gimple_cpp_core.py`'s coroutine-body expression emitter directly:

- `analyze_decls`: `decls = list(decls)` (line 59 of the source) — `list(x)`
  builtin.
- `iter_decls`: `KIND.DECLS & set(kinds)` (line 38) — `set(x)` builtin.
- `check_all`: `for data, failure in check(analysis):` (line 94) — a
  for-loop whose iterable is itself a call through a parameter-valued
  callable (`check` is a loop variable bound from `checks`).

The ordinary (non-coroutine) call path lowers `list(x)`/`set(x)` via
`_lower_ctor_from_iterable` (gimple_gen_calls.py:1457), which desugars them
into a synthetic comprehension and hands it to `_lower_comprehension` — a
real STATEMENT-level loop emission. The coroutine-body expression emitter
(`_cpp_expr` in gimple_cpp_core.py) has no equivalent: its own
`Comprehension` case (line 1122) is a hard-coded stub that returns an empty
`mojo_list_new ()` with a comment stating plainly that "real comprehension
lowering needs a loop, which an expression slot can't hold" — this coroutine
emitter's call-expression-tree model has no support for loops appearing in
expression position at all, distinct from generator suspend/resume itself.
Confirming this: the `for data, failure in check(analysis):` shape isn't a
`**kwargs` issue either — it's a for-loop whose iterable is a bare `CallExpr`
result, which the emitter's for-loop-iterable dispatcher (line ~4334) simply
has no case for since it isn't one of the fixed shapes (range/MojoList*/
MojoStr*/MojoDict*/MojoSet*) it statically recognizes.

Fixing this properly would mean giving the coroutine-body expression
emitter genuine loop-as-expression codegen (effectively re-deriving
`_lower_comprehension`'s statement-emission logic inside the very different
"single C++ function body, values only" model `_cpp_expr` uses) — this is
a materially new codegen capability, not a local bugfix, and squarely the
kind of "large speculative feature project" this round's instructions say
not to attempt. Left untouched; no code change. Because the whole module
still refuses to compile (any one ineligible generator is enough),
`iter_decls`'s previously-identified dynamic-callee `**kwargs` blocker is
now moot until/unless these other two surface first — genuinely structural,
same conclusion as before, just via different trigger sites. Doc stays
open; no regression, no fix.

## Status (re-verified 2026-08-23)

Re-ran against current master tip (`fix/c-analyzer` fast-forwarded to
`626f3f0`, which absorbs all sibling fixes through today). Still fails,
with the EXACT same sole remaining blocker the 2026-08-14 update below
documented: `iter_decls`'s `parse_files(filenames, **kwargs)` call — a
`**kwargs` spread forwarded to a DYNAMIC (parameter-valued) callee — is
honestly refused by the coroutine-body emitter:

```
[gimple_codegen] generator 'iter_decls' not eligible for C++ coroutine
path, falling back to honest refusal: a `*`/`**`-unpack call argument is
not supported in a compiled generator/coroutine body
Error building: cannot compile module: function(s) iter_decls (generator
function(s), contain a `yield`/`yield from`) — ...
```

(MOJO_DEBUG shows the identical refusal on passes 2–4 of the retry loop,
then the final whole-module refusal naming only `iter_decls`.) Nothing
regressed and nothing new surfaced: the static-callee narrow case fixed
below still holds, and the dynamic-callee case remains genuinely
structural (a dynamically-obtained callable's real signature isn't known
at compile time in this codegen's model). Still out of scope; no code
change — doc re-verified only.

## Status (updated 2026-08-14)

Still fails to compile as a whole module, but two of the module's four
generators (`analyze_decls`, `check_all`) and the `**kwargs`-forwarding
shape of a third (`iter_analysis_results`) have since been fixed —
tracked separately below. The file's remaining blocker is now narrower
and genuinely structural (dynamic-callee `**kwargs` forwarding inside
`iter_decls`), not the "gap padded with static defaults" miscompile risk
this doc previously investigated.

### Fixed: `**kwargs` forwarded to a statically-known callee inside a
### compiled generator/coroutine body (real runtime dict lookup, not a
### static-default guess)

`gimple_codegen.py`'s coroutine-body expression emitter (`_cpp_expr`'s
`CallExpr` handling, ~line 24170) used to refuse ANY call inside a
compiled generator/coroutine body whose arguments included a `*`/`**`
spread — including the narrow, provably-safe case of `f(pos...,
**kwargs_var)` where `f` is a statically-known local free function (not
a dynamically-obtained callee). An earlier attempt at supporting this
narrow case (never merged — reverted before landing) filled the "gap"
between the given positional args and `f`'s `**kwargs` slot with `f`'s
STATIC DEFAULT VALUES, ignoring what the caller's kwargs dict actually
contains at runtime: `target(i, **kwargs)` with `kwargs = {'b': 5}`
would have silently computed `b=100` (the hardcoded default) instead of
the real override `b=5` — a WORKING WRONG ANSWER, strictly worse than
refusing to compile.

Fixed properly this time (`GimpleGen._cpp_try_kwargs_forward_call`,
gimple_codegen.py): each "gap" parameter is now resolved with a REAL
runtime lookup against a COPY of the caller's kwargs dict
(`mojo_dict_contains` + `mojo_dict_pop_int`, falling back to the static
default only when the key is genuinely absent at runtime), and the
copy's unconsumed remainder is forwarded into the callee's own
`**kwargs` parameter. The dict is copied — never mutated in place —
because the spread variable is commonly reused across a caller's own
loop iterations (this bug's own repro: `while i < n: yield target(i,
**kwargs)`; popping straight from the shared dict on iteration 1 would
silently lose the override for iterations 2/3).

Only fires when it can PROVE the shape is exactly this (every gap
parameter is a plain `int64_t`-typed, in-order, defaulted parameter with
no real `*args` in between, and the callee is a statically-known
ordinary free function — never a generator/async function, which has no
directly-callable C symbol, and never a dynamically-obtained callable).
Returns `None` (never guesses) for anything else, falling through to the
pre-existing honest refusal unchanged.

A closely related, independent bug was found and fixed in the same
session: the ORDINARY (non-coroutine-body) call path that constructs a
compiled generator from a literal-keyword-argument call site (`gen_forward(3,
b=5)`, `_lower_call`'s `fname_raw in self._generator_api` branch, ~line
14330) padded a callee generator's `**kwargs` C-signature slot the same
unsafe way `_func_kwargs_slot`'s own docstring already documents for
ordinary (non-generator) functions: it popped the next literal keyword
argument's raw lowered VALUE straight into whichever positional slot
came next, with no awareness that one particular slot is a `MojoDict *`
— emitting `_t4 = (MojoDict *)_t3` (an integer reinterpreted as a dict
pointer), which segfaults the instant the generator body reads its own
`**kwargs`. This blocked the bug's own repro's *outer* `gen_forward(3,
b=5)` call even after the coroutine-body fix above, since Python's
top-level `for v in gen_forward(3, b=5):` hits this exact call site.
Now packs into a real `MojoDict *` via the same `_pack_kwargs_dict` the
ordinary path already uses, mirroring rather than duplicating that
established, correct logic.

**Verified against the exact repro this doc originally specified**
(`target`/`gen_forward`, `b` overridden via `**kwargs`) — the interpreter
(`python3 fire.py run`) and the compiled path (`python3 fire.py build ...
&& <out>`) now both print `205`, `206`, `207` (not `300`, `301`, `302`,
the wrong values a static-default guess would produce). Also verified
the no-override case (`gen_forward(3)`, no `b=`) still gets the real
defaults, `300`/`301`/`302`, on both paths.

Also verified the fix degrades safely (honest refusal, not a miscompile)
for two adjacent shapes it deliberately does NOT attempt: `**kwargs`
forwarded into a callee that is ITSELF a compiled generator (`g = inner(n,
**kwargs)` inside another generator body), and a `for x in
subgen(**kwargs):` sub-generator-delegation call site (a separate,
pre-existing gap in a different piece of codegen entirely, untouched by
this fix) — both still refuse cleanly with no bad C++ ever emitted.

Full 5-part quality gate run clean: `test_gimple.py` 247/247,
`test_module_cache.py` 76/76, `make check-selfhost` clean (an early
attempt at this fix used a nested-tuple-unpack `for` loop shape gcc's
`-fgimple` self-host compile of `gimple_codegen.py` itself couldn't
lower — caught by this exact gate step, per CLAUDE.md's warning, and
rewritten to a plain index loop), a from-scratch stdlib dylib rebuild
with 0 `skip <module>:` lines, and `compile_stdlib.py` (no `-j`) 664/664
with 0 unexpected failures.

### Still failing: `iter_decls`'s `**kwargs` forwarded to a DYNAMIC
### (parameter-valued) callee — genuinely structural, not attempted

```python
def iter_decls(filenames, *,
               kinds=None,
               parse_files=_parse_files,
               **kwargs
               ):
    ...
    parsed = parse_files(filenames, **kwargs)
```

`parse_files` here is a PARAMETER — a callable VALUE the caller may
override at runtime (`parse_files=_parse_files` is only its default) —
not a statically-known local free function. There is no way to know at
compile time which real function's parameter names/defaults `**kwargs`
would need to be resolved against, so the fix above correctly and
deliberately refuses this shape (`_cpp_try_kwargs_forward_call` requires
`fname_raw in self.func_param_types`, which only registers real
`FunctionDef`s, not parameter names). This is the same fundamental
limitation the ORIGINAL 2026-08-06/09 investigations of this file
flagged for codecs.py's analogous `getincrementalencoder(encoding)(errors,
**kwargs)` shape — a dynamically-obtained callee's real signature simply
isn't known at compile time in this codegen's model. Genuinely
structural; not attempted.

```
[gimple_codegen] generator 'iter_decls' not eligible for C++ coroutine
path, falling back to honest refusal: a `*`/`**`-unpack call argument is
not supported in a compiled generator/coroutine body
Error building: cannot compile module: function(s) iter_decls (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event loop
/ suspend-resume codegen for async functions, yet, so these cannot be
represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

Because the whole MODULE still refuses to compile (one ineligible
generator is enough), `iter_analysis_results`'s own `**kwargs`-forwarding
call site (`decls = iter_decls(filenames, **kwargs)`, forwarding into
`iter_decls` — itself a generator, not an ordinary function) never
actually gets exercised end-to-end in this file. Confirmed via a
dedicated minimal repro (`g = inner(n, **kwargs)` where `inner` is
itself a compiled generator) that this shape correctly and safely
refuses on its own (`_cpp_try_kwargs_forward_call` explicitly excludes
any callee in `self._generator_api`/`self._async_api`) rather than
mis-compiling — so fixing `iter_decls`'s dynamic-callee case above is
the sole remaining blocker for this specific file.

(Separately, `iter_analysis_results`'s own Mojo/Python source has a
pre-existing typo unrelated to this codegen — its parameter is spelled
`filenmes` but its body reads `filenames` — a real `NameError` in actual
CPython too were this function ever called; not this codegen's concern.)
