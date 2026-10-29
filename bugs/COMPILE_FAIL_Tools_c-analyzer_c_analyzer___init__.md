# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-04 — same blocker (`check_all`), and the imported-module floor is the two `next(...)` shapes

Re-measured on this tree (`python3 fire.py build -o .tmp/out .tmp/ca/c_analyzer/__init__.py`,
sources from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`, arm64, ~8 s). The file still
does not build, and the module-level refusal is `check_all`:

    Error building: cannot compile module: function(s) check_all (generator function(s),
      contain a `yield`/`yield from`)

which is this file's own shape, unchanged: `for check in checks or ():` binds a
CALLABLE-VALUE local and `check(analysis)` is the iterable. `MOJO_DEBUG=1` names it the way
the sibling entries now name theirs — "a `for` over a call through the callable-valued
local/parameter `'check(...)'` is not supported in a compiled generator/coroutine body" —
so the entry below's "the refusal does not even name which call it could not type" is
answered; what is not answered is what the call RETURNS, which is what
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`'s "Next step" lists as its three
sub-problems, and that doc is still the one to read.

**The imported-module floor is down to two modules and both are `next(...)`** — the three
this entry listed in its 2026-10-01 status (`c_parser.info`, `._func_body`, `c_parser.match`)
are all past:

    # ERROR: compiling imported module '.iterutil' from .../c_common/iterutil.py:
      `next(...)` on next(IdentExpr) (receiver typed `MojoList *`) has no lowering
    # ERROR: compiling imported module 'c_parser.info' from .../c_parser/info.py:
      `next(...)` on next(CallExpr) (receiver typed `int64_t`) has no lowering

`iterutil`'s is the cheaper of the two (`items = iter(items); next(items)` — a rebound
list-iterator local, which the compiler already supports elsewhere and which
`bug:CODEGEN_next_on_bound_list_iter_cursor_off_by_one` is about), so it is the one to
take first, after reading that doc. Both this file and
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer_info.md` now name the same two, which makes
them the shortest path to a smaller closure for three of these files at once.

## Status 2026-10-02 — the imported-module floor is down to TWO, and `check_all` is still the one own-file blocker

Re-measured on the current tree (`python3 fire.py build`, sources copied from
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). The own-file
refusal is unchanged, still a single shape:

```
Unsupported shape(s): check_all: unsupported for-loop iterable type: CallExpr.
```

**The floor moved, and this is the entry that says so.** It was three
imported modules; `c_parser.match` is no longer one of them. Its refusal was

```
cannot coerce MojoSet * to MojoList * (incompatible container kinds) at
  .../c_parser/match.py: value='_t6' dest='expected'
```

which is the multi-kind machinery from `a3c9c090` being wrong in two ways at
once, both fixed in `d92a5a8c` (and named there with the measurements):

* `_multi_kind_locals` counted DUPLICATE kinds, not kinds. `expected`'s
  evidence list holds one entry per assignment site and all four branches
  assign a SET, so three identical `MojoSet *` entries read as a conflict —
  while the `TypeLattice.join_all` four lines above had already answered
  `MojoSet *`. That is not a harmless annotation: the flag switches OFF the
  three "trust ground truth" rules, so the name kept `_infer_param_types`'
  usage guess (`MojoList *` — `expected` is iterated and truth-tested) and
  every store was judged against it.
* `_infer_param_types` reads USES and cannot see one assignment, so it has to
  lose to `_infer_local_var_types`, which reads bindings. Applied by rewriting
  `_inferred_param_types` rather than at a reader, because that table feeds
  the forward DECLARATION as well as the definition.

`c_parser/match.py` now compiles past the coercion and stops at the NEXT
blocker, in a different module:

```
c_parser/parser/_common.py:50:9: error: implicit declaration of function
  'parser__regexes__ind_15d274' [-Wimplicit-function-declaration]
c_parser/parser/_common.py:50:7: error: assignment to 'char *' from 'int'
  makes pointer from integer without a cast [-Wint-conversion]
```

`_common.py`'s module-level `_PAREN_RE = re.compile(rf'''...{_ind(...)}...''')`
calls a helper from `_regexes.py` whose generated symbol has no forward
declaration in this translation unit — a different defect (a declaration gap,
not a type gap), in an area two other docs already carry
(`bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`).

### What is left, sized

1. **`c_common/iterutil.py`**: `next(...)` on `next(IdentExpr)` — no lowering.
   `peek_and_iter` does `items = iter(items)` then `next(items)`, i.e. `next`
   of a REBOUND list-iterator local. Adjacent to
   `bug:CODEGEN_next_on_bound_list_iter_cursor_off_by_one`, which another
   worker holds.
2. **`c_parser/info.py`**: `next(...)` on `next(CallExpr)` — `next(self.render())`,
   a call whose result is a generator. The compiler's own message lists the
   supported forms and `next(<a call returning a generator>)` is not among them.
3. **`check_all`** (this file's own): `for data, failure in check(analysis)`,
   a call through a callable-value loop variable whose RESULT is the iterable.
   The same blocker as
   `bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`'s
   `for row in _get_reader(lines, ...)`; that doc's "Next step" still names the
   three things the shape needs.

So the file still does not build. (1) and (2) are not fixable without touching
another worker's claim. (3) is not attempted: a call through a
dynamically-chosen callee has no static return type, and the entry below says
why that is a feature rather than a missing branch.

## Status 2026-10-01 — unchanged; one blocker, shared with c_common/tables.py

Re-measured on the current tree (`python3 fire.py build`, sources copied from
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). The sole
remaining refusal is still a SINGLE shape, unchanged:

```
Unsupported shape(s): check_all: unsupported for-loop iterable type: CallExpr.
```

Nothing moved. `check_all` (c_analyzer/__init__.py:92) binds `check` to a
CALLABLE-VALUE local by the outer loop and then calls it to get the iterable:

```python
def check_all(analysis, checks, *, failfast=False):
    for check in checks or ():
        for data, failure in check(analysis):
            ...
