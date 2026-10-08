# `_step_result_plan` reads the STRING DATA as instructions, and one of its words decodes to a `TBZ` whose discriminator fact is FALSE

**Area:** FORMAL, `formal/arm64_proof_gen.py::_step_result_plan` (and the
`_gen_step_result_lemmas` / `_gen_step_lemmas` pair that read it). **Status:
OPEN, pre-existing, found 2026-10-07 while landing the startup-stub fix in
`formal/arm64_codegen.py` that moved `getrlimit` below `func_offset` (that
fix's own doc is deleted with it).**
It is NOT that fix's doing: the identical failure is in a pre-fix run of
`test_formal_call_proof_gen.py` (see "Measured on the pre-fix tree" below).

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 -m unittest test_formal_call_proof_gen.TestLean
```

and, for one program, the generator alone:

```python
import formal.build as fb
r = fb.compile_formal(src, arch="arm64", output=out, prove=True, check=False)
```

## What I saw

The generated proof for `def main(n): return 7` does not typecheck, and the
error is about a word that is not an instruction at all:

```
no_params_proof.lean:2315:74: error: Tactic `native_decide` evaluated that the
  proposition
    ¬909189220 >>> 5 &&& 16383 &&& 8192 = 0
  is false
no_params_proof.lean:2244:212: error: unsolved goals
  …
  hinsn : arm64_read_insn seven_code 4294969116 = 909189220
  …
```

`909189220` is `0x36312064`; its little-endian bytes are `64 20 31 36` —
`"d 16"`, four bytes of the stack-trap MESSAGE (`model.stack_trap_message`,
which every arm64 image carries as data). `_step_branch_index(0x36312064)`
returns **52** (the `TBZ` row), so `_step_result_plan` emits a full
step-RESULT lemma for it, `_gen_step_lemmas` derives a step-OK lemma from it,
and one of the discriminator facts the model's `if`-chain needs is FALSE for
that word. The kernel rejects the file; the program is perfectly fine.

## Why it is a bug rather than a gap

`_step_result_plan` walks **every** 4-byte word of `code`:

```python
words = [int.from_bytes(code[i:i + 4], "little")
         for i in range(0, len(code) - len(code) % 4, 4)]
for i, w in enumerate(words):
    idx = _step_branch_index(w)
    if idx is None: continue
    rhs = _step_rhs(w, idx)
    if rhs is None: continue
    plan[i] = (w, idx, rhs)
```

`code` is the WHOLE `__TEXT,__text` — every function body **and** the string
data the emitter appends after them (`arm64_codegen.compile`'s `self._strings`
loop, which includes `model.stack_trap_message`). A data word that happens to
match a decoder branch therefore gets a step lemma it must not have. Most data
words match nothing (`_step_branch_index` returns `None`) and cost nothing;
`0x36312064` matches `TBZ`, and `TBZ`'s discriminator facts are not a pure
mask test, so the lemma is false.

**The fix is to derive the plan from the EXECUTABLE range, not from `len(code)`.**
The generator already knows the range elsewhere — `_unfollowable_calls` /
`_same_image_call_plan` carry a `func_end`, and `info["labels"]` names every
string label — so the boundary is available; what is missing is threading it
into `_step_result_plan`. A plan that stops at the first string label (or at
the last function body's end) removes the lemma and every data-word variant of
it. Do not paper over it by special-casing the one word: the same trap is
reachable from any message text whose bytes decode.

## Measured on the pre-fix tree

The same `no_params` failure is in a run of `test_formal_call_proof_gen.py`
taken **before** the startup-stub change, with the identical word and the
identical expression — so this is not a regression from that fix and should be
worked independently:

```
FAIL: test_generated_proofs_typecheck_with_no_sorries
      (program='no_params')
  no_params_proof.lean:2315:74: error: Tactic `native_decide` evaluated that
    the proposition ¬909189220 >>> 5 &&& 16383 &&& 8192 = 0 is false
```

## Why it was invisible

`test_formal_call_proof_gen.py` is one of the eight Lean-checking formal gate
tests that are currently DISABLED, and the failure is a kernel rejection with no
`sorry` anywhere, so nothing short of the kernel (or this one test) reports it.
It is the same shape `bugs/FORMAL_arm64_known_proof_gaps.md` calls out: a proof
that fails to ELABORATE is not a gap, and a census that only counts `sorry` sees
nothing.
