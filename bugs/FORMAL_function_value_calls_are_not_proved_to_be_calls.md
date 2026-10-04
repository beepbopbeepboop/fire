# A call through a VALUE is not proved to be a call: the word might not be an address

**Area:** FORMAL (the value model). Found 2026-10-03 on
`work/formal18-tile-specialization`, while landing the lowering this file is
the boundary of — a function value is a CODE ADDRESS and `f[a, b](x)` through
a word is one `BLR` / `CALL r64`
(`bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
§"What landed"). **NOT FIXED, and deliberately: the residual is named here
rather than papered over, because the lowering it belongs to is right and the
check that would close it is a whole-module dataflow.**

## What is refused, and what is not

```mojo
def apply(size: Int, f, func):      # `f` is unannotated — the common case
    for i in range(size):
        f(i)                        # one BLR / CALL r64 through the word
```

lowers, and the word is whatever the CALL SITE put there. This build does not
check that the word is a code address, and it cannot at the call: the callee
cannot see its call sites, and the call sites cannot see the callee's body
across a dylib boundary. So

```mojo
def main():
    apply(3, 17)                    # CPython: TypeError, 'int' object is not callable
```

builds, and the image branches to address 17.

**The failure mode is a TRAP, not a wrong answer.** An indirect branch to a
word that is not code lands on an unmapped page, so there is nothing to
execute: measured, SIGBUS (exit 138) on arm64 and SIGSEGV (exit 139) on
x86-64. That is the loud end of this backend's range
— `bugs/FORMAL_known_limits.md`'s standing complaint is about refusals that
"build, run, and return a number the source never wrote", and this is not one.
What it costs is a diagnostic: a program whose own bug it is used to be told
about at build time is now told about by the kernel.

## What IS checked, and why each check is the honest one available

Both are in `formal/model.py`, both asked from both backends, and both read the
caller's DECLARATION rather than its dataflow:

* **`value_callee_can_hold_a_function(ann)`** — a parameter declared a
  container this path subscripts (`List[Int]`, `String`, `SIMD`) or a scalar
  (`Int`, `Bool`, `DType`) cannot hold a code address, so a call through it is
  refused by name (`callee_value_refusal`). This is the only soundness check
  available locally and it catches the shape a corpus actually writes. A
  container-typed `f(x)` is a program its own declaration refutes.
* **`value_call_bracket_reading(fn, name, ann)`** — a bracketed callee through a
  value is a specialization or an index, and the declared type is the only thing
  that can say. `Some[…]` and a `def[…]` function type cannot be subscripted on
  this path, so their brackets are comptime parameters; a container's are an
  index; an unannotated parameter is refused rather than guessed at.

An UNANNOTATED parameter is allowed through, deliberately: it is the common
spelling (`stdlib/std/algorithm/backend/cpu/map.mojo`'s own `func`) and a
function value is the most likely thing it holds. That is the permissive
direction on purpose, and it is where the residual lives.

## What closing it would take

A whole-module analysis over every value a callee might have been handed:

* for each name called through a value, every site that WRITES it — an
  assignment, an augmented assignment, a loop target, a `with … as`, a
  container store, a `return` — must be a bare read of a function of this
  image;
* for each PARAMETER called through a value, every call site of that function
  must pass a function-name read in that position, which needs the callee's
  body and the caller's body at once and crosses a dylib boundary.

Both halves are syntactic and neither is cheap to get right: `formal/build.py`
already has a family of walks over the same shapes (`_names_bound_in`,
`bound_names_in_order`) and each has its own documented imprecision, and a walk
that MISSES a write is not a missed warning — it is a program that traps
instead of being refused.

**A cheaper alternative exists and is NOT taken, because it would be a
property of the wrong thing**: emitting a runtime check that the word is one of
this image's function entry addresses. It is O(n) comparisons per call on a
target whose programs are small, it cannot cover a function in another image
(whose addresses are not known at build time), and it turns a static property
into a runtime one, which is the opposite of what this backend is for.

## Reproducing the residual

```sh
export PATH=/opt/homebrew/bin:$PATH
cat > .tmp/fv_bad.mojo <<'EOF'
def apply(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    return apply(3, 17)
EOF
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=$a -o .tmp/fv_bad-$a .tmp/fv_bad.mojo
  .tmp/fv_bad-$a ; echo "[$a] exit=$?"
done
```

Measured: both BUILD; the arm64 image dies of SIGBUS (exit 138) and the x86-64
image of SIGSEGV (exit 139). The interpreter refuses the program outright
(`TypeError: 'int' object is not callable`), so the two engines disagree about a
program they both reject — which is the honest statement of this file's
subject.

Pinned, so the residual stays visible rather than becoming folklore:
`test_formal_specialization.py`'s `the two remaining refusals of a value call`
pins the CHECKED side of it (a keyword, an unreadable bracket, a
container-typed callee) on both architectures, and this file is what the
unchecked side is.
