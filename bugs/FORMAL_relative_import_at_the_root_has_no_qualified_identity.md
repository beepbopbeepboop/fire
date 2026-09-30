# FORMAL_relative_import_at_the_root_has_no_qualified_identity: the same module gets a different library depending on which module reached it first

**Area:** CODEGEN/FORMAL (Mach-O): `formal/imports.py`'s
`_module_identity` and `formal/build.py`'s `_resolve_imports`, which calls
`build_module_dylib` with no `_parent`.

**Found while:** fixing the sibling bug
`FORMAL_relative_submodule_abi_prefix_off_by_one` — fixed, so its doc is
deleted, and this paragraph is where the part of it that was NOT the bug now
lives. Its stated cause was wrong: it measured two hosts reporting
`unresolved-extern` whose bind names were one underscore short of the
libraries on their link lines, and the cause was `tools/formal_sweep.py`'s
`_exports` doing `name.lstrip("_")` on a name the bind stream already spells
the way `dlsym` wants. Removing that is the whole of the fix, and it is what
`test_formal_sweep.py`'s
`test_a_relative_imports_underscored_symbol_resolves_and_the_image_runs`
pins.

Three things in that doc were not the bug, so they are not its deletion's
business either, and all three are here:

* **its step 1**, "pass the importer's own identity as `_parent` from
  `formal/build.py`'s `_resolve_imports`" — a real and separate observation
  about NAMING, restated in full in §"The exact next step" below. This doc is
  that step.
* **its step 2**, "make the emitter's home-module derivation read
  `model.abi_module_name` rather than stripping the dot" — **not needed, and
  should not be done.** The deleted doc only ever showed the two spellings
  *differ*; it never showed the emitter's spelling losing the underscore, and
  the flat `{bare name: symbol}` map it consulted does carry the library's
  export. The three relative-import cases in `test_formal_cross_module.py` —
  one level, two levels, and one behind an alias — all build, link and run
  now, and they would not if the call site were resolving to the wrong module.
  That is why this doc's bug is filed as a naming instability and not as a
  link failure, and it is why doing step 2 as well would be a change with
  nothing left to fix.
* **its step 3**, "a unit test that resolves a dependency's
  `build_module_dylib` identity and asserts the manifest's `module` field
  equals `model.abi_module_name('pkg.sub')`" — still owed, and owed MORE
  strongly after step 1 than before it, because step 1 is what makes the
  correspondence well defined and this is the only thing that would keep it
  that way. Note what the three relative-import cases deliberately do NOT do:
  they assert the observable answer and ignore the spelling, which is right for
  them and is exactly the gap, so nothing in the tree would catch a regression
  that left two spellings of one module in the CAS again.

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
4. Pin the correspondence, which is the deleted doc's step 3 and is the only
   thing that keeps 1–3 from being undone: a test that takes a temp
   `pkg/__init__.mojo` importing `pkg.sub` relatively, resolves the
   dependency's `build_module_dylib` identity, and asserts the manifest's
   `module` field equals `model.abi_module_name('pkg.sub')` — and asserts it
   for the SAME dependency reached both ways, which is the half the deleted
   doc's version did not have and the half that would have caught this.

Step 3 is the one to watch: it renames dylibs on every machine's CAS, so the
integrator's `stdlib-dylib` skip counts and the `formal-imports` directory
contents both move. `test_formal_link_accounting.py` and
`test_formal_imports.py` are the two suites that read them, and
`test_formal_cross_module.py`'s three relative-import cases are the ones that
must stay green — they assert the behaviour, not the spelling, so they should
not move at all, and step 4 is what covers the spelling they deliberately do
not.

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
