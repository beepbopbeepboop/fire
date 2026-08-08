# COMPILE_FAIL: Lib/importlib/metadata/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py`

## Status (updated 2026-08-07, Track B continuation session)

Re-ran fresh: `error: cannot convert to a pointer type` (issue #2 below,
`self.metadata['Name']`/`self.metadata['Version']`) is now FIXED — see
"2. FIXED" below. Still blocked on the OTHER, unrelated class of error
(issue #1/#3, "invalid conversion in return statement" — bare `return`
vs. a real value in the same function, a known, separately-tracked
type-inference gap): now 3 remaining sites (`_read_files_egginfo_
installed` returning `text and text.splitlines()` / `map(...)`, and
`PathDistribution._name_from_stem`'s tuple-unpack-from-call case). Not
attempted here — same architectural area flagged as high-regression-risk
in issue #1's own writeup below (unchanged from the prior session).

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

### 2. FIXED (2026-08-07): `self.metadata['Name']` — subscript on an un-invoked bound-method/property value

```
error: cannot convert to a pointer type
```
at:
```python
@property
def name(self) -> str:
    """Return the 'Name' metadata for the distribution package."""
    return self.metadata['Name']
```
where `metadata` (line 448-449) is a `@property` defined on the BASE
class `Distribution`, inherited (not overridden) by `PathDistribution`.

**Root cause (confirmed via the generated `.ci`)**: `self.metadata`
(accessed WITHOUT call syntax) lowers via `_lower_MemberExpr` /
`_lower_bound_method_value` (gimple_codegen.py) to a deferred, un-called
`MojoBoundMethod *` value — correct when the consuming context is itself
a call (`self.metadata()`), and this codegen has no `@property`-specific
handling anywhere (confirmed: zero hits for `'property'` in
`gimple_codegen.py`/`mojo_compiler.py` — bare 0-arg attribute access is
generically deferred to a `MojoBoundMethod`, with auto-invocation only
happening at whatever consumes it). `_lower_subscript` (gimple_codegen.py,
`_lower_subscript`) had no case at all for a `MojoBoundMethod *` base:
the generated `.ci` showed `self.metadata` boxed into a
`MojoBoundMethod *` via `mojo_bound_method_new`, and the subscript then
fell through to the generic "opaque/unknown pointer type" fallback,
which:
1. treated the un-called `MojoBoundMethod *` itself as an array base
   pointer via the generic `_mojo_at_<Type>` GIMPLE pointer-arithmetic
   helper (`_mojo_at_MojoBoundMethod`, a struct with no such element
   shape) — the actual "cannot convert to a pointer type" GCC error, and
2. even set up to reinterpret the subscript's STRING key (`'Name'`) as a
   raw INTEGER byte offset (`_t6 = (int64_t) _t5;` where `_t5` was the
   string literal's pointer) — a silent miscompile, not just a compile
   error, had the arity happened to align instead.

**Fix**: `_lower_subscript` (gimple_codegen.py) now checks for
`ot == 'MojoBoundMethod *'` immediately after lowering the subscript's
object expression, and if so, calls the bound method with 0 args first
(via `mojo_bound_method_call_0`, using `_bound_method_ret_types` — keyed
by the bound-method value's own C temp name, already populated by
`_lower_bound_method_value` — to recover its real return type), THEN
proceeds with the existing subscript dispatch logic on the ACTUAL
returned value/type. This generically fixes `self.prop[key]` for any
0-arg property/method (inherited or not) followed by a subscript,
without touching `_signature_ctypes`/call-argument-packing machinery at
all (a deliberately different, narrower code path from the held-back
`bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
task #142 — NOT the same fix, NOT touching the same function).

Verification: both `Distribution.name`/`Distribution.version`'s
`self.metadata['Name']`/`self.metadata['Version']` sites now compile
(the "cannot convert to a pointer type" errors are gone; this file's
build now fails only on the separate, pre-existing issue #1/#3 "invalid
conversion in return statement" cluster below). Full quality gate run
clean: `test_gimple.py` (247/247), `test_module_cache.py` (76/76),
`make check-selfhost`, from-scratch stdlib dylib rebuild (0 `skip`
lines), `compile_stdlib.py -j8` (664/664, 0 unexpected). Corpus spot-
check (collections/__init__.py, weakref.py, zipfile/__init__.py) showed
no change in error signature/count vs. before the fix — all still fail
on their own separate, already-documented issues.

### 3. Not investigated: other "invalid conversion in return statement" (line 575)

Not yet looked at — a third, separate site with the same class of error
as issue #1's symptom but not confirmed to share the same root cause.
