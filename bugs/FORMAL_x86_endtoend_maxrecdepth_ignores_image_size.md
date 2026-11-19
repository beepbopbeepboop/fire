# FORMAL: `maxRecDepth` is set from the step count, but `all_bytes` needs the image size

## Symptom, measured

    python3 -m formal.x86_64_endtoend_test formal/examples/call_both_arms.mojo
      call_both_arms  terminates: FAIL lean exited 1: error: maximum recursion depth …

Two examples fail this way (measured 2026-11-19): `call_both_arms` and
`elif_call`. `call_both_arms`'s generated file dies INSIDE `all_bytes`'s
statement, with two cascades behind it:

    .tmp/call_both_arms_proof.lean:512:7: error: maximum recursion depth has been reached
    .tmp/call_both_arms_proof.lean:557:13: error(lean.unknownIdentifier): Unknown identifier `all_bytes`
    .tmp/call_both_arms_proof.lean:556:90: error: unsolved goals
      ⊢ (x86_exec_go_exit (X86State.init n 4294968411) rc 4294968613 100000).isSome = true

Line 512 is the byte-equality conjunction of `all_bytes`; the other two are
the theorem body losing `hb := all_bytes` because the header theorem was
rejected. `elif_call` shows the identical trio (`:512:7`, `:557:13`,
`:556:90`).

## Why the option is what it is

The file header is emitted by `_header` (formal/x86_64_endtoend_test.py):

    depth = max(1000, 40 * max(steps, 1))
    …
    "set_option maxRecDepth %d\n" % depth

with `steps = _nodes(root)`. The comment records the calibration: measured on
`bitops`, 44 steps, the closing `simp` "runs out rather than any single step…
about 27 per step, so 40 is the factor used here". The formula buys depth for
the CLOSING SIMP (one successor equation nested per step).

But `all_bytes` is a FLAT `And` chain over EVERY byte of the image, proved by
a matching flat `And.intro (by native_decide) …` term, and checking it makes
the kernel reduce each `rc a` — a `List.get` at offset `a - base` into the
whole image list — under the nested `Decidable` instance. Its depth scales
with the IMAGE, not with the function's step count:

    file              rc list   all_bytes conjuncts  steps→maxRecDepth  result
    call_both_arms    2281     532                ≤ 25 → 1000          REJECTED
    elif_call         1890     518                ≤ 25 → 1000          REJECTED
    multi_export      2330     581                ≥ 77 → 3080          passes

A SMALL function (few steps → the 1000 floor) with a LARGE image (long
compiler-trap error strings) is exactly the shape that busts the budget:
532-deep `And` plus a 650-deep list lookup is more than 1000. `multi_export`
has an even bigger image but a long function, so its step-proportional budget
happens to cover `all_bytes`.

## The fix, measured

Raising the option in the generated files:

    call_both_arms:  set_option maxRecDepth 1000  →  4000
    elif_call:       set_option maxRecDepth 1000  →  4000

removes the ceiling error and BOTH cascades in each file. What remains in
each is the `imul` error pair documented in
`FORMAL_x86_endtoend_abs_step_imul_modrm_second_opcode.md` (measured: after
the raise, each file fails only on its `x86_imul_ovf` goals).

## What the emitter has to change

The formula must price the `all_bytes` term: its depth is the conjunct count
plus the deepest `rc` lookup, both read off the same `code` the header
already receives — e.g. `depth = max(1000, 40 * steps, 2 * (len(code) + 1))`
— or the header takes the maximum of the two measured components rather than
one.

## Done when

No generated file is rejected with "maximum recursion depth has been reached"
on `all_bytes`, and a small-function/large-image example (the
`call_both_arms` shape) elaborates.
