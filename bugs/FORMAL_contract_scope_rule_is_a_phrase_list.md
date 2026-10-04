# `contract_text_is_scoped` is a phrase list, and a claim about the host's STATE passes it

**Status: OPEN. One instance of the hole is FIXED** (it was one of the fifteen
false contracts in `bugs/FORMAL_trust_audit_2026-10-04.md`); what is left is the
rule itself, which needs a decision rather than another word.

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