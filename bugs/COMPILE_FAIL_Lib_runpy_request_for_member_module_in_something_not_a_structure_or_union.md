# COMPILE_FAIL: Lib/runpy.py — request for member '__module__' in something not a structure or union

## Status (updated 2026-08-07)

The `read_code`/`get_importer` function-scoped-import link failure
described below was root-caused, and a fix was implemented and
verified (confirmed via direct inspection of the generated C: both
call sites and their externs correctly resolved to
`pkgutil_read_code_<suffix>`/`pkgutil_get_importer_<suffix>` instead of
the previous bare, unresolved names) — but the fix was ultimately
REVERTED after it was found to regress a THIRD, unrelated file
(`Lib/importlib/__init__.py`, previously passing). Full writeup,
including exactly why it was reverted and what a future attempt needs
to additionally solve, in
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`.
This file (`runpy.py`) is still COMPILE_FAIL, unchanged from before.

Separately, even with that fix applied (before it was reverted),
`mojo.py build Lib/runpy.py` would NOT have reached PASS anyway — it
compiled further (past the `read_code`/`get_importer` link failure)
but then hit several OTHER, unrelated, pre-existing bugs deeper in the
newly-resolved transitive closure (`Lib/stat.py`'s `int64_t & char *`,
`Lib/posixpath.py`'s `expandvars_repl_env` struct-shape mismatch,
`Lib/operator.py`'s `__matmul__`, `Lib/dis.py`'s `void`-declared
variable, `Lib/enum.py`'s gimple-call conversion) — so this specific
file was never going to be a P/F flip from that fix regardless of the
revert.

`Lib/operator.py`'s `__matmul__` item above IS now fixed separately
(`_lower_matmul`'s blind non-struct-operand call, see
`bugs/COMPILE_FAIL_Lib_socket_request_for_member_module_in_something_not_a_structure_or_union.md`
for the full writeup) — confirmed it no longer appears anywhere in a
fresh `mojo.py build Lib/runpy.py` run. Doesn't change this file's
overall status: it's currently blocked earlier, by the (reverted,
still-open) `read_code`/`get_importer` link failure above, before ever
reaching operator.py's compile at all in the link-mode attempt; the
`build_executable` fallback (which DOES reach operator.py) still hits
the SAME `Lib/stat.py`/`Lib/posixpath.py` bugs regardless.

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
