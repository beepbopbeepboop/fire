# `floordiv` and `udivmod` are red, were red before the narrow-parameter fix, and no document owns them

**Area:** FORMAL, the arm64 proof generator. Found 2026-10-05 while fixing
`FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md`
and re-running the whole `formal/examples` corpus through Lean to gate that fix
— which is the only reason these two are known at all, since they are not in
`test_formal.py`'s `EXPECTED_FAILURES` and are therefore reported as FAILURES
rather than as gaps.

**Status: OPEN, MEASURED, PRE-EXISTING, and unowned.** Not fixed here: they are
not the narrow-parameter defect (neither function declares a narrow type), they
were red before anything of mine, and the full corpus run was the gate for a
different fix.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py -j 1 \
      floordiv udivmod fact sqsum sum sum_range
  [1/6] FAIL  floordiv
  [2/6] FAIL  sqsum
  [3/6] FAIL  sum
  [4/6] FAIL  sum_range
  [5/6] FAIL  udivmod
  [6/6] FAIL  fact
Results for arm64 formal proofs: PASS=0 KNOWN-GAP=0 FAIL=6 TOO-LARGE=0
```

run twice — once with the working tree and once with `formal/arm64_proof_gen.py`
restored from `HEAD` — with **identical verdicts**, which is the whole of the
claim that this is pre-existing rather than a regression from the narrow-parameter
fix. `fact`, `sqsum`, `sum` and `sum_range` are already accounted for in
`bugs/FORMAL_arm64_known_proof_gaps.md` (`fact`/`sqsum`/`sum` are the `dec1`
family owned by `FORMAL_arm64_x30_is_reloaded_from_the_frame.md`; `sum_range` is
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`'s unsigned `loop_cond_flag`).
**`floordiv` and `udivmod` are in neither list and neither has a document.**

## What I saw

Full corpus on the fixed tree, `python3 tools/memslot.py --gb 8 --label t --
python3 test_formal.py -j 1` (52 examples, 7.0 GB peak — over the 4 GB debt line
and worth noting for whoever runs this next):

```
Results for arm64 formal proofs: PASS=37 KNOWN-GAP=7 FAIL=6 TOO-LARGE=2
```

The three examples the narrow-parameter fix recovered (`sgt8`, `sle8`, `ug8`)
are inside that PASS count and were three of the six FAILs before it.

## Why these two are a real gap in the census

`bugs/FORMAL_arm64_known_proof_gaps.md`'s own argument is that **a gap which is
not in `EXPECTED_FAILURES` is a FAILURE, and that a closed list "cannot be a
closed list"** — and it holds the census by measuring one example at a time. Six
examples are red and five of them were named in it as of 2026-10-04. `floordiv`
and `udivmod` are the two the one-at-a-time sampling had not reached, and a
whole-corpus run is what reached them.

## The exact next step

1. Run each through `formal.build.compile_formal(..., prove=True,
   check=False)` and `formal.lean.check_proof_cached(..., repo_root=os.getcwd())`
   — the harness the narrow-parameter doc's §Reproduce already gives, and the
   one that prints the residual goal. **The residual goal is the missing half of
   every one of these rows**: no document in `bugs/` records what `floordiv` and
   `udivmod` cannot discharge, so the next step is a measurement and not a
   change.
2. Both are division, and `TestTheZeroDivisorGuardAgainstLean` in
   `test_formal_call_proof_gen.py` is already **red on `master`** over the
   division path — it asserts that the divide-by-zero residual is `⊢ 1 = …` and
   the generator no longer produces that goal ("fdiv64's div0 arm or the div0
   path's exit status may have been corrected, which is the fix this doc
   wants"). So there is a real possibility that `floordiv`/`udivmod` are red for
   a reason a **third** document owns, and finding out which is step 1.
3. Whichever it is, `EXPECTED_FAILURES` is the wrong instrument here: the file
   says so itself ("marking one of those stems `EXPECTED_FAILURES` would be a lie
   of a specific kind — 'known unproven' is a claim about the proof"), and these
   are red for a reason nobody has written down.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label base -- \
      python3 test_formal.py -j 1 floordiv udivmod
Results for arm64 formal proofs: PASS=0 KNOWN-GAP=0 FAIL=2 TOO-LARGE=0
```

`-j 1` is not optional for a bounded worker: at the default
`min(cpu_count, 20)` workers this run peaked at **18.1 GB** across 38 processes
and `memcap` killed it, which is a RESOURCE verdict and not a result.
