# `contract_text_is_scoped` is a phrase list, and a claim about the host's STATE passes it

**Status: FIXED, 2026-10-04, on `work/formal21-3`.** Option 1 below is
implemented as `formal/admitted.py`'s third scope rule,
`value_attached_claim`, with the probe instrumentation this file's "exact next
step" asked for: `test_formal_admitted.py`'s `SCOPE_PROBES`, 34 rows over three
rules, one row per connective **built rather than written**, a row in BOTH
directions per rule, and the corrected `ctypes` text pinned as an accept row
against the live tree. §"What landed" below is the record, including the two
limits the rule cannot see — which are the residue §"Why I did not just extend
the word list" predicted, and which the probe table carries as accept rows
rather than leaving to be discovered.

Claim: `sweep20:admitted-audit`.

## What I ran

Read `formal/admitted.py`'s `_OVERCLAIM` and then every one of the nineteen
admissions through `contract_text_is_scoped`, looking for a contract whose text
asserts something about the host that is not about the answer.

## What I saw

`ctypes.CDLL`'s admission, before the audit corrected it:

```python
@admitted("the loader handle is 0, meaning no library of that name is on this "
          "target, or a non-zero word this target's dynamic loader owns")
```

`formal/hostmods/ctypes.mojo`'s own docstring said, about the sentence after it:

> The contract is about the HANDLE'S SHAPE, and that is all it may be: whether a
> library of that name exists is a fact about the host's filesystem, and
> `contract_text_is_scoped` refuses an admission here that tried to say so.

**It did not refuse it.** The rule is seven substrings — `always`, `never`,
`deterministic`, `empty`, `no other`, `none running`, `safe` — and this sentence
contains none of them. It asserts a fact about the host's filesystem (a library of
that name being absent) attached to a VALUE by the word "meaning", and that is
grammatical, which is why a word list cannot see it.

The sentence was also **false**, which is how the audit found it: `dlopen(3)`
fails on a file that exists and is not a loadable image, so handle 0 does not mean
the library is absent. The corrected text names what `dlopen` actually promises.

## Why I did not just extend the word list

The obvious fix — add `meaning`, `filesystem`, `exists` — rejects good sentences
and misses the next one. `ctypes`' corrected text says "the file may be absent,
may not be a loadable image, or a symbol may be unresolvable", which is a claim
about the host's filesystem in every word and is *true* and *in scope*: it
constrains the answer 0. A phrase list cannot tell those two apart, and a rule
that rejects the corrected text to keep the false one out has traded a false
admission for an unusable instrument.

## The exact next step

Decide what "constrains the ANSWER" means formally enough to check, then
implement that. Two shapes that look implementable:

1. **Value-attached claims.** The admission is a set of constraints on the answer
   word; a clause introduced by "meaning"/"which means"/"i.e." after a value
   asserts something *about the world* rather than *about the word*, and should
   have to say so about the word. Mechanically: split on those connectives and
   require the following clause to constrain the word too (its subject or its
   predicate mentions the answer). This is a real structural rule and it passes
   the corrected `ctypes` text.
