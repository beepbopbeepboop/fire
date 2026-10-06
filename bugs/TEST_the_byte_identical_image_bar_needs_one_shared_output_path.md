# The "byte-identical image" bar needs the two sides to share an `-o` path, and a raw `cmp` therefore always fails

**Area:** tests / measurement method. **Status: OPEN, measured; the harness is
scratch and the measurement is written down here.** **Found 2026-10-05** on
`work/formal27-3` while running §5.1's own bar for a change that is supposed to
be behaviour-preserving.

## Why this is a bug and not a note

**`bugs/FORMAL_build_cost_2026-10-03.md` §5.1 states the bar for a
behaviour-preserving change as "`cmp` the artifacts", and §6.1 restates it as
"the image is byte-identical (`sha256`)".** Both are the right bar and neither is
achievable as written: **two builds of the SAME source on the SAME tree produce
different bytes**, so a `cmp` reports a difference for every file, the reader
cannot tell a real regression from the noise, and the honest-looking conclusion
is that a change which provably changes nothing is not byte-identical. That is
the worst failure mode this bar has: not a missed regression but a manufactured
one, and it costs a session the whole measurement.

## What I ran, and what it says

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 \
      -o .tmp/smp/b1.out formal/examples/count.mojo
$ python3 fire.py build --formal --no-prove --backend=arm64 \
      -o .tmp/smp/b2.out formal/examples/count.mojo
$ cmp -l .tmp/smp/b1.out .tmp/smp/b2.out | wc -l
1
$ cmp -l .tmp/smp/b1.out .tmp/smp/b2.out
49278  61  62
```

**ONE byte, in a 67 504-byte image**, and it is the image's own **base name**,
which is embedded in the image text:

```console
$ python3 - <<'EOF'
a = open('.tmp/smp/u1.out','rb').read(); b = open('.tmp/smp/u2.out','rb').read()
i = 49277
print(repr(a[i-24:i+24])); print(repr(b[i-24:i+24]))
EOF
b'...\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x01u1-55554944000000'
b'...\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x01u2-55554944000000'
```

**So the two sides must be written to the SAME `-o` path**, and that is the whole
of it on this path today. A harness that gives each side its own output path
(`-o new-…` / `-o old-…`) makes **every** file differ, on this byte, for a reason
that has nothing to do with the compiler — and that is exactly what the first
version of this pass's harness did, reporting **104 DIFFER out of 104** for a
change that turns out to produce 104 byte-identical images. The differing byte is
in no load command a reader would look at; `otool -l` on the image is clean.

**The one hazard worth normalising defensively, which is NOT the observed
cause:** Mach-O's `LC_UUID` is a per-link load command, and a comparison that
reads it is reading a field that is *supposed* to vary per link. On this path it
does not vary — measured, both architectures:

| | `LC_UUID` command at | payload | all-zero? |
|---|---|---|---|
| arm64 | 576 | 16 bytes, 584 is **not** where it starts — see below | **yes** |
| x86-64 | 808 | 16 bytes | **yes** |

(`otool -l` prints `uuid 00000000-0000-0000-0000-000000000000`, and a parser
finds the payload at `cmdoff + 8`, which is 576-592 on arm64 and 808-824 on
x86-64 — the two architectures put the load commands at different offsets, so a
hardcoded offset is wrong on one of them.) Blanking that payload changed **zero
bytes** in this measurement. It is listed because an ad-hoc signature or a real
UUID would move 16 bytes and the bar should not silently depend on that staying
false, not because it is what bit this pass.

## The measurement that then works, and is the real result

With both sides writing to one path (and the `LC_UUID` payload zeroed):

```console
$ python3 .tmp/bytecmp.py HEAD HEAD~1 arm64,x86_64
…
104 builds: 104 images byte-identical,
            0 refusals identical in exit code and full text, 0 DIFFER
```

**52 `formal/examples/*.mojo` × 2 architectures, every image byte-identical
between `HEAD` and `HEAD~1`, and zero refusals whose exit code or diagnostic text
moved.** That is §5.1's bar, met, for the change it was written about (the
one-field table publishing the field's name, so the field set is derived once per
struct). **The base-name byte is at a different offset per architecture** — 49277
on arm64's `count.mojo`, 49293 on x86-64's — so a harness that masks "the byte
that differed last time" is not a harness; writing both sides to one path is the
fix, and it is the only one that generalises.

## The exact next step

**Turn this into a committed helper, and state the one required normalisation at
both places that prescribe the bar.** The helper is ~35 lines (build both sides
to one `-o` path, parse `ncmds` at offset 16 and the commands from offset 32 on
64-bit, blank each `cmd == 0x1B` payload at `cmdoff + 8`, hash). Two candidate
homes, and the choice is a judgement rather than a measurement:

* `tools/` beside the other `formal_*` instruments, with `test_formal_*` coverage
  — the argument for it is that this harness has now been written twice in two
  sessions (this one, and the one `bugs/FORMAL_build_cost_2026-10-03.md` §5.1
  describes), which is the definition of a tool that should exist;
* the two doc paragraphs themselves, as the extra sentence each needs — cheaper,
  and it leaves the harness to be rewritten each time, which is the thing that
  produced this.

**Do not "fix" it by comparing the generated C instead.** There is no committed
way to get the C out of `fire.py build --formal` (the `--dump` machinery is
`mojoc`'s, not this path's), and the image is the artifact the two backends
actually differ in — §OPUS-2's "`hreg` exhausts `maxHeartbeats`" and
`bugs/FORMAL_dylib_block_layer_is_not_the_ceiling.md`'s "`csel x0, x0, x1, eq`
is the eighth instruction" are both statements about bytes inside it. Nothing in
this project claims a difference in an image's embedded base name either, so
writing both sides to one path removes no byte a claim could be resting on.