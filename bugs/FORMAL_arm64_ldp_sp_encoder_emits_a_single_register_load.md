# `encode_ldp_xn_xt_sp` emits a single-register load from a register base, not an `LDP` from `SP`

## Status

OPEN, and NEW — measured 2026-10-04 by `tools/formal_model_fuzz.py`, which
cross-checks every instruction it generates against `as -arch arm64`.

**It is dead code**, so nothing miscompiles today: `tools/arm64_insn_audit.py::unwired_encoders`
lists it. It is written down because it is a two-argument-order bug in an
encoder whose NAME says "SP" and whose base opcode hard-wires a register base
instead, and because `arm64_step` HAS an arm for the instruction the name
describes (0xa9400000) — so the next caller would have produced a proof about
one instruction and an image containing another.

## 1. What it emits, and what it claims

```python
def encode_ldp_xn_xt_sp(xn: int, xt: int, imm12: int) -> bytes:
    """LDP Xt, Xn, [SP], #imm. Loads two 64-bit registers from the stack.
    Encoding: 10110 1 1 00000 1 imm12 Rn Rt Rs
    """
    assert 0 <= xn <= 31
    assert 0 <= xt <= 30
    assert 0 <= imm12 <= 0xfff
    # Encoding: 0xA9400000 | (imm12 << 10) | (xn << 5) | xt
    insn = 0xA9400000 | (imm12 << 10) | (xn << 5) | xt
    return struct.pack('<I', insn)
```

Three things disagree with the docstring:

1. **`Rn` is never set to 31.** The base `0xA9400000` has bits 9:5 = 0, i.e.
   `Rn = X0`, and the encoder's `(xn << 5)` OVERWRITES that field with `xn`.
   So the base register is `xn`, not `SP`. Measured:
   `encode_ldp_xn_xt_sp(1, 0, 2)` → `0xa9400820` → `ldp x0, x1, [x1, #16]`.
2. **Only ONE destination register is written.** Bits 4:0 (`xt`) and bits 9:5
   (`xn`, which is `Rt2` in the real layout — see 3) are the only fields the
   encoder touches, so it loads a PAIR with `Rt2 = xn` and reads a base of
   whatever `Rn` was left as. The names are `(xn, xt)`, so a caller reading
   `encode_ldp_xn_xt_sp(dest1, dest2, off)` gets its arguments the wrong way
   round as well.
3. **`imm12` is in EIGHTIES, not bytes**, because the encoder shifts by 10
   itself. A caller that passes a byte offset (as every other offset-taking
   encoder in this file takes — `encode_ldr_xt_xn_imm` divides by 8 itself too,
   so this one at least is consistent with its neighbours) is wrong by 8×.

The assembler, for the text the docstring describes:

```
$ printf '.text\nldp x0, x1, [sp, #16]\n' | as -arch arm64 -o - - | otool -s __TEXT __text -
a94107e0
```

which is `0xA9400000 | (16>>3 << 10) | (31 << 5) | 0` — `Rn = 31`, `Rt2 = 1`,
`Rt = 0` — and shares no field with what the encoder produces except the base
opcode.

## 2. Why the tool found it and the encoder suite did not

`tools/formal_model_fuzz.py` builds a case from `encode_ldp_xn_xt_sp` and the
text `ldp xA, xB, [sp, #off]`, asks `as -arch arm64` for the text's word, and
compares DISASSEMBLY: `ldp x0, x1, [x1]` against `ldp x0, x1, [sp, #16]`.

`test_arm64_encoders.py` has no `ldp` case at all (measured: `grep -n "ldp" test_arm64_encoders.py`
is empty), so the encoder is in no byte-exact check either. That is the same
hole as `bugs/FORMAL_arm64_movz_encoder_is_named_xd_and_encodes_wd.md` §3: the
encoders a backend leans on hardest are the ones its encoder suite does not
mention, and this tree now has two of them.

## 3. The correct encoding, for whoever fixes it

`LDP <Xt1>, <Xt2>, [<Xn|SP>{, #imm}]` (signed offset, 64-bit) is
`0xA9400000 | (imm7 << 15) | (Rt2 << 10) | (Rn << 5) | Rt`, so:

```python
def encode_ldp_xt1_xt2_sp(xt1: int, xt2: int, imm_bytes: int) -> bytes:
    """LDP Xt1, Xt2, [SP, #imm]. `imm_bytes` is a byte offset, a multiple of 8."""
    assert 0 <= xt1 <= 30 and 0 <= xt2 <= 30
    assert 0 <= imm_bytes <= 32760 and imm_bytes % 8 == 0
    insn = (0xA9400000 | ((imm_bytes // 8) << 10) | (xt2 << 10) | (31 << 5) | xt1)
    return struct.pack('<I', insn)
```

and `arm64_step`'s 0xa9400000 arm already models it, so a caller that starts
using this gets a modelled instruction rather than a silent hole.

## 4. The exact next step

1. Decide whether the backend wants an SP-relative pair load at all. The frame
   traffic it emits today is `STP`/`LDP` with writeback
   (`encode_stp_sp_pre` / `encode_ldp_sp_post`, both wired, both modelled), so
   the honest answer may be **no** — in which case delete
   `encode_ldp_xn_xt_sp` and let `arm64_insn_audit.py`'s "unwired" list drop it,
   which is the only thing that makes an unwired encoder safe.
2. If it does want one, replace the function with the §3 form under a name that
   matches (`encode_ldp_xt1_xt2_sp`), fix the two call sites if any appear, and
   add `ldp` to `test_arm64_encoders.py`'s `cases()` — `ldp x0, x1, [sp, #0]`,
   `#8`, `#32760`, and with `Xt2 = 31`, which the current `assert` forbids and
   the architecture allows (LDP loads into XZR's slot, discarding it).
3. Re-run `python3 tools/formal_model_fuzz.py --cases 300 --seed sweepB` and
   `python3 test_arm64_encoders.py`. Nothing changes in the fuzzer's tally for
   this one — it draws no case from an unwired encoder — and that is the point:
   §2 is why it found the defect by hand instead.

## 5. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 -c "from formal import arm64 as A; \
  print('%08x' % int.from_bytes(A.encode_ldp_xn_xt_sp(1, 0, 2), 'little'))"
printf '.text\nldp x0, x1, [sp, #16]\n' > .tmp/q.s && as -arch arm64 -o .tmp/q.o .tmp/q.s \
  && otool -tv .tmp/q.o && otool -s __TEXT __text .tmp/q.o
grep -n "ldp" test_arm64_encoders.py        # no output
python3 -c "import importlib.util as u; s=u.spec_from_file_location('a',
    'tools/arm64_insn_audit.py'); m=u.module_from_spec(s); s.loader.exec_module(m);
    print('encode_ldp_xn_xt_sp' in m.unwired_encoders())"   # True
```