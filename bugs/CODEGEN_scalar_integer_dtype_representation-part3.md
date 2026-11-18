# CODEGEN: imported overload choice on real integer types (`mulhi` / FastDiv) (part 3)

## Goal

Once parts 1-2 give an integer `Scalar[dtype]` its real C type, stop refusing
the exact-C-type overload choice inside a SPECIALISED generic, so the
`FastDiv[dtype]` shape calls the overload its arithmetic needs.

The production case is `stdlib/std/utils/fast_div.mojo`: in
`FastDiv[dtype]`, `mulhi(self._mprime.cast[.uint32](), other.cast[.uint32]())`
must bind `mulhi(UInt32, UInt32)`. Today it binds `mulhi(Int64, Int64)`,
which is the last undefined `_std_` name in the dylib
(`_std__gpu_intrinsics_mulhi__1_0_5_Int64_1_1_5_Int64`).

- `mojo/backend_gimple/emit_infra.py:6273` `_erasure_free_context` returns
  False for any body inside a generic function or struct, so
  `_elaborate_overload_call` (line 6318) never passes the lowered argument C
  types to `_imported_overload_call_symbol` and falls into the elaborated
  path, which picks the Int64 overload in a body that is in fact being
  emitted for a concrete `DType.uint32` instance.
- Narrow that guard rather than deleting it: an exact match on the lowered
  argument C types is safe exactly when the enclosing generic has been
  substituted to concrete types. Measure how the current specialised instance
  records its concrete bracket arguments (the emitted name is already
  `Fd_5_dtype_17_DType_x002Euint32_f`, so the instance is concrete) and gate
  the call on that, keeping today's refusal for a body still emitted with a
  symbolic/erased dtype parameter. Update the comment at lines 6319-6322
  that states the old reason.
- Keep `_choose_overload_symbol`'s exact-match rule: two candidates that both
  match exactly must still keep the stub/elaborated path, not guess.
- No change to `_imported_overload_call_symbol`'s arity-only path, and no
  change to a non-generic caller.

## Acceptance

- A two-module mirror of the production shape (the real `std.utils.fast_div`
  is external to this worktree, so keep the quick test local):

      # home.mojo
      def mulhi(a: Int64, b: Int64) -> Int64:
          return 0
      def mulhi(a: UInt32, b: UInt32) -> UInt32:
          return UInt32((UInt64(a) * UInt64(b)) >> 32)
      struct Fd[dtype: DType]:
          var m: Scalar[dtype]
          def __init__(out self, m: Scalar[dtype]):
              self.m = m
          def hi(self, other: Scalar[dtype]) -> UInt32:
              return mulhi(self.m.cast[DType.uint32](), other.cast[DType.uint32]())

  imported by a caller that instantiates `Fd[DType.uint32]` compiles, and the
  home module's emitted specialised `..._hi` body calls the mangled
  `uint32_t mulhi (uint32_t, uint32_t)` symbol. It does not call the
  `int64_t mulhi (int64_t, int64_t)` symbol.
- `python3 test_import_overload_choice.py` still passes (the non-generic
  choice is unchanged).
- In the production tree the dylib's undefined list no longer carries
  `_std__gpu_intrinsics_mulhi__1_0_5_Int64_1_1_5_Int64`; that is the
  integrator's `stdlib-dylib` observation, not the quick test.

## Done when

Add `test_scalar_integer_overload_choice()` to `test_import_overload_choice.py`
(its `test_import_overload_by_argument_type` shows the temp-dir two-module
build with `build_stdlib_dylib.compile_module_to_c`; the new function builds
the `mulhi`/`Fd` mirror, discovers each overload's symbol from the home C's
definitions rather than hard-coding hashes, and asserts the `hi` body names
the UInt32 one and not the Int64 one); add it to that file's `__main__` chain
as the other three tests are. Run, from the worktree root:

    python3 -c "import test_import_overload_choice as t; t.test_scalar_integer_overload_choice()"

It prints `PASS` and exits 0.
