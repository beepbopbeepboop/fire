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
## 2026-10-05 (`work/formal19-3-r2`): the copy is ARM64-COMPLETE and x86-64 loses
## its tail, and three of the four x86-64 faults are named

**Status: the capability is IMPLEMENTED and MEASURED on arm64 and is NOT correct
on x86-64, so nothing landed.** The refusal stands on both architectures, because
a fix that is right on one machine and wrong on the other is the failure mode this
whole repository exists to prevent, and shipping it would make `formal/x86_64_*`
and `formal/arm64_*` answer one construct differently — which
`bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md` §"What closing it
would take" calls the worst outcome for a second recogniser and is equally the
worst outcome here.

**What "the copy" is, and it is smaller than §"The exact next step" makes it.**
§"The exact next step" asks for three pieces: a size, a caller-side block, and a
callee-side `memmove`. **The caller-side block is not needed**, and the measurement
says why: `malloc` takes a run-time size, so the callee can allocate the copy
itself and hand the caller a heap pointer — which is exactly what `os.listdir`
and `formal/hostmods/glob.mojo` already do, and what makes their blobs outlive
the frame. So the work is **two** pieces, both in the callee, and neither of them
is a new ABI:

| piece | what it is | where |
|---|---|---|
| the copy | at a `return` of a blob, `malloc((count+1)*8)` then `memmove` of the blob; **the length is word 0, a run-time count**, which is item 2 of `FORMAL_listdir_no_run_time_sequence.md` | `_emit_move_blob_to_the_heap`, one per backend |
| the question | "is THIS `return` handing back a blob", asked per return site through the emitter's existing `_is_container_expr` — **not** through `functions_returning_containers`, which is a by-name fixpoint answering "on SOME path" and would copy the scalar return of a two-path function | `_returns_container_value`, one per backend |

And the refusal goes: `formal/build.py::_refuse_returned_container_blobs` and
`model.container_escape_sites` become unused, because there is no escape left to
find. `model.functions_returning_containers` survives, published per definition
the way `_image_returns_frame` is.

**arm64: DONE and measured.** `.tmp/esc.mojo` is §"What it is" verbatim. Before:
refused. With the copy:

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/esc.arm64 .tmp/esc.mojo && .tmp/esc.arm64
right after: 11 22 33
after: 11 22 33
```

**`after` was `7 8 9` before the refusal existed.** The copy is six
instructions, the length is a run-time word, and it is the whole of the fix on
that machine.

**x86-64: the sequence emits correctly and the copy loses its TAIL.** The
emitted instruction stream was read back out of the assembler and disassembled
by hand, and it is right: `mov r10,rax` · `mov r11,[rax]` · `add r11,1` ·
`imul r11,r11` · `sub rsp,0x20` · `mov [rsp],r10` · `mov [rsp+8],r11` ·
`mov rdi,r11` · `call malloc` · `mov rdi,rax` · `mov rsi,[rsp]` ·
`mov rdx,[rsp+8]` · `add rsp,0x20` · `call memmove`. And the shortfall is
measured across sizes, on `return [<k literals>]` read back in `main`:

| elements | words the copy must move | words that arrive | printed |
|---:|---:|---:|---|
| 1 | 2 | 1 | `n=1 v0=0` |
| 2 | 3 | 2 | `n=2 v0=11 v1=0` |
| 3 | 4 | 2 | `n=3 v0=11 v1=0 v2=0` |
| 4 | 5 | 4 | `n=4 v0=11 v1=22 v2=33 v3=0` |
| 5 | 6 | 5 | `n=5 v0=11 v1=22 v2=33 v3=44 v4=0` |
| **6** | **7** | **7** | `n=6 v0=11 v1=22 v2=33 v3=44 v4=55 v5=66` |
| **8** | **9** | **9** | all correct |

**Both the count and the first element always arrive and the shortfall is at the
END**, which is what makes "the length register is wrong" and "the source is
incomplete" the two candidates, and both were tested:

* **the length**: raising the `add` from 1 to 2 and to 3 changes NOTHING
  (same three rows), and raising it to 4 fixes every size — so the value reaching
  `memmove` is not the one computed, and the non-monotonicity (2 and 3 identical,
  4 correct) is not a length arithmetic problem.
* **the source**: `def lit(): var q = [11,22,33]; printf("in lit: %d %d %d %d",
  len(q), q[0], q[1], q[2]); return q` prints `n=3 a=11 b=22 c=33` **inside**
  `lit` and `n=3 a=11 b=0 c=0` in `main` — so the blob is complete before the
  copy and incomplete after it, on the same frame, with nothing between but the
  copy.
* **`memcpy` instead of `memmove`**: identical result, so it is not the symbol.
* **storing the length into the destination before the call** (to read it back at
  `[rax+32]`): the program exits 1 with nothing printed, which is its own
  measurement — `malloc(32)` really does hand back exactly 32 usable bytes on this
  target, so the copy of a 3-element blob fits exactly and the block is not the
  thing being overrun.

**Three x86-64 faults in the sequence are named and were each a segfault, not a
wrong number**, which is worth more than the bug they are inside:

1. **`encode_imul_r64_1op` is NOT a shift.** It is the one-operand form,
   `RDX:RAX = RAX * reg`, and it leaves the register you meant to scale untouched
   and hands `malloc` a length computed out of RAX. `encode_imul_r64_r64` is the
   two-operand form. (arm64's twin trap is
   `encode_ldr_xt_sp_imm`'s offset being in UNITS OF EIGHT, so `8` for "the
   second word" reads 64 bytes up the frame.)
2. **`encode_mov_r64_rm64(dst, src, 0)` is a LOAD, not a move.** `mov rdi, r11`
   has to be `encode_mov_r64_r64`; the `_rm64` form reads `[r11]` and hands
   `malloc` the blob's first ELEMENT as its length.
3. **`RDI` must be re-loaded from RAX after `malloc`.** `memmove`'s destination
   is argument 0 and `malloc`'s length is argument 0, and RDI is caller-saved, so
   the version that does not reload writes the copy to the address
   `(count+1)*8`.

**So the next attempt does not start at the design.** It starts at "what does
`memmove` receive as `rdx` on x86-64, in a binary whose `call` goes through a
`__TEXT,__stubs` stub" — and the first thing to try is emitting the copy with the
backend's OWN store loop instead of a library call, because `formal/arm64_codegen.py`
already has `_emit_blob_store` and the x86-64 twin has `encode_mov_rm64_r64`, so a
loop is a handful of instructions in a register set this emitter already owns. The
doc's §"The exact next step" is right that a library call is the better answer
(`formal/hostmods/os/_syscalls.mojo`'s `str_build` uses one for the same reason);
it is simply not the answer that can be verified today, because on this backend it
cannot be observed.

**What this cost and what it bought, stated plainly:** the arm64 half is done and
measured, the design question is answered (two pieces, not three, and no caller
convention), the refusal's own text is now known to be removable, and four
encoder-level traps in this file's copy sequence are named. The x86-64 half is
one unresolved measurement, and it is the ONLY thing standing between this and
`FORMAL_listdir_no_run_time_sequence.md` items 2 and 3 both closing.
