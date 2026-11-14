# Consumer program importing `c_common/tables.py` fails to link

Part 1 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`.
Class: easy (self-contained: fix parameter typing for imported-module generator compile and surface the underlying g++ diagnostic).

## Goal

A consumer program that imports and uses `c_common.tables.read_table` must build and link successfully, the same way a consumer can already build and run when the module is compiled as the root file. The imported-module compiled-generator path must produce the same parameter typing evidence as the root compile for `read_table` (so the `with _open(...) as infile:` assignment type-checks in the generated C++), and a failure to compile the link-mode inline-module C++ unit must report g++'s stderr instead of surfacing later only as undefined `_mojogen_*` symbols.

## Acceptance

- Building a consumer that does `from c_common.tables import read_table` and iterates `read_table(...)` over a tab-separated file with a header succeeds (`fire.py build` exits 0) and the resulting binary runs and prints the expected rows (CPython's answer for the same input).
- The parameter C type for `read_table`'s `infile` (and any other parameter affected by `isinstance(..., str)` / pointer evidence) is consistent between compiling `c_common/tables.py` as the root file and compiling it as a transitive import: the ptr-evidence scan is a property of the parsed module, not of whichever generator compile happened to be the root.
- When g++ fails while compiling the link-mode inline-module C++ unit, the reported error includes the compiler's stderr (or the captured failing output) so the real cause is visible, rather than only a later link failure with undefined generator symbols. The diagnostic must not be swallowed.

## Done when

File: `test_gimple_tables_consumer_link.py` (repo root).

Command: `python3 test_gimple_tables_consumer_link.py`

It builds a consumer program that imports `c_common.tables.read_table` (from the c-analyzer sources) and runs it over a small TSV; the build/link must succeed and the program must print CPython's expected rows. The test currently fails/skips-then-fails-on-build until the fix lands; it must pass.

## Notes

Background and measured repro (sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`): `fire.py build -o _check_rt _check_rt.py` for a driver importing `c_common.tables.read_table` currently fails to link with undefined `_mojogen_c_common_tables_read_table_{start,resume,value,destroy}` and `_mojogen_c_common_tables__fix_read_default_{start,resume,value}`. `MOJO_DEBUG=1` shows `failed to compile link-mode inline-module cpp unit` (g++ exit 1) but `_compile_link_inline_cpp_unit` swallows stderr; compiling the left-behind `.tmp/mojo_linkmod_cpp_*/link_inline_module.cpp` by hand shows `invalid conversion from 'int64_t' to 'char*'` at the `with _open(...) as infile:` assignment inside the imported-module compile of `read_table`, because `infile` is typed `char *` in the import compile but as the `int64_t` word in the root compile (ptr evidence from `isinstance(infile, str)` is not applied the same way). Do not "fix" the typing divergence by casting the assignment to the local's declared type in the with-open arm: after `with _open(...) as infile:` the local must hold the runtime file word.

## Status (2026-11-14)

- Fixed: `mojo/backend_gimple/cpp_async.py` now treats a cpp-path generator parameter as the runtime `int64_t` word when the module's own `_ptr_evidence` shows `isinstance(p, str|bytes)` even if call-site/type inference narrowed it to `char *` or a container pointer (so `read_table`'s `infile` stays a word in imported-module cpp units regardless of how a consumer calls it).
- Fixed: `mojo/backend_gimple/module_gen.py` xmod generator param-hint merge now respects the same module-local ptr-evidence word typing and does not narrow such params from importer hints.
- Fixed: `mojo/backend_gimple/emit_infra.py` now reports g++ stderr/stdout unconditionally when compiling a link-mode inline-module C++ unit fails (the diagnostic is no longer swallowed behind `MOJO_DEBUG`).
- Verified: `python3 tools/memslot.py --gb 8 --label lm-path -- python3 -c "import test_link_mode,sys; sys.exit(0 if test_link_mode.test_imported_module_path_word_generator_unit_compiles() else 1)"` -> PASS. `python3 -c "import test_link_mode; assert test_link_mode.test_link_inline_cpp_unit_failure_reports_compiler_stderr()"` -> PASS (cpp_unit_diagnostic). Repros: a consumer that passes a string path or a list to `c_common.tables.read_table` now builds/links successfully (`fire.py build` exits 0).
- Remaining: `python3 test_gimple_tables_consumer_link.py` still fails at runtime (`Unhandled exception: bad header ''`) because the compiled generator path cannot iterate a file object (`for line in infile` / `_iter_significant_lines` over the `mojo_open_file_ex` handle yields nothing). This is the separate, already-documented issue in `bugs/CODEGEN_generator_for_over_file_object.md`; the done-when test cannot fully pass until that lowering exists. Doc left in place per rules.
