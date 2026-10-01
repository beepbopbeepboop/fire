# COMPILE_FAIL (hard): Tools/c-analyzer/c_common/fsutil.py

**State: PARTIAL, and better than the entry below it, but the file still
does not build.** The blocker this doc's previous pass identified as "the
real blocker" — **calling a keyword-only callable-valued parameter** — is
FIXED for the same-module case: two of the file's four such generators
(`walk_tree`, `iter_files_by_suffix`) now compile and run, and the
underlying representation bug underneath them (a callable-valued parameter
defaulting to a NULL function pointer, so calling it SIGSEGVed) is fixed
everywhere, including in an ordinary `def`. The file remains unbuildable
for three reasons that are NOT this bug: the two remaining
same-import-spelling generators (`_walk_tree`, `glob_tree`), whose
callable defaults name an **imported** module's function and so are still
refused; `iter_files`'s variadic lambda; and `process_filenames`'s
`Exception(...)`-as-a-value.

## Status (2026-09-29 — the kw-only-callable blocker is fixed for the same-module case; the file still does not build)

Re-derived against the CURRENT tree with the real file at
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py`, with
CPython alongside for every probe. Six generators refused before; **four
now, and the two that cleared are precisely the two the previous entry
called the blocker.**

```
$ MOJO_DEBUG=1 python3 fire.py build -o fsutil fsutil.py
Error building: cannot compile module: function(s) _walk_tree, glob_tree,
iter_files, process_filenames ...
Unsupported shape(s):
  _walk_tree:           unsupported for-loop iterable type: CallExpr
  glob_tree:            unsupported for-loop iterable type: CallExpr
  iter_files:           a `lambda` with more than one parameter, a
                        `*`/`**`-forwarding parameter, or a parameter default
  process_filenames:    call to unresolved callee 'Exception(...)'
