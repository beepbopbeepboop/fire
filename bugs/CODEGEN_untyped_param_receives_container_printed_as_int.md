# CODEGEN: an untyped function parameter that receives a list prints the list's pointer as an int

Split out 2026-11-01 from `CODEGEN_ctor_temp_field_read_loses_element_type`
(that doc's named case — a container read off a constructor temporary — is
fixed; see its deletion commit). This is the doc's third measured case, which
is a different root: a CALL boundary, not a constructor field.

## Repro

```mojo
def show(t):
    print(t)

def main():
    x = [i for i in range(3)]
    show(x)
    y = [i for i in range(3)]
    print(y)
```

CPython: `[0, 1, 2]` twice.
Compiled (gimple backend): `show(x)` prints `4311987456` (a heap pointer as a
decimal); `print(y)` is correct.

Measured with `gimple_codegen._run_pipeline(src, do_imports=True)` + gcc
`-fgimple` against `runtime/fire_runtime.c` on master (`f92e7b109`).

## Cause, as far as measured

The generated C signature is `void show_9f63a2 (int64_t t)`: the untyped
parameter `t` defaults to `int64_t`, so the caller's `MojoList *` is passed
as an integer and `print(t)` takes the int route. The list's own per-list
element repr (`mojo_list_set_elem_repr`, set by the comprehension literal) is
never reached, because nothing hands the list to a list-aware print.

The constructor path already solves the same problem for CTOR parameters: the
`_ctor_container_lit_obs` / `_ctor_lit_param_types` observer in
`mojo/backend_gimple/module_gen.py` (around lines 6226-6400) reads each call
site's argument container type and types the parameter `MojoList *` when the
evidence is unanimous. Free-function parameters have no such observer for
container arguments.

## Next step

1. Add a free-function analogue of the constructor observer: for each call
   `f(<arg>)` to a module-level `def f(p)` with an UNTYPED, unannotated `p`,
   record the argument's container ctype (`_gmi_container_ctype` on a literal,
   the same local/self-field tracing `_ctxlit_ident_container` does), keyed
   `"<fn>::<param>"`, veto on conflict, and type the parameter from it.
2. Verify that `show(x)` then prints `[0, 1, 2]`, and that the change is
   behaviour-preserving for every other program (byte-identical generated C on
   a large succeeding case, per CLAUDE.md).
3. Gate: this is `module_gen.py` (`mojo/backend_gimple/*`), so it owes
   `make gate` before it is done. Not run in the light-worker round that filed
   this doc.

## Not yet known

- Whether a parameter typed `MojoList *` also needs its element type carried
  (`_field_elem_types`-style) or whether the runtime element repr is enough.
- Whether the interpreter (`myinterpreter.py`) is already correct here; only the
  compiled path was measured.
