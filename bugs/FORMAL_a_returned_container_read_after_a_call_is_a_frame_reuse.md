# FORMAL_a_returned_container_read_after_a_call_is_a_frame_reuse: a list a function hands back is a block of its own frame, and the caller's next call overwrites it

**Status 2026-10-04 (`work/formal21-5`): the wrong answer is REFUSED, and the
capability that would make it right is the next step rather than the work.** A
container returned by a function in this image is frame-resident on both
architectures, the caller's next call reuses that frame, and the two machines
read back two DIFFERENT wrong answers for one source. `formal/model.py::
container_escape_sites` now refuses the escape at the read — which is where the
fact is, and refusing the return instead would take `formal/hostmods/struct.mojo`
out for a use its own docstring measured as sound.

**Claim** `sweep20:host-import` — no: `formal21-5`'s, working
`bugs/FORMAL_listdir_no_run_time_sequence.md` item 3, which is the same defect
seen from the `os` side.

## What it is

```mojo
def lit() -> List[Int]:
    return [11, 22, 33]

def litter(n) -> Int:
    var junk = []
    junk.append(n); junk.append(n + 1); junk.append(n + 2)
    return len(junk)

def main(n) -> Int:
    var p = lit()
    printf("right after: %d %d %d\n", p[0], p[1], p[2])   # 11 22 33, both machines
    var k = litter(7)                                   # any call at all
    printf("after: %d %d %d\n", p[0], p[1], p[2])
    return 0
```

CPython answers `11 22 33` in both lines. This backend, before the refusal:

| | arm64 | x86-64 |
|---|---|---|
| right after the call | `11 22 33` | `11 22 33` |
| after `litter(7)` | **`7 8 9`** — `litter`'s own scratch | **`8 9 33`** — a MIX of the two frames |

The program **builds, runs, and exits 0**. That is the failure mode this
backend exists to prevent: not a crash, not a refusal, a plausible answer.

**Two constructions, one defect.** `return [11, 22, 33]` (a list LITERAL) and
`return xs` where `xs` was built by appends are the same wrong answer, measured
identically — which CORRECTS
`bugs/FORMAL_listdir_no_run_time_sequence.md` item 3's "a RETURNED CONTAINER
LITERAL is `malloc`'d rather than frame-resident". **It is not.** The values read
correctly immediately after the call, and that is the only reason it looked like
it was: nothing has been pushed over the dead region yet.

## Why the values are not simply garbage

The blob is laid out in the frame by `_blob_est` (arm64_codegen.py:9805,
x86_64_codegen.py:4744) — per append SITE, in the frame's own scratch, with the
count in word 0. The callee's frame is popped when it returns, so the region
above the caller's SP is free. A later call pushes a frame at that same SP and
writes into it. Whether the caller's list survives therefore depends on **how
much stack the next call uses**, which is why:

* `printf(...)` in the control below leaves the values intact on both machines
  (measured), and
* `litter(7)` — a Mojo function with its own list — destroys them.

**So "read it before you call anything" is not a sound rule and not a
justifiable one**: it is a size coincidence. The refusal below is therefore
conservative (any call between the binding and the read) and the docstring says
why, rather than pretending the immediate case is proved.

## What landed

`formal/model.py`:

* `functions_returning_containers(functions)` — a monotone fixpoint over this
  image's own functions: a function returns a container if it returns a list
  literal, a name it binds to one, or a call to a function already known to
  return one. It is what makes the CALL side decidable without a manifest, and a
  call to ANOTHER IMAGE is deliberately not in it: `os.listdir` `malloc`s and its
  docstring says the caller owns it, which is why `names = os.listdir(p)`,
  `names[i]` and `for x in names` work today.
* `container_escape_sites(fn, returns_container)` — the read side: a name bound
  to such a call, read again after a statement containing any call. Both
  architectures, both message halves.
* `returned_container_refusal` — says what was measured, names the two
  different wrong answers, and gives the spellings that lower today.

`formal/build.py::_refuse_returned_container_blobs` asks it per function beside
`_refuse_variadic_reads`, and the once-per-unit fixpoint is computed with the
other tables at the top of `check_module_symbols`.

**The check is at the READ and not at the callee's RETURN, and that is the
design.** A returned container read before the caller calls anything else is
what this tree has a dozen of on purpose:

* `formal/hostmods/struct.mojo`'s `unpack_from` builds its list in its own frame
  and its docstring records the measurement — "a list built here is in this
  frame, which is correct for the corpus's immediate `[0]`";
* `formal/x86_64_decode.py:105` and `:251` are
  `struct.unpack_from("<i", code, at)[0]`.

Refusing the return would have refused `struct.mojo` (measured: the hostmods
census drops from 64/64 rows building to 62/64) for a use its own author measured
as correct. **Measured after the change: 64/64 hostmods build on both
architectures, and `test_formal_os_backing.py` is 58/58** — nothing in the corpus
depended on the escape.

## The exact next step

**The capability is the struct-frame convention, applied to a blob**, and
`formal/model.py`'s own section says so: "The fix is a COPY, and the copy has to
land somewhere the CALLER owns … the caller passes the block's address as one
hidden TRAILING argument, the callee copies into it and returns it"
(`struct_returned_frame_sites`, `returned_frame_convention_refusal`). A container
needs the same three pieces and nothing new in principle:

1. **a size** — the callee must know how many words to copy. `_blob_est` is a
   compile-time bound today and a run-time count for a returned blob (the count
   IS word 0), so the copy length is available exactly where the returned struct's
   size is available today;
2. **a caller-side block** — reserved in the caller's scratch at the call site,
   which is `struct_returned_frame_sites` with the blob shape in place of the
   struct;
3. **a callee-side `memmove`** — `formal/hostmods/os/_syscalls.mojo`'s primitive
   for exactly this (it is what `str_build` uses), so the copy is one library
   call rather than a loop the two emitters would each spell.

**What it is worth**: it converts the largest remaining wrong-answer class in the
container value model into a refusal this change has already made, and it is the
same project as `FORMAL_listdir_no_run_time_sequence.md` item 2 (a list whose
length is only known at run time has to be `malloc`'d for the copy to have
anything to copy). Items 2 and 3 of that document are one piece of work, not
two, and this file is where the copy half is written down.

**What is NOT left**: the immediate-read shape keeps working, deliberately and
with the measurement in `formal/hostmods/struct.mojo` where its author put it.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
# The measurement, both architectures.
cat > .tmp/esc.mojo <<'EOF'
def lit() -> List[Int]:
    return [11, 22, 33]
def litter(n) -> Int:
    var junk = []
    junk.append(n); junk.append(n + 1); junk.append(n + 2)
    return len(junk)
def main(n) -> Int:
    var p = lit()
    printf("right after: %d %d %d\n", p[0], p[1], p[2])
    var k = litter(7)
    printf("after: %d %d %d\n", p[0], p[1], p[2])
    return 0
EOF
# with the refusal reverted, for the two wrong answers:
git stash push -- formal/model.py formal/build.py     # (or edit the reader out)
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label esc -- \
      python3 fire.py build --formal --no-prove --backend=$a -o .tmp/esc/$a .tmp/esc.mojo
  .tmp/esc/$a; echo "exit=$?"
done
# The refusal and its control:
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_frame_return_overloads.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os_backing.py
```

Nothing here is a whole-closure compile, a self-host build or a Lean run: four
single-file builds and three narrow suites.