```

Before this change the same command listed SIX — the two above plus
`iter_files_by_suffix: call to unresolved callee '_iter_files(...)'` and
`walk_tree: unsupported for-loop iterable type: CallExpr`. Those two are
the ones this change fixed.

### Corpus impact — measured, not assumed

Because this change is deliberately NOT behaviour-preserving, the usual
"byte-identical C" bar does not apply; but the *silent*-regression bar
does, so: `python3 fire.py --dump-full fire_compiler.py` (the whole
compiler closure, ~1.2 M lines of generated C, run from one directory
before and after) has an **unchanged generator/refusal profile** —
`__mgco_` (A3 stack-switch) 185/185, `_mojogen_` (C++20 path) 15/15,
`mojo_unsupported_iter` 124/124. Nothing in the corpus moved between
"compiled", "refused", and "zero-iterated". The rest of that diff is the
two new `GimpleGen` fields, the new `_default_expr_to_pair` parameter, and
temp renumbering inside the compiler's own functions.

### What was actually wrong

The previous entry's diagnosis was right about the shape and wrong about
where the refusal came from, in a way that matters: it read
`stackswitch refuses at 'kwonly params (v0)'` as the blocker. That gate
was real, but it was not the *shape* being refused — it was a blanket
refusal of ANY generator with a keyword-only parameter, so it hid the
real one. Underneath it were two separate defects, both of which turned a
callable-valued parameter into a NULL pointer:

1. **A callable-valued parameter default lowered to `0`.**
   `calls_shared._default_expr_to_pair` ends in `return ('int', '0')`
   after handling literals and `None`/`True`/`False`. A default that *is*
   a function — `walk=_walk_tree` — therefore padded address 0 into the
   omitted argument, and the body called it. Measured on the ordinary
   (non-generator) path, which is the case neither this doc nor its
   sibling mentioned:

   ```
   $ <p2b: def leaf(root): return root + "/a"
           def apply_it(x, *, f=leaf): return f(x)
           print(apply_it("q")); main()>
   CPython   q/a                      # correct
   compiled  Segmentation fault: 11   # exit 139, nothing on stdout
   ```

2. **A generator used as a bare value lowered to `0`.**
   `_lower_IdentExpr`'s "C function name used as a value" arm tests
   `name in gen.func_return_types`, and for a generator that dict holds
   only `__mgco_<g>_start`/`_resume`/`_value`/`_destroy` — never the
   generator's own name. So `consume("/r", leaf)` passed 0 and the callee
   called address 0.

Both are now answered by one place, `calls_shared._callable_value_symbol`
("what C symbol does a function used as a value mean"), which emits the
real address through the `_funcptr_<sym>` static this codegen already uses
for every other function-as-a-value site — `module_gen`'s `_funcptr_
target` redirects a generator's bare csym to `<base>_start`, which is
exactly right, since calling a generator FUNCTION is what constructs the
object.

### The two backend changes that clear `walk_tree` and `iter_files_by_suffix`

* **The kwonly eligibility gate** (`mojo/middle/coro.py`'s `_eligible`)
  was `if fn.kwonly: return False, 'kwonly params (v0)'`. A keyword-only
  parameter is just a parameter no call site may fill positionally, and
  the stack-switch lowering already carries every one of them (`_lower_one`
  builds `<base>_start` over `fn.params`, which the parser records
  keyword-only names in, with `meta['defaults']` from the same
  `param_defaults` dict the call-site padding reads). The gate is now the
  question that actually decides anything: **is every keyword-only
  default faithfully lowerable to a C value?** (`_unrepresentable_kwonly` /
  `_default_is_faithful_literal`.) It is deliberately stricter than
  `_default_expr_to_pair`, which pads anything it cannot represent with a
  typed `0` — admitting a list literal here would trade today's
  whole-module fallback (always correct) for a compiled NULL container
  pointer.

* **Driving the result.** `for f in walk(root):` and
  `yield from walk(root)` used to reach the ordinary path's
  `mojo_unsupported_iter` zero-iteration stub, because nothing knew what
  `walk(root)` returns. `_lower_one` now records
  `callable_param_generators` on the generator's meta (the lowered
  `__mgco_<g>_body` has moved every source parameter into a
  `var p = __mojo_gen_arg(...)` local and so carries none of the source's
  `param_defaults`, which is why the information has to travel on the
  meta), `register`'s second pass resolves those names against
  `_generator_api` AFTER every generator is registered — so a callee
  declared later in the module still works — and `gen_func` hands the
  result to `_lower_fnptr_call_value`, which types the call result as
  `MojoGenerator *` and records the api on the temp exactly as a direct
  generator call does. The loop target's and the `yield from`'s value kind
  come from the same default (`_sibling_gen_kind` / `_delegated` /
  `_delegated_yield_kind`, each given the enclosing `fn`), so the yield
  slot stops defaulting to `int64_t` and printing a string as its own
  pointer.

### Verified — CPython's text, not just "no crash"

| probe | CPython | before | after |
|---|---|---|---|
| `def leaf(root): yield root+"/a"; yield root+"/b"` / `def consume(root, *, walk=leaf): for f in walk(root): yield f` | `/r/a`, `/r/b` | SIGSEGV | `/r/a`, `/r/b` |
| same, `yield from walk(root)` | `/r/a`, `/r/b` | SIGSEGV | `/r/a`, `/r/b` |
| same, caller overrides `walk=other` | `/r/a`, `/r/X` | SIGSEGV | `/r/a`, `/r/X` |
| positional-with-default `walk=leaf` (not keyword-only) | `/r/a` | SIGSEGV | `/r/a` |
| ordinary path: `def apply_it(x, *, f=twice): return f(x)` | `6 8 10 12` | SIGSEGV | `6 8 10 12` |
| ordinary path: `def via_param(x, f): return f(x)`, called `via_param(7, twice)` | `14` | SIGSEGV | `14` |

Regression tests: `run_callable_param_tests` in
`test_gimple_generator_runner.py` (6 cases, incl. the two A3-gate NO
answers and one positive) and `gimple_callable_valued_parameter_default` /
`gimple_function_passed_as_argument` in `test_gimple_runner.py`. Both
files ARE in the `check`/`gate` bucket (`gimplegenerators` /
`gimplerunner`) — `bugs/hard/README.md`'s note that they run in no bucket
is stale for these two; see the report.

### What is NOT fixed, precisely

1. **`_walk_tree(root, *, _walk=os.walk)` and
   `glob_tree(root, *, suffix=None, _glob=glob.iglob)`** — still refused
   `unsupported for-loop iterable type: CallExpr`. Same mechanism, one
   step further out: the default is a `module.attr` reference, and A3's
   `_eligible` runs in `lower()`, before any `GimpleGen` exists, so it
   cannot know whether the imported function will be resolved by the time
   the default is padded. It WILL be under `do_imports=True` when the
   module's own source is translated, and will NOT under `do_imports=False`
   (where imports are deliberately not inlined). Guessing "resolved"
   would compile the generator and then pad NULL — trading a refusal for a
   crash — so the gate says no. **Exact next step:** either make the
   decision after the closure is known (gen_module's per-generator
   eligibility loop at `module_gen.py`'s `_generator_quick_eligible` runs
   after imports are compiled and is the natural home), or make
   `_lower_one` able to un-lower. The second of the two is cheap and
   worth checking first.
2. **The NULL-pointer crash behind (1) still exists on the ordinary
   path.** `def probe(x, *, g=os.walk): return g(x)` pads 0 and takes
   SIGSEGV — `os` is an imported-symbol marker but its `walk` is never in
   `func_return_types` at all (measured: zero entries containing
   `"walk"`). Filed separately, with the repro and the two design options:
   `bugs/CODEGEN_unresolved_imported_callable_default_null_pointer.md`.
   This is the exact case `_walk_tree`/`glob_tree` would hit if their
   eligibility gate were simply relaxed, which is why it is not.
3. **`iter_files`' `lambda *a, **k: _walk(*a, walk=_files, **k)`** — the
   variadic forwarding lambda. Correctly still refused, correctly still
   another worker's claim (`CODEGEN_generator_lambda_expr_unsupported.md`).
4. **`process_filenames`' `onempty = Exception('no filenames provided')`** —
   a call to an exception CONSTRUCTOR used as a value. A distinct shape,
   unrelated to callable-valued parameters.

`gen_module`'s whole-module escalation means the file stays unbuildable
until all four clear. Items 3 and 4 are outside this bug.

### Residue in the fix itself, stated rather than hidden

The result of `walk(root)` is typed from the parameter's DECLARED DEFAULT
— that is the only callee identity a signature can carry. A caller that
overrides the parameter with a differently-typed generator would get the
default's `value_ctype`. The override case is pinned by a test (it runs
and produces each callee's own values), and this is the same residual
`fn_returns_generator` already carries for a first-class generator value
and the same one the existing `_generator_var_api` has for a reassigned
local — a default names exactly ONE callable where a returned value can
come from any of several. It is smaller than either, not absent.

Also not fixed, and adjacent: **a call through a callable-valued
parameter still returns the `int64_t` default type**, so
`def apply_it(x, *, f=twice): return f(x)` called with a string argument
prints the returned pointer's decimal rather than the string. That is a
separate inference gap (the callee's return type is genuinely unknown at
the call site), it predates this change, and it was previously masked by
the SIGSEGV. Left alone deliberately: narrowing the returned box to the
default's return C type would turn a wrong *number* into a wrong
*pointer* on an override, which is the worse of the two.


---

## History (superseded entries, kept for the per-shape table and the `set()`/tuple-yield confirmations)

## Status (2026-09-26 second pass — built the REAL file; the "5 of 6 fixed" conclusion is withdrawn)

The entry immediately below said fsutil.py was "no longer present in this
checkout" and reconstructed each of the six recorded refusal shapes as a
minimal Mojo program. That was the error: **the real file is on disk**, at
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py`, and
building it gives a completely different picture. Every reconstructed shape
below differs from the real one by dropping the same thing — a
**keyword-only parameter that holds the callee**.

