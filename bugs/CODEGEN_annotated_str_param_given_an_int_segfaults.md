# CODEGEN: an annotated `str` parameter given a non-string argument SEGFAULTs

**State: OPEN, found 2026-09-30, mechanism located, not fixed.** This is
what `bugs/CODEGEN_method_returning_self_str_field_segfaults.md` (not on this
tree; read it with `git show round8-merged:bugs/CODEGEN_method_returning_self_str_field_segfaults.md`)
actually measured. That doc's diagnosis is wrong on both counts, and the
correction matters because the real defect is much smaller and lives
somewhere else. See "What that doc got wrong" — the other half of its repro
is an already-filed, already-claimed bug and is deliberately NOT re-filed.

## What I ran and what I saw

Single module, no imports, no name collision anywhere:

```python
class Dialog:
    def __init__(self, widgetName: str):
        self.widgetName = widgetName
    def show(self):
        return self.widgetName

def main():
    a = Dialog(5)
    print(a.widgetName)
    print(a.show())
main()
```

| | CPython | compiled |
|---|---|---|
| `Dialog(5)`, read the field | `5` | **SIGSEGV, exit -11, no output** |
| `Dialog("hello")` (string arg) | `hello` / `hello` | `hello` / `hello` — **correct** |

So it needs no import, no collision, and no unusual return path: it needs an
argument whose Python type is not the one the annotation says.

The generated C is **correct**. `Dialog_show` really is `char *`, its
`return self->widgetName` really is a `char *` load, the call site really is
`_t8 = Dialog_show (a); mojo_print (_t8);`. The crash is at the CONSTRUCTOR's
argument, one line earlier:

```c
void __GIMPLE Dialog___init__ (Dialog * self, char * widgetName)   /* correct */
...
_t5 = (int64_t)5;
_t3 = (void *)_t5;
_t4 = (char *)_t3;          /* <-- the int 5 becomes the char * */
Dialog___init__ (_t2, _t4);
...
_t6 = a->widgetName;        /* strlen(address 5) */
mojo_print (_t6);
```

`mojo_print` `strlen`s address 5.

## Mechanism

The annotation is a STATIC PROMISE that codegen takes literally: `str` means
the C type is `char *`, so the call site coerces the argument to `char *`. In
Python a parameter annotation is documentation, not a cast — `Dialog(5)` is
perfectly legal and `print(5)` prints `5`. The compiled path has one C type
per parameter slot and no runtime tag, so the coercion is the only thing it
can do; what it must not do is produce a SIGNAL.

The general shape is: **any int64_t that gets cast to a pointer-typed slot and
then dereferenced as a C string is a crash**, and the compiled path's way of
being wrong about that is a segfault rather than the honest
`TypeError: expected str, got int` CPython's own `str` operations would
eventually produce.

Related but distinct, and NOT what this doc is about: an UNANNOTATED
parameter whose only use is a `print` argument was typed `char *` and
segfaulted the same way. That one is
`bugs/CODEGEN_print_unannotated_param_typed_char_star_segfaults.md` (fixed
2026-09-30 by removing the `print` entry from `BUILTIN_PARAM_TYPES`).

## What that doc got wrong

`CODEGEN_method_returning_self_str_field_segfaults.md` claims the crash is in
"the value's *return path* out of the method" and suggests "a missing field
ctype on the `self.<field>` return path". Both are disproved by the C above:
the field's ctype is `char *`, the load is a `char *` load, and the method's
return type is `char *`. The crash is entirely upstream of the method.

Its second observation — the cross-module case exiting 1 with
`Unhandled exception: AttributeError: widgetName` for what it takes to be "the
field read at the call site, separately wrong" — is real, and it is a
DIFFERENT bug with a different cause. Measured 2026-09-30 on the current tree,
with a genuine string argument so nothing else interferes:

| program (struct `Dialog` in `ma2.py`, `def __init__(self, widgetName: str)`) | CPython | compiled |
|---|---|---|
| `import ma2` + `ma2.Dialog("hello")`, in `main()` | `hello` | **exit 1, `AttributeError: widgetName`** |
| `import ma2` + `ma2.Dialog("hello")` at module level | `hello` | **exit 1, same** |
| `from ma2 import Dialog` + `Dialog("hello")` | `hello` | **exit 1, same** |
| single module, `Dialog("hello")` | `hello` | `hello` — correct |

Generated C for the qualified spelling:

```c
_t7 = _t2;  /* int64_t.Dialog() stubbed */
a = _t7;
_t8 = (void *)a;
_t9 = _mojo_dispatch_getattr (_t8, _t10);   /* a is not a Dialog */
```

The CONSTRUCTOR is stubbed to the module handle, so `a` is a `MojoDict *` and
every later field read is an honest `AttributeError` about a type that was
never constructed. So: **cross-module struct construction is entirely stubbed
on this tree**, in every spelling (qualified in a function, qualified at
module level, `from X import C`). That is a cross-module-subsystem defect, it
is already filed as
`bugs/CODEGEN_aliased_imported_struct_construction_unresolved.md` for the
`as Alias` spelling of the same ctor-dispatch miss, and `construct:cross-module-link`
is another worker's claim — so it is left alone here and only measured, to keep
this doc from being read as a new cross-module finding.

## Exact next step

The call site knows the argument's own type and the callee's declared
parameter type at the moment it emits the coercion. A `char *` parameter
receiving a `double` or an `int64_t` that is not a pointer is the detectable
case, and the honest answer is the one the runtime already has machinery for:
either

* a diagnostic naming the parameter and exit non-zero, the way
  `mojo_list_assign_step`'s `ValueError: slice step cannot be zero` and
  `bytearray`'s `IndexError: bytearray index out of bounds` do — a Python-level
  `TypeError: expected str, got int` is what CPython's own `str` usage would
  produce; or
* keep the value boxed (`int64_t`) and let the consumer that needs a C string
  ask `mojo_cstr_or_int_str`, which already answers "is this word a boxed
  `char *`, or an integer?" with the runtime's own discriminator.

The first is the smaller change and the honest one. Either way the criterion
is the same: a program that does this today gets a SIGNAL, and every
alternative to that is an improvement.

## Suite-bucket note

None. `test_gimple_runner.py` (`gimplerunner`, in both `check` and `gate`) is
where the regression test belongs, with a `test_gimple_runtime_error` on the
diagnostic.
