# x86-64: a `for` target nested more than one group deep prints nothing and
# exits 1, where arm64 answers CPython's number

**Class:** a silent wrong program — it builds, links, runs, produces no output
and exits 1. **Area:** FORMAL, the x86-64 backend only. Found 2026-10-05 on
`work/formal40-2` while landing the `for`-target capture arm in
`mojo/middle/closures.py`, and **not fixed here**: it is in a backend emitter,
which is not this pass's subject, and it is not a regression from that change
(measured below).

## What I ran

Three shapes, each `printf`ing the accumulated sum, each built with
`--no-prove` on both backends and then run.

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ cat .tmp/tup6.mojo
def main():
    s = 0
    for a, (b, (c, d)) in [(1, (2, (3, 4)))]:
        s = s + a + b + c + d
    printf("s=%d\n", s)
    return 0

$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A \
      -o .tmp/tup6.$A .tmp/tup6.mojo && ./.tmp/tup6.$A; echo "  exit=$?"; done
Built: .tmp/tup6.arm64  [arm64/macho]
s=10
  exit=0
Built: .tmp/tup6.x86_64  [x86_64/macho]
  exit=1                       <- no output at all
$ python3 -c 'exec(open(".tmp/tup6.mojo").read().replace("printf(\"s=%d\\n\", s)","print(s)"));main()'
10
```

## What is wrong, and the boundary of it

**Depth two is where it starts.** Each of these builds and runs correctly on
BOTH backends:

| shape | arm64 | x86-64 | CPython |
|---|---|---|---|
| `for a, b in [(1, 20)]: s = s + b + a` | `21` | `21` | `21` |
| `for a, (b, c) in [(1, (20, 300))]: s = s + b + a` | `21` | **nothing, exit 1** | `21` |
| `for a, (b, (c, d)) in [(1, (2, (3, 4)))]: s = s + a + b + c + d` | `10` | **nothing, exit 1** | `10` |

So one level of unpacking is fine on x86-64 and two is not. That is the whole
of the measured boundary; I did not go further (a depth-3 flat list, a starred
leaf inside a nested group, a nested group over a tuple-typed iterable).

## It is not a regression from the closure change on this branch

`work/formal40-2` adds a `ForStmt` arm to
`mojo/middle/closures.py::discover_closures`'s `enriched_scope` build, so a
nested `def` can capture a loop variable. The programs above contain **no
nested `def` at all**, so that arm has nothing to act on. Measured anyway, with
the arm neutralised back to master's behaviour in-process:

```console
$ cat .tmp/prev.mojo
import sys; sys.path.insert(0, '.')
import mojo.middle.closures as C
C.loop_target_names = lambda target: []      # master's behaviour: no arm
import fire; fire.main()

$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 .tmp/prev.mojo build --formal --no-prove --backend=$A \
      -o .tmp/prev.$A .tmp/tup6.mojo && ./.tmp/prev.$A; echo "  exit=$?"; done
Built: .tmp/prev.arm64  [arm64/macho]
s=10
  exit=0
Built: .tmp/prev.x86_64  [x86_64/macho]
  exit=1
```

Identical, so the defect is on master and this pass did not bring it here.

## Where to look

`fire_compiler.for_target_names` is the one reader of this field and it
flattens correctly (`'(a, (b, c))'` → `['a', 'b', 'c']`, measured), so the
parser is not where this lives. That leaves the **x86-64 emitter's loop-target
unpack** — `formal/x86_64_codegen.py`'s `ForStmt` arm, which rebuilds the
`ForStmt` it lowers (`formal/x86_64_codegen.py:2328`, the mirror of
`formal/arm64_codegen.py:2605`). The arm64 emitter gets the same flat name list
and works, so the comparison to make first is those two `ForStmt` arms against
each other on a NESTED `target_slots(...)` split.

**The next step, in order.** Diff the two emitters' `ForStmt` arms and find
where the nested-group case emits a different instruction sequence; then narrow
it with `fire.py build --formal --no-prove --dump-full`-free means — a
scratch `.mojo` per depth is enough, since the boundary is already measured
above. **No Lean is needed for any of it**, which is why this is a cheap bug
rather than a project: the defect is visible in the emitted image's behaviour
alone.

**Why it is worth more than its file count.** This is the failure mode
CLAUDE.md's `check`-reading warns about in the other direction from the usual:
not a wrong value but NO value, with exit 1 rather than a diagnostic. A program
that loops and accumulates is ordinary code, and a reader gets a silent
nothing.