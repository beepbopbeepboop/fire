# `p[i] op= v` on a `Pointer[Float64]` is still refused

**Area:** FORMAL (the pointer value model, augmented assignment). **Found
2026-10-07** while landing the `Pointer[Float64]` subscript work
(`FORMAL_float_pointer_subscript`, fixed 2026-11-03: subscript load and plain
store are answered; this augmented form was left refused).

## Symptom

    def bump(p: Pointer[Float64]) -> Int:
        p[0] += 1.0
        return 0

is refused at build time with `` `p[i]` reads an element of a FLOAT pointee,
and an element of this kind is answered only for a read or for a plain store of
a double: an augmented assignment, a `del` and a tuple-unpack target … ``. The
refusal is pinned by `deref_refuse_a_binary64_subscript_augmented_store` in
`test_formal_run.py`.

## Why it is refused (not a silent wrong answer)

`_emit_subscript_aug` (arm64 `formal/arm64_codegen.py`, x86-64 twin) combines
the loaded element with the value using the INTEGER opcodes
(`encode_add_xd_xn_xm` and friends, and the x86 `add`/`sub`/...), so a double
element would be added as bits. The subscript-addr call therefore passes
`element_kind_ok=False`, and `model.subscript_base_lowering` refuses. Nothing
is written, so the refusal is the safe direction.

## Expected

`p[0] += 1.0` on a `Pointer[Float64]` holding 2.0 stores 3.0 and reads back
`3`. The same for `-`, `*`, `/` (if the op set grows), and the value on either
side of the operator being a double.

## The exact next step

1. Lower the augmented float form as the desugaring the source states:
   `p[i] = p[i] <op> v`. The read of `p[i]` is already answered (`pointee_kind_of`
   gives FLOAT for the subscript), so the binary op's own kind-aware emitter
   (the one `1.0 + x` uses) does the float arithmetic — no new instruction
   class for the add.
2. Route the resulting store through the same check the plain subscript store
   uses: `_emit_subscript_store` → `M.pointer_store_lowering(target, value=<the
   BinOp node>, class_of=self._printf_arg_conversion_class)`. A BinOp of two
   doubles is `"float"`, so it is answered; a BinOp that is an integer is
   refused by `pointer_store_kind_disagreement`.
3. Dispatch: in `_emit_subscript_aug` (both backends), when
   `M.subscript_float_element(...)` is true, take the desugared path above and
   do not fall into the integer `ops` table. Non-float bases are untouched.
4. Flip the pin: `deref_refuse_a_binary64_subscript_augmented_store` becomes an
   answering row `deref_a_binary64_subscript_augmented_is_exact` on both
   architectures (`bump` then `show` printing `[3]` from a `malloc`'d 2.0).

Quick tests: the pinned row above, plus `test_formal_run.py`'s
`POINTER_DEREF_CASES` group (run by name, as in the `FORMAL_float_pointer_subscript`
round).

## Also open (same area, not a silent wrong answer, noted here so it is not lost)

`model.pointer_store_kind_disagreement` returns `None` (permissive) when the
stored value's kind is UNESTABLISHED — an unannotated parameter, or a name bound
from an unclassified call. So `p.value() = n` and `p[0] = n` with `n` an
unannotated `Int` parameter store the integer's bits into a double slot, the
same denormal the `.value() = 1` refusal exists to stop. Only a literal or a
kind-established name is refused today. Deciding whether to refuse unestablished
kinds (the stricter reading the step-1 note asked for) changes `.value()` and
subscript stores together and needs the full gate, because stdlib code stores
through `Pointer[Float64]`; it belongs with that gate run, not in this change.

## Status (2026-11-03)

**Code landed, not yet closed on master.** The augmented float store is
answered on both backends:

- `formal/arm64_codegen.py`: `_emit_float_subscript_aug` (dispatched from
  `_emit_subscript_aug` when `model.subscript_float_element` holds). It takes
  the address once, reads the element's bits, evaluates the right-hand side
  into X1, moves both into D0/D1, and runs the FP operation through
  `_emit_float_op_on_vregs`, which is also the tail of `_emit_float_binary`.
- `formal/x86_64_codegen.py`: the SSE2 twin, `_emit_float_subscript_aug` over
  `_emit_float_op_on_xmm`, the tail shared with `_emit_float_binary`.
- The operator and mixed-pair decision is `model.float_binary_refusal`, read
  as-is. `%`, `//`, `**`, bitwise and mixed `Float64`/`Int` right-hand sides are
  refused by name. The integer ALU is never reached for a double element.
- `test_formal_run.py`: the pinned refusal row is replaced by
  `deref_a_binary64_subscript_augmented_is_exact` (`+= -= *= /=` on a
  `malloc`'d buffer, printing `[3 0.5 6 0.25]`) and
  `deref_refuse_a_binary64_subscript_augmented_with_an_integer`. The
  `deref_a_binary64_subscript` prefix is added to the both-architecture runner.

**Verified:** with `formal/model/__init__.py` temporarily replaced by the HEAD
side of `formal/model.py` (a shim, since reverted), all four
`deref_*subscript*` rows pass on both backends.

**Blocked on the model package, not on this code.** On the branch as committed,
`formal/model/__init__.py` (the package, which Python imports in preference to
`formal/model.py`) has no `subscript_float_element` and no `element_kind_ok`,
so every arm64 subscript store raises `AttributeError` before any float logic
runs. See `bugs/FORMAL_model_package_shadows_model_py.md`. The rows above will
stay red until that is repaired.

**Next step:** after the package repair lands, run
`python3 test_formal_run.py deref_a_binary64_subscript_augmented_is_exact deref_refuse_a_binary64_subscript_augmented_with_an_integer deref_a_binary64_subscript_store_of_a_double_is_exact deref_refuse_a_binary64_subscript_store_of_an_integer`
and, if green, delete this doc in the same commit and run
`python3 tools/dangling_doc_refs.py --ratchet`.

Still open from the same area (unchanged): an unestablished value kind
(unannotated parameter) into a `Pointer[Float64]` store is permitted by
`pointer_store_kind_disagreement`, as described above.
