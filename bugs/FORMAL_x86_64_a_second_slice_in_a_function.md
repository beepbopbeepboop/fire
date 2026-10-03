# FORMAL/x86_64: a SECOND slice in one function corrupts the first

**Area:** FORMAL (x86-64 backend). **Status: OPEN, measured, root cause NOT
found.** Found 2026-10-02 while fixing the slice and concatenation emitters for
`bugs/FORMAL_arm64_slice_concat_and_with_refusal.md`; that work is landed and
its own doc is deleted, and this is the part of the same measurement that is
x86-64's alone and was not fixed.

**One slice per function works. Two do not, and the failure is silent.** This is
not a slice bug in the sense the fixed doc meant: a single slice of every shape
in a 29-case table now matches CPython on both backends. It is that the SECOND
one, in the same function, loses the first.

## What I ran

```
$ cat .tmp/sl/z_two_vars.mojo
def main(n: Int) -> Int:
    var xs=[1,2,3,4,5,6]
    var a=xs[1:3]
    var b=xs[2:6]
    var s=0
    for v in a:
        s+=v
    for v in b:
        s+=v
    printf("s=%d a0=%d b0=%d\n", s, a[0], b[0])
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64   -o .tmp/a2 …   # arm64: s=23 a0=2 b0=3
$ python3 fire.py build --formal --no-prove --backend=x86_64  -o .tmp/x2 …   # x86-64: no output, SIGSEGV (exit -11)
```

CPython's answer is `s=23 a0=2 b0=3`. arm64 gives it. x86-64 dies in the
kernel.

Three shapes, all pre-existing — each was re-measured with the pre-change
`formal/x86_64_codegen.py` restored from `HEAD` into the tree, and each gave the
same answer before and after the slice fix, so nothing in
`bugs/FORMAL_arm64_slice_concat_and_with_refusal.md` caused or hid them:

| program | x86-64 before the slice fix | x86-64 after | CPython |
|---|---|---|---|
| two slices bound to two names, both iterated | **SIGSEGV** | SIGSEGV | 23 |
| `len(xs[1:3]) + len(xs[:])` | — | **`v=8` → garbage bytes on stdout** | 8 |
| `sum(xs[1:5][1:3])` (a slice of a slice) | **`14`** | **`14`** | **7** |

The third is the quietest and the worst: a slice of a slice answers the sum of
the OUTER slice, so `xs[1:5][1:3]` behaves as if the inner slice were the
identity. It builds, it runs, it exits 0, and it is wrong.

## Why it is not in the tree as a refusal

The honest cheap answer would be to refuse a second slice in a function, and the
`x86-examples` differential would be cheaper to keep green that way. But a
refusal needs a rule that is true, and I do not have one: `len(xs[:3])` and
`len(xs[:])` are two slices in one program and the first is a `len` whose
operand is the expression, so "two slices" is not even a well-defined count
without deciding what a `len` of a slice does to the frame — which is the same
question the fixed doc's §4 was. A guess at that count is the kind of
approximation this backend refuses elsewhere.

## What is known, and where to look

The x86-64 slice emitter is `_emit_slice_parts` in
`formal/x86_64_codegen.py` (~line 5335). It differs from arm64's in one way that
matters here: it pushes the source blob with `_push_slot`/`_pop_slot` and then
holds FOUR values live across the copy loop in registers it does not save —
`R8` (n, then the clamped start), `R9` (the element count), `R10` (the walking
element pointer), `R11` (the index). The second call re-enters the same function
with those four registers already live, and the register allocator is not told,
so a value the first slice left in one of them is read as the second's.

The three shapes are consistent with that and with nothing else I measured:
* two bound slices → the second's `[SP]`-relative or register state is wrong
  enough to fault;
* `len(a) + len(b)` → both are read, one is a pointer (`0x2F61` in the measured
  run, i.e. bytes of an address);
* a slice of a slice → the inner copy loop's `R10` starts from the outer blob
  and the count it takes is the outer's, so the result is a copy of the outer.

**The next step** is to read `_emit_slice_parts` with the four live registers
listed as live-across and find which one the second entry breaks; the cheapest
way to see it is `otool -tvV` on a two-slice image beside the same build's
one-slice image, comparing the register the copy loop ends with. That is where I
stopped — I had the measurement and the suspect list, not the answer.

**Blast radius for whoever takes it:** `tools/formal_sweep.py`'s file counts are
unaffected (nothing new is refused), but any real program with two slices in one
function produces wrong answers silently on this backend today. The
`x86-examples` differential (45 `formal/examples` through both backends) is the
cheapest regression signal for it.