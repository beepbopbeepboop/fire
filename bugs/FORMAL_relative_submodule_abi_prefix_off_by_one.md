# FORMAL_relative_submodule_abi_prefix_off_by_one: a relative submodule's library and the call sites in its importer disagree on the ABI prefix by one underscore

**Area:** CODEGEN/FORMAL (arm64 + Mach-O): `formal/imports.py`'s
`build_module_dylib` / `_module_identity`, and the module qualifier the
emitter reconstructs for a call into a dependency.

**Found while:** relocating `os/`, `sys.mojo` and `struct.mojo` into
`formal/hostmods/` (worker `hostmods-relocate`), while checking that
`tools/formal_sweep.py` still sweeps the module sources sensibly. It does
sweep them, and two of the five are classified `not-answerable/unresolved-extern`.

**Status: OPEN, and PRE-EXISTING.** It is not caused by the relocation: the
identical verdict, with the identical symbol and library names, comes out of a
copy of the same tree in a scratch directory (measured below). It was there
while the modules sat at the repository root, and nothing in the module's own
test files can see it, because every one of them drives the module the way a
PROGRAM imports it rather than the way the sweep builds the module itself.

**Severity: a link failure, not a wrong answer.** The image builds, passes the
static bind audit, and then cannot be loaded — the class
`FORMAL_module_exports_nothing` was written about.

---

## What I ran

```console
$ python3 tools/formal_sweep.py --no-stdlib \
    formal/hostmods/os/__init__.mojo formal/hostmods/os/path/__init__.mojo
NOT-ANSWERABLE/UNRESOLVED-EXTERN: formal/hostmods/os/__init__.mojo  (builds, but
  16 import(s) dyld cannot resolve: _syscalls_fs_chdir_9f63a2,
  _syscalls_fs_chmod_2dbb98, _syscalls_fs_cwd ... [_syscalls_fs_chdir_9f63a2 is
  not exported by .../cas/formal-imports/arm64/__syscalls.70906a625aaf.arm64.dylib])
NOT-ANSWERABLE/UNRESOLVED-EXTERN: formal/hostmods/os/path/__init__.mojo  (builds,
  but 26 import(s) dyld cannot resolve: __syscalls_fs_access_2dbb98, ... )
[arm64] 2 files: PASS=0 not-pass=2
```

The two verdicts differ by exactly one underscore, in the same place: the first
file binds `_syscalls_fs_chdir_9f63a2` and is linked against a library named
`__syscalls.…`, the second binds `__syscalls_fs_access_2dbb98` and is linked
against `___syscalls.…`. The library is right in both cases:

```console
$ python3 -c "import json; m=json.load(open('.../__syscalls.70906a625aaf.arm64.dylib.manifest.json')); \
    print([e['symbol'] for e in m['exports'] if 'chdir' in e['symbol']])"
['__syscalls_fs_chdir_9f63a2']
```

So the library defines `__syscalls_fs_chdir_9f63a2` and the image binds
`_syscalls_fs_chdir_9f63a2`. The call site is one leading underscore short of
the thing it is calling.

**Not the relocation.** The same two files, copied to a scratch directory with
no relationship to the search roots, produce the same two verdicts and the same
symbol and library names:

```console
$ cp -R formal/hostmods/os .tmp/presweep/os
$ python3 tools/formal_sweep.py --no-stdlib .tmp/presweep/os/__init__.mojo \
      .tmp/presweep/os/path/__init__.mojo
  ... _syscalls_fs_chdir_9f63a2 is not exported by .../__syscalls.70906a625aaf.arm64.dylib
[arm64] 2 files: PASS=0 not-pass=2
```

## Why

`formal/imports.py` derives a module's ABI prefix from its module IDENTITY,
and there are two places that identity is spelled, and they spell a leading
dot differently.

The LIBRARY's side. `build_module_dylib` names the library, and keys every
export in its manifest, by `model.abi_module_name(module_identity)`. For the
program at `os/__init__.mojo`, the dependency is named `._syscalls` by
`imported_modules`, and `_resolve_imports` (`formal/build.py`, the executable
path) calls `build_module_dylib(mod, path, out_dir, arch, …)` with no
`_parent` — so `_module_identity('._syscalls', parent=None)` returns the name
UNCHANGED, dot and all, and `abi_module_name` replaces the dot:

```
$ python3 -c "import formal.imports as I; \
    print(repr(I._module_identity('._syscalls')), I._model.abi_module_name(I._module_identity('._syscalls')))"
'._syscalls' '__syscalls'
```

Two leading underscores, which is what the library on the link line is called.

The CALL SITE's side. A bare call `fs_chdir(p)` reaches the emitter as
`ARM64Codegen._extern_symbol('fs_chdir')`, which answers a name with no dot
out of `_dylib_syms` — the flat map built from the manifest — and that map DOES
carry `__syscalls_fs_chdir_9f63a2`. So the rewrite is not what is losing the
underscore. The underscore is already gone before that: it is lost in how the
compiler decides the callee's HOME MODULE, which for a relative import is the
name with the leading dot STRIPPED (`_syscalls`) rather than the name with the
dot REPLACED (`__syscalls`).

So the two halves of one name disagree by exactly the substitution, and neither
is wrong on its own terms: `abi_module_name` is documented as the one spelling
a manifest is keyed by, and the emitter's spelling is a different answer to a
different question. Nothing in the tree owns the correspondence, which is why
this is a link error found by the loader rather than a refusal.

`os/__init__.mojo` and `os/path/__init__.mojo` are the only two files in the
tree that hit it, and they hit it for the same reason: they are the only ones
whose importer is a RELATIVE import (`from ._syscalls import …` /
`from .._syscalls import …`). A top-level `import x` has no leading dot and
the two spellings agree, which is why `struct`, `sys` and the package tests are
all clean.

## What I did NOT do, and why

Fixing it means deciding which spelling owns a relative submodule's identity
and making the other one read it — in `formal/imports.py` (the producer side:
`_resolve_imports` should pass `_parent`, and `_module_identity` should
normalize a leading dot rather than pass it through) and in whatever builds the
callee's home module for the emitter. That is a change to the module-identity
contract of the whole formal import path, on top of the ABI-prefix
consolidation that landed alongside it, and it changes generated C for a linked
image. It wants a full `make gate` and the integrator's measurement, not a
worker's edit inside a relocation.

## The exact next step

1. Pass the importer's own identity as `_parent` from `formal/build.py`'s
   `_resolve_imports`, so a program's dependency on `._syscalls` builds as
   `os__syscalls` and not `__syscalls`. One line, and it makes the library's
   name agree with the qualified form a relative import already implies.
2. Find the emitter's home-module derivation for a relative import and make it
   read `model.abi_module_name` rather than stripping the dot. Until both are
   done the mismatch only moves.
3. Pin it without a build: a unit test that takes a temp `pkg/__init__.mojo`
   importing `pkg.sub` relatively, resolves the dependency's
   `build_module_dylib` identity, and asserts the manifest's `module` field
   equals `model.abi_module_name('pkg.sub')` — which is the correspondence
   that is currently unenforced, and which no existing test states.
4. Then re-run `tools/formal_sweep.py --no-stdlib` over
   `formal/hostmods/os/__init__.mojo` and `formal/hostmods/os/path/__init__.mojo`
   and require `pass` rather than `unresolved-extern`. Those five lines are the
   whole measurement.
