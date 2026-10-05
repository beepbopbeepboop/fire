# a list grown by `s = s + [x]` inside a loop is correct on arm64 and exits 1 on x86-64 past 65 elements, with no diagnostic

**Area:** the x86-64 container path (`formal/x86_64_codegen.py`'s list-concat
emission and whatever reserves its scratch) · **found 2026-10-04 on
`work/formal25-6`** while measuring whether `random`'s Mersenne Twister is
reachable on this path (it is — see the last section) · **NOT fixed** · both
architectures measured, because the whole point is that they disagree

## What I ran

One program, five sizes, both backends, `printf` for the answer rather than the
exit status (which is 8 bits and truncated a first round of this measurement to
nonsense):

```mojo
def p(n: Int) -> Int:
    var s = [0]
    for i in range(K):
        s = s + [1]
    printf("len=%d", len(s))
    return 0
```

`python3 tools/memslot.py --gb 8 --label mtc -- python3 .tmp/mtclean3.py`, each
build with `formal.build.compile_formal(prove=False, check=False)` — no Lean.

## What I saw

| elements | arm64 | x86-64 |
|---|---|---|
| 4, 11, 51, 61, 63, 64, 65 | `len=N` — correct | `len=N` — correct |
| **66, 67, 71, 81, 91, 96, 100, 201, 301** | `len=N` — **correct** | **exit 1, no output at all** |
| 624 (a literal, no concat) | `len=624` | `len=624` |

So the two architectures agree up to 65 elements and then **one of them stops
answering**: x86-64 exits 1 having printed nothing, on a program that is a
three-line loop. There is no diagnostic, no refusal text, and no build-time
error — the image builds, links and dies at run time, which is the shape
`docs`'s own "an image that answers a different number is worse than a refusal"
rule is about, except that here one architecture has the right answer and the
other has none at all.

The threshold is EXACT and it is 65/66: `len=65` prints `65`, `len=66` prints
nothing. 66 words of payload plus an 8-byte count is 528 bytes, and 512 = 64
words is the round number just below it, so the shape is a scratch reservation
of 64 words for the concatenation's destination — on x86-64 only. arm64's
`_blob_cap` accounting is per-function and does not trip at this size.

**What is NOT wrong here, and I checked it before filing anything.** Two
candidate explanations died on measurement, and both are worth recording because
they are the obvious ones:

* *"`len` is truncated to a byte."* No: the same programs print `len=624` for a
  624-element literal. A first round of this measurement read the answer out of
  the process EXIT STATUS, which is 8 bits wide, and every number came back
  `n mod 256` (624 → 112, 300 → 44, 777 → 9) — which is the OS, not the
  compiler. `printf` is the only way to ask this question, and
  `formal/hostmods/_syscalls.mojo`'s own `str_put` is why it can be asked.
* *"An in-loop store at the loop counter's index is lost."* No: a loop storing
  into every element of a 624-element literal is correct on both backends
  (`s[i] = s[i] + 1` for `i` in `range(624)` then `s[623]` and `s[0]` both read
  2), and so is `s[0] = 7` and `s[k] = 9` inside a loop. The concat is the only
  thing that differs.

## Why it matters beyond this one program

`bugs/FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell.md`
§5 item 2 proposed modelling `random`'s `seed`/`randrange` as a Mersenne
Twister and called it "worth a worker's afternoon". That measurement says the
state is expressible — a 624-word literal, in-loop stores into all of it, and
MT's own xor/shift arithmetic (all three measured correct on both backends,
`1812433253 ^ (1812433253 >> 30)` agreeing with CPython's 33252) — so the row
is real work. **The one way to build that state that x86-64 cannot do is to
grow it**, which is the shape the arithmetic itself wants (`init_genrand` fills
624 words one at a time). A literal works and is probably the right answer for a
fixed-size state, but any corpus code that builds a list by appending is on the
wrong side of this on x86-64 today.

## The exact next step

1. **Find the 64-word reservation.** `_emit_list_concat` on x86-64 is the
   emission to read (arm64's is `_emit_list_concat` at
   `formal/arm64_codegen.py:10304` and it is correct); the question is what caps
   the destination at 512 bytes when the source blob is already in the frame.
   `_blob_cap` is set from the scratch/spill accounting on both, so the answer
   is in how x86-64 computes it for a value that GROWS inside a loop — a
   reservation taken once at entry cannot know the final length.
2. **Then decide the fix**: reserve the destination per iteration (the count is
   known only at run time here, so this may be a loop-invariant reservation of
   the worst case), or refuse `s = s + […]` inside a loop on x86-64 with the
   frame message arm64's `frame_blob_refusal` already has. Either is honest;
   what is not honest is exit 1 with nothing printed.
3. **Pin it either way** in `test_formal_value_model.py` (which is the file
   whose stated job is "build, run, and require the same bytes CPython prints",
   and which already covers both architectures per case), as a loop that grows a
   list past 65 elements. It is ~2 s per architecture.

## Reproducing

    python3 - <<'PY'
    import os, sys, tempfile, subprocess
    sys.path.insert(0, os.getcwd())
    import formal.build as B
    src = ("def p(n: Int) -> Int:\n    var s = [0]\n    for i in range(70):\n"
           "        s = s + [1]\n    printf(\"len=%d\", len(s))\n    return 0\n")
    for arch in ("arm64", "x86_64"):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "p.mojo"); open(p, "w").write(src)
            r = B.compile_formal(p, output=os.path.join(d, "p.aout"),
                                prove=False, check=False, arch=arch)
            out = subprocess.run([r["path"]], capture_output=True, text=True)
            print(arch, out.returncode, repr(out.stdout))
    PY
    # arm64 0 'len=71'
    # x86_64 1 ''