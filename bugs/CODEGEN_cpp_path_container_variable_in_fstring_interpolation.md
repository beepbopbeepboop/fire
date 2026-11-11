# CODEGEN: a container *variable* in a cpp-path f-string interpolation prints object bytes

## Symptom

The sibling of the collection-literal f-string interpolation refusal landed on
2026-11-10 (that bug's doc was deleted with its fix): on the C++20 escape-hatch
emitter (`MOJO_CORO=cpp`), an f-string whose interpolated expression is a
**container-typed value that is not a literal** still compiles, but prints the
container struct's raw header bytes instead of its `repr`:

```
def g():
    xs = [1, 2]
    print(f"{xs}")
    yield 0
```

`MOJO_CORO=cpp python3 fire.py --jit` prints two garbage bytes followed by the
rest of the program's output, where the interpreter prints `[1, 2]`. The same
happens for a dict local (`f"{d}"` for `d = {'a': 1}` prints garbage; the
interpreter prints `{'a': 1}`).

This is the remaining half of the report's claim that "a non-literal container
*variable* [is] fine": it **compiles**, but it is a SILENT MISCOMPILE, which the
literal case was not (the literal case at least failed loudly in g++).

## Evidence

```
$ MOJO_CORO=cpp python3 fire.py --jit .tmp/gen_listvar3.mojo
<two header bytes>\n0\n
$ python3 fire.py run .tmp/gen_listvar3.mojo
[1, 2]
0
$ MOJO_CORO=cpp python3 fire.py --jit .tmp/gen_dictvar.mojo
<two header bytes>\n0\n
$ python3 fire.py run .tmp/gen_dictvar.mojo
{'a': 1}
0
```

## Root cause

`mojo/backend_gimple/cpp_core.py`, `_cpp_string_literal_expr`'s interpolation
arm. After the literal-shape refusal added with the sibling fix, this arm still
has no container case: `_infer_simple_expr_ctype` reports `MojoList *` /
`MojoDict *` / `MojoSet *`, the `char *`/`double`/`_Bool` arms do not match, and
the fallback is

```
piece = f"mojo_str((void *)({v}))"
```

`mojo_str` is a pointer heuristic (`val > 65536` ⇒ "this is a C string, return
it as-is"), so a `MojoList *`/`MojoDict *` is handed back as a `char *` and its
struct header is printed as text.

The ordinary GIMPLE path does not have this hole because `_stringify_value` /
`_repr_value` (emit_infra.py / emit_resolve.py) dispatch `MojoList *` /
`MojoDict *` / `MojoSet *` to real repr walkers. Those walkers emit GIMPLE
statements via `gen._new_val`; this expression-only emitter has no such side
channel, which is why the literal case was refused rather than routed.

## Exact next step

Add container arms to `_cpp_string_literal_expr`, keyed on `ectype`, BEFORE the
generic `mojo_str` fallback:

- `MojoList *` — the public runtime helpers already exist in
  `runtime/fire_runtime.h` (`mojo_repr_list_ints`, `_doubles`, `_bools`,
  `_bytes`, and the kinds-aware `mojo_repr_list_kinds(l, "<kind bytes>")`).
  Choose the helper/kind string from the statically-known element type — for a
  local assigned from a literal, `gen._cpp_list_local_elem_types` (populated by
  `_cpp_container_literal_init`) already records it; otherwise derive it from
  the assigned RHS (`_cpp_list_literal_arg_expr` has the same element-kind
  classification). The kind alphabet is `i` int, `d` double, `p` str, `b`
  bool, `s` bytes, `n` None, `l` nested list.
- `MojoDict *` / `MojoSet *` — no public repr exists today (`_mojo_repr_dict` /
  `_mojo_repr_set` are `static` in the ordinary `.c` translation unit and not
  callable from the companion `.cpp`). Either add public runtime wrappers or
  refuse honestly; do not fall through to `mojo_str`.

Whichever shapes are not routed must raise
`gimple_exprtypes._UnsupportedGeneratorShape` naming the interpolation (same
chokepoint as the literal refusal), never print struct bytes.

Pinning test: next to `run_cpp_path_fstring_container_literal_refusal` in
`test_gimple_generator_runner.py` — a `MOJO_CORO=cpp` compile-and-run row for
`xs = [1, 2]; print(f"{xs}")` against CPython's `[1, 2]` (and the dict twin).

Filed 2026-11-10 while fixing the literal case; same function, deliberately not
folded into that change because the correct fix needs a container repr in this
emitter. The literal-refusal pinning tests are
`run_cpp_path_fstring_container_literal_refusal` in
`test_gimple_generator_runner.py`.