```

This is the SAME blocker now in front of
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (`read_table`'s
`for row in _get_reader(lines, ...)`, where `_get_reader` is a
default-valued callable parameter). One fix, three files — that doc's
"Next step" still names the three things the shape needs.

The imported-module floor (`c_parser.info` / `._func_body` / `c_parser.match`)
is also unchanged, and is now filed on its own rather than carried here:
`“The compiler has no way to see CPython's `Lib/` from an entry file outside it”`.

## Status 2026-09-30 — two of three of this file's own blockers gone; one remains, and is shared with two other files

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). The
sole remaining refusal is now a SINGLE shape:

```
Unsupported shape(s): check_all: unsupported for-loop iterable type: CallExpr.
```

Both of the file's other blockers are resolved:

| blocker | what it was | how it went |
|---|---|---|
| `iter_decls: a `*`/`**`-unpack call argument is not supported in a compiled generator/coroutine body` | `iter_decls` doing `parsed = parse_files(filenames, **kwargs)` | cleared by commit `b67c170e` (see below) — not by a `**`-forwarding fix |
| (imported-module floor) `# ERROR: compiling imported module '.preprocessor' ... 169:17: Expected KW got NAME('_resolve_file_values')` | `c_parser/preprocessor/__init__.py:169` — `for patterns, in _resolve_file_values(...)` — a bare trailing comma in a `for` target, which the PARSER rejected | `b67c170e` |

**Read that table carefully: neither `**`-forwarding support nor any change
to `_cpp_try_kwargs_forward_call` was needed.** `iter_decls` stopped refusing
because its module stopped failing to PARSE its own import closure. The
`for patterns, in ...` parse failure was making `c_parser/preprocessor` fall
back to source, and with it gone, `iter_decls`'s remaining shape resolved
through paths that were already there. Anyone picking this up should not
start by extending `_cpp_try_kwargs_forward_call` — that machinery is still
exactly as narrow as its docstring says, and the two cases its docstring
names as deliberately-unhandled (`iter_analysis_results` doing
`iter_decls(filenames, **kwargs)`, `track_progress_compact` doing
`iter_marks(groups=groups, **mark_kwargs)`) are still unhandled by it.

### The blocker now in front of this file

`check_all` (c_analyzer/__init__.py:92):

```python
def check_all(analysis, checks, *, failfast=False):
    for check in checks or ():
        for data, failure in check(analysis):
            ...
            yield data, failure
```

`check` is a CALLABLE-VALUE LOCAL bound by the outer loop, and `check(analysis)`
is a dynamic call whose return is the iterable — a generator, in real code.
This is the SAME blocker now in front of
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (`read_table`'s
`for row in _get_reader(lines, ...)`, where `_get_reader` is a
default-valued callable parameter). One fix, three files — see that doc's
"Next step" for the three things that shape needs.

### Also worth recording: the imported-module floor has not gone away

Three imported modules still fail in every closure that reaches them, and
`c_analyzer/__init__.py` reports all three:

```
# ERROR: compiling imported module 'c_parser.info' from .../c_parser/info.py:
    cannot materialize a generator as a list: no known generator API for
    'rendered' (pass the generator through a variable, or consume it with a
    for loop)
# ERROR: compiling imported module '._func_body' from .../c_parser/parser/_func_body.py:
    cannot coerce MojoDict * to MojoList * (incompatible container kinds) at
    .../_func_body.py: value='_t513' dest='data'
# ERROR: compiling imported module 'c_parser.match' from .../c_parser/match.py:
    cannot coerce MojoSet * to MojoList * (incompatible container kinds) at
    .../match.py: value='_t6' dest='expected'
```

(`c_parser/preprocessor` was the fourth and is now fixed.) So even a perfect
`check_all` would not make THIS file build — the floor has to go first. The
`c_parser.info` one is understood and is the same `rendered, = rendered`
shape described in `bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
(it unpacks the first value out of a classmethod GENERATOR,
`cls._format_data(...)`, whose return the ordinary path types
`MojoGenerator *` but whose api it never records).

