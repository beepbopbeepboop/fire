# An x86-64 module dylib is a Mach-O, so no x86-64 program can import anything

**Area:** CODEGEN (formal x86-64). `formal/imports.py`'s
`build_module_dylib` hardcodes `fmt="macho"` when it calls
`compile_formal_dylib`. **Found while:** writing `struct.mojo` for the formal
backend (worker `mod-struct`), which is the first change to put a module on
the x86-64 import path that is not caught by another limit first.

**Severity: a refusal on a correct program.** Nothing is miscompiled; every
x86-64 program with an import is refused at the link step.

## What I ran

```
$ cat ANY.mojo
def add1(x):
    return x + 1

$ cat ANYP.py
import ANY

def main():
    return 0

$ python3 -c "import formal.build as B
    B.compile_formal('ANYP.py', arch='x86_64', fmt='elf', prove=False)"
built

$ file ~/.gmojo/cas/formal-imports/x86_64/ANY.*.dylib
ANY.ca3f99e8d0f1.x86_64.dylib: Mach-O 64-bit dynamically linked shared library x86_64
```

The directory is named `x86_64` and the file name carries the `.x86_64.dylib`
suffix, and the file is a **Mach-O** — the wrong container for a Linux-shaped
ELF image, produced for a Linux-shaped target. It builds; it just cannot be
linked into one. The case is a two-line module, so nothing about `ANY`
contributes: the container is wrong on its own.

The refusal this produces is a Mach-O diagnostic, which is the confusing part:

```
$ python3 -c "... B.compile_formal('X86.py', arch='x86_64', fmt='elf', ...)"
FormalBuildError: X86.py imports 'struct', which cannot be built either:
  struct.mojo: …/struct.31a4a06bea51.x86_64.dylib: main executable failed
  strict validation
```

`main executable failed strict validation` is what macOS `codesign` says about
a **Mach-O** (see `formal/macho_linker.py`'s notes on the ad-hoc signature that
lands on the first instructions), so an ELF-target build is being handed a
Mach-O error. A reader chasing that sentence looks for a signing bug and never
reaches the container mismatch that caused it.

## Why

`formal/imports.py:849`:

```python
result = compile_formal_dylib(
    [source_path], output=out, prove=False, check=False,
    module_prefixes={source_path: prefix},
    link_dylibs=dep_dylibs, arch=arch, fmt="macho",     # ← here
    reexports=reexported_names(...))
```

`arch` is threaded through correctly — the codegen really is the x86-64 one,
which is why the emitted code inside the library is x86-64 — but `fmt` is
pinned to `"macho"`, so the CONTAINER is Mach-O. `compile_formal_dylib`
documents `fmt` as "select the CODEGEN and the container, exactly as
`compile_formal` does for an executable", and the executable path gets its
container from `default_format(arch)` via `fmt_wants_macho`
(`formal/build.py:801`). The dylib path does not consult either.

`formal/build.py` also gates the executable's import resolution on it
(`_resolve_imports` returns `[]` unless `fmt_wants_macho(arch)`, `:751`), which
is why an x86-64 executable with an import reaches this at all rather than
being refused earlier: on x86-64 the import is not resolved through
`build_module_dylib` for the *executable*, but a module reached as a
dependency still is, and it emits the wrong container on the way.

## Expected vs actual

- expected: `ANY.<digest>.x86_64.dylib` is an ELF shared object
- actual: a Mach-O 64-bit dynamically linked shared library, x86_64

## Next step

**There is no one-line fix, and it is worth saying so before anyone writes
one.** Threading the format through is the first half and it is necessary, but
it is not sufficient, because `compile_formal_dylib` does not HAVE an ELF
container: asked for one directly, it still emits Mach-O.

```
$ python3 -c "import formal.build as B
    B.compile_formal_dylib(['ANY.mojo'], output='probe.dylib', arch='x86_64',
                           fmt='elf', module_prefixes={...})"
$ file probe.dylib
probe.dylib: Mach-O 64-bit dynamically linked shared library x86_64
```

So `fmt` on that path is accepted and then not honoured, which is a worse
property than a hardcoded literal: the argument reads like it is doing
something. The first half is to stop passing `"macho"` unconditionally from
`formal/imports.py:849` and to make the function REFUSE `fmt="elf"` rather
than silently produce a Mach-O:

```python
if not fmt_wants_macho(arch) and fmt != "elf":
    raise FormalBuildError(…)
```

— or, better, refuse `fmt="elf"` outright until the container exists, so the
error names the gap instead of a signing failure three steps later. The
honest intermediate state is a clean "there is no ELF module dylib container
on this path yet", which is a fact a reader can act on and which points at the
work below.

**The work underneath** is an ELF shared-object emitter for the module path:
`formal/macho_linker.py`'s `_export_trie`, `_bind_info`, the stub/GOT layout
and the `install_name` are Mach-O-shaped by construction, and
`formal/elf.py` builds executables (PT_LOAD segments, an interpreter path) and
has no `.dynamic`/`.dynsym`/`.dynstr`/`.hash` section emitter at all. So this is
a feature, not a repair, and it is the same size as the string-value model's
missing buffer: a container of a size nothing knows until runtime.

Two things to settle, both outside my claim area (`module:struct`), so I have
not touched either:

1. It is a change to `formal/imports.py` and `formal/build.py` and therefore
   owes a full `make gate`.
2. `test_formal_dylib.py` has a `test_module_dylib_matches_the_programs_arch`
   case that passes today; it checks the ARCHITECTURE and not the container,
   which is why a Mach-O labelled `x86_64` passed it. A container assertion is
   the test that belongs there, and it would have caught this on a two-line
   module.

## Why it was not caught

`test_formal_dylib.py` runs on arm64, where `fmt="macho"` is correct, and
`test_formal_imports.py` likewise. Every existing x86-64 test in this tree
either exercises no import or checks the architecture rather than the
container. `tools/formal_sweep.py` has an x86-64 mode, and this is the class of
thing it exists to find — it is simply not been pointed at a file with an
import.