```
$ cd /tmp/fx4 && MOJO_DEBUG=1 python3 .../fire.py build -o fsutil \
    /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py
Error building: cannot compile module: function(s) _walk_tree, glob_tree,
iter_files, iter_files_by_suffix, process_filenames, walk_tree ...
Unsupported shape(s):
  _walk_tree:           unsupported for-loop iterable type: CallExpr
  glob_tree:            unsupported for-loop iterable type: CallExpr
  iter_files:           a `lambda` with more than one parameter, a
                        `*`/`**`-forwarding parameter, or a parameter default
  iter_files_by_suffix: call to unresolved callee '_iter_files(...)'
  process_filenames:    call to unresolved callee 'Exception(...)'
  walk_tree:            unsupported for-loop iterable type: CallExpr
```

### Per-shape, against the real file

| # | generator | the real shape in the source | the real blocker | the entry below claimed |
|---|---|---|---|---|
| 1–3 | `_walk_tree` / `walk_tree` / `glob_tree` | `for … in _walk(root)` / `walk(root)` / `_glob(…)`, where each callee is a **kw-only parameter** defaulting to the function (`_walk=os.walk`, `walk=walk_tree`, `_glob=glob.iglob`) | stackswitch refuses at `kwonly params (v0)`, so the cpp fallback reports the derived `unsupported for-loop iterable type: CallExpr` | "**WORKS** — `for x in <a generator call>()` lowers and runs" |
| 4 | `iter_files` | `get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))` | the variadic lambda — **correct as recorded** | "still open" ✓ |
| 5 | `iter_files_by_suffix` | `yield from _iter_files(root, suffix, relparent)`, `_iter_files` a **kw-only parameter** | `call to unresolved callee '_iter_files(...)'` — a hard refusal | "compiles and runs, but **produces a wrong value**" |
| 6 | `process_filenames` | `onempty = Exception('no filenames provided')` inside the body | `call to unresolved callee 'Exception(...)'` | "`set(...)` + tuple-yield — **WORKS**" |

