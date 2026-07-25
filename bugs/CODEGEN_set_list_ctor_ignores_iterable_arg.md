# CODEGEN: `set(iterable)`/`list(iterable)` silently produce an EMPTY collection in compiled code

## Repro

```python
def f():
    s = set([1, 2, 3, 3])
    print(len(s))          # prints 0 instead of 3
    for x in s:
        print(x)            # prints nothing

def g():
    l = list([1, 2, 3])
    print(len(l))           # prints 0 instead of 3

f()
g()
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `3`, then
  `1`/`2`/`3`, then `3`.
- `python3 mojo.py build repro.py -o out && ./out`: compiles with NO error
  or warning, but silently prints `0` for both `len(s)` and `len(l)`, and
  the `for x in s:` loop prints nothing — the constructed collection is
  empty. This is a silent-wrong-result bug, not a compile failure, so it's
  especially dangerous (no diagnostic at all).

Real stdlib trigger: `Lib/test/test_type_cache.py:55` (`len(set(all_version_tags))`
where `all_version_tags` is a list) actually surfaces as a DIFFERENT,
loud compile-time error there (`error: invalid conversion in gimple call`,
`bugs/COMPILE_FAIL_test_test_type_cache.md`) rather than this silent-empty
symptom — likely because that call site's exact surrounding shape (nested
inside an f-string default-arg / assertEqual call) hits a different
downstream inconsistency stemming from the same root cause. Also found via
`Lib/test/test_largefile.py`-adjacent investigation that `list(iterable)`
has the identical bug.

## Root cause

`gimple_codegen.py`'s `_lower_builtin_set` (~line 8965-8968):

```python
def _lower_builtin_set(self, node: CallExpr) -> tuple[str, str]:
    t = self._new_val('MojoSet *', 'mojo_set_new ()')
    for a in node.args: self.lower_expr(a)
    return 'MojoSet *', t
```

and `_lower_builtin_list` (~line 8984-8985):

```python
def _lower_builtin_list(self, node: CallExpr) -> tuple[str, str]:
    return 'MojoList *', self._new_val('MojoList *', 'mojo_list_new ()')
```

Both unconditionally create a brand-new EMPTY collection and either lower
the constructor argument's code for side effects only and discard the
result (`set`), or don't even look at the argument at all (`list`) —
neither ever actually populates the new collection from the argument
iterable. Compare `_lower_builtin_dict` (~line 8970-8982), right between
them, which correctly handles being passed an existing iterable
(`mojo_dict_from_pairs` for a `MojoList *` of pairs, `mojo_dict_copy`
otherwise) — `set`/`list` never got the equivalent treatment.

`runtime/mojo_runtime.h` has no `mojo_set_from_list`/`mojo_list_copy`-style
helper for this either (grepped `mojo_set_*`/`mojo_list_*` — only
`mojo_set_add_int`/`mojo_set_add_str`/`mojo_set_union`/etc. and presumably
similar per-element list helpers exist, no bulk "copy all elements from
this generic iterable" entry point for either).

## Impact

`list(x)`/`set(x)` (used to copy or convert a collection — e.g. `list(some_tuple)`,
`set(some_list)` to dedupe, `list(other_list)` to shallow-copy) are
extremely common Python idioms. Silently producing an empty collection
instead of erroring is a correctness bug that could easily go unnoticed
(no compiler diagnostic, no crash — just wrong output), and is likely to
affect a large number of real stdlib files.

## Suggested fix

Give `set(iterable)` and `list(iterable)` the same kind of treatment
`_lower_builtin_dict` already has: when called with an argument, actually
populate the new collection from it. Since Python's `set()`/`list()`
constructors accept ANY iterable (not just another list/set — could be a
tuple, range, dict (iterates keys), generator, string, etc.), figure out
what iterable shapes this codegen already knows how to iterate generically
(check how `for x in <iterable>:` loops / comprehensions are lowered
elsewhere in `gimple_codegen.py` for the general iteration mechanism used
across different source types) and reuse that same mechanism to walk the
argument and insert each element (via `mojo_set_add_int`/`mojo_set_add_str`
dispatched by element type for `set`, or whatever the equivalent
list-append runtime call is for `list`), rather than inventing a
new, narrower iteration scheme just for this. At minimum, handle the common
`MojoList *` argument case (list/tuple-backed) correctly; use your
judgment (per CLAUDE.md, favor the production-quality general fix over a
narrow one, but don't over-engineer past what this codebase's existing
iteration infrastructure already supports elsewhere) on how broadly to
support other iterable argument types in one pass.
