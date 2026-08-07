# COMPILE_FAIL: Lib/importlib/metadata/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py`

## Status (updated 2026-08-06)

Three issues found. One (str.partition()) has a real runtime fix landed;
the other two are documented but not fixed.

### 1. FIXED (commit 1584798): `str.partition()`/`str.rpartition()` were unimplemented

```
error: invalid conversion in return statement
```
at (`PathDistribution._name_from_stem`):
```python
name, sep, rest = filename.partition('-')
return name
```

`str.partition()`/`str.rpartition()` had NO codegen lowering at all —
any call fell to the generic "unknown char* method" stub, unconditionally
returning `int64_t 0`. Implemented both as real runtime helpers
(`mojo_str_partition`/`mojo_str_rpartition`, mirroring the existing
`mojo_str_split`/`mojo_str_rsplit` shape: build a 3-element `MojoList *`
of strings) and wired the method names into the char* method-call
dispatch. Full quality gate verified clean.

**Not fully resolved by this fix** — a SEPARATE, deeper gap remains for
this exact call shape (`a, b, c = <call>()`, not a literal tuple RHS):
`_infer_local_var_types` (gimple_codegen.py:6933), a pre-pass that scans
a function body BEFORE the real per-statement compilation to seed
`_inferred_var_types`, has a documented, DELIBERATE limitation:

```python
if (isinstance(node.value, TupleExpr) and len(node.value.elements) == len(targets)):
    elem_types = [self._quick_type(e) for e in node.value.elements]
else:
    # Unpacking a single iterable: per-element type is unknown
    # here; use the int64_t storage default, not the container.
    elem_types = ['int64_t'] * len(targets)
```

Whenever the RHS isn't a literal tuple (e.g. any function/method call
returning a tuple, including `partition()` now that it's implemented),
EVERY unpack target gets pre-seeded `int64_t`, unconditionally. This
hint later WINS over the correctly-computed type at the real
compilation site (`_assign_target`'s `hint or et`, gimple_codegen.py:
16418-16421 — `hint` takes priority whenever present). So even with
`partition()` now correctly implemented and correctly TYPE-INFERRED at
its own call site (`_tuple_elem_value` resolves `char *` correctly via
`_elem_types`), the unpack target `name` still ends up C-declared
`int64_t` — `_track_pointer_actual_type` DOES still correctly record
the real type in `_actual_types['name'] = 'char *'` (so some consumers,
e.g. a binary op, recover correctly via that side-table), but a bare
`return name` doesn't consult `_actual_types` (`_lower_IdentExpr`'s
generic fallback and `_infer_return_type`'s own shallow scan both only
look at `var_types`, i.e. the DECLARED type) — hence the function's own
inferred return type stays `int64_t`, producing "invalid conversion in
return statement" at its `-> str`-shaped real usage (or, absent an
annotation, a return-type mismatch at the CALLER).

Not fixed: `hint or et`'s priority exists for OTHER good reasons this
session hasn't fully mapped (forward-reference cases where the live
`et` isn't yet reliable) — flipping it blindly risks the same class of
broad regression already hit twice this session in adjacent shared
type-inference code. A real fix likely needs `_infer_local_var_types`
to attempt real container-element-type inference for the CALL-RETURN
case too (mirroring what `_tuple_elem_value` already knows how to do at
the real compilation site, e.g. via `self._elem_types`/`_return_elem_
types` if that pre-pass can see them yet) rather than just widening
`_assign_target`'s priority.

### 2. Not investigated: `self.metadata['Name']` — subscript on a property-returned struct

```
error: cannot convert to a pointer type
```
at:
```python
@property
def name(self) -> str:
    return self.metadata['Name']
```
`self.metadata` is itself a `@property` returning `_adapters.Message(
email.message_from_string(text))` — a user-defined struct instance, not
a built-in dict. `self.metadata['Name']` is thus a SUBSCRIPT (`__getitem__`)
call on an arbitrary struct instance — likely no generic `__getitem__`
dispatch exists for user structs in the compiled path (not confirmed;
not investigated further this session).

### 3. Not investigated: other "invalid conversion in return statement" (line 575)

Not yet looked at — a third, separate site with the same class of error
as issue #1's symptom but not confirmed to share the same root cause.