The entry below's shape-1–3 reconstruction was `for f in leaf():` with `leaf` a
plain module-level generator. That does compile and run correctly (verified) —
it is simply not fsutil's shape. With the kw-only indirection it is refused:

```python
def consume(root, *, walk=leaf):
    for f in walk(root):   # CPython: TypeError only because leaf takes 0 args;
        yield f             # the compiled path refuses the CALL, whatever it resolves to
```
```
Unsupported shape(s): consume: unsupported for-loop iterable type: CallExpr
```

Isolated further: a generator with a kw-only parameter that is **not** called
compiles and runs fine (`def consume(root, *, extra=None): … else: yield
"without"` → `without`). So the blocker is not "has kw-only params" — it is
**invoking a kw-only parameter as a callee**. A callable-valued higher-order
parameter has no representation in the compiled generator body model, which is
the same missing piece `CODEGEN_generator_lambda_expr_unsupported.md` names
(signature-carrying callable values), reached from a different direction.

### Shape 5's mapping onto the `value_ctype` bug is WITHDRAWN

The entry below split Shape 5 out into
`CODEGEN_generator_consuming_generator_value_ctype.md` as "the real cause
behind that doc's `iter_files_by_suffix` entry". That general bug was real and
is now **fixed** (its doc is deleted; see `_sibling_gen_kind` in
`mojo/middle/coro.py`), but it is **not** what `iter_files_by_suffix` was
exhibiting: `_iter_files` is refused outright, so no value is ever produced and
no `value_ctype` is ever consumed. The two docs were never the same bug, and
fsutil is not a witness to that one.

### What IS confirmed fixed

Re-tested 2026-09-26 as standalone minimal programs (the real file cannot
build, so these were isolated):

- `set(<generator expression>)` — **works**: `set(filt([1, 2]))` → `2`. So the `set(...)` half of Shape 6 was indeed already fixed upstream.
- A 4-tuple `yield filename, relfile, check, solo` — **works**: unpacks per slot correctly. So the tuple-yield half of Shape 6 is fixed too.
- One residue there, and it is NOT this file's: a `bool` in a tuple-yield slot read back as `1`/`0`, not `True`/`False` (`x True False` → `x 1 0`). That was `CODEGEN_generator_value_slot_loses_bool.md`; it was **fixed 2026-09-27** (the generator value-slot KIND lattice gained a `'b'`/`_Bool` entry, so a bool-yielding generator's scalar and tuple slots are `_Bool` and `print` renders `True`/`False`), so this residue is gone. `fsutil`'s `check` is a bool, so it would have hit it — but only after the kw-only blocker is cleared anyway.

### Not attempted

Fixing the kw-only-callable-parameter blocker is the same feature-sized
callable-value representation the sibling lambda doc declines, and it would
unblock nothing on its own: `iter_files` (variadic lambda), `process_filenames`
(`Exception(...)` — a call to an exception *constructor* used as a value, a
distinct shape) and the other two remain regardless. Per `gen_module`'s
whole-module escalation, this file stays unbuildable until all are addressed.

