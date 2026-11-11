# FORMAL: ELF module dylib writes non-zero bytes past its last PT_LOAD segment

Found 2026-11-09 by the recovery sweep (`recover/save.md` row 20, commit `da444a039`,
"formal: a dylib runs its module body at load time").

## What I ran

    git archive master | tar -x -C .tmp/master_export   # master as of 2026-11-09
    cd .tmp/master_export
    python3 test_formal_x86_64_dylib.py                 # under tools/memslot.py --gb 8

## What I saw

    PASS  a module body is a load-time initializer in both containers
    FAIL  an ELF module dylib is a loadable object
          7 non-zero byte(s) past the last segment's 2425-byte tail
    formal x86-64 dylib: PASS=16 FAIL=1

The test is `test_an_elf_module_dylib_is_a_loadable_object` in
`test_formal_x86_64_dylib.py` (master line ~286; the tail check at ~line 423).
Its assertion is that `data[body_end:]` is all zeros, where `body_end` is the end
of the last PT_LOAD segment. The check is named by the row-20 commit's own test
diff (`git show da444a039 -- test_formal_x86_64_dylib.py`), so the commit pins it.

Registered as the gate job `formal-x86-dylib` in `tools/suite.py` (master, around
line 3566) with **no** `expect=` or `disabled=` marker. On master that gate job is
red for this reason.

## What is expected

Every byte past the last segment is page padding to `p_align`, and padding is zero.
The ELF image's file size is a page multiple, and nothing the emitter writes lies
outside a PT_LOAD.

## Why it is not already fixed

The row-20 commit changes `formal/elf.py` (105 changed lines). Its hunk does not
apply to master's `formal/elf.py`:

    git read-tree master                      # into a temp GIT_INDEX_FILE
    git show da444a039 --no-merges -- formal/elf.py | git apply --cached --check
    error: patch failed: formal/elf.py:57

So the commit's layout change is either not on master, or master changed the same
region after it. I have not isolated which bytes are written past the segment or
which emitter writes them. The commit's `formal/elf.py` hunk is the reference for
the layout the test expects.

## Next step

1. Dump the file tail of the failing image: build a one-function module with
   `compile_formal_dylib([src], output=out, arch="x86_64", fmt="elf", prove=False, check=False)`
   on the master export, then read `data[body_end:]` and map the non-zero offsets to
   the section or table that owns them (`.dynamic`, `.hash`, `.dynsym`, `.dynstr`,
   or the section header table). `formal/elf.py` holds the writer.
2. Compare that region in master's `formal/elf.py` with the row-20 commit's version
   (`git show da444a039 -- formal/elf.py`). Decide: is the bytes' writer a later
   master change that should be reverted, or a path the commit's hunk covers?
3. Fix the writer so the tail is zero (not a test edit), and rerun
   `python3 test_formal_x86_64_dylib.py`: it must report FAIL=0.

Do not mark `formal-x86-dylib` with `expect=`: the failure is a real emitter defect,
and the row-20 commit's own test asserts the zero tail.
