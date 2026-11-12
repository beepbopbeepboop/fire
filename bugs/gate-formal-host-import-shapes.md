# Gate: formal-host-import-shapes is red on master

**Job:** `formal-host-import-shapes` (`python3 test_formal_host_import_shapes.py`, registered in `tools/suite.py`).
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

## Done so far (this branch)

- Dead host imports removed: `import inspect` in `formal/arm64_proof_gen.py`, `subprocess` in
  `test_formal_container_stride_pin.py`, `from types import SimpleNamespace` in
  `test_formal_frame_method_finder.py`. The job's `test_the_whole_tree_has_no_dead_host_import` passes.

## Still red (2 cases)

1. **datetime is still used live.** `test_ratchet_datetime_is_not_imported_again` fails (files 3, live 1).
   The live use is `tools/generate_dashboard.py`: `from datetime import datetime` (line 8) and
   `datetime.now().strftime('%Y-%m-%d %H:%M')` (line 782). Fix: format with `time.strftime('%Y-%m-%d %H:%M')`
   and drop the import. Then the row is dead and the case passes.

2. **importlib.util row names differ.** `test_importlib_util_row_names_include_find_spec` expects the row to
   name `find_spec`, `module_from_spec` and `spec_from_file_location`. The live row names only
   `module_from_spec` and `spec_from_file_location` (6 files). `find_spec` still appears in
   `myinterpreter.py`, `formal/imports.py`, `mojo/backend_gimple/emit_resolve.py`, `tools/formal_stdlib_reach.py`,
   `test_formal_imports.py` and `test_formal_link_accounting.py`.
   **Decision for the owner:** either `find_spec` left the swept corpus (the test's pinned names are stale, so
   update the test), or a sweep file that should list it is missing. Do not fix this by editing code until that is decided.

## Done when

`python3 test_formal_host_import_shapes.py` passes on master, with this doc deleted in the same commit
and `tools/dangling_doc_refs.py --ratchet` clean.
