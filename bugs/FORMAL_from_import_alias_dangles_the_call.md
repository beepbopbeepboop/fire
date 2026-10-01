# FORMAL_from_import_alias_dangles_the_call: `from m import f as g` calls a symbol named `g`

**Status:** open. Found while writing `os`; the call spelling is
`formal/arm64_codegen.py:_callee_symbol` and the export map is
`formal/imports.py:load_dylib_manifests`, neither of which this task owns. It
is written down because the diagnostic it produces is good enough to be
worth keeping in mind and bad enough to send a reader looking in the wrong
place — and because `import os` + `os.path.join` is the shape 532 of the
measured `os` uses are written in, so the neighbouring shape matters.

## What I ran

```
$ cat > .tmp/osp3.mojo
from os.path import exists as os_exists, isdir as os_isdir
…
    printf("os-exists=%d@@", os_exists(join(root, "d")))
$ python3 fire.py build --formal --no-prove -o .tmp/osp3 .tmp/osp3.mojo
build: osp3.mojo: the image would bind 2 symbol(s) that nothing provides, so it
could not be loaded: os_exists, os_isdir. Nothing on this link line defines
them: not the C library, and not any library this program linked. …
```

The same two names imported **without** the alias build, link and run. So it is
the alias and nothing else.

## Why

`load_dylib_manifests` builds `{bare callee → exported symbol}` from each
library's export list, keyed by the DEFINING name (`exists`), and
`_emit_call` asks for `self._dylib_syms.get(name, name)` where `name` comes
from `_callee_symbol(e.func)` — which is the name AS SPELLED at the call site,
`os_exists`. There is no step that maps a local binding back to the module it
came from, so the fallback `name` is used and the `BL` names a symbol nothing
defines.

`formal/imports.py:imported_modules` already does the mapping for the *other*
half of the same question — it reads `st.extra` and the from-import names so
that the right MODULE is built — so the information exists at import time and
is simply not carried to the call site.

Worth saying plainly, because the failure mode invites the wrong conclusion:
**the link audit caught this correctly and did not paper over it.** An audit
that had let it through would have produced an image that builds, links, and
dies in dyld at launch — which is the outcome the whole dylib mechanism exists
to prevent, and this is that mechanism working.

## What I expect

`os_exists(p)` to call the same function as `exists(p)`. The alias is a
property of the importing file, not of the library.

## The exact next step

Carry the alias through, in the same place the module is already known:

1. `_resolve_imports`/`load_dylib_manifests` already know, for each
   `FromImportStmt`, the module each imported name came from
   (`imported_modules` + `declared_kinds` give the pair). Extend the map that
   `_emit_call` consults from `{bare → symbol}` to `{spelling → symbol}`: add an
   entry per `from m import f as g`, mapping `g` to `m`'s exported `f`. **The
   map is consulted with `setdefault` and first-wins, so an alias must not
   shadow a real export of the same name** — an alias whose local name collides
   with another module's function is a name-based-dispatch collision that
   `doc/ABI.md` already excludes, and it should be a refusal.
2. `formal/model.py`'s name check needs the same map, or `g` is refused as an
   unresolved name before the call is ever emitted (the `placed` set in
   `_check_unresolved_names` is where an imported name is currently accepted on
   the strength of being a call's callee).

While it is open: **do not alias a from-import of a function you intend to
call.** `os`'s own test had to move the re-export check into a second program
for exactly this reason — one program cannot import `exists` from `os.path` and
`exists as os_exists` from `os` and call both.
