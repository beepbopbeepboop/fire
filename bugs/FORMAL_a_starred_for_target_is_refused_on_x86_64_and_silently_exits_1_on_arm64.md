# A starred for/comprehension target is refused on x86-64 and builds-then-exits-1 on arm64

**Area:** FORMAL, both backends — the for/comprehension target unpack. Found
2026-10-08 on `work/formal154-docs` while pinning the nested-group fix
(`model.for_target_tree`) that landed as `6b27eb42`.

**Status: OPEN. Not fixed here** — it is a construct neither backend lowers, and
the two disagree about how to say so.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ cat > .tmp/star.mojo
def main():
    s = 0
    for a, *rest in [(1, 2, 3)]:
        s = s + a
    printf("s=%d\n", s)
    return 0

$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A -o .tmp/star.$A \
      .tmp/star.mojo && ./.tmp/star.$A; echo "  $A exit=$?"; done
Built: .tmp/star.arm64  [arm64/macho]
  arm64 exit=1                       <- no output at all
build: for-loop target must be a plain name or tuple of plain names
       (got '(a, *rest)')
  x86_64 exit=1
$ python3 -c 'exec(open(".tmp/star.mojo").read().replace("printf(\"s=%d\\n\", s)","print(\"s=%d\" % s)"));main()'
s=1
```

CPython binds `a = 1`, `rest = [2, 3]` and prints `s=1`. arm64 **builds** and
then exits 1 printing nothing; x86-64 **refuses at build time**. Same shapes for
a comprehension target, a one-element `*rest`, and `for *rest, in …`:

| target | arm64 | x86-64 |
|---|---|---|
| `a, *rest` over `[(1, 2, 3)]` | builds, exit 1, no output | build refusal, names the target |
| `a, *rest` over `[(1, 2)]` | builds, exit 1, no output | build refusal |
| `*rest,` over `[(1, 2, 3)]` | builds, exit 1, no output | build refusal |

Measured on this tree with `6b27eb42` applied (the shared `for_target_tree`),
both directions.

## Why it matters

This is the parity failure the two backends are not allowed to have, in the
worse direction: one machine **silently stops** (exit 1, nothing printed, which
`test_formal.py`'s own reading calls the failure a reader cannot tell from an
assert or a crash) and the other **refuses by name**. `6b27eb42`'s message
already says x86-64 "never lowered a starred target"; arm64's
`_emit_for_unpack_star_rest` and the star arms in `_emit_for_unpack` exist, so it
is *intended* to lower one, and it does not.

## The next step

Pick one of two, and do it on BOTH backends so they cannot answer differently:

1. **Refuse it, in one shared sentence.** The x86-64 refusal is already the
   right shape (`for-loop target must be a plain name or tuple of plain names`);
   arm64 should raise the same before it reaches `_emit_for_unpack`, and the
   now-unreachable star machinery in `formal/arm64_codegen.py`
   (`_emit_for_unpack_star_rest` and the `'*name'` arms) should be deleted in the
   same commit, not left as dead code that reads as support.
2. **Lower it.** Debug `_emit_for_unpack_star_rest` — the exit 1 happens on a
   one-element `rest` too, so it is not a capacity bound — then port the same
   arm to `formal/x86_64_codegen.py`. This is the option that matches CPython.

Nothing in the corpus uses a starred for-target (`grep` over `*.mojo` finds
none), so neither option moves a sweep number; the value is closing the
divergence and replacing arm64's silent exit 1 with an answer.

**No Lean is needed for either**: the defect is visible in the built image's
behaviour and in the build refusal.
