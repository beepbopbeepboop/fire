# FORMAL_a_starred_for_target_is_broken_on_both_backends: `for a, *rest in …` builds and then exits 1 with nothing printed

**Class:** a silent wrong program on BOTH formal backends — it builds, links,
runs, produces no output and exits 1, where CPython and the interpreter bind the
fixed name and the rest blob. **Area:** FORMAL, arm64
(`arm64_codegen.py::_emit_for_unpack` / `_emit_for_unpack_star_rest`) and x86-64
(`x86_64_codegen.py::_emit_for_unpack`, which has no star arm at all). Found
2026-10-05 on `work/formal123-docs` while fixing the nested-target unpack and
testing that the star spelling still behaved as before; it is PRE-EXISTING and
not a regression from that change.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ cat .tmp/star5.mojo
def main():
    for a, *rest in [(1,)]:
        printf("a=%d\n", a)
    return 0

$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A \
      -o .tmp/star5.$A .tmp/star5.mojo && ./.tmp/star5.$A; echo "  exit=$?"; done
Built: .tmp/star5.arm64  [arm64/macho]
  exit=1                       <- no output at all
Built: .tmp/star5.x86_64  [x86_64/macho]
  exit=1                       <- no output at all
```

The interpreter and CPython both answer the program:

```console
$ cat .tmp/star3.mojo
def main():
    for a, *rest in [(1, 2, 3)]:
        print(a)
        print(len(rest))
    return 0
$ python3 fire.py run .tmp/star3.mojo
1
2
```

## The boundary of it

* An EMPTY iterable is fine on both backends — the unpack never runs:
  `for a, *rest in []:` prints nothing and exits 0 on both. So the failure is in
  the per-element unpack, not in the loop setup.
* A star is required for the failure: the one-level and two-level nested targets
  without a star (`for a, (b, c) in …`) are fixed and answer CPython's number.
* Both backends fail identically, which is why this is filed as one shared bug
  rather than as a backend divergence. It is NOT one: they fail the same way.

## Where to look

* **arm64** owns a star path already (`_emit_for_unpack`'s `star_i` branch and
  `_emit_for_unpack_star_rest`). The rest-blob loop's guard is the first thing to
  read: it is the `cmp X4, X3` / `cset X0, "ge"` / `cbz X0, <done>` pair, and a
  "while `i < rest_count`" loop that branches to `done` on the **ge** result
  wants `cbnz`, not `cbz`. I did NOT confirm this against a disassembly — the
  build is green and the failure is a bare `exit(1)` with no diagnostic, so the
  next step is to disassemble `main` (`otool -tvV`) or step the exit site, not to
  trust this paragraph.
* **x86-64** has no star handling in `_emit_for_unpack` at all; the only reason
  the spelling does not raise `_no_home` there is that the for-target reader
  strips the star before it reaches the emitter (`_strip_stars` in
  `x86_64_codegen.py`, which preserves the pre-existing behaviour). Whatever the
  arm64 fix turns out to be, the x86-64 half needs the same arm so the two agree.

## Next step

Reproduce with the two commands above, disassemble the arm64 image's `main` to
find which of the three `exit(1)` sites is taken (the top arity check, the
star-rest cap guard, or the `oob` arm), and fix the guard; then give x86-64 the
matching star arm and pin the whole thing on both backends (a `BOTH_ARCH_CASES`
row in `test_formal_run.py` whose expected output is CPython's, which is what
would have caught this).
