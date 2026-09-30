# a `from p import f` whose module only RE-EXPORTS `f` compiles to a call against a symbol that does not exist (`p_f_...` vs the real `sub_f_...`) — a hard GCC error on the single-TU path and a silent 0 on the link-mode one

**State: OPEN. Found 2026-09-29 by `work/hard-fn-import` while fixing
the (now fixed and deleted) cross-module-import report. Verified
pre-existing: reproduced identically with that fix's three source files
reverted to their pre-fix content, so it is not a regression from that work.**

## What I ran

Single-TU (`do_imports=True`) and link mode (`link_mode=True`), both through
`gimple_codegen._run_pipeline` then `gcc -fgimple` + `runtime/fire_runtime.c`,
against CPython on the same text.

```python
# p/__init__.py
from .sub import tri

# p/sub.py
def tri(x):
    return x * 3

# p/w.py
from p import tri

def f():
    from p import tri
    return tri(7)

print(f())
```

## What I saw

CPython prints `21`. The compiled program:

- **single-TU**: a hard `gcc -fgimple` failure,
  ```
  p/w.py:4:9: error: implicit declaration of function 'p_tri_9f63a2';
      did you mean 'sub_tri_9f63a2'?
  ```
- **link mode**: no compile error at all — it builds, links and runs, and
  prints `tri: unavailable in compiled mode` followed by `0`, exit 0. That
  is the extern-preamble's `weak` stub printing into the program's OWN
  stdout, the same failure class as
  the cross-module-import report (see `bugs/hard/README.md`).

## What I expected

`21`, and no module ever named `p` should be assumed to define `tri` — `p`
only re-exports it.

## Where

The definition is emitted correctly (`sub_tri_9f63a2`, qualified by the
module that actually defines it, `p/sub.py`). Only the CALL SITE is wrong:
it qualifies by the module the CLIENT imported from (`p`).

`mojo/middle/module_shared.py::_register_sym` computes the call site's
qualifier from the import statement's own module string, sanitized:

```python
_qual = (s.module.lstrip('.').replace('.', '_').replace('-', '_'))
```

`p/__init__.py` is where the re-export lives, and nothing follows
`s.module` (`p`) forward through it to `sub`.

The re-export-hop walk this codebase already has, and which this shape
needs the free-function analogue of, is
`_find_generic_source` (`mojo/middle/funcs_shared.py`: "Source path of the
module that DEFINES generic `name` ... reachable from `module` by following
`from X import (...)` re-export hops (e.g. std.os re-exports listdir from
.os = os.mojo)"). It is used for GENERICS only. Plain top-level functions
imported through a re-export do not get it — which is why a generic behind
the same re-export would probably work and `tri` does not.

Compare the two paths that already work, both of which skip the re-export
question because the client names the defining module directly:
`from p.sub import tri` and `from .sub import tri` in a function body (both
work, fixed in the same series; see the 2026-09-29 section of
`bugs/hard/README.md`).

## Exact next step

Route the qualifier for an imported free function through the same re-export
hop resolution `_find_generic_source` already implements, so
`_register_sym`'s `_qual` (and `_note_own_func_home`, which writes the
`_imported_home_param_types` key beside it) name the module that DEFINES
the symbol rather than the module the client happened to import from.

Two things to get right, both measured here:

1. The hop must be applied to the import-resolution site
   (`mojo/middle/module_shared.py::_register_sym` and the function-scoped
   twin at `mojo/backend_gimple/emit_funcs.py`'s `_fi_home` /
   `_note_own_func_home` call), NOT by changing
   `_find_generic_source` — that helper is keyed on generics and is
   correct as it stands.
2. A re-export that itself resolves to a re-export must terminate, and a
   cycle (`p/__init__.py` re-exporting from `q`, `q/__init__.py` from `p`)
   must not hang. `_find_generic_source` has the visited-set to copy.

Worth measuring after the fix that the `linkmode` weakness does not persist:
if the qualifier is right, the link-mode weak stub should disappear on its
own, because the stub only exists to catch a call whose symbol cannot be
bound.

## Not filed under a hard doc

The single-TU half is a compile refusal, not a silent miscompile, and the
link-mode half's wrong value comes from a stub that prints a diagnostic
rather than a plausible-looking number. It is real, and it is a
compile-stage gap on a shape real Python packages use (a package
`__init__.py` that re-exports its submodules is the standard layout), but
it is not the "silent miscompile" class `bugs/hard/` is for.