## Status (2026-09-26 audit — SUPERSEDED by the entry above, which built the real file and got a different answer; kept for the per-shape table and the `set()`/tuple-yield confirmations, NOT for its "5 of 6 fixed" conclusion)

`Tools/c-aalyzer/c_common/fsutil.py` is **no longer present in this
checkout**, so this pass could not build the real file. Instead each of the
six refusal shapes the 2026-08-24 entry catalogued was reconstructed as a
minimal Mojo program and tested directly. Five of the six now work — they
were fixed by the A3 stack-switch generator work that landed after this doc
was written, not by anything here.

| # | recorded refusal | now |
|---|---|---|
| 1–3 | `_walk_tree` / `glob_tree` / `walk_tree`: `unsupported for-loop iterable type: CallExpr` | **WORKS** — `for x in <a generator call>()` lowers and runs |
| 4 | `iter_files`: the `lambda *a, **k: _walk(*a, walk=_files, **k)` gap | still open, but now correctly scoped — see `CODEGEN_generator_lambda_expr_unsupported.md`'s 2026-09-26 entry, which found the real defect underneath it (ANY capturing lambda silently returned 0) and fixed the dominant shape |
| 5 | `iter_files_by_suffix`: `call to unresolved callee '_iter_files(...)'` | compiles and runs, but **produces a wrong value** — see below |
| 6 | `process_filenames`: `call to unresolved callee 'set(...)'` + tuple-yield | **WORKS** — mixed-arity tuple yields (`yield "store", ("name",)` / `yield "rel", (1, 2, 3)`) unpack correctly, giving `store 2` / `rel 6` |

### Shape 5: RETRACTED — the general `value_ctype` bug was real, but fsutil is not a witness to it

> **Superseded 2026-09-26.** The general bug described below
> (a generator that consumes a sibling generator typed the callee's yielded
> value as the `int64_t` default) was real, and is now **FIXED** — its doc is
> deleted, and the mechanism and regression tests live in the source (see
> `_sibling_gen_kind` in `mojo/middle/coro.py`). But the mapping asserted here
> is **wrong**: `iter_files_by_suffix` does not reach that code. Its
> `_iter_files` is a kw-only parameter, so the generator is refused outright and
> never produces a value at all. See the current entry at the top of this file.

