# HARD BUG: a method call on a struct passed as a free-function parameter is silently mistyped — 3 of 8 method names give a wrong value with exit 0, the other 5 crash

**State: OPEN.** Found 2026-09-26 while re-testing the return-type claims of
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

| method name | `use`'s C param type in the generated `.ci` | CPython | compiled | exit |
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
CPython:   str
           str
compiled:  0
           str
```

`b.get()` on a local is right. The identical call on the same object, one line
away, arriving as an argument, is wrong. There is no diagnostic and exit 0.

And a one-line contrast that isolates the trigger to the *use*, not the
declaration — a free function that only reads a **field** through the same
parameter is fine (`/tmp/vd3/q2.py`, `def field(b): return b.v` → `str` ✓, and
the generated declaration is `char * field_d64af5 (Box *);`); swapping `b.v`
for `b.get()` is what breaks it.

Cross-module is no different, and the two forms fail differently:

| | CPython | compiled | exit |
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
entirely — `:1132`:

```python
if pname not in inferred and len(fields_accessed) > 0:
```

With that branch skipped, the parameter falls through to a chain of
**name-based builtin-container heuristics** that were written to disambiguate
`char *` / `MojoList *` / `MojoDict *` / `MojoBytes *` from each other, and which
have no way to express "this is a user struct":

- `:1186-1187` — `is_dict_method` → `'MojoDict *'`. `is_dict_method` is set from
  a bare name-set membership test at `:714` (`DICT_ONLY_METHODS` = `items`,
  `keys`, `values`, `setdefault`, `get`). A user class is free to define a
  method called `get`; the analysis cannot tell, and does not try.
- `:1193-1194` — `is_string_method` and no field accesses → `'char *'`
  (`STRING_ONLY_METHODS`, `:282`).
- `BYTES_ONLY_METHODS` (`:317`, `decode`/`hex`) → `MojoBytes *` via the
  analogous bytes branch.
- otherwise → the `int64_t` default.

That predicts the table exactly: `get`/`items`/`keys` → `MojoDict *`;
`hex`/`decode` → `MojoBytes *`; `append` and `other` → `int64_t`.

Once the receiver's C type is wrong, the method dispatch has nothing to resolve
against and lands in the generic scalar-receiver stub at
`mojo/backend_gimple/emit_methods.py:3072-3074`:

```python
# Other scalar methods: pass the receiver through unchanged
for ea in node.args[1:]: gen.lower_expr(ea)
return gen._stub_result(ot, ov_local, f'{ot}.{method}() stubbed')
```

"Pass the receiver through unchanged" is what produces the two silent rows: the
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

`find` is in `STRING_ONLY_METHODS` (`:282`) and the param has no *other* signal,
so `:1193` should have typed it `char *`. It is typed `int64_t` instead. The
reason is that the bare member access `b.find` is *also* recorded into
`fields_accessed`, so the `:1193` guard `len(fields_accessed) == 0` is false; the
struct branch at `:1132` then runs on the evidence field `'find'`, matches no
registered struct, and the parameter falls all the way through. So a method
call poisons the very counter that would have let the string heuristic fire. The
same shape presumably suppresses other single-signal inferences; not
enumerated.

## Why the removed docs did not catch this

`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`'s final recorded
state is that a method body of exactly `return self.<field>` **does** now get
its return type inferred (verified: `one_ret.py` prints `str`). That is a
**method** receiver — always a known `self` struct pointer, so
`_lower_struct_method_call` resolves it. This bug is exclusively about a
**free-function parameter** used as a receiver, which is a different entry point
into type resolution and was never in either removed doc's scope.

## Where

- `mojo/middle/infra_infer.py:1132` — the struct-inference branch that requires
  `len(fields_accessed) > 0`; the whole bug.
- `mojo/middle/infra_infer.py:1186-1187`, `:1193-1194`, and the bytes analogue —
  the name-based builtin-container fallbacks that mis-type a user struct.
- `mojo/middle/infra_infer.py:714`, `:282`, `:308`, `:317` — the name sets
  themselves, and the "a user class may define a method with any of these names"
  gap.
- `mojo/backend_gimple/emit_methods.py:3072-3074` — the receiver-passthrough stub
  that turns the mis-typing into a wrong value instead of a refusal.

## Suggested shape of a fix (not attempted)

The cheap, honest, low-blast-radius version is a **refusal**, not an
inference: when a parameter is used as a method receiver and no struct-type
evidence was found, refuse the method call through the compiled path's existing
"cannot lower this" idiom rather than stubbing it — the shape
`test_gimple.py`'s `nested_async_gen_capture_from_async_for_refused` pins for
the coroutine case. Turning six SIGSEGV/SIGBUS crashes and two silent wrong
values into one honest "unsupported: method call on an untyped receiver" is
worth doing before attempting real inference, and it is a strictly smaller
change than teaching `_infer_param_types` to prefer a user struct over a
builtin-container heuristic — that preference is a judgement call, and getting
it wrong would regress the `gencodec.py` `marshalmap` case `:1140` documents.

The correct inference is available and is already implemented elsewhere: the
**call site** knows the argument is a `Box`. Pass 1.3d's cross-call contract
(`module_gen.py`) already threads call-site types back into
`_inferred_param_types`; it just has no rule for "this argument is a struct
pointer, and the callee only ever uses it as a receiver".

## Test coverage

There is none for this shape, and the obvious place to put it is currently
**orphaned** — see the note in
`CODEGEN_ctor_arg_field_type_scalars_only.md`'s "Test coverage" section:
`test_gimple_runner.py` is in no `tools/suite.py` bucket, so no gate runs it.
A regression test here must be registered, or it will rot exactly the way that
file did.
