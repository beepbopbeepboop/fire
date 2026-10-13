# `str.partition` / `str.rpartition` do not mark their result as a tuple

PRE-EXISTING defect: the `bytes` half of the same pair marks its result and
the `str` half does not.

## What I ran

A differential program against CPython, built and run through the compiled
path (`gcc -fgimple -o exe file.c runtime/fire_runtime.c`, the harness
`test_gimple.py`'s `isinstance_of_list_emits_gimple_safe_predicates` uses):

```python
def probe(x):
    if isinstance(x, list):
        print("list")
    elif isinstance(x, tuple):
        print("tuple")
    else:
        print("other")

probe([1, 2])
probe(('a', 'b'))
probe(b'a=b'.partition(b'='))
probe('a=b'.partition('='))
probe(7)
```

## What I saw

    $ python3 .tmp/probe.py
    list
    tuple
    tuple
    tuple
    other
    $ .tmp/probe.exe
    list
    tuple
    tuple
    list          <-- the str partition result, WRONG
    other

The fourth line is the defect. The `bytes` result is recognised as a tuple
because `mojo_bytes_partition_go` marks it; the `str` result is not, so
`isinstance('a=b'.partition('='), tuple)` is `False` and
`isinstance(..., list)` is `True` on the compiled path. CPython says the
opposite.

## Why

`runtime/fire_runtime.c`'s `mojo_str_partition` and `mojo_str_rpartition`
build a `MojoList *` and `return l` on every arm, with no
`mojo_mark_as_tuple`. The `bytes` pair right beside it,
`mojo_bytes_partition_go`, calls `mojo_mark_as_tuple(l)` before every one of
its three returns — and its own comment says why:

> partition/rpartition -> a 3-element TUPLE (head, sep, tail), which is a
> MojoList * carrying the mojo_mark_as_tuple marker — the same shape a tuple
> LITERAL lowers to […] It used to return an unmarked list, so
> `print(b'a=b'.partition(b'='))` showed `[b'a', b'=', b'b']` where CPython
> shows `(b'a', b'=', b'b')`.

That fix was applied to the `bytes` half and not the `str` half. There is no
separate tuple container struct, so the marker is the ONLY thing that
distinguishes the two, and `mojo_is_registered_list` cannot see it. The
consequence is wider than the repr: with the marker absent,
`mojo_require_mutable_list` (which refuses to mutate a marked list, the way
CPython refuses to mutate a tuple) lets the result be mutated, so
`p = 'a=b'.partition('='); list.append(p, 'x')` succeeds where CPython raises
`AttributeError`.

The codegen's pointer-typed `isinstance(x, list)` lowering already excludes
the marker, and the boxed runtime `mojo_isinstance`/`mojo_isinstance_p`
`type_id == 5` arm was likewise repaired to exclude it. This is the marker
never being SET by the `str` partition, which is upstream of both: with the
marker set, every check answers correctly with no further change.

## Expected

`probe('a=b'.partition('='))` printing `tuple`, and the `str` spellings
behaving identically to the `bytes` ones.

## Next step

Add `mojo_mark_as_tuple(l);` before each of `mojo_str_partition`'s and
`mojo_str_rpartition`'s returns in `runtime/fire_runtime.c` — the same
three-arm shape `mojo_bytes_partition_go` already has. Then extend the
differential case above to cover all three `str` arms (separator found,
separator absent, empty separator), because `mojo_str_partition` has an
empty-separator arm the `bytes` version raises on, and a mark placed on only
the fall-through return would leave two of the three unmarked. `split`,
`rsplit` and `splitlines` are worth auditing in the same pass: they return
lists, so they must NOT be marked, and the audit is what distinguishes "add the
mark in the right three places" from "mark everything that returns a
MojoList".
