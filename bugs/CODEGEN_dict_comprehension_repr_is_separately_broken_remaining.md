# Remaining work for CODEGEN_dict_comprehension_repr_is_separately_broken

Status: NOT FULLY FIXED; partial progress (defect 2 fixed, comprehension
arm fixed) is on master; full fix blocked on two external steps.

Measured 2026-10-26 against master (work/bug-codegen-dict-comprehension-
repr-is-s-8985).

Defects fixed (verified with `fire.py --jit`):
- Defect 2 (0 -> None): `_mojo_repr_dict` reads `kind`; passes.
- Defect 3 ASLR (tuple key as heap address): comprehension arm now calls
  `_emit_dict_pair_store`; passes (content key still quoted, separate doc).

Still broken (verified with `python3 fire.py --jit .tmp/test_repr.py`):
- Defect 1: `{i:1 for i in range(3)}` -> `{'0': 1, ...}`.
- Defect 3 remaining: tuple content quoted/None; float/bool quoted.

Root cause remains missing per-slot key-kind discriminator (`_DictSlot.
keykind`). The design was prototyped and reverted (see original doc's 2026-10-19
Status) because:

1. New runtime entry `mojo_intkey_str_transient` needs `runtime/fire_runtime.h`
   update, which moves ABI counts 684 -> 685 and requires updates in
   `formal/` (formal/model.py, formal/build.py) — outside this worker.
2. Removing `_canon_int` promotion changes `d[5]` vs `d["5"]` merge, which
   breaks `test_ptr_registry.py` groups `dict_int_keys` / `dict_set_inline`.

Next steps (in order, per original Status):
1. Remove `_canon_int` promotion + lookup redirects; update ptr-registry.
2. Land marked integer key (runtime header + ABI + two codegen sites).
3. Add `_mojo_repr_dict` unquoted arm for `keykind == 2`.
4. Separate change for float/bool key kinds.

Regression: test_dict_comprehension_repr_regress.py (fails on compiled path).
