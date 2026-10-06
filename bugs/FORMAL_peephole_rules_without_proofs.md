# `arm64/copy_chain`'s liveness check is wrong for a loop, and no x86-64 rule has a proof

## What this is

`formal/peephole.py` is the verified peephole pass (landed 2026-10-05,
`work/formal36-verified-peephole`, with `lib/Peephole.lean`). Three rules are
proved there and two are enabled. This doc is about the three that are not, and
it is a work list rather than a defect report: nothing here is reachable from
the shipped toolchain, because the pass is behind `--opt` and off by default.

The pass's design rule is that a rule is only allowed to fire when its Lean
theorem's side conditions are discharged. Two of the three gaps below are a
rule that IS proved and whose matcher cannot yet discharge the condition, and
one is a rule with no theorem at all — and the difference is why the registry
has `RULES` (enabled) and `PENDING_RULES` (proved, matcher unsound) rather
than one list with exceptions in it.

## 1. `arm64/copy_chain` — proved, matcher wrong for a loop

`peephole_arm64_copy_chain` (`lib/Peephole.lean`) says that `mov xa, xb ;
mov xc, xa` and `mov xc, xb` leave the machine model agreeing on every
register except `xa`, plus the flags, memory and the pc. That theorem is
correct and is the strongest statement the model can be asked for here.

The rule needs one thing the theorem cannot supply: that nothing reads `xa`
again. `formal/peephole.py`'s `_Ctx.live_after` is a backward dataflow over
the whole image, with a relaxation pass over backward branch edges.

**Measured 2026-10-05**, over all 52 `formal/examples/*.mojo`, arm64, built
with `--opt` and run against the unoptimised build. (These numbers are from
before the two matcher bugs in `mov_self` were fixed; they are what the
differential fuzzer and the end-to-end test caught, and the shipped
configuration — `mov_self` and `add_imm_fuse` only — is clean.)

| rule | fires | result |
|---|---|---|
| `arm64/mov_self` | 20 | 13 of 52 examples crashed (`SIGSEGV`, exit −11) |
| `arm64/copy_chain` | 44 | `sqsum.mojo` answered **109** for **129**; `sum_range.mojo` **never terminated** |

Both of those were the `consumed`/window bug as well, so they are what the
end-to-end differential test caught rather than the first symptom. With that
fixed and only `copy_chain` enabled, **2 of 52 still disagree**:

```
sqsum.mojo      exit 129 unoptimised  →  109 optimised
sum_range.mojo  exit  45 unoptimised  →  never terminates
```

Both are loops, and both read a register the loop body wrote — which is the
backward-edge case the relaxation was supposed to close and did not.

**Where to look.** `_Ctx.live_after` in `formal/peephole.py`: the linear scan
builds `table[i]` from `table[i+1]` and a `{0, 30}` seed, then relaxes
`table[j] |= table[t]` for every `(j, t)` from `_back_edges`. Two things are
worth checking first:

1. `_back_edges` only recognises the six branch classes in
   `_ARM64_BRANCHES`, and returns `None` for `BL`. A `BL` inside a loop body
   is fine (the callee reads x0…x7, which `reads_arm64` already accounts for),
   but a **backward `CBZ`/`CBNZ` past the point the table was relaxed** will
   not be an edge at all if the bit layout is wrong — `arm64_branch_target`
   returns an INDEX, and it is worth asserting against one hand-computed loop
   rather than trusting the sign extension of each field width.
