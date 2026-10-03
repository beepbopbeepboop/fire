# COMPILE_FAIL: Tools/c-analyzer/c_common/scriptutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-02 — items 1 and 2 are FIXED; `iter_marks` compiles. ONE blocker left, and it is item 3

Fresh `python3 fire.py build -o .tmp/out/ca/scriptutil
.tmp/ca/c-analyzer/c_common/scriptutil.py` on `ad7ffd96` (sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`), arm64, ~2 s. The
complete refusal list:

```
_iter_filenames: a call to unresolved callee 'process(...)' is not supported in a
                 compiled generator/coroutine body (not a builtin this emitter
                 supports, a known module-level/imported function, a same-module
                 struct constructor, or a declared callable-value local)
```

**`iter_marks` is gone from the list** — it compiles and runs. So are items
1 and 2 of the entries below, which this entry records as landed rather
than re-asserts:

* **Item 1 (the module-member VALUE read).** `div = os.linesep` beside
  `end = f'{mark}{os.linesep}'` disagreed on the yield slot because the
  read had no type. Fixed in two commits, `12106a4b` and `c260fdc1`:
  `_cpp_module_global_field` reads the constant off the module's OWN
  `_module_globals` field triple (or, for a marker that is never inlined,
  off the new shared `builtin_module_constant` table — `os` and `signal`
  have no field row to read, and the ordinary GIMPLE path's two literal
  dicts for them are now that one table);
  `_cpp_expr_static_ctype` answers the same question for a CONDITION; and
  `_infer_simple_expr_ctype`/`_generator_yield_ctype` take a new
  `module_global_types` hint, seeded per generator unit in all three cpp
  unit emitters. `div` is now a `char *` local and the yields agree.
  Regressions `cpp_coroutine_body_reads_foreign_module_constant`,
  `cpp_coroutine_body_compares_foreign_module_constant` and
  `cpp_coroutine_body_reads_marker_module_constant` in
  `test_gimple_generator_runner.py`, all compiled-vs-CPython.
* **Item 2 (`Exception(...)` as a value).** `onempty =
  Exception('no filenames provided')` is now an emission site plus the
  matching local type (`_cpp_exc_ctor_value`), commit `7374f254`; the
  local still HOLDS the message, which is this model's one exception
  representation and what the ordinary path already produced for the same
  source. Regression `cpp_coroutine_exception_ctor_as_value`.

### The one that is left, and why it is a different kind of work

`_iter_filenames`'s `process(filenames, relroot=relroot)` — `process` is an
unannotated PARAMETER of `_iter_filenames`, so the callee is a value, not a
function. This is the item the entry below calls "a separate capability
(callable-value-local signature discovery), not a tweak", and nothing in
this round changed that assessment.

Three things are needed together, and none is a one-liner:

1. The callee's real signature. This model has exactly two callable-value
   ctypes (`_CPP_CALLABLE_CTYPE`, zero-arg, and
   `_CPP_CALLABLE_CTYPE_1ARG`), and this call passes two arguments, so
   there is no representation to call it through yet. What is missing is
   the discovery itself: `_cpp_declared` carries no return type for a
   callable-valued parameter, and the ordinary path's
   `_PLAIN_CALLSITE_PARAM_KINDS` (`mojo/middle/coro.py`) answers a
   different question — a value KIND for a yield slot, not a C signature.
2. The returned ITERATOR's element type, for the same reason the
   `for`-over-a-callable refusal is (see
   `bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` — the same
   blocker one function over, where the refusal now NAMES
   `_get_reader(...)` instead of reporting an undifferentiated
   `CallExpr`).
3. Whatever `process` is expected to return in each of the four shapes
   `_iter_filenames` then distinguishes (`isinstance(peeked, str)` /
   `len(peeked) == 4`), which needs element access as well.

Also still open in this file, unchanged by this round and untouched by it:
`iter_files`' lambda-with-`*a/**k` refusal and `_iter_filenames`' five
further shapes after this one (`yield from
fsutil.process_filenames(...)`, `iterutil.peek_and_iter`,
`iterutil.iter_many`, a lambda inside a tuple yield, `yield from items` on
a non-generator local). Note `iterutil` itself does not compile — its
`next(...)` on a plain identifier has no lowering — and this file's whole
closure depends on it.

## Status 2026-10-01 — THREE blockers are now TWO; `track_progress_compact` has cleared, and `iter_marks`' real cause is narrower than recorded below

Fresh `python3 fire.py build .tmp/ca/c_common/scriptutil.py` (sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`) on `6b9b6b18`, arm64.
The complete refusal list:

```
_iter_filenames: a call to unresolved callee 'Exception(...)' is not
                 supported in a compiled generator/coroutine body
iter_marks:     every `yield` must carry a value, and all values must
                 agree on one scalar type (int64_t/double/_Bool)
```

**`track_progress_compact` is gone from the list.** The entry below recorded
it as blocked by `a *`-/`**`-unpack call argument in a generator body`
(`iter_marks(groups=groups, **mark_kwargs)`, scriptutil.py:580). That shape
now lowers. Nothing in this branch touched it — the change is a later
lander's — but the doc's claim about it was accurate when written and is now
stale, and the file has one fewer blocker than it says.

### `iter_marks`' cause, measured: it is NOT the `**`-unpack

The entry below argues at length that `iter_marks` fails because its
`yield` types disagree, and that the disagreement comes from `os.linesep`
being read into a generator body (`div = os.linesep` inferring `int64_t`
against `end = f'{mark}{os.linesep}'` inferring `char *`). That is still the
immediate mechanism, but it is worth stating what the refusal list now
shows: with `track_progress_compact`'s `**mark_kwargs` forwarding lowered,
`iter_marks` is the *only* remaining `iter_marks`-family blocker, so the
`**`-unpack and the mixed-yields were never the same problem.

Measuring `_cpp_expr` on the live tree confirms the module-member VALUE read
is still the diagnosed stub:

```
[gimple_codegen] stubbed operation: generator-body module-member value read os.linesep
```

i.e. where it does NOT trip the yield-type check it produces `''` where
CPython produces `'\n'` — a wrong answer with a diagnostic rather than an
error. That is the honest statement of what is left, and it is the entry
below's step 1, unchanged.

### Next step (unchanged in substance; re-verified 2026-10-01)

1. **Module-attribute value reads in a generator body** (`os.linesep`,
   `fsutil.USE_CWD`, …). Still the highest-value item, still worth doing
   first, still the difference between an honest refusal and a wrong
   program. The bound module object is an opaque `int64_t` in this body
   model, so the fix needs the constant's real C symbol — and since
   `6b9b6b18` there IS a per-module globals-struct lookup to read it from:
   `_module_global_field_type(module, name)` in `gimple_codegen.py`, which
   resolves a name against `_module_globals[mod]`'s `(name, c_type,
   g_mtype)` triples (the same list the struct typedef, the initializer and
   the `_<mod>_mojo_global_get_<name>` accessors are generated from).
   `_cpp_expr_static_ctype` needs the matching row so the yield types agree
   afterwards. **This is a smaller job than the entry below assumed** — the
   per-module lookup it needed did not exist then and does now.
2. **`Exception(...)` as a value.** Unchanged; still the `_iter_filenames`
   blocker. `_cpp_raise_stmt` already builds the `_MojoCppExc{tag, msg, obj}`
   payload for `raise ExcName(...)` and for a bare `raise ExcName`; what's
   missing is the ASSIGNMENT form.
3. **`**`-forwarding into a compiled generator.** **REDUCED**: the one real
   call site in this file (`iter_marks(groups=groups, **mark_kwargs)`) now
   lowers, and `c_analyzer/__init__.py`'s `iter_decls(filenames, **kwargs)`
   is the remaining one. If it is still refused, re-measure before working —
   it may have cleared with the same change.

## Status 2026-09-30 — three blockers, unchanged in count; two of them are now the shared blockers other files also hit

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`):

```
Unsupported shape(s):
  _iter_filenames: a call to unresolved callee 'Exception(...)' is not supported
    in a compiled generator/coroutine body
  iter_marks: iter_marks: every `yield` must carry a value, and all values must
    agree on one scalar type (int64_t/double/_Bool)
  track_progress_compact: a `*`/`**`-unpack call argument is not supported in a
    compiled generator/coroutine body
```

Nothing this session moved these three, and it is worth being precise about
why the `**`-unpack one did NOT clear here the way it cleared in
`c_analyzer/__init__.py`: that file's `iter_decls` stopped refusing because
its import closure stopped failing to PARSE (`c_parser/preprocessor`'s bare
`for patterns, in ...:` target — commit `b67c170e`). `scriptutil`'s own three
shapes are independent of that and still need real work. In particular
`_cpp_try_kwargs_forward_call` is UNCHANGED and still refuses exactly what its
docstring says it refuses — including this file's
`iter_marks(groups=groups, **mark_kwargs)`, named in that docstring as a
deliberate non-case.

Two of the three are shared with other files in this family, which is the
grouping a follow-up should use:

| blocker | site | also in |
|---|---|---|
| `Exception(...)` in a generator body | `onempty = Exception('no filenames provided')` (:560) — a call to an exception CLASS as a constructor, then `raise onempty` | `c_common/fsutil.py`'s `process_filenames` (the `hard-fsutil` claim) |
| `**`-unpack call argument in a generator body | `iter_marks(groups=groups, **mark_kwargs)` (:580) | `c_analyzer/__init__.py`'s `iter_analysis_results` doing `iter_decls(filenames, **kwargs)` |
| mixed yield types | `iter_marks` (:595) — see below | `c_analyzer/__main__.py`'s `render` |

### The `iter_marks` refusal is a SILENT-WRONG upstream of itself

`_generator_yield_ctype` refuses because the yields disagree — and they
disagree because `os.linesep` is read into a generator body:

```
[gimple_codegen] stubbed operation: generator-body module-member value read os.linesep
iter_marks: every `yield` must carry a value, and all values must agree on one
scalar type
```

`div = os.linesep` (scriptutil.py:601) infers as `int64_t` because
`_infer_simple_expr_ctype` has no row for a module-member value, while
`end = f'{mark}{os.linesep}'` infers `char *` — hence the disagreement. The
cpp emitter's own answer to a module-member VALUE read is a diagnosed stub of
`0` (`cpp_core.py`, "generator-body module-member value read"), so where this
does NOT trip the yield-type check it produces `''` where CPython produces
`'\n'`: a wrong answer with a diagnostic rather than an error.

That makes the module-attribute VALUE read the actual bug, not the yield
check, and it is worth fixing first: it is the difference between an honest
refusal and a wrong program.

### Next step

1. **Module-attribute value reads in a generator body** (`os.linesep`,
   `fsutil.USE_CWD`, …). The bound module object is an opaque `int64_t` in
   this body model, so a value read needs the constant's real C symbol — the
   module-globals structs already exist and are already emitted per module
   (`__parser__regexes_globals` etc.), so `os.linesep` is a field read on a
   struct this emitter knows how to name. `_cpp_expr_static_ctype` needs the
   matching row so the yield types agree afterwards.
2. **`Exception(...)` as a value.** `_cpp_raise_stmt` already builds the exact
   `_MojoCppExc{tag, msg, obj}` payload for `raise ExcName(...)` and for a
   bare `raise ExcName`; what's missing is the ASSIGNMENT form
   (`e = ValueError(msg); raise e`). Representing it as the same
   (tag, msg) pair — a per-generator local-name → tag map beside
   `_cpp_reraise_stack` — keeps one exception representation rather than the
   two the emitter would otherwise have.
3. **`**`-forwarding into a compiled generator.** Both real call sites
   (`iter_marks(groups=groups, **mark_kwargs)`, `iter_decls(filenames,
   **kwargs)`) forward into something that is NOT an ordinary local free
   function — a generator, and a callable-valued parameter respectively — so
   `_cpp_try_kwargs_forward_call`'s narrow shape cannot be widened to cover
   them without first knowing the callee's real parameter names and defaults.
   That is a separate capability (callable-value-local signature discovery),
   not a tweak.
4. Only then: `_iter_filenames`'s remaining blockers after (2) — `yield from
   fsutil.process_filenames(...)`, `iterutil.peek_and_iter`,
   `iterutil.iter_many`, a lambda inside a tuple yield, and `yield from items`
   on a non-generator local. Five more shapes after one.

