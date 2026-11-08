# plan/step-08d: pin the function-value / BLR refusal so it cannot become a wrong certificate
**Status: DONE 2026-11-07 (measured).** `test_formal_call_proof_gen.TestFunctionValueCallIsRefusedNotCertified` passes: `prove=True` raises with "binds it to nothing", `prove=False` builds an image with exactly one BLR word.
Class: easy      Size: S      Depends: 08c      Blocks: none
Source: `bugs/plan/step-08c-blr-br-design-memo.md` "Decision (08c)", Reading A.

## Work order
1. In `test_formal_call_proof_gen.py`, add one test: write `def dbl(x: Int) -> Int:\n    return x * 2\n\ndef main(n: Int) -> Int:\n    var g = dbl\n    return g(n)\n` to a temp `.mojo`; `fb.compile_formal(path, arch='arm64', prove=True, check=False)` must RAISE and its text must contain `binds it to nothing`.
2. In the same test, build it with `prove=False`, read the output file as little-endian 32-bit words and require exactly ONE with `(w & 0xfffffc1f) == 0xd63f0000`.
3. Run only that test: `python3 -m unittest test_formal_call_proof_gen.<Class>.<test>`; set line 2 of this file to `**Status: DONE <date> (measured).**`; `python3 tools/plan_index.py --write`; commit.

## Do NOT
- Do not add a BLR arm to `lib/ProofLib.lean` or a `_STEP_CONDS` row. Do not delete the test if it starts failing; report it.
