# CODEGEN: a set of two distinct `id()` tokens collapses to one element

Found 2026-11-20 while running `test_gimple_runner.py` (worker
`work/bug-codegen-untyped-parameter-word-kind`). PRE-EXISTING on this tree:
reproduces on a clean checkout of the base commit with none of that worker's
changes (measured in a throwaway worktree of `f781ea622`). The suite's
`gimple_id_is_an_integer` case (`test_gimple_runner.py`) fails with exactly
one differing line:

| | output |
|---|---|
| CPython 3.14 | `set 2 True True` |
| compiled | `set 1 True True` |

Everything else in the case matches, including `distinct True` on the line
BEFORE — the compiled binary is internally inconsistent: `id(a) != id(b)` is
True, yet `len({id(a), id(b), id(a)})` is 1 for two live distinct lists `a`,
`b`.

## Reproduction

```python
def show(label, x):
    print(label, isinstance(id(x), int), id(x) == id(x))

def main():
    a = [1, 2]
    b = [1, 2]
    show('list', a)
    show('list', b)
    print('distinct', id(a) != id(b))
    print('same', id(a) == id(a))
    cache = {}
    print('miss', id(a) in cache)
    cache[id(a)] = 'A'
    print('hit', id(a) in cache, cache[id(a)] == 'A')
    print('other', id(b) in cache)
    ids = {id(a), id(b), id(a)}
    print('set', len(ids), int(id(a)) > 0, id(None) == id(None))
    s = 'text'
    t = 'text'
    print('str', id(s) != id(t), isinstance(id(s), int))
    d = {int(id(a)): 'v'}
    print('int key', d[int(id(a))] == 'v')

main()
```

Measured, `python3 tools/memslot.py --gb 8 --label idbase -- python3
tools/pydiff.py <the-program>`: CPython prints `set 2 True True`, the
compiled binary prints `set 1 True True` (WRONG), all other lines equal.

## What a fix needs

`id()` of a list is a live pointer (a large positive int64). The dict half
works — `cache[id(a)] = 'A'` and `d[int(id(a))]` both round-trip, so the
dict's int64 key path hashes/compares large tokens correctly. The SET half
does not: a `MojoSet` built from two distinct large int64 tokens reports
`len 1`. So the next step is the set literal's int64 construction path
(`emit_exprs`'s set-literal lowering into `mojo_set_add_*` / the int64
`mojo_set` ctor) and the `len` read: with the dump above, check whether the
second `mojo_set_add` reports "already present" (a hash fold of the pointer
bits, e.g. truncation to a smaller word or a low-byte comparison) or whether
the token itself is the same value at both call sites (an `id()` aliasing).
The `distinct True` line argues against the latter.

## Status

Filed by the `work/bug-codegen-untyped-parameter-word-kind` worker; that
worker's change does not touch this path (its detector is inert on the
program: no parameter has a mixed-kind body proof). Not fixed here — outside
that task's scope.
