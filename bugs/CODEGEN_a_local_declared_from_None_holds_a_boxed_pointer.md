# A nested `def`'s local declared by `x = None` stays `int`, so the boxed pointer assigned into it is TRUNCATED

## Status

OPEN, measured, NOT fixed. Found 2026-10-04 while merging `work/bugs6-2` and
bisecting why `fire.py build fire.py` stopped building. The compile error that
led here IS fixed — `mojo/backend_gimple/emit_infra.py`'s `_len_of_boxed` and
`_repr_boxed_container` now read their subject through `_ensure_local`, so the
copy into the `int64_t` is a CAST — but the truncation that made the error
necessary is pre-existing on `master` and is untouched: the cast preserves the
truncated value faithfully rather than repairing it.

## What I ran, and what I saw

`fire.py --dump-full fire.py` on `master` (`77b24183`) and grep the emitted C
for `pinfo`:

```console
$ grep -n "int pinfo\|pinfo = (int)" fire.ci
708135:  int pinfo;
708649:  pinfo = (int)_t31;
708673:  pinfo = (int)_t40;
```

and the source it came from, `mojo/middle/coro.py`'s `_visit_call` (a nested
`def` inside `_scan_callsite_param_kinds`):

```python
    fd = None
    pinfo = None                 # <- declares `int pinfo`
    if gname in gen_names:
        pinfo = gen_params[gname]   # <- a BOXED dict: int64_t
        fd = gen_fdefs.get(gname)
    ...
    _n_positional = len(pinfo)      # <- reads the truncated value
```

`pinfo = None` is what types the local, and the type it picks is `int` — a
32-bit integer — while the value assigned into it two lines later is a boxed
`MojoDict *`. The assignment is emitted with a CAST, so it compiles:

```
int pinfo;  …  pinfo = (int)_t31;
```

and every later read of `pinfo` sees the low 32 bits of a pointer. On arm64 a
heap address is 48 bits, so the truncation is not a value that happens to
survive; the pointer is destroyed.

## What I expected

`int64_t pinfo;` and no cast — `None` is this codegen's box (an
`int64_t`-typed 0), and a local that is later assigned a boxed value has to
be declared at the WIDEST type any of its assignments reaches, exactly as a
parameter whose call sites disagree is. Note the asymmetry that makes this a
local-only bug: the SAME source at module level declares `int64_t` and is
correct. Only a nested `def`'s local takes the `int` path.

## Why it matters even where it does not crash

`len(pinfo)` on the truncated word goes down a runtime dispatch:
`mojo_is_registered_dict` compares whole pointers and says no;
`mojo_boxed_is_str` tests the pointer RANGE `[2^31, 2^47)`, which a truncated
arm64 heap address can well land inside, and then `mojo_strlen` walks it for
a NUL. So the two reachable answers are a length read from a bogus address
(SIGSEGV) and a "length" that is some string's byte count (a silent wrong
answer) — and which one you get depends on where the allocator put the dict.

`master` is not safe here either: it committed to `mojo_list_len((MojoList
*)pinfo)` unconditionally, which reads the same truncated word as a list
header. The difference between `master` and the tree that led here is only
WHICH wrong answer the truncated pointer produces.

## The reproduction, smallest form

```python
def outer(names, table):
    def visit(node, caller):
        info = None                 # declares `int info`
        key = names
        if key in table:
            info = table[key]       # a boxed dict
        if info is None:
            return 0
        n = len(info)               # reads the truncated pointer
        return n
    return visit(names, table)
```

Compiled by `gimple_codegen.compile_to_gimple` and asserted in
`test_gimple.py::len_of_a_local_declared_from_None_is_cast_into_its_int64_t_copy`
— which pins the CAST (`(int64_t)info`), not the declaration, because the
declaration is the bug this doc is about. The emitted text for the program's
nested function:

```console
$ python3 - <<'EOF'   # with the probe from this doc's next step
int info;
info = (int)_t11;
_t15 = (int64_t)info;      # <- the fix: a cast, not a reinterpreting copy
```

## The exact next step

1. Find where a nested `def`'s locals are typed from their first assignment
   and make the declared type the WIDEEST over ALL assignments to the name,
   the way `_param_ctype` already does for a parameter whose call sites
   disagree. `mojo/backend_gimple/emit_exprs.py`'s `var_decl` emission reads
   `gen.var_types[node.name]` (`emit_exprs.py:1107`) and inserts a cast on
   assignment; the type DECISION that put `int` there is upstream of it.
   A pre-pass over the function's own assignments (there is already a walk
   per function for the scalar observations, `_scalar_obs` in
   `module_gen.py`) is the natural place: a local assigned any non-scalar
   value is `int64_t`.
2. Then ASSERT the declaration, not the cast: the same test with
   `must_not_have=['int info;']`, which fails today and is the statement this
   doc is about.
3. While in there, check the other direction the truncation hides — a local
   declared `int64_t` that is assigned a `char *` truncates the same way, and
   `mojo/middle/coro.py` has several of those (`fn = None` then
   `fn = <a function value>`).

## How to confirm the fix

The program in "The reproduction, smallest form", through
`compile_to_gimple(..., do_imports=False, filename='probe.py')`, printed and
grepped:

    $ python3 .tmp/probe.py . | grep 'int info;'
    (nothing)

i.e. no `int info;` declaration at all — and `test_gimple.py` still green with
the added `must_not_have`, which is the statement that has to become true.