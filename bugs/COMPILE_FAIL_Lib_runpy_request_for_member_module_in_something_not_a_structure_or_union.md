# COMPILE_FAIL: Lib/runpy.py — request for member '__module__' in something not a structure or union

## Status (updated 2026-08-07, final): RESOLVED — builds and links clean

**Confirmed via a direct rebuild in the final state: `python3 mojo.py
build Lib/runpy.py` succeeds, 0 errors.** The `read_code`/`get_importer`
function-scoped-import LINK failure described below is fixed at its
root cause by "Mechanism 1" of
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`
(the link-mode preamble now emits a weak stub instead of a bare,
definition-less `extern` for a function-scoped import with no buildable
signature).

A SEPARATE fix ("Mechanism 2" in that same doc, making `_parsed_import`
genuinely resolve and inline `pkgutil.py`'s real body instead of
stubbing around it) was also implemented and briefly landed, and DID
get past this file's original link failure too — but before reaching a
full pass it surfaced a large, unrelated error set further into the
now-successfully-resolved transitive closure (`Lib/importlib/abc.py`-
internal redefinition/conflicting-type errors, an `implicit declaration
of function '_write_atomic'`, plus earlier-suspected `Lib/stat.py`/
`Lib/posixpath.py`/`Lib/operator.py`/`Lib/dis.py`/`Lib/enum.py` issues
from an even earlier diagnosis pass). That fix was reverted after being
found to regress an unrelated THIRD file
(`Lib/importlib/__init__.py`) — see the hard-bug doc's own Status
section for the full story. With it reverted, this file no longer
reaches that deeper error set at all — Mechanism 1's stub-based
approach never actually inlines `pkgutil.py`'s real body, so those
deeper, unrelated bugs (real, but out of scope) are simply never
reached by this file's own build.

The separate `os.py: 'relpath' is ambiguous` informational note
mentioned below (a transitively-imported `os.py` falling back to
source interpretation due to a cross-module free-function-name
collision) no longer applies — that specific ambiguity was
independently fixed earlier this session
(`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`'s
follow-up fix).

## Original status (2026-08-06, superseded above for the read_code/get_importer mechanism)

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
