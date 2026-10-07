# FORMAL x86-64: `getsize` segfaults (executes at address 0) inside an imported hostmod dylib, where arm64 answers

**Area:** `formal/x86_64_codegen.py` / the x86-64 dylib call sequence (the hostmod
`os.path.getsize` -> `fs_stat_field64` chain). **Found 2026-10-07 on
`work/x86-run-rows-b`** while running the x86-64 rows of `test_formal_run.py` on
this arm64 host under Rosetta 2. **Not the row my half owns**; filed because it
is a real x86-64 execution bug and the row that carries it is host-only so no
gate currently runs it on x86.

## What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
# the row's program, reduced:
cat > .tmp/t1.mojo <<'EOF'
from os.path import getsize
def main() -> Int:
    return getsize("/etc/hosts")
EOF
python3 tools/memslot.py --gb 8 --label t -- \
  python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/t1.x .tmp/t1.mojo
.tmp/t1.x        # Segmentation fault: 11  (exit 139)
python3 tools/memslot.py --gb 8 --label t -- \
  python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/t1.arm .tmp/t1.mojo
.tmp/t1.arm      # exit 86 == 342 % 256, i.e. /etc/hosts is 342 bytes: CORRECT
```

`test_formal_run.py`'s own row is
`fd_write_on_an_open_result_writes` (in `FD_CASES`): it builds and runs on arm64
(there is no `expect=` anywhere in the file for it) but on x86-64 the same
program dies with `exit status -11, expected 5`. Measured by building every
host-positive row for x86-64 directly:

```
host-positive x86 sweep: 428 pass, 5 fail of 433
  FAIL fd_write_on_an_open_result_writes :: exit status -11, expected 5
  FAIL comptime_call                       :: (EXPECTED: x86-64 has no comptime lowering)
  FAIL every_element_of_a_16000_element_list_reads_back      :: (EXPECTED: x86 frame budget)
  FAIL list_literal_past_the_immediate_offset                :: (EXPECTED: x86 frame budget)
  FAIL range_literal_past_the_immediate_offset               :: (EXPECTED: x86 frame budget)
```

Only `fd_write_on_an_open_result_writes` is a real defect; the other four are
documented architectural limits (`FORMAL_known_limits.md` §3 for `comptime`, and
the 16 KiB x86-64 frame in `test_formal_run.py`'s own comments).

## What it is

`lldb` and `DYLD_PRINT_BINDINGS=1` on the x86_64 image:

```
stop reason = EXC_BAD_ACCESS (code=1, address=0x0)
frame #0: 0x0000000000000000
frame #1: 0x000000000108247408
frame #2: os_path___syscalls.a90cc49e04ba...x86_64.dylib
frame #3: os_path___syscalls.a90cc49e04ba...x86_64.dylib
frame #4: os_path.e32e8721b1ea...x86_64.dylib
frame #5: fd.x86 / t1.x
```

The x86_64 executable is a thin `Mach-O 64-bit executable x86_64` (verified with
`file`/`lipo -info`; Rosetta really executes it), so this is not an arm64 slice
being run by mistake, and not a Rosetta "cannot translate" failure: the process
launches and then jumps to address 0.

### Ruled out already

* **Not a missing bind.** `dyld_info -fixups` shows all 52 `__stubs` of
  `os_path___syscalls` matched 1:1 to 52 `__got` slots, and
  `DYLD_PRINT_BINDINGS=1` prints every one applied to a real libSystem address
  (including `__platform_memset` at bind#26, a real non-zero address).
* **Not `__platform_memset` itself.** A clang `-arch x86_64` C program calling
  `_memset` *and* `__platform_memset` runs clean under Rosetta.
* **Not "a Mojo dylib cannot call libc".** `from os.path import exists` (same
  dylib pair) builds and answers correctly on x86-64.
* **Not the row's absolute `/tmp` path or its `open(...).write` receiver**: the
  reduced `getsize("/etc/hosts")` above has neither and still crashes.

## Signature shared with the one first-half red

`test_formal_run.py`'s `byref_folded_module_constant_as_a_memset_byte_in_a_dylib`
(the only red in the first alphabetical half on this tree) is the *same*
`EXC_BAD_ACCESS (code=1, address=0x0)` stop, reached through a module dylib that
calls `memset`. Both are "a call from inside a Mojo-built x86-64 dylib ends at
address 0". A fix for one should be measured against the other; see
`work/x86-run-rows-a` (owned by another worker) for that half.

## The exact next step

`fs_stat_field64` (`os_path___syscalls`, export offset `0x6799`) calls
`0x63d4` and then compares the result to zero. Break there in lldb on the
reduced `t1.x` and find the branch/jump that lands at 0 — the disassembly of
that dylib shows **no indirect `callq *`/`jmpq *` at all**, so the failure is a
`retq` to a corrupted return address or a stub whose `__got` slot is zeroed
after binding, not an obviously indirect call. Then compare the x86-64 lowering
of the `lstat`/`stat` hostmod call and the dylib call-register save/restore
against arm64, which answers correctly.
