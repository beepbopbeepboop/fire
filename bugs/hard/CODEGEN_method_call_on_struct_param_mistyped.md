# HARD BUG: a method call on a struct passed as a free-function parameter is silently mistyped — 3 of 8 method names give a wrong value with exit 0, the other 5 crash

**State: the single-file case is FIXED (2026-09-27); one cross-module row
remains, blocked by a different bug.** See "Status" at the bottom for what
landed, the evidence, and the exact shape of the one row that is still red.
The *return*-value twin of this bug — a function whose only `return` is a
module-level constructor's result — was fixed in the same pass and its doc
deleted.

**Original state: OPEN.** Found 2026-09-26 while re-testing the return-type claims of
the now-removed `CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
(a cross-module `repr(obj.method())` repro reached it). It is NOT residue of
either removed doc: it is a distinct mechanism, in a different function
(`_infer_param_types`, free-function **parameters**), with a much wider blast
radius. It is written up here because it is the worst silent miscompile found in
this verification pass and it had no home.

## Symptom

One class, one no-op-ish method, one free function that takes the object as a
parameter. The **only** thing that varies is the method's *name*. Nothing else
about the program changes.

`/tmp/vd4/m_<name>.py`:

```python
class Box:
    def __init__(self, v):
        self.v = v
    def <name>(self, *a):
        return 7

def use(b):
    return b.<name>(1)

def main():
    print(use(Box('str')))
```

Built with `python3 fire.py build` (the real link-mode pipeline) and run. Every
one of the eight compiles with **zero** `error:` lines.

| method name | `use`'s C param type in the generated `.ci` (before) | CPython | compiled (before) | exit |
|---|---|---|---|---|
| `get` | `MojoDict *` | `7` | **crash — SIGBUS, or SIGSEGV** | 138 / 139 † |
| `items` | `MojoDict *` | `7` | **Segmentation fault** | 139 |
| `keys` | `MojoDict *` | `7` | **Segmentation fault** | 139 |
| `append` | `int64_t` | `7` | **Bus error (SIGBUS)** | 138 |
| `other` | `int64_t` | `7` | **`4328331776`** — the boxed `Box *` printed as a decimal | **0** |
| `find` | `int64_t` | `7` | **`-1`** | **0** |
| `hex` | `MojoBytes *` | `7` | **Segmentation fault** | 139 |
| `decode` | `MojoBytes *` | `7` | **Segmentation fault** | 139 |

† `get` is not deterministic about *which* fault: 5 runs gave 138,138,138,138,139.
`append`/`items`/`hex` were stable across 5 runs each. The two silent rows'
pointer value varies per run (ASLR), as expected for a printed address.

The correct type is `Box *` in all eight rows. Two of them are silent
wrong-values with exit 0; six are hard crashes on a program CPython runs
cleanly.

The single sharpest demonstration is one file where **both** spellings appear and
the right one is in the same binary (`/tmp/vd3/q3.py`):

```python
class Box:
    def __init__(self, v):
        self.v = v
    def get(self):
        return self.v

def meth(b):
    return b.get()

def main():
    b = Box('str')
    print(meth(b))
    print(b.get())
```

```
CPython:   str      compiled (before):  0
           str                        str
