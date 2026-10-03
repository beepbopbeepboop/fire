"""`posixpath` — CPython's own name for `os.path`, for the formal backend.

THE MODEL IS ALREADY WRITTEN. `formal/hostmods/os/path/__init__.mojo` IS
CPython's `posixpath` (`genericpath` plus the POSIX half), transcribed rule for
rule and measured against this interpreter's own `posixpath` by
`test_formal_os.py`. So this file is a SPELLING and not a module: every public
name is re-exported under the name CPython gives it, and `import posixpath` /
`from posixpath import join` reach the code `os.path` already reaches.

Why the spelling was worth having. A name with no Mojo source is classified by
`formal/imports.py` as a host module — a CPython standard-library module this
backend cannot compile — and the 2026-10-02 arm64 sweep had one file blocked on
`posixpath` for exactly that reason while the code it wanted was sitting in this
tree under a different name. That is the failure
`bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md` §5 item 3 measures,
and it is the same shape as `import os.path` reaching a module that already
exists: the capability was never missing, the NAME was.

WHAT IS NOT HERE, and it is the same boundary `os.path` has rather than a new
one. CPython's `posixpath` also exports `sep`, `curdir`, `pardir`, `extsep`,
`altsep`, `pathsep`, `defpath`, `devnull`, `commonpath`, `expanduser`,
`expandvars`, `sameopenfile`, `samestat` and `supports_unicode_filenames`. The
constants CPython spells as module attributes come from `os` (a module-level
name is a CALL on this path — see `formal/hostmods/os/__init__.mojo`'s header),
and the rest are either not implemented in the model at all (`expanduser`,
`expandvars`, `commonpath`) or are the same function under a second name
(`sameopenfile`/`samestat` are `samefile`). `os.path`'s `join3`/`join_all` are
NOT re-exported either: they are this tree's workaround for a variadic
`join(*parts)`, not CPython names, and a module that exports a name CPython does
not have is a claim a reader will believe.
"""

from .os.path import join, split, dirname, basename, splitdrive, splitext
from .os.path import normpath, isabs, commonprefix
from .os.path import abspath, realpath, relpath
from .os.path import exists, isfile, isdir, islink, lexists, samefile, getsize
