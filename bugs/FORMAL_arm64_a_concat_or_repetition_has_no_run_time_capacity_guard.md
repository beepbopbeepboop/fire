# FORMAL_arm64_a_concat_or_repetition_has_no_run_time_capacity_guard_so_an_under_estimate_overruns_the_frame

**Area:** `formal/arm64_codegen.py`'s `_emit_list_concat`, `_emit_list_repeat`
and `_emit_set_union` (the three blob-producing sites that reserve their
destination and then copy into it at run time). **Found 2026-10-04 on
`work/formal28-6`** while fixing
`formal/model.py`'s `blob_loop_growth` — the companion fix, landed in
commit `1ec3467d`, which is the change that made a list grown in a loop
reserve for its last iteration.
**NOT fixed** — it is a different root cause from the loop-growth fix this
was found beside (commit `1ec3467d`), and it is filed because that fix makes
arm64 and x86-64 agree about the RESERVATION while leaving them disagree about
what happens when the reservation is wrong. Pre-existing and independent: it
reproduces with that fix reverted.

## The finding, in one sentence

**x86-64 bounds-checks the element total against the reservation on its `+`,
`*` and `|` paths and arm64 does not**, so on arm64 an under-estimate is a
silent frame overrun while on x86-64 it is a loud `exit(1)` — the same source,
two different failure modes, and the project's own rule is that a build which
answers nothing must at least say so.

## What I measured

`formal/x86_64_codegen.py`'s `_emit_list_concat` emits, right after computing
the runtime total in `RAX`:

```python
self.asm.emit(encode_cmp_r64_imm32(Reg.RAX, cap))
self._emit_jcc(COND_BE, overflow_label)
self._emit_call_exit(1)
```

`formal/arm64_codegen.py`'s `_emit_list_concat` computes `cap`, reserves
`8 + 8 * cap` bytes and then copies `nL + nR` elements into it with **no
comparison against `cap` anywhere**. Same for `_emit_list_repeat` and
`_emit_set_union`. `lib/ProofLib.lean` has no obligation here either way: the
frame's own bounds lemmas talk about the reservation, not about a check the
emitter declined to emit.

The observable difference, measured before the companion fix, on the same
three-line program with the loop moved into a callee:

```mojo
def g(a: Int) -> Int:
    var s = [0]
    for i in range(70):
        s = s + [1]
    printf("len=%d", len(s))
    return 0
def main(n):
    g(1)
    return 0
```

`g` printed `len=71` on both machines — so the length was right — and
`printf("len=%d", g(1))` (the same `g` reached as a `printf` argument) exited
**71** having printed nothing, on arm64, and exited 1 on x86-64. The 71 is the
callee's return value and the missing output is `printf`-with-a-call, which is
`bugs/FORMAL_printf_of_a_call_result_prints_nothing_and_leaks_the_return_value_as_the_exit_status.md`
— but the *reason* `g`'s own frame was overrun at all is the missing guard: at
70 iterations the reservation was 65 words and the copy wrote 71, and what the
overrun landed on was the caller's spill area.

A larger case makes the corruption unambiguous without the `printf` confound,
because the overrun then runs off the end of the blob region into the spill
slots: `for i in range(16000)` on arm64 built, ran, and printed `len=16001`,
i.e. it wrote 16001 elements into a 65-element region and nothing noticed.

## Why it is not fixed here

The companion fix (`formal/model.py`'s `blob_loop_growth`, read by both
backends) makes the two machines reserve the SAME number of words for a
loop-carried container, which removes the reason the two disagreed *in this
program*. It does not remove the guard's absence, and adding a guard is a
separate decision:

* arm64's copy loops write through `X10`/`X11` computed from the two runtime
  counts, so the comparison the x86-64 path already emits has an obvious
  arm64 spelling (`cmp` the total against the literal `cap`, branch to an
  overflow label, and reuse the `write(2)`-then-`exit` sequence
  `_emit_list_append` already has);
* but every existing arm64 test that grows a container past its estimate today
  would change from "runs" to "stops", and that is a coverage question for
  somebody who can run the sweep. A light worker changing the arm64 failure
  mode for an unmeasured population of programs is the wrong trade.

## The exact next step

1. Add the guard to arm64's three sites, mirroring
   `formal/x86_64_codegen.py::_emit_list_concat`'s four instructions and
   `model.list_append_overflow_message` (already shared, so the message is the
   same on both machines).
2. Measure `tools/formal_sweep.py --no-stdlib` on both architectures and count
   the files that move from `pass` to `not-answerable` **with the companion fix
   in place** — the number should be small, because after that fix the
   reservation is the same on both machines, but "should be small" is not a
   measurement.
3. If step 2 shows real movement, the alternative is to leave arm64 as it is
   and say so in `formal/model.py`'s `blob_loop_growth` docstring, which is a
   worse answer than either the guard or the reservation.

## Reproducing

    git show HEAD:formal/arm64_codegen.py > /tmp/pre.py   # see the note below
    python3 tools/memslot.py --gb 8 --label t -- python3 .tmp/guard_probe.py

`guard_probe.py` builds the `range(16000)` program above on arm64 and prints
`(returncode, stdout)`; on this tree it is `(0, 'len=16001')` and the
reservation the emitter made was 65 elements.