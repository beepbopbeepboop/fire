# FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open: `fdiv64`'s
# `if b = 0` has nothing to discharge it on the walk's only path, so `a // b`
# with a symbolic `b` is ADMITTED rather than proved

**Area:** FORMAL, arm64 — `lib/ProofLib.lean`'s `sdiv64`/`fdiv64` zero-divisor
guard against `formal/arm64_proof_gen.py`'s terminal value flow (the `simp
+decide only [...]` line that carries the block's `hsid_*` chain and no branch
fact).
**Status: NOT FIXED, and it PREDATES the floor correction** — it is a property
of `sdiv64`'s guard, which `fdiv64` inherited verbatim, so `a / b` has always
been in this state and `a // b` and `a % b` joined it on 2026-10-04.
Found 2026-10-04 on `work/formal16-4` while landing the floor-division fix, by
generating the proof for a two-parameter program that divides by a parameter
instead of by a literal.

## What I ran

```console
$ cat .tmp/fd/symb.mojo
def q(a, b):
    return a // b
$ python3 .tmp/fd/genonly.py build --formal -o .tmp/fd/symb.out --backend=arm64 .tmp/fd/symb.mojo
Proof: .tmp/fd/symb_proof.lean
$ grep -n "terminal value flow" -A 2 .tmp/fd/symb_proof.lean | head -3
        -- terminal value flow: (s_7).x0 = mojo n n1
        have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
        simp +decide only [h8, mojo, q_go, hsid_6, hsid_4, hsid_2, hsid_0, q_b0_qS0, …]
```

and, in the same file, the divide-by-zero branch the walk takes:

```lean
      have hcbz_4 : arm64_step s_4 q_code = some
          (if arm64_reg 1 s_4 = 0 then ({ s_4 with pc := 4294968148 } : Arm64State)
                                 else ({ s_4 with pc := 4294968096 } : Arm64State)) := …
      by_cases hc_4 : arm64_reg 1 s_4 = 0
```

## Why the goal cannot close

`hc_4` is exactly the fact the model's guard needs — on the path the walk
follows, `arm64_reg 1 s_4 = 0` is FALSE — and it is **in scope**: it is the
`by_cases` that opened the branch the rest of the proof sits in. It is simply
not in the terminal `simp only [...]` list, which carries `h8`, the model, the
`hsid_*` chain, the `qS`/`qT` definitions and the value simp set, and nothing
that mentions a branch condition.

So the goal after that `simp` is

```lean
    … = if n1 = 0 then 0 else fdiv64_unfolded n n1
```

with `n1` a parameter, and `simp only` cannot reduce an `if` whose condition is
a variable. What is left is `all_goals (first | done | sorry)` — the walk
terminal's admission — so the theorem is stated and not proved.

**A literal divisor is why nobody measured this.** `formal/examples/udivmod.mojo`
— the corpus's only division example, and the slowest legitimate proof in the
tree at 297.8 s — divides by `7`, and `decide` disposes of `if 7 = 0`. So the
shape has never been in the corpus, and the run suite cannot see it either:
every case in `test_formal_run.py` that divides does it by a literal or by a
value that is already in a register (`neg_div_rem`'s `a / 2`).

## The exact next step

Put the branch fact in the terminal value flow's `simp only` list, the way the
`hsid_*` chain already is. The generator has the name at the point it emits
that line — the `by_cases hc_{bi} : …` it just wrote is the same statement, and
`_gen_run_cert` already tracks branch hypotheses for the `hcond_*` goals — so
this is one entry in the list built where `h8, {mojo}, {hsid…}` are, not a new
mechanism.

**It is unverified and that is the whole reason it is filed rather than landed.**
`lib/ProofLib.olean` has to be rebuilt for any proof in this tree to check, its
measured build peak is 7.82 GB, and a light worker's ceiling here is 8 GB — so
the run that would show whether the added hypothesis closes the goal, and
whether it costs anything on the other 49 examples, cannot be made from a
branch that holds 8 GB. Whoever takes it should measure both directions: the
dividing case closes, **and** `formal/examples/` is no slower than its measured
297.8 s / 2.30 GB worst case, because the list is on every program's terminal
flow and not only on the dividing ones.

While there: the same run is the one that has to confirm the FLOOR correction
reduces, since `fdiv64` is in that same list for the same reason. That half is
not this doc's subject, and it is already accounted for: `//` floors and `%`
takes the sign of the divisor on both backends (`model.division_floors` is the
one decision both emitters ask), so the term in that list is the corrected one
and what is left here is only the zero-divisor guard above.