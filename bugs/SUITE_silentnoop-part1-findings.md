# SUITE_silentnoop-part1 findings: the failure is a build error, not a timeout or a case divergence

Part 1 of the `SUITE_silentnoop` replan is investigation-only. This file is its
record: the failure mode, the exact failing cases, and the observed error, so
the fix (tracked by `bugs/SUITE_silentnoop-part2.md`) has concrete inputs.

**Evidence:** part 1's measurement, recorded when part 1 was closed (commit
`8784f44f8`), is reproduced by the replanned part 1 capture in
`bugs/SUITE_silentnoop-part1-run.txt` — the `python3 tools/suite.py silentnoop`
run and the direct `python3 test_silent_noop_iter.py` run. The same measurement
is written up as the literal-kind mixed-parameter container refusal fixed by
commit `d2bc1dd5d`, which is the defect this classification identified.

## Classification

**Build error** — both failing cases stop during compilation, before any
compiled program runs. It is **not** a timeout, and it is **not** a
compiled-case divergence from the CPython reference.

Brief justification from the captured run:

- `python3 tools/suite.py silentnoop` completes in **644 s** against the
  registered `timeout=1500` and reports the job as `FAIL silentnoop (644s)
  exit 1`; it is not killed by the clock.
- Run directly, `python3 test_silent_noop_iter.py` reports exactly two
  failures, and both raise the same `RuntimeError` from the compiled path's
  container-kind guard while the fixture is being compiled. No compiled
  executable exists for either case, so there is no compiled stdout to compare
  against CPython. All other cases pass (including their CPython-oracle
  comparison), which rules out a general compiled-vs-CPython divergence.
- The refusal is deterministic and names the parameter, the function, and the
  unsupported source shape, so the failure is at build level rather than an
  output mismatch that only appears at runtime.

## Cases

Two cases fail, and they are one defect (both compile the same fixture):

| case | observed error / output mismatch |
|---|---|
| `parameter_rebound_to_one_container_kind_is_not_multi_kind` | Build-time `RuntimeError`: `parameter 'box' of 'pick' is passed a container at one call site and a str or number at another, and the body uses it as a container; the compiled path has no representation for that yet (the per-kind clone pass only covers literal arguments)`. Expected (CPython): `['a']`, `['x']`, `['q', 'r']`, `first`; the case never reaches that output because the build is refused. |
| `sorted_two_string_set_pinning` | Same fixture (`pick`), so the same build-time `RuntimeError` and the same absence of compiled output. Its own subject — a two-string set's `sorted` order matching CPython, plus failure-artifact retention — cannot be exercised until the fixture compiles. |

The shared fixture passes `None`, `"x"`, and `{"q", "r"}` to `box` at three
call sites while every branch of the body rebinds it to a set. CPython prints:

```
['a']
['x']
['q', 'r']
first
```

No other case fails and no case times out.

## Disposition

The defect is not a one-line lowering fix, so it was filed on its own with the
fixture, the CPython oracle, and the reason the case is a pin for a fix rather
than a shape to mark as an expected refusal; it is fixed by commit
`d2bc1dd5d`. Making the job green is
`bugs/SUITE_silentnoop-part2.md`.
