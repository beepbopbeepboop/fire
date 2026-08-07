# COMPILE_FAIL: Lib/runpy.py — request for member '__module__' in something not a structure or union

## Status (updated 2026-08-07)

The `read_code`/`get_importer` function-scoped-import link failure
described below is now FIXED at its root cause — see
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`
for the full writeup (fixed `_parsed_import`'s inability to resolve a
plain sibling `.py` file, e.g. `pkgutil.py` next to `runpy.py`, in link
mode). Confirmed via direct inspection of the generated C
(`gimple_codegen.compile_linked()`): both call sites and their externs
now correctly read `pkgutil_read_code_<suffix>`/
`pkgutil_get_importer_<suffix>` instead of the previous bare, unresolved
`read_code`/`get_importer`.

**Still not PASS, though** — `mojo.py build Lib/runpy.py` now compiles
much further (this specific link failure is gone) but hits several
OTHER, unrelated, pre-existing bugs deeper in the now-successfully-
resolved transitive closure (`Lib/stat.py`'s `int64_t & char *`,
`Lib/posixpath.py`'s `expandvars_repl_env` struct-shape mismatch,
`Lib/operator.py`'s `__matmul__`, `Lib/dis.py`'s `void`-declared
variable, `Lib/enum.py`'s gimple-call conversion). Since `mojo.py`
already falls back from link mode to a separate inline pipeline on any
link failure, and that fallback pipeline was ALREADY hitting
essentially the same transitive-closure bugs before this fix (this file
transitively pulls in a large fraction of the Python-3.14.6 stdlib),
the file's overall build categorization is unchanged — still not PASS.
Not chased further; these are separate, independent bugs each deserving
their own investigation, out of scope for this specific fix.

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
