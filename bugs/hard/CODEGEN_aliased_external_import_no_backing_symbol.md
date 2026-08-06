# HARD BUG: calling a name imported (possibly aliased) from an external/relative package this compiler doesn't resolve

## Status

Unfixed. Genuinely out of scope for a targeted patch — needs real external-
package / relative-import resolution, which this compiler does not have.

## Symptom class

`load_module()` (`module_loader.py`) only resolves imports from this
compiler's own tracked Mojo stdlib/test set. Any import from something else
— real Python's `os`/`sys`, a relative import (`from . import x`), or any
third-party/unmodeled package — raises, and `gen_module`'s `FromImportStmt`
handling catches that exception and moves on with no real signature for the
imported name(s).

When such a name is later **called**, there is no real C symbol backing it
anywhere in the compiled output, so the call fails one of two ways:

- `implicit declaration of function 'X'` — nothing declares `X` at all.
- `conflicting types for 'X'` — `X` collides with something else this
  compiler already emits under that exact name (most commonly `main`,
  since `<program>`'s own synthesized C entry point is *also* literally
  named `main`).

This is a strictly different, later-stage failure than the bug fixed by
commit 12ff719, which only fixed the *narrower* problem of such a call
being wrongly *redirected* to this module's own synthesized entry point.
After that fix, calls like these no
longer produce the wrong, misleading "conflicting types for '_gimple_main'"
diagnostic — but they still don't compile, because the callee genuinely
doesn't exist as compiled code.

## Minimal repro

```python
# aliasmain.py / aliasmain.mojo
from os import getcwd as main
main()
```

Compiling this (`python3 mojo.py build aliasmain.mojo`) now correctly avoids
redirecting the `main()` call to the synthesized entry point, but fails with:

```
aliasmain.mojo:10:5: error: conflicting types for 'main'; have 'int(int, const char **)'
```

(`getcwd` is unresolved since `os` isn't this compiler's own stdlib; the
alias name `main` then collides with the program's real, synthesized `int
main(int, char**)`.)

## Real-world files exposing this

- `Lib/tkinter/__main__.py` — `from . import _test as main` (a **relative**
  import; `load_module()` has no relative-import resolution at all).
  See `COMPILE_FAIL_tkinter___main__.md` in this directory.
- `Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py` — `from idlelib.pyshell
  import main` (external/unmodeled package `idlelib`).
  See `COMPILE_FAIL_Mac_IDLE_IDLE.app_Contents_Resources_idlemain.md`.
- `Tools/clinic/clinic.py` — `from libclinic.cli import main` (external
  package `libclinic`).
  See `COMPILE_FAIL_Tools_clinic_clinic.md`.
- `Tools/c-analyzer/c-analyzer.py` — same "implicit declaration of function
  'main'" tail symptom, though this file is *also* independently blocked by
  an unrelated pre-existing bug in `Tools/c-analyzer/cpython/__main__.py`
  (`'cpython___main___fmt_summary_79c856' undeclared`) — not investigated
  as part of this issue.

All four previously failed with the wrong "conflicting types for
'_gimple_main'" diagnostic (fixed by 12ff719); all four still fail to
compile today, now for this legitimate, deeper reason.

## What a real fix needs

Real relative-import and external-package resolution in `load_module()` (or
a deliberate, explicit "give up cleanly" path for calls to such names —
e.g. always route them through the existing runtime dynamic-dispatch
fallback, `mojo_obj_call1`-style, instead of emitting a direct C call to a
name that may not exist). Either direction is a real feature, not a
one-line fix.
