# CODEGEN: self-host cannot type a float subclass value (`_MojoFloat8Value`) beside a float

The float8 refusal fix (landed by `bug-land-gpu-offload-validation-modular-3`, the
`work/bug-land-gpu-offload-validation-modular-3` branch) adds `_MojoFloat8Value`,
a `float` **subclass** in `myinterpreter.py`, and makes `_MojoScalarType.__call__`
return one for the float8 family:

    def __call__(self, x=0):
        if self._spelling is not None:
            return _MojoFloat8Value(self._spelling, x)   # a float subclass instance
        return float(x) if self._is_float else int(x)    # a plain float / int

That is correct for the two paths the fix targets (the python3 interpreter and the
kgen compiled path, pinned 7/7 by `test_regress_gpu_offload_validation_modular_part8.py`).
It breaks a THIRD path: the SELF-HOST, which compiles `myinterpreter.py` itself.

## Symptom

`python3 test_gimple.py` fails one case, the only one that compiles `myinterpreter.py`
to derive a return type:

    FAIL test_handwritten_selfhost_signature_tables_match_the_source (line 12708):
    TypeError: function '_MojoScalarType___call__' returns a float beside a
    '_MojoFloat8Value *'; a tagged word can carry a float beside an
    int/str/list/tuple/bytes/None, but not beside this pointer kind
    (a box of it would be rendered by the wrong repr)

## Root cause

`_MojoFloat8Value` is a class, so `gen_module_impl`'s struct pass registers it in
`struct_field_types` (an empty field table, `module_gen.py:7104`). Both the return-type
inference and the call lowering then treat a `_MojoFloat8Value(...)` constructor call as
a STRUCT pointer, because in each of them the struct check runs before the scalar-ctor
check:

- inference: `mojo/middle/resolve_shared.py:553` (`if _fname_ctor in gen.struct_field_types:
  return f'{_fname_ctor} *'`) precedes the `_SCALAR_CTORS` arm at :598;
- lowering: `mojo/backend_gimple/emit_calls.py:5834` (same struct check) precedes the
  `_lower_scalar_ctor` dispatch at :5849.

So `_collect_return_types` sees the two arms of `__call__` as `double` (the
`float(x)` arm) and `_MojoFloat8Value *` (the float8 arm). `infra_infer._infer_return_type_core`
(`:2091`) detects a float beside a pointer and widens the return to the tagged word
`int64_t`, recording the body in `_float_mixed_return_bodies`. The emitter then boxes each
arm in `emit_stmts._box_float_mixed_return_arm` (`:3502`), which handles int/bool/float/
str/list/bytes but raises `TypeError` for any OTHER pointer kind — and `_MojoFloat8Value *`
is exactly such a kind.

The deeper issue: the self-host type lattice has no way to represent a `float` *subclass*
as a value type. It can name `double`, `int64_t`, or a pointer — not "a float that is also a
`_MojoFloat8Value`". And `_MojoFloat8Value(spelling, value)` is not a standard scalar
ctor (it takes a spelling), so it cannot be routed through the existing `_SCALAR_CTORS` /
`_lower_scalar_ctor` path as-is. The float subclass is the only way the interpreter carries
the lowered spelling on the value (the coercion/operation refusal keys off
`isinstance(value, _MojoFloat8Value)`), so dropping the subclass would break the very
behaviour the fix adds.

## What was run / expected

- `python3 tools/memslot.py --gb 8 --label x -- python3 -m unittest
  test_regress_gpu_offload_validation_modular_part8 -v` → 7/7 OK (the fix works on both
  target paths).
- `python3 tools/memslot.py --gb 8 --label x -- python3 test_gimple.py` → 462 passed,
  1 failed (the case above). Expected: the self-host to type `_MojoFloat8Value(...)` as a
  `double` (its runtime value IS a float) so `__call__`'s arms join to `double`, not a
  float+pointer tagged word.

## Next step

Make the self-host represent the float subclass value, with either of:

1. **Codegen**: teach the self-host that a constructor of a class that subclasses a scalar
   (`float`/`int`) yields that scalar. Add a "scalar value subclass" answer BEFORE the
   `struct_field_types` struct check in BOTH `resolve_shared._quick_type` (:553) and
   `emit_calls`'s ctor dispatch (:5834), and make the lowering emit a `double` whose runtime
   object is the float subclass (so `isinstance(value, _MojoFloat8Value)` still holds at
   runtime). Keep the two-arg `(spelling, value)` shape. Then `__call__`'s arms join to
   `double` and no tagged word is emitted.
2. **Interpreter redesign**: carry the float8 spelling without a float subclass (e.g. keyed
   off the declared type or a side table) so `__call__` never returns a subclass instance.
   More invasive; the coercion/operation refusal sites (`_coerce_to_declared_type`,
   `_float8_operand_spelling`) would read the spelling from the new mechanism.

Either way, re-run `test_gimple.py` (whole file) plus the 7-probe regression test, and the
stdlib compile (the integrator gates on it). The python3 and kgen halves are already green;
only the self-host (compiled `myinterpreter.py`) is red.

Quick test that pins this: `python3 tools/memslot.py --gb 8 --label x -- python3
test_gimple.py` (the `handwritten_selfhost_signature_tables_match_the_source` case) —
currently red, must be green once fixed.
