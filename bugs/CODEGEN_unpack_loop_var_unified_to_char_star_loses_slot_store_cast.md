# CODEGEN: a loop variable unpacked from a runtime list is unified to `char *` by a later string use, and the unpack's boxed-slot store loses its cast

Status: OPEN. Filed 2026-11-12 while fixing the `gen_module_impl` `char *` ← `int64_t` import-extern clobber (that doc is deleted with its fix); the one remaining error of its shape in the reduced single-module repro of `mojo/backend_gimple/module_gen.py` is this, and it is present before and after that fix — a local type-unification defect with no cross-module element.

## Symptom

`mojo/backend_gimple/module_gen.py:13765`:

```python
for _i, (_pn, _pt) in enumerate(getattr(s, 'params', None) or []):
```

`_pn` is a list element read back from a runtime pair (a boxed `mojo_list_get_int` slot) and is later used as a string (`_pn.startswith('**')`). Whole-function unification declares the loop variable `char *` (from the string use), but the unpack store is emitted UNCAST:

```c
char * _shadow344__pn;               /* declaration, from the string use */
...
_t47043 = mojo_list_get_int (_t47041, 0);
_shadow344__pn = _t47043;            /* error: assignment to 'char *' from
                                        'int64_t' ... [-Wint-conversion] */
...
_t47047 = (char *)_t47045;           /* the string use DOES cast */
mojo_str_startswith (_t47047, ...);
```

gcc: `assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]`. The slot's `int64_t` IS the `char *` (a string slot is the pointer), so the cast the string use carries is the correct one — the unpack store needs the same cast the read side of the unification gets.

## Scope

1. When a local is unified to a pointer type and a use emits a cast, the boxed slot-LOAD store into that local must carry the same cast (or the declaration must stay `int64_t` with the string use casting — one consistent direction).
2. Reduce to a single-file program (`for i, (a, b) in enumerate(pairs): a.startswith(...)` over a list of string pairs) and add a regression test with the gcc `-fgimple -Os -g -ftrivial-auto-var-init=zero` verdict.

## Done when

The reduced program compiles and runs to CPython's answer. A worker does not run the self-host build; say so.
