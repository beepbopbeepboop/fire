# An ELF image cannot carry a module dylib: there is no ELF shared-object emitter

**Area:** CODEGEN (formal x86-64 / ELF container). Split out of the closed
`CODEGEN_x86_64_module_dylib_emitted_as_macho.md`, whose central claim was
wrong and whose real content was two separate defects, both now fixed.

## What is closed, and what is not

The old doc said an x86-64 module dylib "is a Mach-O, so no x86-64 program can
import anything", and that the fix was to thread `fmt` through and stop
emitting the wrong container. Measured on this tree, that was not the case:

- **`fmt="macho"` is correct on a macOS host for x86-64, not a bug.**
  `formal/build.py`'s `default_format` is `"macho" if sys.platform == "darwin"
  else "elf"` — it does not vary by architecture. An x86-64 *executable* built
  here is a Mach-O, because an x86-64 image that runs on Apple Silicon has to
  be one Rosetta 2 will load, and `fire.py`'s `_formal_run_argv` is what runs
  them (`arch -x86_64 <path>`). So a Mach-O module dylib is the container that
  agrees with the thing linking it. The old doc's repro passed `fmt='elf'`
  explicitly, which is a request for a container that cannot exist here, and
  then read the refusal-or-ignore as a bug in the default path.

  The test that carried the premise (`test_struct_formal.py`, "the x86-64
  module dylib is an ELF object") was asserting the dylib and the executable
  beside it must DISAGREE on the container. It now asserts both against
  `default_format(arch)`.

- **The real defect in that area was that `fmt` was accepted and ignored.**
  `compile_formal_dylib`'s guard was
  `if not fmt_wants_macho(arch) and fmt != "macho"`, and on a Mach-O host
  `fmt_wants_macho` is true for every architecture — so the first operand is
  false and `fmt="elf"` returned a Mach-O while reporting
  `x86_64/macho-dylib`. Now refused by name (14a3938b, c669eb28).

  Separately, and the one that actually cost a working module: an x86-64
  module dylib with an extern call could not be signed at all
  (`FORMAL_x86_64_dylib_externs_unsigned`,
  `FORMAL_x86_64_dylib_with_an_extern_call_does_not_load`). `build_macho_dylib`
  emitted stubs with no `arch`; fixed in 14a3938b. `struct.mojo`, `os` and
  `sys` all call the C library, so all three were blocked by it.

**What remains is this**, and it is a feature rather than a repair.

The gap, precisely, is (1) only. (2) is FIXED — see the end of this
document.

## The gap, precisely

`fmt="elf"` on a Linux host is a real request, and this path cannot satisfy it:

- `formal/imports.py`'s `build_module_dylib` has one emitter,
  `formal/macho_linker.py`'s `build_macho_dylib`. Its export trie
  (`_export_trie`), its bind stream (`_bind_info`), its stub/GOT layout and
  its `install_name` are Mach-O-shaped by construction.
- `formal/elf.py` builds EXECUTABLES. `build_elf` carries one `lib_name`
  (`DEFAULT_LIBC = "libc.so.6"`) and writes exactly one `DT_NEEDED`, with no
  `.dynamic`/`.dynsym`/`.dynstr`/`.hash` emitter at all.

The combination was a silent wrong image, not a refusal, and it is now a
refusal (`compile_formal`, `fmt != "macho" and import_dylibs`). Measured on
this tree before the refusal:

```console
$ cat ANYP.mojo
import ANY

def main():
    print(ANY.add1(41))
    return 0

$ python3 -c "...compile_formal('ANYP.mojo', arch='x86_64', fmt='elf')..."
built                                    # exit 0
$ file ANYP.out
ANYP.out: ELF 64-bit LSB executable, x86-64, statically linked, no section header
```

and inside that ELF: `external_syms == ['ANY_add1_9f63a2', 'printf']`, one
`DT_NEEDED` (`libc.so.6`), and a `.dynstr` of
`ANY_add1_9f63a2, printf, libc.so.6`. The module library — a Mach-O — was
built, audited, and then put nowhere.

**The audit made this look right, which is why it is worth writing down.**
`_audit_bound_symbols` reads each linked library's manifest, sees
`ANY_add1_9f63a2` in its export list, counts it as `provided`, and passes. That
is true, and irrelevant: no ELF loader will ever open that Mach-O, so nothing
provides the symbol at runtime. The check asks "does something on this link
line declare this name", and the answer was yes while the question that
mattered was "will the loader open that library".

## The exact next step

Write the ELF shared-object emitter. `formal/elf.py` needs a `build_elf_dylib`:
`PT_LOAD` segments with a `.dynamic` section, `.dynsym`/`.dynstr`, a `.hash`
(or `.gnu.hash`), a `DT_NEEDED` per dependency and a `DT_SONAME` matching
`install_name`. The export table is the same information
`formal/macho_linker.py`'s `_export_trie` carries — a name and an address per
export — so it is the container that must be written, not a second analysis of
the exports. `.plt`/`.got.plt` or a direct `jmp *GOT(%rip)` per extern:
x86-64's RIP-relative indirect jump is the same six bytes the Mach-O stub uses,
so the per-symbol work is nearly identical and should be shared rather than
re-derived.

Then `formal/imports.py`'s `build_module_dylib` stops hardcoding
`fmt="macho"`, passes `default_format(arch)` through, and the ELF refusal
becomes unnecessary because there is a container to build.

## FIXED: the audit now asks whether the loader can open the library

This was item (2) above and it is done, independently of the emitter.

`_audit_link_line_containers` compares each library on the link line against
the image's own container, reading four bytes of magic from the FILE rather
than from the build that produced it — `file(1)`'s own test, and the only
thing a loader gets to look at before deciding it can open the image. It runs
on both link lines (the executable's and `compile_formal_dylib`'s, so a sibling
in the wrong container is caught before its path is written into a load
command) and before any codegen pass, since a library the loader cannot open
makes every symbol it exports unresolvable and there is nothing worth
compiling.

Deliberately not ELF-only: a Mach-O image with an ELF library is the same
defect with the formats swapped, and nothing about the host decides which way
it goes, because `fmt` is the caller's choice.

Two things had to change for it to be checkable, and both are small:
`load_dylib_manifests` now carries each entry's `path`, and the audit reads
the file rather than any recorded claim about it.

## Verification, and what it is worth

`test_formal_x86_64_dylib.py` pins what is closed: the x86-64 dylib stubs are
`ff25` 6-byte entries, `codesign -v` accepts the library, every byte of the
file is claimed by a segment, a program importing an extern module runs under
Rosetta and matches CPython (both the `import` and the `--link-dylib` path),
the export trie carries the module-prefixed API, `fmt='elf'` is refused by name,
an ELF image with a module import is refused, and the link-line container audit
both catches a mismatch and passes a matching line. An import-free ELF build
still succeeds, so both refusals are about the link line and not the format.

`test_formal_dylib.py`'s "default path emits a checked proof" fails on this
tree with a **lean timeout**, and does so on the base commit with these changes
reverted as well — pre-existing and unrelated.