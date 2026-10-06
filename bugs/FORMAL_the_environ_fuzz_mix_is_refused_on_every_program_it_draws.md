# FORMAL_the_environ_fuzz_mix_is_refused_on_every_program_it_draws

**Area:** FORMAL, the program-differential fuzzer's `environ` mix
(`tools/formal_fuzz.py`'s `FIXED_ENV` family, which is `os.getenv` against a
fixed process environment).

**Status: OPEN, diagnosed, not fixed. Pre-existing on this tree; found while
running `test_formal_fuzz.py` as a regression check after the arm64 `SMULH`
model arm landed (which touches no refusal and no generator).**

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_fuzz.py
    ...
      FAIL  environ_produced_no_answer: 2 refusal(s) and nothing else — a family
      that is always refused measures nothing and reports numbers anyway
    formal fuzz: builds   environ   FAIL answers=0/2 (1 arch, 2 refused)
    ...
    Results: FAIL — 1 failure(s)

    $ python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_fuzz.py --mix environ -n 2
      refusal  #0  len(os.getenv(...))
      refusal  #1  len(os.getenv(...))
      refusal audit: true=4, unnamed=0, false=0, no-predicate=0

## What was seen

**`environ` is the only one of the 30 mixes that produces no answers**, and it
produces them at a rate of 0/2 on both backends. Every program the mix draws is
refused by name, and the refusal is the SAME SHAPE every time: `len` applied to
the result of `os.getenv`, i.e. `len(Optional[String])`.

Two things follow, and they are different:

* **The harness is right and the corpus is dead.** The refusal audit says
  `true=4`, `false=0` — every refusal is a TRUE one, so this is not a spurious
  rejection being counted as coverage. And `environ_produced_no_answer` is the
  harness's own anti-vacuity check doing exactly what it exists to do: a mix
  that measures nothing must not report numbers as though it measured
  something. **So the tree is telling the truth here and `test_formal_fuzz.py`
  is red for a real reason.**
* **`tools/formal_fuzz.py`'s own docstring is what is wrong.** Line 233
  describes `environ` as "`os.getenv` against a FIXED process environment" and
  line 262 lists it among the mixes that are swept "because they were newly
  lowered" — the reference is to
  `bugs/FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it.md`, which
  landed a real `os.environ` (a snapshot in `malloc`'d memory with
  `count`/`get`/`has`/`set`/`keys`/…). **What landed is `os.environ` as a
  module attribute; what this mix draws is `os.getenv(...).len()`, and the
  optional the latter returns is refused.** So the mix was pointed at the
  construct that works and given a spelling that does not, and nobody noticed
  because a dead mix reports `refusal=N` rather than an error.

## What is expected

Either the mix draws a shape that lowers — `os.environ["HOME"]`, or
`os.getenv(...) is None` / `os.getenv(...) == "x"`, which is the comparison the
optional can carry — or it is withdrawn from the default mix with a note saying
the `os.environ` model is not reachable through it yet. **Not** a third option:
leaving it in the default sweep, where it costs two builds per sweep and returns
nothing, is what produced this finding.

## The exact next step

1. Read the refusal's own name (it is not in the run above because
   `formal_fuzz.py` prints the CONSTRUCT, not the sentence — `--minimize` or a
   one-off build of one drawn program gives the text) and decide which of the
   two repairs it implies: `len` of an `Optional[String]` should probably be a
   refusal with a repair in it, and `os.getenv(k) is None` is the test a program
   that wants the optional actually writes.
2. Either way, `tools/formal_fuzz.py`'s `FIXED_ENV` comment must name the
   construct it draws, because the gap between "the model landed" and "the mix
   draws the model" is exactly the gap this doc exists to close.

**Not fixed in the branch that found it:** `tools/formal_fuzz.py` and the
`os.environ` model are both inside other claims' areas
(`bug:FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it` and
`bug:FORMAL_optional_needs_a_niche`, worker `formal28-4`), and this branch's
claim is the arm64 model and proof-generator diagnostics. `test_formal_fuzz.py`
is a registered gate job, so the red row is visible on every gate until it is
fixed — it cannot rot unnoticed, which is why this doc is short.