```

`b.get()` on a local is right. The identical call on the same object, one line
away, arriving as an argument, is wrong. There is no diagnostic and exit 0.

And a one-line contrast that isolates the trigger to the *use*, not the
declaration — a free function that only reads a **field** through the same
parameter is fine (`/tmp/vd3/q2.py`, `def field(b): return b.v` → `str` ✓, and
the generated declaration is `char * field_d64af5 (Box *);`); swapping `b.v`
for `b.get()` is what breaks it.

Cross-module is no different, and the two forms fail differently:

| | CPython | compiled (before) | exit |
|---|---|---|---|
| `/tmp/vd1b/k2.py` — single file, `def show(p): return p.label()` | `v` | `4354021824` | 0 |
| `/tmp/vd1b/k3.py` — `import insp` + `def show(p): return p.label()`, called `show(insp.Parameter('v', 7))` | `v` | `0` | 0 |

The two-module form is what made this surface: it is how `repr(obj)` is spelled
in real code, and `bugs/hard/CODEGEN_function_scoped_import_module_not_inlined.md`
row 4 (a cross-module `repr(Parameter('v', 7))`) is this bug, not that one.

## Root cause

`mojo/middle/infra_infer.py`, `_infer_param_types` (`:213`). The function's own
docstring states the design:

> If a parameter is accessed with .field, infer it's a struct with that field.
> If a parameter is passed to a known function, infer type from that function.

**Method-call usage is neither.** A parameter used *only* as a method receiver
contributes zero field accesses, so the struct-inference branch is skipped
entirely (the `len(fields_accessed) > 0` guard — line numbers in this file have
moved since this was written; grep for `_struct_evidence_list`):

With that branch skipped, the parameter falls through to a chain of
**name-based builtin-container heuristics** that were written to disambiguate
`char *` / `MojoList *` / `MojoDict *` / `MojoBytes *` from each other, and which
have no way to express "this is a user struct":

- `is_dict_method` → `'MojoDict *'`. `is_dict_method` is set from
  a bare name-set membership test (`DICT_ONLY_METHODS` = `items`,
  `keys`, `values`, `setdefault`, `get`). A user class is free to define a
  method called `get`; the analysis cannot tell, and does not try.
- `is_string_method` and no field accesses → `'char *'`
  (`STRING_ONLY_METHODS`).
- `BYTES_ONLY_METHODS` (`decode`/`hex`) → `MojoBytes *` via the
  analogous bytes branch.
- otherwise → the `int64_t` default.

That predicts the table exactly: `get`/`items`/`keys` → `MojoDict *`;
`hex`/`decode` → `MojoBytes *`; `append` and `other` → `int64_t`.

Once the receiver's C type is wrong, the method dispatch has nothing to resolve
against and lands in the generic scalar-receiver stub in
`mojo/backend_gimple/emit_methods.py` (`_lower_method_call`'s
"Other scalar methods: pass the receiver through unchanged"):

```python
# Other scalar methods: pass the receiver through unchanged
for ea in node.args[1:]: gen.lower_expr(ea)
return gen._stub_result(ot, ov_local, f'{ot}.{method}() stubbed')
```

"Pass the receiver through unchanged" is what produced the two silent rows: the
`Box *` comes back out of the function still boxed, and `print` renders it as
`4315306496`. The six crashing rows are the same mistake landing in a builtin
container's runtime helper with a struct pointer as its handle.

The generated C says so in as many words — the call is not lowered at all:

```c
int64_t use_9f63a2 (int64_t b)
{
  int64_t _t1;
  _t1 = b;
  _t2 = _t1;  /* int64_t.other() stubbed */
  return _t2;
}
```

### A second, independent defect in the same function

`find` is in `STRING_ONLY_METHODS` and the param has no *other* signal,
so the string branch should have typed it `char *`. It was typed `int64_t`
instead. The reason is that the bare member access `b.find` is *also* recorded
into `fields_accessed`, so that branch's `len(fields_accessed) == 0` guard is
false; the struct branch then runs on the evidence field `'find'`, matches no
registered struct, and the parameter falls all the way through. So a method
call poisons the very counter that would have let the string heuristic fire. The
same shape suppressed other single-signal inferences; not enumerated.

### A third defect, one level down, found while fixing this

`_quick_type`'s `CallExpr`/`MemberExpr` branch decides a method call's result
type from the method's NAME before it ever looks at the receiver: `items`/
`keys`/`values`/`split` → `MojoList *`, `read`/`readline` → `char *`,
`expandtabs`/`strip`/`decode`/… → `char *`. Those rows exist because the
receiver's type is usually still unknown at pre-pass time. But when the receiver
IS known, the name is no longer evidence of anything — and a user class may
define a method called `items`. So `def use(b): return b.items(1)` was DECLARED
`MojoList *` against a body that dispatched the real `Box_items` returning an
`int64_t`: the same value-identity failure as the two above, one level below the
parameter they were fixed at.

## Status (2026-09-27)

Three changes, all in the "a value whose type the lowering knows and the
inference pass does not" family. The one that matters is the first: **the
answer now comes from the call site**, which is the only place this codegen ever
knows the argument's type.

1. **A struct-pointer cross-call contract** (`mojo/backend_gimple/module_gen.py`,
   "Pass 1.3d-struct", alongside the existing `char *`/`double` one). A new
   observer `_arg_struct_ptr_type` records, for every call site, the argument's
   `<Struct> *` type when it is provable — a caller local, a `self`/local field,
   or a **struct constructor** (`use(Box('x'))` and its cross-module spelling
   `show(insp.Parameter('v', 7))`). A parameter is retyped only when the
   observation is unanimous across all call sites, has no explicit annotation,
   and its current entry is one of the no-evidence FALLBACKS (`MojoDict *`,
   `MojoList *`, `MojoSet *`, `MojoBytes *`, `MojoStr *`, `char *`, `int`,
   `int64_t`) — i.e. a name-based guess, not an inference. The scalar contract's
   own observation set is deliberately left untouched: mixing struct pointers
   into it would suppress an otherwise-unanimous `char *` resolution in a pass
   that has its own history.

   It is further scoped to parameters actually used as a **method receiver**
   (`p.<m>(...)`). Widening it to every unanimous struct argument retypes
   *dynamic-attribute* receivers too — `def get_or_init(cls): cls.__slot_names__`
   called as `get_or_init(Holder())` must stay opaque until an
   `AttributeError` says otherwise, and typing it `Holder *` turns
   `_mojo_dispatch_getattr` into a `->__slot_names__` field read on a struct
   with no such field (a hard GCC `'Holder' has no member named
   '__slot_names__'` failure). A method call, by contrast, has exactly one
   lowering — the struct's own mangled method — so there is nothing for the
   name-based fallback to get right.

2. **A method call is not field evidence** (`_infer_param_types`). `called_methods`
   now records *every* method called on the parameter, not just the
   builtin-container names, and the struct-evidence list is built once and read
   by both the struct branch and the string-evidence fallback — "no struct
   evidence" has to mean the same set in both places, which it did not while one
   gated on the raw `fields_accessed` and the other on the filtered list. That
   is the second defect above, and it is what promotes `param.find(...)` to
   `char *`.

3. **A known struct receiver beats a name-keyed row** (`_quick_type`): the
   mangled-method-symbol resolution moved to the TOP of the
   `CallExpr`/`MemberExpr` branch, gated on `var_types` actually naming a
   registered struct, so only a provable receiver changes behaviour.

Two things fell out of (2) that are worth naming because they are the compiler
describing *itself* wrongly and now does not:

- 11 signatures in the self-host closure got a MORE PRECISE type (measured by
  diffing the file-scope function signatures of the whole-closure `fire.ci`
  before vs after; no signature got less precise). Examples:
  `discover_closures__scan_for_closures (GimpleGen *, char *)` was
  `(int64_t, char *)` — its first param is the `gen` handle that
  `_infer_param_types`' own docstring opens by complaining about;
  `Interpreter._bind_dotted_import(_, char *)` and `_bind_comprehension_target`
  were `(Interpreter *, int64_t, int64_t)`, though both take a plain
  `module_name` / `target_str` string; `ModuleLoader._scan_source` took
  `src_content` as `int64_t` though its only use is `src_content.split('\n')`;
  and `emit_infra._elaborate_overload_call` / `emit_resolve._elaborate_generic_call`
  were declared `int64_t` while returning a real `MojoList *`.

- One of those exposed a latent inconsistency that had to be pinned: a
  `@classmethod`'s first parameter is the CLASS object, and every heuristic in
  `_infer_param_types` reads `cls.<name>(...)` as receiver evidence — `join` is
  in `STRING_ONLY_METHODS`, so `TypeLattice.join_all`'s `cls` inferred `char *`
  while its sibling `join`'s `cls` stayed `int64_t`, and `join_all` then passed
  a `char *` where `join` declared `int64_t`. `cls` is now pinned to the
  `int64_t` class handle before any body-usage heuristic can see it. (Caught by
  `check`'s `selfhost`; without this pin the whole self-host compile fails.)

### Evidence

All eight rows, `python3 fire.py build` + run, CPython alongside:

```
get    cpy=7   compiled=7   exit=0
items  cpy=7   compiled=7   exit=0
keys   cpy=7   compiled=7   exit=0
append cpy=7   compiled=7   exit=0
other  cpy=7   compiled=7   exit=0
find   cpy=7   compiled=7   exit=0
hex    cpy=7   compiled=7   exit=0
decode cpy=7   compiled=7   exit=0
```

(every one of the eight declared `int64_t use_d64af5 (Box *)` afterwards).
`/tmp/vd3/q3.py` → `str / str`; `/tmp/vd1b/k2.py` → `v`.

Suites, all at default parallelism, from the repo root:

| | result |
|---|---|
| `python3 tools/suite.py check` | 7 passed, 0 failed |
| `python3 tools/suite.py stdlib` | 2 passed, 0 failed |
| `python3 tools/suite.py coroutine` | 1 passed, 0 failed (`test_coro_runtime.py` 20/20) |
| `python3 compile_stdlib.py` | `PASSED: 664` / `FAILED: 0 (0 expected, 0 unexpected)`; `GCC CAS: 664/664 hits` — the generated C is **byte-identical** on all 664 modules, so `U` did not increase and nothing regressed |
| `stdlib-dylib` skip count | 0 before, 0 after; the full `build_stdlib()` output is byte-identical |
| `python3 test_gimple_runner.py` | 124 passed, 0 failed |
| `python3 test_gimple_generator_runner.py` | 145 passed, 0 failed |

The corpus is unchanged because the stdlib has no free function that returns a
`struct.*(...)` result and no unannotated free-function parameter used as a
method receiver on a user struct — the shapes simply do not occur in real Mojo
source, which is also why they went unnoticed.

### What is still red

`/tmp/vd1b/k3.py` — `import insp` + `def show(p): return p.label()`, called
`show(insp.Parameter('v', 7))` — still prints `0`, exit 0. **It is not reachable
by any change to this bug.** The generated C shows why:

```c
_t7 = _t2;  /* int64_t.Parameter() stubbed */
_t8 = show_9f63a2 (_t7);
int64_t show_9f63a2 (int64_t p)
```

The value handed to `show` is already the stub's `0` before `show` is entered:
`module.Class(...)` construction is unresolved in link mode, so the callee
receives a literal `0` and no receiver typing can recover the struct. That is a
separate, bigger bug — the one `README.md` already names as blocking
`CODEGEN_same_bare_name_struct_collision_across_modules.md` ("`module.Class(...)`
construction is unresolved on every path … Fix that first"). Note also that in
the single-translation-unit path the same file IS fixed by this change:
`compile_to_gimple(src, do_imports=True)` gives
`int64_t show_0a1953 (Parameter * p)`. So the parameter-side mechanism this doc
is about is closed; only the link-mode constructor stub stands in front of it.

### Test coverage

Four regression tests, added to `test_gimple_runner.py` (which executes the
built binary, so it catches the silent-wrong-value rows an exit-code-only or
`-fsyntax-only` check cannot):

- `gimple_method_call_on_struct_param_not_mistyped` — all eight method names in
  one program (red before: SIGSEGV; green after).
- `gimple_method_call_on_struct_param_matches_local` — the q3 two-spelling
  contrast (red before: `0 / str`; green after: `str / str`).
- `gimple_struct_param_field_and_dict_receiver_unaffected` — the field-read and
  real-dict control (green before and after; it exists to catch the over-reach
  that change 1 had before it was scoped to receivers).
- `gimple_struct_ctor_result_returned_from_function` — the return-value twin
  (red before: exit 1, `AttributeError: size`).

**`test_gimple_runner.py` is in NO `tools/suite.py` bucket**, so the gate does not
run any of them and they will rot exactly the way that file already has. It
needs this row next to the `gimple` test, plus `'gimple-runner'` added to the
`check` bucket:

```python
test('gimple-runner', [PY, 'test_gimple_runner.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_gimple_runner.py'],
     desc='GIMPLE compile-AND-EXECUTE suite (runs the built binaries)')
```
