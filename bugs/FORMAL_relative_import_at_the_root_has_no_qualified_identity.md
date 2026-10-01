# FORMAL_relative_import_at_the_root_has_no_qualified_identity: the same module gets a different library depending on which module reached it first

**Area:** CODEGEN/FORMAL (Mach-O): `formal/imports.py`'s
`_module_identity` and `formal/build.py`'s `_resolve_imports`, which calls
`build_module_dylib` with no `_parent`.

**Found while:** fixing the sibling bug
`FORMAL_relative_submodule_abi_prefix_off_by_one.md` (whose stated cause was
wrong — the probe was double-stripping a leading underscore — but whose step 1,
"pass the importer's own identity as `_parent`", is a real and separate
observation about naming).

**Status: OPEN, measured, benign today.** Not a link failure and not a wrong
answer. It is a NAMING instability: a module's ABI prefix — which is baked into
every symbol it exports and into the library's own filename — is not a function
of the module's source.

## What I measured

`formal/hostmods/os/path/__init__.mojo` imports `.._syscalls`. Built on its
own, `_module_identity('.._syscalls', parent=None)` passes the name through
with its dots, so the library is `___syscalls.<digest>.arm64.dylib` and its
exports are `___syscalls_fs_chdir_9f63a2`. Reached as `.path` from
`formal/hostmods/os/__init__.mojo` in the SAME process, `_BUILT` — keyed by
`(arch, resolved path)` — hands back the `._syscalls` library instead
(`__syscalls.…`, exports `__syscalls_fs_chdir_9f63a2`), and the `_path` library
is built and linked against THAT.

So the same source file, reached two ways, produces two different libraries
with different export spellings, and which one you get depends on the order
`imported_modules` happened to walk. Both are internally consistent — the
manifest is written from the same prefix the exports were mangled with, and the
consumer reads that manifest — which is why nothing fails and no answer is
wrong. It is a content-addressing problem: `build_module_dylib`'s own comment
says the source digest in the filename is "what makes sharing safe rather than
merely rare", and for a relative import at the root the digest is no longer
sufficient, because the ARTIFACT depends on the spelling that reached it.

The composed names are also meaningless, which is the visible symptom:
`_module_identity('.sub', parent='._syscalls')` is `._sub.._syscalls`, so a
submodule's own relative dependency is filed under a prefix that reads as
punctuation. `_module_identity` strips a trailing `.__init__` from the parent
and nothing else.

## Why it is not a wrong answer, stated precisely

Two processes can therefore produce different libraries for one module. A
program does not notice, because within a process `_BUILT` is keyed by resolved
path and every consumer reads the manifest that sits next to the library the
build actually produced. The two can only disagree if a consumer resolved the
module itself by name instead of reading the manifest — which is exactly what
this backend now never does for a linked library, and is why the fix is worth
making rather than worth worrying about.

## The exact next step

Give the file being compiled an identity and pass it down. `_resolve_imports`
already has `source_path`; what it needs is the module name that file is
ADDRESSED by, which is derivable from the nearest search root above it
(`_search_roots` already computes those):

1. `formal/imports.py`: `own_module_identity(source_path, project_root)` —
   the longest search root that is a strict ancestor of `source_path`, then the
   dotted path relative to it with `__init__` dropped. For
   `formal/hostmods/os/path/__init__.mojo` under `_HOSTMODS_ROOT` that is
   `os.path`; for a swept program at the project root it is the program's own
   stem, which is harmless because a program's identity only ever qualifies its
   dependencies.
2. `formal/build.py`'s `_resolve_imports`: pass it as `_parent` to
   `build_module_dylib`. One line, and it makes `.._syscalls` from
   `os/path/__init__.mojo` resolve to `os._syscalls` whether the file is
   reached from `os` or built on its own.
3. `formal/model.py`'s `abi_module_name` then flattens a name with no leading
   dot at all, so `abi_module_name` stops being load-bearing for a prefix and
   the `__syscalls`/`___syscalls` pair disappears from the CAS.

Step 3 is the one to watch: it renames dylibs on every machine's CAS, so the
integrator's `stdlib-dylib` skip counts and the `formal-imports` directory
contents both move. `test_formal_link_accounting.py` and
`test_formal_imports.py` are the two suites that read them, and
`test_formal_cross_module.py`'s three relative-import cases are the ones that
must stay green — they assert the behaviour, not the spelling, so they should
not move at all.

## Not this

`formal/macho_linker.py` line ~864 writes a module dylib's export trie entry
as `export["symbol"] if export["symbol"].startswith("_") else "_" + symbol`,
which is NOT `_` + the C name when the C name itself begins with an
underscore. It is consistent with `_bind_info`'s inverse in the ordinary case
(`dmod_x` ↔ trie `_dmod_x` ↔ bind `dmod_x`) and it happens to be consistent for
an underscore-prefixed name too, because the executable's bind stream strips one
underscore back off. So there is no divergence to fix there and the trie
reader, the link audit and dyld all agree — measured, and the image runs. It is
recorded here only because it LOOKS like the same off-by-one and is not; do not
"fix" it without re-measuring the bind name first.