2. **Type the claim.** Give `Contract` an optional declared KIND — `status`,
   `byte_string`, `handle`, `pid`, `word`, `timing` — each with the shape
   constraint that kind is allowed to assert, and check the text against it. This
   is bigger, it duplicates the `@admitted` text in a second place (the thing
   `formal/admitted.py`'s header forbids), and it is the only version that scales
   to a new kind of contract without a new phrase.

Whichever is chosen, it needs the same treatment as the truth probes: a row per
rule that is fed a sentence which must be refused, so the rule cannot rot into
passing everything. `test_formal_admitted.py`'s `truth` group has the shape of
that instrument already (`PRE_AUDIT_TEXT` and its refusal check), and the scope
side has no equivalent — the `-1` sentinel that `popen_poll` used, and "meaning no
library of that name", both passed a rule that had never been given something it
had to catch.

## What landed (option 1), 2026-10-04

**Option 1, and the two halves of the "exact next step" above with it.**

`formal/admitted.py::contract_text_is_scoped` now runs THREE named rules rather
than two implicit ones, and every refusal carries the name of the rule that
fired, so a writer who is refused can find it:

| rule | what it is |
|---|---|
| `no_text` | a `sorry` with an empty statement is an absence, not a claim |
| `overclaim_phrase` | the seven-substring table above, unchanged and still the cheap arm it was |
| `value_attached_claim` | **the structural rule**, new |

`SCOPE_RULES` names them and `test_formal_admitted.py` keys its probes on those
names, so a rule nothing exercises is reported rather than passing quietly.

**The rule.** An admission is a set of constraints on one word; a writer who also
wants to say something about the host's STATE has to attach it to that word, and
English does that with an explanatory connective — `X is V, meaning P` / `…,
i.e. P` / `…, namely P` / `…, read as P`. The sentence itself therefore says
which clause is the claim about the word (before the connective) and which is the
claim about the world (after it), and the rule is that **the second has to be
about the first**: the clause the connective introduces must mention the answer's
own content words, or carry a numeral (a numeral is a value specification, which
is a constraint on the word by construction — the `or -N for a death by signal N`
arm of every status contract in the tree).

Thirteen connectives, in two shapes because English takes them differently:
`_EXPLANATORY_CLAUSE` (`meaning`, `means`, `i.e.`, `in other words`, `that is`,
`which is`) introduces a clause, and `_EXPLANATORY_PHRASE` (`namely`,
`denoting`, `denotes`, `signifying`, `signifies`, `read as`, `stands for`)
introduces a phrase.

Measured on this tree, with `python3 test_formal_admitted.py registry scope truth`:
**the rule fires on the pre-audit `ctypes` sentence and on nothing else** — all
nineteen live admissions pass, and all eighteen other pre-audit sentences still
pass it exactly as before (they are `truth` probes' business, not this rule's).

**The instrumentation, which is the other half of the ask.** `SCOPE_PROBES` in
`test_formal_admitted.py` is 34 rows over the three rules:

* **one row per connective, BUILT rather than written** — a comprehension over
  `_EXPLANATORY_CLAUSE` / `_EXPLANATORY_PHRASE`, so a connective added to
  `formal/admitted.py` brings its row with it and the row fails if the connective
  does not fire. This is not tidiness: eleven of the thirteen had **no row** on
  the first attempt, and the run that found it is `.tmp/deadconn.py`'s — removing
  each connective in turn and asking whether any row notices. Two more were
  *subsumed* (`that is to say` is matched by `that is`) and were deleted from the
  table rather than left as entries whose removal changes nothing. The shape is
  the one `tools/formal_sweep_causes.py` was fixed for in
  `bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §5.1, and its `check_cause_table`
  asserts every label is reachable from a sample.
* **a row in BOTH directions per rule** — the accept half is what stops a rule
  that refuses everything from passing every refuse row while `group_scope` goes
  red on the tree's own nineteen contracts. The corrected `ctypes` text is an
  accept row *and is pinned against the live contract's text*, so a rewrite of
  `ctypes.cdll_open` that reintroduced an attached claim has to update this table
  rather than pass quietly.
* **the two LIMIT rows**, which are the point of the boundary being written down
  rather than discovered: the `-1` sentinel the audit found false (no connective,
  no banned phrase — `TRUTH['subprocess.popen_poll']` refuses it, because `-1` is
  an answer CPython really gives) and a world claim attached by a **causal**
  connective (`the loader handle is 0 because no library of that name is on this
  target`). `because` is absent from the connective table on purpose, because
  `subprocess.check_output`'s corrected admission uses it to explain a truncation
  that IS a constraint on the word — so a rule that caught that sentence would
  refuse the tree.

**Non-vacuity, measured rather than asserted** (`.tmp/vacuity.py`, scratch):
removing each of the three rules in turn makes
`test_the_scope_probes_refuse_what_they_are_written_for` fail.

**What the rule cannot see**, which is the honest residue of a text check and is
stated in the rule's own comment as well as here: a world claim with no
explanatory connective passes (the two limit rows), and a world claim that
happens to share a word with the answer passes — the overlap test asks whether
the clause is ABOUT the answer, not whether every part of it is. Option 2 is
the version that scales past both, and it is not done here for the reason §"The
exact next step" gives: it duplicates every `@admitted` text in a second place,
which is the thing `formal/admitted.py`'s header forbids.