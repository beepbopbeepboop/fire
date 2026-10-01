# Compiled `for` target: a bare 1-tuple and a parenthesised single name are the same AST

**State: OPEN. NOT fixed. Pre-existing, and now more reachable than it was.**

`fire_compiler.py`'s `_parse_for` / `_parse_unpack_target` reduce both of
these to the IDENTICAL target string `"(a)"`:

    for (a,) in b:     # 1-tuple target — each item is unpacked
    for (a) in b:      # parenthesised NAME — binds the whole item

Python distinguishes them, and so must the compiler. They don't, so the
compiled path silently computes the wrong answer for the second shape.

## What I ran and what I saw

Compiled path is `python3 fire.py build` (GIMPLE); CPython 3.14 alongside.
Repro:

```python
def main():
    for (a) in [(1,), (2,)]:
        print(a)

main()
```

```
$ python3 t_for2.py          # CPython
(1,)
(2,)
$ python3 fire.py run t_for2.py   # myinterpreter.py
(1,)
(2,)
$ python3 fire.py build t_for2.py && ./t_for2.exe   # compiled
1
2
```

So `for (a,) in b:` — the shape the fix deliberately reuses `"(a)"` for —
compiles AND runs, exits 0, and prints `1` where CPython prints `(1,)`. No
error anywhere: the worst kind of failure. The interpreter is wrong the same
way (it binds the whole item, matching CPython by accident on this input, but
for the wrong reason — see `myinterpreter.py`'s
`_bind_comprehension_target`, which strips the parens, finds no comma, and
takes the single-name branch).

AST evidence:

```
>>> for (a) in b:  -> target = '(a)'
>>> for (a,) in b: -> target = '(a)'
>>> for a, in b:   -> target = '(a)'    # after commit b67c170e
```

## Why the obvious fix is wrong

Emitting a distinct spelling for the 1-tuple (`"(a,)"`, or the bare
`"a,"`) does disambiguate — but a trailing comma then leaves an EMPTY name
after the split, and every consumer splits the target independently:

    mojo/backend_gimple/cpp_async.py:1103        for part in s[1:-1].split(',')
    mojo/backend_gimple/cpp_core.py:5661         _split_top_level_commas(target[1:-1])
    mojo/backend_gimple/emit_infra.py:3254       ',' in inner_str   (list loop)
    mojo/backend_gimple/emit_infra.py:3473       [v.strip() for v in _inner_str.split(',')]
    mojo/backend_gimple/emit_loops.py:722, 830, 1232, 1361, 1418, 1511
    mojo/backend_gimple/emit_resolve.py:2376, mojo/backend_gimple/emit_stmts.py:335
    mojo/middle/module_shared.py:231, mojo/middle/boundnames.py:68
    myinterpreter.py:5348                        [n.strip() for n in name.split(',')]

`['a', ''].split` semantics would try to bind a variable literally named
`''` at eleven of those sites, so the change cannot be made in the parser
alone — and dropping the empty element at each site by hand is exactly the
"parallel implementations" drift CLAUDE.md warns against.

## Next step

1. ONE splitter, in `fire_compiler.py` next to the `ForStmt` definition that
   owns the representation — e.g. `for_target_names(target_str) -> list[str]`
   — that strips the outer parens, splits on top-level commas, and drops
   empty names (a trailing comma is the only thing that can produce one, and
   a bare `for (a, b)` can never). `mojo/middle/types.py`'s
   `_unpack_target_leaf_names` is the closest existing thing and is already
   bracket-aware; the new helper differs only in being non-recursive and
   dropping empties, so the two should be reviewed together rather than
   left as a third variant.
2. `_parse_unpack_target` emits `"(a,)"` for a 1-element tuple target and
   keeps `"(a)"` for a parenthesised single name.
3. Route every site in the list above through the helper. Each one then needs
   a read: they are not interchangeable (some pick a per-slot accessor, some
   only need names), so the helper should return names and each call site
   keep its own slot/type logic.
4. Regression: a CPython-comparison test per engine (compiled binary +
   `myinterpreter.py`) asserting BOTH shapes —
   `for (a,) in [(1,), (2,)]` prints `1`/`2` and `for (a) in [(1,), (2,)]`
   prints `(1,)`/`(2,)`.

`mojo/middle/types.py`'s `_declared_vars_body` and
`mojo/middle/boundnames.py` also read for-targets; a wrong spelling there
would declare a variable named `''`, which is a distinct (and louder)
failure worth checking explicitly in step 3.
