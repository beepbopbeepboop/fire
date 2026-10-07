# FORMAL/x86_64: a dylib's outbound call goes through the bound `__got` slot and dies under Rosetta

**Status: open, believed ENVIRONMENTAL (Rosetta 2), not a compiler bug.** This
doc is the reproduction and the evidence; the model/emitters were not changed to
accommodate it (see the task's "Rosetta is a translator, not hardware" rule).

## Symptom

`test_formal_run.py::byref_folded_module_constant_as_a_memset_byte_in_a_dylib`
(and any `both` row whose **module dylib calls anything out**) is red on this
arm64 host. arm64 answers 0; `--backend=x86_64` SIGSEGVs (exit -11) with the
GOT slot holding the *right* symbol.

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      byref_folded_module_constant_as_a_memset_byte_in_a_dylib
  FAIL  byref_folded_module_constant_as_a_memset_byte_in_a_dylib: [x86_64] exit status -11, expected 0
formal run: PASS=177 FAIL=1
```

## Minimal reproduction (no constants, no `memcmp`)

Two modules, or one module that calls libSystem — either crashes:

```mojo
# byref_xmod.mojo
def one(pat):
    memset(pat, 45, 1)      # any extern: memset/exit/write/malloc all crash
    return 0
```
```mojo
# prog.mojo
from byref_xmod import one
def main(n: Int) -> Int:
    var got = malloc(64)
    one(got)
    return 0
```
```
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o p.x86 prog.mojo
$ arch -x86_64 ./p.x86            # Segmentation fault: 11
```
A→B sibling-module call (`from modb import helper` inside `moda`) crashes
identically, so it is not libSystem-specific. The **`got` extern style**
(`call *disp(%rip)` straight through the slot, no `__TEXT,__stubs`) crashes too,
so it is not the stub. The program→dylib direction is fine; only a **dylib
calling out** dies.

## What is demonstrably correct, and why this is not (yet) a compiler bug

Under `SIGSEGV` handler and `DYLD_PRINT_BINDINGS`, for moda calling modb's
`helper`:

- dyld binds the slot: `fixup: moda...dylib/*0x010325F000 = 0x...<modb/_helper>`;
- the stub bytes at runtime are `ff 25 96 3b 00 00` and its RIP-relative target
  is exactly `__DATA_CONST + 0` (the slot dyld wrote);
- the 8 bytes at that target are the bound helper address.

Yet the fault lands at a **different, unmapped address** (`moda_base - 0x3F0000`
in one run, `0x0` in another). I.e. Rosetta's translated `jmp *disp(%rip)` used
a target other than `[rip+disp]`.

Corroborating, all of these make the crash **disappear** without changing the
program's meaning:

- attaching `lldb` and single-stepping the stub (the call then completes);
- changing **any single byte** of the dylib after it was signed (which
  invalidates the ad-hoc code signature); and re-running the *same on-disk
  content* after a remap can then change the verdict from SIGSEGV to dyld's
  `Abort trap: 6`. That is a macOS code-signing / mapping cache being consulted,
  not a property of the emitted bytes.

The crash reproduces for a dylib built by this tree but **not** for the same
function compiled by `clang -dynamiclib` — so it is a formal-dylib-vs-Rosetta
interaction, and on a real Intel CPU (position-independent, bound GOT) the image
would run.

### Ruled out (each measured, each left the crash in place)

stub vs `got` extern style; 32-bit vs other displacement magnitude; image
preferred base (`TEXT_BASE` vs `0`); `PAGE_SIZE` 0x1000 vs 0x4000; the module
`__DATA` gap; **adding `LC_DYSYMTAB`** (`-Wl,-dynamic`-equivalent not needed);
**`__DATA_CONST` `SG_READ_ONLY` (0x10)**; the `__stubs` `reserved2` field
(below); the mach_header flags (below); chained fixups vs classic `LC_DYLD_INFO`;
lazy vs non-lazy binding; `LC_FUNCTION_STARTS`/`__unwind_info`; the target
(libSystem vs sibling); code-signature presence. `clang`'s dylib works with and
without every one of those, signed or not.

## Latent real bugs found while bisecting (NOT the cause above)

These are spec violations that do **not** change the crash's outcome, but match
`ld`'s output and are worth fixing independently:

1. **`__stubs` reserved fields are swapped.** `<mach-o/loader.h>`: for
   `S_SYMBOL_STUBS`, `reserved1` is the indirect-symbol-table index and
   `reserved2` is **the size of one stub**. `formal/macho_linker.py`'s
   `_write_text_segment` puts the stub size (`ssize`) in `reserved1` and leaves
   `reserved2 == 0`; `ld` emits `reserved1 0 / reserved2 6` (x86-64). The three
   call sites pass the size as the 6th tuple element. (Verified: patching the
   emitted `reserved2` to 6 makes `otool -l` read like `ld`'s; it does not fix
   the crash.)
2. **dylib mach_header flags are wrong.** `build_macho_dylib` hardcodes
   `0x800005` = `MH_NOUNDEFS|MH_DYLDLINK|MH_HAS_TLV_DESCRIPTORS` — it is
   **missing `MH_TWOLEVEL` (0x80)** and sets a TLV-descriptor bit the library
   does not have. `formal/macho.py` carries the root cause:
   `MH_TWOLEVEL = 0x00800000` (should be `0x00000080`); its `MH_BIND_AT_LOAD`
   and `MH_DEAD_STRIPPABLE_DYLIB` are likewise aliased onto other flags. `ld`
   emits `0x100085` for the same dylib. (Changing the header flags to `0x100085`
   does not fix the crash.)
3. **`__DATA_CONST` is not marked `SG_READ_ONLY` (0x10).** `ld` sets it on the
   GOT-carrying segment for executables and libraries alike; this tree leaves it
   `0x0`. Hardening only.

## Next step

Run the reproduction on **real Intel hardware**. If it answers 0 there (as the
position-independent image implies), this is purely Rosetta and belongs with the
other translator-era reds; if it fails there too, the bug is real and the search
should move to a byte-level diff against `ld`'s dylib for this exact program
(every structural difference above is already eliminated, so it would be
something the load-command diff has not named yet).
