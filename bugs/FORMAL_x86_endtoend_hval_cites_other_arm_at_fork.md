# FORMAL: `hval` facts across a fork cite the other arm's last fact by global index

## Symptom, measured

    python3 -m formal.x86_64_endtoend_test formal/examples/multi_export.mojo
      multi_export  terminates: FAIL lean exited 1: error(lean.unknownIdentifier): …

Two examples fail this way (measured 2026-11-19): `multi_export` and `pair`.
Both die on the same shape, in the first step of the SECOND arm of a
`by_cases` fork:

    .tmp/multi_export_proof.lean:2169:18: error(lean.unknownIdentifier):
        Unknown identifier `hval41`
    .tmp/multi_export_proof.lean:2170:10: error: Expected type must not contain
        free variables
      s36.rsp = 18446744073709518264 ∧ s36.rbp = 18446744073709534920 ∧ …

`pair` is the same pair of errors with `hval26`/`s21`
(`.tmp/pair_proof.lean:1493:18`, `:1494:10`).

## The mechanism

The fork in `multi_export` is at line 1933:

    have hs36 : s36 = { s35 with rip := if x86_cond 0 s35 = true then 4294968934 else 4294968929 }
    …
    have hval36 : s36.rsp = 18446744073709518264 ∧ … := by   ← the fork state's fact,
      simp [hs36, hval35, …]                                     in scope for BOTH arms
    <;> decide
    by_cases hc35 : x86_cond 0 s35 = true
    ·                                                              ← arm 0: nodes k=36…40,
      … emits hval37…hval41 (hval41 is ARM 0's LAST fact, scoped here)
    ·                                                              ← arm 1: starts at node k=41
      have hstep41 : x86_step s36 rc = some { s36 with rip := 4294968986 }
      …
      have hval42 : s42.rsp = 18446744073709518264 ∧ … := by
        simp [hs42, hval41, x86_get_reg, x86_set_reg, x86_rex_b, x86_rex_r]
        ^^^^^^^^  arm 0's hypothesis — not in scope: Unknown identifier

Arm 1's first step starts from the FORK state `s36`, so its value fact
(`hval42`, about `s42 = one step from s36`) must reduce through `s36` — the
fact it needs is `hval36`, which is in scope. It cites `hval41` because
`emit_value_facts` cites the predecessor fact by GLOBAL STEP INDEX:

    simp = ["hs%d" % index, "hval%d" % (index - 1), "x86_get_reg", …]

(index = `k + 1`; `k - 1` is arm 0's last node, stamped earlier in tree
order). `pair` is the identical shape: arm 1's `hval27` cites `hval26`
instead of the fork state's `hval21`.

The second error is a cascade: with `hval41` unknown, the `simp` cannot use
the fork state's fact, the goal stays at the `s36` level, and `decide` fails
with the free variables — the goal shown is EXACTLY `hval36`'s own statement.

## The fix, measured

A one-word patch in each generated file — cite the fork state's fact:

    multi_export:  simp [hs42, hval41, …]  →  simp [hs42, hval36, …]
    pair:          simp [hs27, hval26, …]  →  simp [hs27, hval21, …]

removes BOTH errors in both files; the only remaining errors in each are the
`imul` pair documented in
`FORMAL_x86_endtoend_abs_step_imul_modrm_second_opcode.md` (measured:
`multi_export` and `pair` then fail only on their `x86_imul_ovf` goals).

## What the emitter has to change

`emit_value_facts` (formal/x86_64_endtoend_test.py) must cite the fact for
the state the node STARTS FROM, not `hval{index-1}`: the `walk` recursion
already carries the path (cases, hs_path, fs_path, …), so it can carry the
fork state's index too — reset to the fork state's fact at each arm's first
node, and advance by one per step within an arm.

## Done when

`multi_export` and `pair` no longer report `Unknown identifier hval…` or the
free-variable cascade on arm 1's first value fact, and a `by_cases` fork in a
generated file whose arms both need value facts elaborates.
