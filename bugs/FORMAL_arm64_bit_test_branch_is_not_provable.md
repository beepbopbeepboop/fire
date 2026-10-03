# An `if` whose condition is a BIT TEST cannot be PROVED, because the branch-condition value flow reads the condition out of a cset

**Area:** FORMAL / proof generation. Found 2026-10-03 on `work/formal13-2` while
wiring `TBZ`/`TBNZ` into the arm64 backend (the two largest genuinely-uncovered
instructions in `bugs/FORMAL_arm64_instruction_coverage.md`'s survey).
**NOT FIXED** — the generator refuses, which is the right failure, and closing it
is a distinct piece of work from the one the coverage survey names.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 24 --label lean -- python3 - <<'PY'
import sys; sys.path.insert(0, ".")
import test_formal as T
print(T.run_one("bittest"))          # formal/examples/bittest.mojo
PY
```

## What was seen

With `formal/examples/bittest.mojo` present:

```python
def bittest(n):
    x = 0
    if n & 8:
        x = x + 1
    if not (n & 4):
        x = x + 2
    if 16 & n:
        x = x + 4
    return x
```

the build and the image are fine — `build --formal --no-prove` succeeds and the
program answers CPython on both architectures — and the proof generator raises:

```
ValueError: unsupported: branch condition value flow (frame/flag unavailable)
```

`formal/arm64_proof_gen.py`'s `emit_block`, at the `elif kind == "cbz":` arm.

## Why

A conditional branch is turned into a source-level proposition by finding the
**cset that wrote the register the branch tests** and reading the condition off
its condition code:

```python
_cset_bi = next((b for b in [bi] + reversed(prior) if r in _cset_registers(blocks[b], words)), None)
_cset_blk = blocks[_cset_bi]
_cnd = _cset_cond(_cset_blk, words)
_fl  = _fl_map.get(_cnd)          # arm64_flag_eq / arm64_flag_ne / …
_fls = [f for f in (_fl_map.get(c) for c in _cset_conds(_cset_blk, words)) if f]
if not _Xs or _fl is None:
    raise ValueError("unsupported: branch condition value flow (frame/flag unavailable)")
```

`TBZ`/`TBNZ` write **no register and set no flags**: they read one bit of a
register and branch. There is no cset to find, `_cset_cond` answers None, and the
generator refuses rather than emitting an `hcond` about a register whose value
says nothing about the condition. That is the correct failure — the alternative
is a theorem that is stated and never applied, which is the `either`/`both`
failure mode `bugs/FORMAL_arm64_known_proof_gaps.md` records.

Everything ELSE about the two instructions is already in place and measured, so
what is missing is one arm and not the model:

  * `lib/ProofLib.lean` has the two `arm64_step` cases (`0x36000000` / `0x37000000`,
    imm14 at bits 5..18, bit number at bits 19..23), and `lib/ProofLib.lean`
    TYPECHECKS with them — verified through `formal/lean.py::ensure_library`;
  * `formal/arm64_proof_gen.py`'s `_STEP_CONDS` carries them (52, 53), so
    `_step_facts` emits the discriminator facts every generated step-result
    lemma needs, and `_step_rhs` / `_step_rhs_generic` state the right-hand side;
  * the block scanner classifies them as the `cbz` kind, which is what keeps
    `cond_branches` attributing the right source condition to the right block;
  * `loop_test` answers for them, so a `while x & 8:` loop's exit predicate is
    not an unrecognised test.

## The exact next step

1. In `emit_block`'s `elif kind == "cbz":` arm, the CONDITION TEXT is already
   two lines away — add `_bidx in (52, 53)` beside the `_bidx == 17` arm,
   stating `((arm64_reg r s >>> UInt64.ofNat b) &&& 1) = 0` for `TBZ` and
   `≠ 0` for `TBNZ`. The polarity is the existing one: the emitted `hcond` is
   `(<taken test>) ↔ ¬(<source condition>)`, and for `TBZ` the taken test is the
   bit being CLEAR.
2. Then the `hcond` PROOF. The `else` arm closes with
   `by_cases h : (<src>) <;> simp [h, <flags…>, Arm64State.init, …] <;> bv_decide`
   and `_fls` is empty here, so the flag half drops out and what is left is the
   register's value — `n` at `Arm64State.init`, reached through the block's own
   `qT` chain. **`bv_decide` is the thing to try first and the thing most likely
   to fail**: it decides over 32-bit words and this is a 64-bit `>>>`, so the
   first attempt should be `simp [...]` plus a `UInt64.shiftRight` lemma rather
   than `bv_decide`.
3. `formal/examples/bittest.mojo` is the test, and it is deliberately NOT
   committed with the coverage work: it fails today, and adding a failing
   example without an `EXPECTED_FAILURES` entry would be the wrong shape. Put it
   back with the entry when the arm lands, and the harness's own stale check
   will say so if it lands without the entry.

## What is NOT claimed

* Not measured on x86-64. The gap is in `formal/arm64_proof_gen.py`, which is
  arm64's generator alone; `test_formal.py`'s docstring is explicit that the two
  generators prove different things and that a gap in one says nothing about the
  other.
* The codegen half is correct and tested independently
  (`test_arm64_emission.py`'s `TBZ is emitted, tests the right bit, and its
  displacement is patched` and `a mask that is not one bit keeps the general
  path`), so this is a gap in PROVING a construct that COMPILES and computes the
  right answer — not a wrong answer anywhere.