The `iter_files_by_suffix` entry ("call to unresolved callee
'_iter_files(...)'") was recorded as a **silent miscompile**, not a compile
failure, with a general cause: a generator that consumes a sibling generator
types the callee's yielded value as the `int64_t` default, so a yielded string
comes out as a pointer's bit pattern. That cause is real and general, and it was
tracked separately. What is wrong is only the claim that this file exhibits it.

`fsutil` looked like a natural witness — those generators yield **file paths**,
so a string-typed value collapsed to `int64_t` would read exactly like a
dangling pointer — but the reconstruction that suggested the mapping also
dropped the kw-only indirection, so it never had the shape the mapping requires.

## Status (re-verified 2026-08-26, branch fix/rest-remainder15 — unchanged)

Source-confirmed `map()`/`filter()` have no coroutine-body lowering
(`gimple_cpp_core.py`'s CallExpr dispatch, ~line 2632-2660, own comment
explicitly lists them as unhandled) — relevant to `iter_files`'s
`get_files(...)` polymorphic-callable-value gap indirectly, and the
`_CPP_CALLABLE_CTYPE*` lambda categories are still fixed at 0-arg/
1-plain-arg only (re-confirmed against current tree, `a913ab8` — see
this session's `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`
re-verification for the same source read). Nothing in this campaign's
recent landings (generator-consumption fixed-point retry, defaults-
aware padding, int()/float() coroutine builtins, isinstance() fix,
itertools.zip_longest) touches variadic callable-value representation
or the six independently-refused module-level generators this file's
2026-08-24 entry catalogues. Confirmed unchanged, not attempted. No
code change; full rebuild not re-run this pass (source-level
confirmation of the exact same unmet preconditions is conclusive given
the 2026-08-24 entry's already-exhaustive fresh investigation one day
prior).

## Status (updated 2026-08-24, branch fix/opencode-fsutil — gap 1 investigated DEEPER than ever, confirmed feature-sized AND insufficient on its own; NOT attempted; one adjacent silent-emission hazard discovered)

Attempted per session task: extend generator-body LambdaExpr support to
`iter_files`'s parameterized shape (`lambda *a, **k: _walk(*a,
walk=_files, **k)`). Investigated end-to-end with minimal synthetic
probe files (each shape isolated, built via `MOJO_DEBUG=1 fire.py
build`). No code change; conclusions below.

**First, a correction of this doc's recorded picture**: the module does
not fail on ONE generator. The whole-module escalation lists SIX
independently-refused module-level generators (re-confirmed on branch
tip `2d0823b`):
```
_walk_tree           unsupported for-loop iterable type: CallExpr
glob_tree            unsupported for-loop iterable type: CallExpr
walk_tree            unsupported for-loop iterable type: CallExpr
iter_files           the lambda (gap 1, message below)
iter_files_by_suffix call to unresolved callee '_iter_files(...)' (param-aliased same-module generator)
process_filenames    call to unresolved callee 'set(...)' (+ tuple-yield gap 2 behind it)
```
Since `gen_module` hard-fails when ANY module-level generator is
refused, `fire.py build` cannot exit 0 for this file until ALL SIX
clear. Fixing gap 1 alone therefore cannot turn this build green under
any circumstances.

**Gap-1-specific findings** (probe files, all verified):

1. The recursive `yield from iter_files(..., get_files=get_files, ...)`
   (lines 275-277) is NOT a blocker — a synthetic probe of exactly that
   shape (self-recursive yield-from WITH kwargs forwarding through a
   kw-default param) compiles clean, exit 0 (task #138's machinery
   covers it).
2. The lambda refusal fires first in `iter_files`'s body, but it is
   only the FIRST of several unsupported shapes IN THAT ONE BODY:
   - `filenames = get_files(root)` / `get_files(root, suffix=suffix)`:
     calling a function-valued LOCAL is refused ("unresolved callee
     'get_files(...)'") even with NO lambda involved — a probe with
     plain `get_files = walk_tree` (module generator assigned as a
     value) is refused identically. The existing "declared
     callable-value local" category only arises from lambda/bound-method
     assignments (the `_CPP_CALLABLE_CTYPE*` types); assigning a bare
     module function/generator as a value does not create one, and no
     kwargs-capable call-site machinery exists for any such local.
   - `for filename in filenames:` where `filenames` holds a call
     result: see item 4 below — worse than a refusal.
3. Why no NARROW fix for the lambda exists for THIS occurrence: any
   compile-time specialization/beta-reduction of the forwarding lambda
   requires knowing exactly what the callable local holds. But
   `get_files` is POLYMORPHICALLY assigned across branches — it arrives
   as a keyword-only PARAMETER (default `os.walk`, or an arbitrary
   caller-provided callable), then is reassigned to `_glob` OR the
   lambda depending on the `if get_files in (glob.glob, glob.iglob,
   glob_tree):` test. A general mechanism instead needs a callable-value
   representation carrying a real signature that tolerates
   positional+keyword forwarding — i.e. runtime args/kwargs packing and
   named-slot binding (note `std::function` cannot even hold a variadic
   signature) — plus new call-site lowering keyed on that signature.
   That is new shared call-argument/lowering machinery, the exact class
   of change this project's history (the "_tuplegetter incidents",
   MEMORY.md's compiled-generator-codegen-project notes) warns has
   caused broad regressions when attempted narrowly. Feature-sized, per
   this doc's own prior assessments — now with concrete evidence.
4. Adjacent hazard DISCOVERED while probing (not previously catalogued,
   single synthetic occurrence so far — below the "recurs >= 2 times"
   bar for its own doc, recorded here): a generator body holding a
   generator CALL RESULT in a local and iterating it —
   ```python
   filenames = gen(root)
   for x in filenames:
       yield x
   ```
   PASSES the eligibility pre-check (no `_UnsupportedGeneratorShape`)
   and emits broken C++: `filenames = gen_<hash>(root);` where the
   generated start function returns void → real g++ error "void value
   not ignored as it ought to be". I.e. this shape ESCAPES the
   honest-refusal convention as a bad emission rather than being
   refused. Not reachable in fsutil.py today (every path to it is
   blocked by earlier refusals), but it is the same family as the
   segfault class fixed in CODEGEN_generator_lambda_expr_unsupported.md's
   2026-08-21 note and deserves attention if any future fix exposes
   this region. (Contrast: iterating a DIRECT param-indirect call
   result — `for parent, _, names in _walk(root):` — IS honestly
   refused, "unsupported for-loop iterable type: CallExpr", which is
   the shared blocker of `_walk_tree`/`walk_tree`/`glob_tree`.)

Net: gap 1 remains OPEN — root-cause assessment unchanged (feature-
sized), now corroborated by isolated-shape evidence, AND proven
insufficient to close even if implemented (items 2 and the six-generator
list stand between it and any green build). Gap 2 (tuple-valued yield)
untouched, additionally masked behind `process_filenames`'s separate
`set(<comprehension>)` refusal. Tree sanity re-confirmed post-investigation
(no source changes): `test_gimple.py` 252/252, `test_module_cache.py`
76/76.

## Status (re-verified 2026-08-23, unchanged)

Re-ran against current master tip (`626f3f0`): identical outcome to the
2026-08-20 update below. `iter_files` is still refused for exactly the
same reason — its `get_files = (lambda *a, **k: _walk(*a, walk=_files,
**k))` is a parameterized `*args`/`**kwargs`-forwarding lambda, which
the (real, but deliberately narrow) zero-arg/single-plain-param lambda
support does not attempt:

```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: a `lambda` with more than one
parameter, a `*`/`**`-forwarding parameter, or a parameter default is
not supported as a value inside a compiled generator/coroutine body
(only a zero-argument lambda or a single plain-parameter lambda, e.g.
`lambda: None` / `lambda x: x`, is supported)
Error building: cannot compile module: function(s) iter_files ...
```

The whole-module pre-check aborts at `iter_files`, so
`process_filenames`'s 4-tuple yield (second documented blocker) is not
re-flagged this run — presumably still present behind it, unverified.
Both gaps remain structural per the analysis below; no code change —
doc re-verified only.

## Status (updated 2026-08-20, LambdaExpr blocker narrowed, NOT closed for this file)

`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` has been fixed
for a ZERO-ARGUMENT `lambda` literal / a bound-method-as-VALUE read off
a struct whose real methods are statically known (see that doc's own
2026-08-20 update for the mechanism — a `std::function<int64_t()>`
declared-type category, a native-capturing-C++-lambda `LambdaExpr`
case, and a bound-method case reusing the struct's already-known
mangled method symbol). `iter_files`'s own occurrence does NOT qualify:
```python
get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
```
is a lambda WITH parameters (`*a, **k`), which the fix deliberately
does not attempt — its one declared-type category has a fixed
zero-argument signature (this project's real corpus, both confirmed
`CODEGEN_generator_lambda_expr_unsupported.md` occurrences, only ever
needed 0-arg callables; a `*args`/`**kwargs`-forwarding lambda would
also need the separate, deliberately-unfixed `bugs/hard/CODEGEN_args_
kwargs_signature_assumed_forwarding_only.md` gap even if a parameterized
lambda itself were supported). Re-verified directly via `MOJO_DEBUG=1` +
`compile_to_gimple_with_cpp`: `iter_files` is still refused, now with a
more precise message confirming exactly this:
```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: a `lambda` with parameters is not
supported as a value inside a compiled generator/coroutine body (only a
zero-argument lambda, e.g. `lambda: None`, is supported)
```
`process_filenames`'s separate tuple-valued-yield blocker (below) is
unaffected/unchanged. Net: this file remains blocked by the same two
structural gaps as the 2026-08-09 update — LambdaExpr support is now
real for one shape but not the shape THIS file needs, and tuple-valued
yield is untouched.

## Status (updated 2026-08-09, re-verified: TWO blockers now, both known structural gaps)

Re-verified fresh via `MOJO_DEBUG=1 python3 fire.py build`. `iter_files`
still hits the exact same `LambdaExpr`-in-generator-body blocker as the
2026-08-07 finding below (`unsupported expression in generator body:
LambdaExpr`) — unchanged, still tracked at
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`, still not a
narrow fix (see that doc's "feature-sized" writeup).

Additionally, the module-level generator pre-check now also flags a
SECOND generator in this same file, `process_filenames` (line 151):

```
[gimple_codegen] generator 'process_filenames' not eligible for C++
coroutine path, falling back to honest refusal: process_filenames:
every `yield` must carry a value, and all values must agree on one
scalar type (int64_t/double/_Bool)
```

Its body is `yield filename, relfile, check, solo` — a 4-tuple-valued
`yield`. This is a confirmed instance of the OTHER already-known,
already-catalogued structural gap for this session ("Tuple-valued
`yield` in a generator (structural, no fix)" — the compiled generator
coroutine path only supports a single scalar-typed value per `yield`,
not a tuple). Not attempted, per that gap's established structural
classification.

Net effect: this file is blocked by TWO independent, already-
catalogued structural gaps (tuple-valued yield + LambdaExpr-in-
generator-body), neither narrow, neither attempted here. The file will
not compile until BOTH are addressed (a real generator-coroutine
tuple-value-carrying mechanism, and real LambdaExpr support inside a
compiled generator body) — both feature-sized efforts, not one-spot
fixes.

## Status (updated 2026-08-07, LambdaExpr blocker root-caused, feature-sized, doc written)

The `LambdaExpr` blocker noted just below (`get_files = (lambda *a,
**k: _walk(*a, walk=_files, **k))`) has now been root-caused and
folded into a proper hard-bug doc:
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` (2 confirmed
occurrences — this file and `Lib/pickletools.py`'s `_genops`).
Investigated and found to be feature-sized, not a narrow fix — see
that doc's "Why this is feature-sized, not narrow" section. Not
attempted here. This file's `iter_files` remains refused.

## Status (updated 2026-08-07)

**NOT resolved** (task #140), despite the root-cause bug this doc
points to (`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.
md`, task #138) now being FIXED. Confirmed via `MOJO_DEBUG=1`: `iter_
files` is no longer blocked by the arg-forwarding/self-recursion gap —
but this file STILL fails to compile, now hitting a DIFFERENT, genuinely
separate, previously-MASKED blocker in the same function:
```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: unsupported expression in
generator body: LambdaExpr
```
`iter_files`'s own body (line 285 of the real file) has:
```python
get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
```
a lambda expression (with its own `*args`/`**kwargs` forwarding)
assigned to a local — entirely unrelated to yield-from/self-recursion,
and out of this narrow generator-body codegen's scope on its own
merits. This was always there; the arg-forwarding bug just refused
`iter_files` earlier (via the blanket whole-module pre-check) before
ever reaching this line. Not investigated/fixed further — a distinct,
new potential hard-bug candidate (LambdaExpr support inside a compiled
generator body) for a future session, not in scope for task #138's fix.

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py`

Root cause (current): see
`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md` in this
directory (that file has the minimal test case). Summary: `iter_files` is a
generator using a recursive `yield from iter_files(...)` call with
keyword-only parameters; this file hits a blanket "generator not supported"
pre-check and fails to compile before even reaching the C++ coroutine
codegen.

**This is NOT the bug originally reported here.** The original report
(below, preserved for history) was about `create_backup`'s `exc.filename`
attribute access ("request for member 'filename' in something not a
structure or union"). That specific error **no longer reproduces** — the
generator pre-check above now fires first and blocks the whole module
before `create_backup` is ever reached, masking whatever the original
symptom's current status actually is (fixed or still-latent — unconfirmed
either way).

## Current error (2026-08-05, after commit 12ff719)

```
$ python3 fire.py build Tools/c-analyzer/c_common/fsutil.py
Error building: cannot compile module: function(s) iter_files (generator function(s), contain a `yield`/`yield from`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead
```

Exit code: 1 (despite the message claiming a fallback, `fire.py build`
does not actually fall back — no object file is produced).

## Original report (2026-07-xx, superseded — kept for history)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function 'create_backup_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:44:14: error: request for member 'filename' in something not a structure or union
   44 |         return os.path.abspath(filename)
      |              ^~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:47:8: error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast [-Wint-conversion]
   47 |     return _fix_filename(filename, relroot)
      |        ^
```

(Both the reported line and error text as they existed then; the file
compiled far enough to reach `create_backup`/`fix_filename` at that time,
which is no longer the case now that the generator check blocks it
earlier.)
