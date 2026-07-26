# CODEGEN: compiled `repr()`/`print()` of a list containing doubles is wrong (and can crash)

## Discovery context

Found while manually verifying the fix for
`bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md`
(cross-call scalar-contract inference now also applies to unannotated
compiled-generator parameters). Testing the "bonus" positive case — an
unannotated generator parameter that's provably `double` at every call
site, e.g. `def g(x): yield x` called only as `g(3.5)` — surfaced this
separate, PRE-EXISTING, unrelated bug: `python3 mojo.py build` on

```python
def g(x):
    yield x
print(list(g(3.5)))
```

compiles cleanly (the generator itself is now correctly typed `double`
end-to-end: the coroutine promise's `current_value`, `yield_value`,
`<base>_value`, and the C-side `mojo_list_append_double` call are all
consistently `double`) but the resulting binary **segfaults** inside
`_mojo_repr_list` / `_mojo_generic_elem_repr` when printing the list.

## Root cause (confirmed, NOT specific to generators)

`MojoList` (runtime/mojo_runtime.c) stores every element as a raw
`int64_t` slot with no per-element type tag; `mojo_list_append_double`
just `memcpy`s the double's bit pattern into that slot
(`mojo_list_append_double`, runtime/mojo_runtime.c:399). Every compiled
`print()`/`repr()` of any `MojoList *` (`_repr_value` in
gimple_codegen.py) unconditionally routes through the single generic
`_mojo_repr_list` → `_mojo_generic_elem_repr` runtime helpers emitted by
`gen_module` (around gimple_codegen.py:18280-18320), which read each slot
back out via `mojo_list_get_int` and dispatch on the bits as if they were
either a small integer, a boxed pointer to a registered nested
list/tuple, or a string pointer (`mojo_read_type_tag_safe` /
`mojo_is_registered_list`) — there is no "this list holds doubles" case
at all. A double's raw bit pattern reinterpreted this way either prints a
nonsensical integer (harmless-looking but wrong) or — if the bit pattern
happens to look like a plausible heap address — dereferences it inside
`mojo_read_type_tag_safe`, segfaulting.

Confirmed with NO generator involved at all, reproducing the same wrong
result:
```python
lst = [3.5, 2.5]
print(lst)
```
`mojo.py run` (interpreter): `[3.5, 2.5]` (correct).
`mojo.py build` + run: prints `4389869872` (garbage — the bit pattern of
3.5 reinterpreted as an integer) instead of crashing, purely because that
particular bit pattern doesn't happen to look like a registered/valid
address to `mojo_read_type_tag_safe`. Other double values crash instead,
as seen via the generator repro above (`3.5`'s IEEE-754 bits,
`0x400c000000000000`, happens to read as a plausible pointer in that call
chain and faults in `mojo_read_type_tag_safe`).

## Impact

Any compiled program that constructs a `MojoList`/tuple of `Float64`
values and prints/reprs it (directly, via f-string `{}`/`{!r}`, via
nested container repr, etc.) gets wrong output or a crash, silently and
unpredictably depending on the specific double values' bit patterns. This
is a general, pre-existing gap in the compiled path's list-repr codegen
— not introduced by, and not specific to, the compiled-generator work
this session was addressing. Left unfixed here (out of scope for the
generator-parameter-typing bug this session was tracking); flagged for a
separate fix.

## Suggested fix direction (not implemented here)

`_mojo_repr_list`'s generic per-element dispatch has no way to know a
list's declared/tracked element type at the point it's called, since
`MojoList` itself carries no type tag. Fixing this properly likely means
either (a) giving `_repr_value`'s `MojoList *` case access to the
element-type evidence gimple_codegen.py already tracks elsewhere for
other purposes (`_elem_types`/`_scan_container_elems`/
`_infer_list_elem_type`) and emitting a specialized double-aware repr
call when that evidence says `double`, or (b) giving `MojoList` an actual
per-instance (or per-element) type tag at the runtime level so
`_mojo_generic_elem_repr` can dispatch correctly without static
evidence. Given how many call sites route through the single shared
`_mojo_repr_list`/`_mojo_generic_elem_repr` runtime helpers, whichever
approach is chosen should stay a single source of truth rather than
special-casing individual call sites.
