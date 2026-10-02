# COMPILE_FAIL: Tools/c-analyzer/c_common/scriptutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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

