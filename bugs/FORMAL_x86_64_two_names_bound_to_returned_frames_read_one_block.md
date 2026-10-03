# FORMAL_x86_64_two_names_bound_to_returned_frames_read_one_block: on x86-64 the second frame-returning call overwrites the first one's block, and both names read it

**Area:** FORMAL (`formal/x86_64_codegen.py`, the returned-frame convention's
caller side). Found 2026-10-03 on `work/formal13-4` while trying to land
`bugs/FORMAL_a_function_whose_return_value_is_a_construction_is_not_frame_returning.md`,
which this defect blocks. **Status: OPEN, pre-existing, measured on this tree, and
it is a SILENT WRONG ANSWER on one architecture** — not a crash, not a refusal.

This is the same neighbourhood as
`bugs/FORMAL_x86_64_a_field_of_a_returned_frame_in_an_argument_position_segfaults.md`
(thirteen `test_formal_returned_frame.py` cases, all `--backend=x86_64`, mostly
SIGSEGV). That one is a field of a returned frame in an ARGUMENT position; this one
is two NAMES bound to returned frames in one function, and it answers with a
number. If they are one emitter bug, this is the smaller reproducer and the
cheaper fix; if they are two, this one is the one that has been hiding, because a
program that reads the wrong block and prints a plausible integer is invisible to
every suite that only checks exit statuses.

## What I ran

Four programs, all the same twelve-line shape, both backends, CPython on the same
text. `mk` returns a frame by NAME (not by construction — that spelling is what
works today, see the other doc):

```python
struct A:
    var x: Int
    var y: Int

def mk(v: Int) -> A:
    var a = A()
    a.x = v
    a.y = v
    return a

def plain(v: Int) -> Int:
    return v

def main(n: Int) -> Int:
    var t = mk(1)
    var u = mk(2)
    printf("%d %d", t.x, u.x)
    return 0
```

`python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal
--no-prove --backend=<arch> -o .tmp/ow/<name> .tmp/ow/<name>.mojo`, then run it.

## What I saw

| program | CPython | arm64 | x86-64 |
|---|---|---|---|
| `var t = mk(1)` / `var u = mk(2)`, print `t.x, u.x` | `1 2` | `1 2` | **`2 2`** |
| same, but `u = mk(7)` FIRST and `t = mk(1)` second | `1 7` | `1 7` | **`1 1`** |
| one `mk` plus an ordinary call between (`t = mk(1); k = plain(9); t.x`) | `1 9` | `1 9` | `1 9` |
| two `mk` calls with an ordinary call between | `1 9 2` | `1 9 2` | **`2 9 2`** |
| both call results as ARGUMENTS: `two(mk(1), mk(2))`, `two(p,q) = p.x*100 + q.x` | `102` | `102` | **`202`** |
| a NAME bound by the first call compared with a call: `var t = mk(1); t == mk(2)` | `0` | `0` | **`1`** |

Two readings, and the first three rows are what separates them:

* **It is not "any call clobbers a holder".** Row 3 is one returned frame and one
  ordinary call, and x86-64 is right. Row 4 adds the second returned frame and
  `t` goes wrong while the ordinary call's result stays right — so the ordinary
  call is not involved.
* **It is not "the second name wins" either.** Row 2 reads the FIRST block
  (`u` was made with 7 and `t` with 1; both print `t.x`, both give 1), so what
  both names end up naming is the LAST block's contents whatever its position in
  the source. Whatever the mechanism, it is per-BLOCK and not per-name.

The name-bound case is also what makes this a silent wrong answer rather than a
crash: `A___eq__(t, mk(2))` reads both blocks and gets two equal objects, so a
struct with a field-wise `__eq__` reports two DISTINCT values as equal.

## Where it is NOT

The reservation and the per-name store are both correct, which is worth recording
because it is the half a reader would otherwise suspect. Dumping the emitted text
of `main` for row 1 (`.tmp/dumpasm.py`, which wraps `X86_64Codegen.compile` and
decodes `formal/x86_64_decode.py`):

```
  lea  rax, [rbp-16408]      ← reserved block for the mk(1) call site
  call mk
  mov  r12, rax              ← `t` gets THAT address
  …
  lea  rax, [rbp-16392]      ← reserved block for the mk(2) call site, 16 higher
  call mk
  mov  r13, rax              ← `u` gets THAT address
  …
  mov  r11, r12 ; mov rax, [r11]     ← t.x
  mov  r11, r13 ; mov rax, [r11]     ← u.x
```

So `model.struct_returned_frame_sites`' offsets are honoured (two distinct
addresses, 16 bytes apart), `t` and `u` hold distinct addresses, and the two
reads are two loads off two different registers — and both loads return the same
value. That puts the fault in what the CALLEE wrote: `_emit_frame_return`'s copy
destination, or what the callee believes the destination to be, which is
`self._load_var(_SRET_LOCAL, Reg.R10)` on x86-64 (`_emit_frame_return`, line 7780).

The callee's own text was not read instruction by instruction here: the decoder in
`formal/x86_64_decode.py` does not distinguish `mov reg, [mem]` (`8B`) from
`mov [mem], reg` (`89`) in the form it reports, so the copy loop's two halves look
alike in the dump. **That is the first thing to fix in the investigation** — one
field on `Insn` — because without it every reading of the callee's copy is a guess.

## Why it has been invisible

`test_formal_returned_frame.py` is in `UNREGISTERED` in `test_suite.py` (see
`bugs/COMPILE_FAIL_estate_check_red_for_eleven_formal_suites.md`), and its
thirteen x86-64 failures are already filed as the segfault doc above. This shape
would not appear in that file at all: every case there compares an EXIT STATUS, and
a program that prints the wrong integer and exits 0 passes a status comparison.
`test_formal_run.py`'s `stdout` comparison would catch it, and the one case in
there that would (`eq_operator_reaches_a_declared_eq_through_a_call_operand`,
`diff=1` where CPython gives 0) is run by `run_case`, which builds only the HOST's
architecture — so on an arm64 host the x86-64 answer is never computed.

That is the same shape of hole as `test_runtime_diff.py`'s, and the same answer
applies: `run_both_arch_case` exists for it, and this construct needs it.

## Exact next step

1. **Distinguish the two `mov` forms in `formal/x86_64_decode.py::Insn`** (or
   disassemble with `otool -tV` on the built image, which needs no code change at
   all — start there). Then read `mk`'s copy loop and answer one question: is the
   destination `_SRET_LOCAL` the address the caller passed, and is it the same on
   both calls?
2. **Compare against arm64's `_emit_frame_return`**, which is right: same three
   steps, and its destination is X17 loaded from `_SRET_LOCAL` after the source is
   in X0. The two differ in which scratch register holds what, and a store through
   a register the callee has just clobbered would look exactly like this.
3. **The cheapest confirmation is row 5**, `two(mk(1), mk(2))` → `202`: one
   `printf`, no holder names at all, so a fix that makes rows 1–4 right and leaves
   row 5 wrong has fixed the binding and not the block.
4. Then re-run `test_formal_returned_frame.py` (its own thirteen x86-64 failures
   are the guard against a "fix" that only moves the symptom) and the eq-dispatch
   row of `test_formal_run.py`, and `bugs/FORMAL_a_function_whose_return_value_is_a_construction_is_not_frame_returning.md`
   becomes landable — its last table row is this defect.