# COMPILE_FAIL: Lib/runpy.py — request for member '__module__' in something not a structure or union

## Status (RESOLVED 2026-08-07)

**Builds and links successfully now.** `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/runpy.py` succeeds end-to-end in ~7s
(both `driver.compile_program`'s link mode directly, and the full CLI
path). The link failure described below (`_get_importer`/`_read_code`
undefined symbols) was root-caused and fixed in
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`
— see that doc for the full mechanism and fix (two coordinated changes
in `gimple_codegen.py`'s link-mode import-symbol registration/preamble
logic). Full 5-part quality gate passed (test_gimple.py 247/0,
test_module_cache.py 76/0, check-selfhost clean, stdlib dylib rebuild 0
skips, compile_stdlib.py 664/664 0 unexpected).

The separate `os.py: 'relpath' is ambiguous` informational note
mentioned below (a transitively-imported `os.py` falling back to
source interpretation due to a cross-module free-function-name
collision) still appears during the build but does not block it — an
intentional, already-implemented honest-refusal diagnostic, not
investigated further as part of this fix.

## Status (updated 2026-08-06, historical — link failure now fixed, see above)

Re-ran (150s timeout, one retry with a longer background run that DID
complete): current error is a LINK failure, not the stale `__module__`
GCC error below:

```
link failed: Undefined symbols for architecture arm64:
  "_get_importer", referenced from:
      _run_path_132aaf in ...o
  "_read_code", referenced from:
      __get_code_from_file_584a43 in ...o
ld: symbol(s) not found for architecture arm64
```

(A separate, informational note also appears during the same build:
`# ERROR: compiling imported module 'os' ...: 'relpath' is ambiguous`
— a transitively-imported `os.py` falling back to source interpretation
due to a free-function-name collision between two sibling modules both
defining `relpath`. This looks like an intentional, already-implemented
honest-refusal diagnostic for that specific ambiguity, not a crash —
did not chase whether it's related to the LINK failure above or purely
incidental; `os.py` falling back to interpretation doesn't by itself
explain an undefined C symbol reference from `runpy.py`'s own code.)

Root-caused: `runpy.py`'s `_get_code_from_file`/`_run_path` do
FUNCTION-SCOPED (not top-level) imports —
```python
from pkgutil import read_code
...
from pkgutil import get_importer
```
— then call `read_code(f)`/`get_importer(path_name)`. This is a second,
independent confirmed instance of the SAME mechanism found in
`bugs/COMPILE_FAIL_importlib_resources__common.md` (`from ._adapters
import wrap_spec` there) — written up in full as a new hard bug,
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`.
Not fixed here; see that doc.

## Original stale note (pre-2026-08-06, unverified)

**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

```
request for member '__module__' in something not a structure or union
```

This error pattern was tracked in:
`consolidated/COMPILE_FAIL_cc_error_request_for_member_x_in_something_not_a_structure_o.md`
(directory no longer exists as of 2026-08-06).

Source file: `/Users/mrs/net/Python-3.14.6/Lib/runpy.py`
