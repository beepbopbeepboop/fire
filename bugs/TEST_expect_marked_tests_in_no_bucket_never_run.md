# TEST: 11 expect-marked tests are in no bucket, so no gate ever runs them

## Status — OPEN. Test infrastructure, not a compiler bug. Cheap to fix.

`tools/suite.py --list` shows 16 `EXPECTED-FAIL` tests. **11 of them have an
empty bucket list**, so `make check`, `make gate` and every other bucket pass
straight over them. They are registered, they carry a mandatory reason, and
nothing executes them.

Measured, from `python3 tools/suite.py --list`:

| test | buckets | declared failures |
|---|---|---|
| `ab-native` | `gate,native` | (bootstrap pre-pass blowup) |
| `bootstrap-stage2-dumps` | `gate,bootstrap` | (dump divergence) |
| `native-dumpfull` | `gate,native` | (bootstrap pre-pass blowup) |
| `async-runtime-scaffold` | **none** | 1 of 2 |
| `async-void-return` | **none** | 3 |
| `async-with-lock-guard` | **none** | 2 |
| `coro-detached-async` | **none** | 2 |
| `coro-future-await` | **none** | 17 |
| `gimple-async-runner` | **none** | 36 |
| `mutable-async-capture` | **none** | behaviour gap |
| `nested-async-generic` | **none** | 2 |
| `taskgroup` | **none** | 3 |
| `transitive-closure-capture` | **none** | behaviour gap |
| `x86-containers` | **none** | 1 (formal backend) |

That is **~69 failing cases** across 11 tests that no gate reports on. The
compiled-path async/await cluster is the bulk of it and is entirely ungated.

## Why this is worse than an ordinary gap

`expect=` is a claim about the world, and the suite enforces it in one
direction only. An expect-marked test that **passes** is reported as a
FAILURE ("marked expect=… but it PASSES — drop the marker"). That is the
anti-rot mechanism, and it is exactly what cannot fire here: a test no gate
runs can never be observed passing, so a stale marker on it is immortal. If
one of these 11 starts passing, or rots into referencing a renamed file, no
run will ever say so.

This is not hypothetical in this repo. `coro` previously sat in the gate
naming `mojo_*` runtime files that had been renamed to `fire_*`; all 20 of
its cases failed to compile and the suite reported 0/20 the whole time.
Nothing was expected, nothing was reported, and the coroutine runtime was
untested. The same failure mode is available again here, silently, and the
`expect=` marker actively disguises it — a reader sees a documented known
failure rather than a test that is not running.

## Next step

Give each of the 11 a bucket. The obvious home for the async/coroutine ones
is `coro`, which the gate already includes; `x86-containers` belongs in
`x86` (or `gate` if it is meant to be gated directly). That is a one-line
`buckets=[...]` per registration in `tools/suite.py` and nothing else.

Two things to check while doing it:

1. `coro` is in the gate bucket, so putting the 8 async tests there makes the
   gate meaningfully longer — they are `mem=small`, and `gimple-async-runner`
   alone reports 36 failing cases. Measure the added wall time and say so in
   the registration rather than discovering it as a surprise gate slowdown.
2. `test_suite.py` already checks that a recipe's memclass may not exceed the
   class of the job that runs it, and `suite.TALLY` refuses to start on an
   unhandled status. Run both after the change; a bucket addition is exactly
   the kind of edit those two exist to catch.

Once they are in a bucket, each will start reporting, and the ones that now
PASS will immediately surface as the "marked expect=… but it PASSES"
failures they should have been all along. That burst is the point: it is the
measurement that was never being taken.