2. The relaxation loop runs `len(entries) + 1` times and stops when nothing
   moved. For a *nested* backward edge (a loop whose latch branches back past
   another loop's header) the fixpoint needs the number of edges, not the
   number of instructions, and one pass of relaxation over `back_edges` in
   source order does not reach it.

**The right fix is a real CFG**, not a better relaxation: successors are the
fallthrough plus each branch target, and the same backward pass runs to a
fixpoint over that. Every loop-exit edge then participates for free, and
`live_after` stops being an argument about the analysis and becomes the
standard dataflow it is pretending to be.

**What it is worth.** 44 rewrites over 2498 arm64 instructions in the corpus —
**3.4%**, and it is the only rule with a measured win here. It is also the rule
the corpus was built for: 499 of the 633 `ADD (immediate)` instructions
`formal/arm64_codegen.py` emits add **zero**, because `encode_mov_zr_xn` spells
a register copy as `ADD Xd, Xn, #0`. That is 20% of the arm64 code the emitter
produces.

## 1a. The side condition `peephole_arm64_mov_self` cannot express

Fixed here, recorded because it is the shape of thing this pass will keep
meeting and because a reader of the theorem deserves to know what it does NOT
say.

`peephole_arm64_mov_self` says that `add xd, xd, #0` leaves the machine model
unchanged. It is right. It is also, on this compiler's output, not enough —
because `formal/arm64.py`'s `emit_adrp_add` emits an `ADRP Xd, #page` and an
`ADD Xd, Xd, #off` as ONE pair that `Assembler.resolve` back-patches from a
single relocation, and when the label is page-aligned that `ADD` is `#0`. The
ADD is a genuine no-op on the register; what it carries is the within-page
half of an address the ADRP was patched to a PAGE for.

`tools/formal_fuzz.py --seed peephole-diff -n 30 --opt` found it in generated
program 11: `d 29 1 1 / d 0 0 0 / d` where CPython said
`29 1 1 0 29 / 0 0 0 29 5 / -21 -21`. The condition is now
`_Ctx.after_adrp_add`, and `TestRules.test_mov_self_declines_the_low_half_of_an_adrp_add_pair`
pins both directions of it.

The general lesson, which is the reason this is written down rather than left
in the code: **a machine-model theorem bounds what the MODEL can see, and a
compiler's address arithmetic is not the model.** Any rule over a class a
relocation writes into needs a condition about the relocation.

## 2. `arm64/store_load`, `arm64/mem_pair`, `arm64/movz_pair` — no theorem

Three rules that match nothing on the corpus and have no Lean theorem. They are
deliberately NOT in the registry, so `unlicensed_rules()` does not refuse the
pass for them; they are named here so the gap is visible.

**What each needs**, and why it is more than a copy of
`arm64_step_add_imm64`:

| rule | the window | the arm in `arm64_step` | the obstacle |
|---|---|---|---|
| `arm64/mem_pair` | two identical `STR Xt,[Xn,#o]`, or two identical `LDR` | `0xF9000000` / `0xF9400000`, about **26th** in the if-chain | 26 negations before it, plus `mem_write_u64`/`mem_read_u64` lemmas about the store |
| `arm64/store_load` | `STR Xt,[Xn,#o]` ; `LDR Xt,[Xn,#o]` | same two | the same, and the theorem must relate a store and a load of one address |
| `arm64/movz_pair` | `MOVZ Xd,#i` ; `MOVZ Xd,#j` | `0xD2800000`, about **19th** | 19 negations; the value side is trivial once the decode is pinned |

**The recipe that works**, once a `bv_decide` negation per earlier arm is
accepted (which `work_step_*` in `lib/ProofLib.lean` already does 40 times):
write the arm's step lemma with the word as a `UInt32` parameter and one
hypothesis per earlier class, `intro t; bv_decide` on each, then
`unfold arm64_step; rw [hpc, hread]; rw [if_neg …, if_pos h]`. The memory
lemmmas are the part with no precedent: `ProofLib` has
`mem_read_after_write_u64` and `mem_read_two_writes`, but nothing that says
`mem_read_u64 (mem_write_u64 m a v) a = v` in the shape a rule theorem needs.

**Measured 2026-10-05:** 0 occurrences of any of the three over the 52
examples. 62 `STR (immediate-offset)`, 60 `LDR`, 306 `MOVZ` — and no two
adjacent ones that touch the same base and offset. These rules are the ones
that would pay on real code and there is nothing in the corpus to develop them
against; `formal/examples` is register-only, which is the same fact
`bugs/FORMAL_wide_receiver_by_reference.md` records about the memory forms.

## 3. x86-64: the pass runs, no rule is proved

`X86_RULES` is an empty list. `peephole_x86` runs — the decoder sweep, the
fixed point and `_Remap` all execute — so the machinery is exercised by
`test_formal_peephole.py` rather than written twice when the first rule lands.

**What the first one needs.** `x86_step`'s arms for the useful forms are deep:
`op = 0x89` (`mov r/m64, r64`, 821 occurrences in the corpus) and `op = 0x8b`
(`mov r64, r/m64`, 274) sit below about thirty `if`s, and `op = 0x81` with
digit 0 (`add r/m64, imm32`, 108) below those. Two approaches:

* **Byte-concrete lemmas.** `x86_step` reads its instruction through
  `code pos`, so for a *literal* encoding every condition folds with `decide`
  and the negation list is unnecessary. The cost is one lemma per register:
  `mov rax, rax` is `48 89 c0` and `mov r8, r8` is `49 89 c0`, so
  `peephole_x86_mov_self` is sixteen near-identical theorems. `lib/X86.lean`
  already has sixteen `[simp]` `x86_rex_*` facts, which is what makes the
  literal case this cheap.
* **Symbolic registers.** `x86_rm_read`/`x86_rm_write` take a `modrm` byte and
  a `rex` byte as `UInt8`, and the register indices come out as
  `(modrm.toNat >>> 3 &&& 7) + x86_rex_r rex` — symbolic `Nat`s, which is the
  case `bv_decide` cannot discharge from the class mask alone.

The byte-concrete route is the one to take first, and `x86_64/mov_self` is
the rule to take it with: it needs no memory lemmas, and it is the rule whose
absence is visible — the x86 emitter already uses real `mov` instructions
rather than arm64's zero-adding copies, so it is worth measuring whether there
is anything to win at all before investing in the other three.

## 4. `add_imm_fuse` is proved and enabled and fires zero times

Not a defect, so it does not belong in a work list — but it would be easy to
spend an afternoon on it by mistake, so: over all 52 examples the rule's
window (`add xd, xn, #i` ; `add xd, xd, #j`, same register, `j` possibly
nonzero) occurs **zero** times. The 48 adjacent same-destination pairs in the
corpus all have `j = 0`, and those are copy chains, which §1 is about. A
program with `a += 1; a += 2` would exercise it; `formal/examples` has none.

## Reproducing

    export PATH=/opt/homebrew/bin:$PATH
    python3 test_formal_peephole.py                    # 25 tests, the licence and the remap
    python3 tools/formal_bench.py                      # per-example instruction counts
    python3 tools/formal_bench.py --opt                # the same, through the pass

To see the §1 failures with the rule enabled:

    python3 - <<'EOF'
    import sys, subprocess; sys.path.insert(0, '.')
    import formal.peephole as P, formal.build as B
    P.ARM64_RULES = P.ARM64_RULES + P.PENDING_RULES
    for name in ('formal/examples/sqsum.mojo', 'formal/examples/sum_range.mojo'):
        B.compile_formal(name, output='/tmp/x.aout', prove=False, check=False, opt=True)
        print(name, subprocess.run(['/tmp/x.aout'], timeout=5).returncode)
    EOF