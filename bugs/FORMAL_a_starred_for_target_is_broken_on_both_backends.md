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

## Update 2026-10-12 (`work/merge-qwen1`, formal154 merge): x86-64 no longer
silently exits — the two machines now answer differently, and arm64 is the
worse side

Re-measured every shape below on the merged tree, both backends,
`python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal
--no-prove --backend=$A`. CPython is the column they must both match:

| target | arm64 (merged tree) | x86-64 (merged tree) | CPython |
|---|---|---|---|
| `a, *rest` over `[(1, 2, 3)]` | builds, exit 1, no output | **build refusal** (below) | `s=1` (`a=1`, `rest=[2, 3]`) |
| `a, *rest` over `[(1, 2)]` (one-element rest) | builds, exit 1, no output | build refusal | `s=1` |
| `*rest,` over `[(1, 2, 3)]` (star only) | builds, exit 1, no output | build refusal | `rest=[1, 2, 3]` |
| `a, *rest` over `[]` (empty) | builds, exit 0, `s=0` | build refusal (never runs) | `s=0` |
| `a, (b, c)` (no star) — the fixed neighbor | builds, exit 0, `s=321` | builds, exit 0, `s=321` | `s=321` |

So the 2026-10-05 picture ("both build and silently exit 1") is stale for
x86-64: a shared home-consistency walk now refuses the star name at BUILD time,
with the named diagnostic

```console
$ ./.tmp/star.arm64                       <- arm64 still: builds, then
  exit=1                                  <- no output at all
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/star.x86_64 .tmp/star.mojo
build: main: '*rest' has no home: the register allocator collected no home for
  it, so the emitter and the allocation walk disagree about this function's
  locals. This path places a name in a register or a spill slot allocated for
  THIS function, a receiver field's frame, or a module-level constant the build
  folded — and a name in none of them is refused rather than read out of
  whatever register the allocator left behind, ...
```

* **Where x86-64 refuses now.** `x86_64_codegen.py::_strip_stars` strips the
  star in the UNPACK EMITTER (the two for-emit call sites), but the star name
  `*rest` still sits in the function's locals, and the per-function walk in
  `build.py` that asks `M.unresolved_name_refusal` (`formal/model.py`) sees a
  name with no register, spill slot or frame slot and refuses before anything
  is emitted. This supersedes the "x86-64 has no star handling … the for-target
  reader strips the star before it reaches the emitter, which preserves the
  pre-existing behaviour" reading above: the strip is real, but it is local to
  the emitter and the walk does not share it.
* **arm64 is unchanged and is now the WORSE side.** The 2026-10-05 divergence
  was "they fail the same way"; the merged-tree divergence is "one machine
  refuses by name at build time, the other silently exits 1 with nothing
  printed — which `test_formal.py`'s own reading calls the failure a reader
  cannot tell from an assert or a crash." arm64 still owns the intended star
  path (`_emit_for_unpack_star_rest`, `formal/arm64_codegen.py:3834`, called
  from `_emit_for_unpack`'s star arm at :3829) and still produces the bare
  `exit(1)`; the exit happens on a one-element `rest` too, so it is not a
  capacity bound.
* **What did not move.** The empty-iterable boundary (arm64 runs the loop body
  zero times and answers CPython's `s=0`), and the non-star nested target
  (`a, (b, c)` answers `s=321` on both).

The next step from the 2026-10-05 section stands, with one addition measured
from `work/formal154-docs` (whose branch-local doc for this bug is superseded
by this section): the fix may be EITHER of two, and it must land on BOTH
backends so they cannot answer differently — (1) refuse it, in one shared
sentence, and delete the then-unreachable arm64 star machinery in the same
commit rather than leave it as dead code that reads as support; or (2) lower
it (debug the arm64 guard first), which is the option that matches CPython.
Nothing in the corpus uses a starred for-target — re-checked 2026-10-12,
`grep -r 'for \*rest\|, \*rest in\|\*rest, in' --include='*.mojo'` matches no
source — so either option moves no sweep number; the value is closing the
divergence and replacing arm64's silent exit 1 with an answer. No Lean is
needed for either: the defect is visible in the built image's behaviour and in
the build refusal.
