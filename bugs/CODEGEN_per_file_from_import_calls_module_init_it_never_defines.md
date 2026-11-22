# CODEGEN: a per-file `from M import f` importer calls `M_init`, which the per-file compile of `M` never defines

Found 2026-11-22 while probing the class-body shapes of the module-alias read. Pre-existing:
reproduced on the tree before the module-alias fixes in the same branch.

## Repro

    # helper.py:  def double_it(x: int) -> int: return x * 2
    # main.py:
    from helper import double_it
    print(double_it(21))

Compile both through `build_stdlib_dylib.compile_module_to_c` (`do_imports=False`), compile each
with `-fgimple`, link with `runtime/fire_runtime.c` and a trivial `main`:

    ld: symbol(s) not found: "_helper_init", referenced from: __main_toplevel in main.o

`main.c` declares `extern void helper_init (void);` and calls it from `main_init`/`_main_toplevel`.
`helper.c` has no `helper_init` (it has no top-level statements; its only top-level code is the
`def`).

## Expected

Either the importer does not reference an init the definer does not emit, or the per-file compile of
a def-only module emits an empty `<mod>_init`. Which side owns the contract is the open question: the
driver (`fire.py build`, `do_imports=True`) may already link the init away; the per-file harness does not.

## Next step

1. Find where the importer's `extern void <mod>_init` is emitted for a `from` import
   (`grep -rn "_init (void)" mojo/backend_gimple`) and where the definer's `<mod>_init` is emitted
   (`module_gen`'s init pass), and check which condition each one tests.
2. Make the two agree (preferred: the definer always emits its init, even when empty, when the
   importer will call it; or the importer's call is gated on the definer having top-level code).
3. Quick test: add a `from helper import double_it` case to `test_codegen_module_alias_function_value.py`
   (or a sibling file) that links and runs.
