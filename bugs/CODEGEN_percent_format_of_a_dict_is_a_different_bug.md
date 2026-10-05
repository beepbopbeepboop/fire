# `'%(k)s' % d` works, `'%s' % d` does not compile — and `'%r' % d` prints two characters

Found 2026-10-04 while closing
`CODEGEN_print_of_a_container_never_frees_the_repr_it_asked_for.md`'s last
consumer (the `'%s' % xs` and `'%r' % d` spellings of a `%`-formatted
container). The leak is fixed; this is the shape the fix's own regression test
had to step around, and it is a different defect with a different mechanism.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` + `runtime/fire_runtime.c`,
against CPython on the same text.

```python
xs = [1, 2, 3]
d = {'k': 'v'}
print('%s' % xs)
print('%r' % xs)
print('%(k)s' % d)
print('%s' % d)
```

```
$ python3 fire.py run <file>          # CPython's own answer
[1, 2, 3]
[1, 2, 3]
v
{'k': 'v'}

$ <compiled>
... does not compile:
a.c:5:38: error: passing argument 2 of 'mojo_str_format_dict' makes pointer
  from integer without a cast [-Wint-conversion]
  expected 'MojoDict *' but argument is of type 'int64_t'
```

**Two failures, and the same `%` operator reaches three different lowerings.**

| shape | CPython | compiled |
|---|---|---|
| `'%s' % xs` (a list) | `[1, 2, 3]` | correct |
| `'%r' % xs` (a list) | `[1, 2, 3]` | correct |
| `'%(k)s' % d` (a dict, keyed form) | `v` | correct |
| `'%s' % d` (a dict, **module-level global**) | `{'k': 'v'}` | **does not compile** |
| `'%s' % d` (a dict, function local) | `{'k': 'v'}` | **2 characters** |
| `'%r' % d` (a dict, function local) | `"{'k': 'v'}"` | **2 characters** |

## Mechanism, in two parts

**1. The compile failure is the module-global box.** `mojo_str_format_dict`'s
second parameter is declared `MojoDict *` (fire_runtime.h:1410). A dict bound
at module scope is stored as an `int64_t` — every global in this compiler is —
and `_lower_percent`'s dict arm hands it straight through with no coercion, so
gcc rejects it. This is not new and not this doc's subject: it is why
`gimple_dict_repr_kinds_agree_with_cpython` (whose last line is
`print('%s' % d)` over a module-level dict) is **RED on this tree**, verified by
reverse-applying a finished branch and re-running it. The coercion every other
container consumer does (`_coerce_to_type('int64_t', 'MojoDict *', v)`) is
missing here and nowhere else that has been measured.

**2. The two-character answer is the dict-keyed formatter being handed a
container it has no spec for.** `'%r' % d` reaches `mojo_str_format_dict`,
whose whole job is the `%(key)…` template: it walks the format string, and for
a spec that is not `%(`, copies the `%` and its conversion character through
verbatim (fire_runtime.c's own comment: "a stray '%' in a dynamic template …
Copy verbatim and keep going"). So `%r` produces the two-character text `%r`.
Correct for a lenient reading of a template, and wrong for Python, where
`'%r' % d` is `repr(d)`.

So the two are ONE defect wearing two coats: `_lower_percent` sends a
non-keyed `%`-spec on a DICT operand to a function whose only job is keyed
formatting. The list cases are right because a list operand takes the ordinary
`_format_percent_spec` route (which calls `_stringify_value` / `_repr_value`),
and `'%(k)s' % d` is right because it IS the keyed form.

## Exact next step

1. **In `_lower_percent` (emit_exprs.py), route a dict operand with a
   NON-KEYED spec away from `mojo_str_format_dict`.** The dispatch already
   exists for lists — `_format_percent_spec`'s `s`/`r` arms call
   `_stringify_value` / `_repr_value`, which handle `MojoDict *` through
   `_mojo_repr_dict` — so the fix is to apply the same test the list arm
   applies and only fall through to the dict-keyed primitive when the format
   string actually contains a `%(`. `mojo_str_format_dict`'s leniency for
   stray `%` is a property of a RUNTIME template; a compile-time format
   literal is decidable, and Python decides it.
2. **The module-global coercion**, for whatever still reaches the keyed
   primitive: `MojoDict *` is what the prototype says, and
   `_coerce_to_type('int64_t', 'MojoDict *', v)` is the spelling every other
   boxed container read uses. This one also un-reds
   `gimple_dict_repr_kinds_agree_with_cpython`, whose comment already says the
   case belongs in the tree.
3. Regression rows beside `gimple_percent_keyed_of_dict_repr_is_released` in
   `test_gimple_runner.py`: `'%s' % d` and `'%r' % d` for a LOCAL dict and for
   a module-level one, diffed against CPython. The local/global pair is the
   point — the two halves of this doc are two different failures and only one
   of them is a compile error, so a single-row test would pin one and leave
   the other green.

## Related

- `CODEGEN_print_of_a_container_never_frees_the_repr_it_asked_for.md` — the
  leak this shape shares with `'%s' % xs`, `f"{xs}"`, `str(xs)` and
  `repr(xs)`. Its `mojo_str_format_dict` rung is what makes the keyed form
  flat now; this doc is why the `'%r' % d` row of that fix's memory coverage
  is written `'%(k)s' % d` instead.
- `CODEGEN_dict_comprehension_repr_is_separately_broken.md` — the same
  generated `_mojo_repr_dict` walker's other known defect.
- `bugs/UNTESTED.md` §3.3: a compile failure and a wrong value are both
  invisible to a suite that only reads stdout of the cases it happens to
  name, and neither of these shapes was named.