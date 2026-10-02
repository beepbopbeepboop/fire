# FORMAL_fnmatch_translate_absent: `fnmatch.translate` is answerable and deliberately not written

**Status: OPEN, filed 2026-10-01 by the `construct:x86-byte-read-and-platform`
claim, which wrote `formal/hostmods/fnmatch.mojo`. Not a defect in anything that
exists: `fnmatch`, `fnmatchcase` and the shared matcher are there and checked
against CPython. This is the one name of that module that is absent, and it is
absent for a reason a reader can check.**

## What is missing and what is not

`formal/hostmods/fnmatch.mojo` exports `fnmatch`, `fnmatchcase`, `match_any`
and `match_core`. CPython's `fnmatch` also exports `filter`, `filterfalse` and
`translate`. The first two are absent for a reason that is a property of this
target and is stated in the module's docstring: they take a list of names and
answer a list of names, and a list on this path is a blob carved out of the
frame that built it, which cannot cross a dylib boundary
(`bugs/FORMAL_listdir_no_run_time_sequence.md`).

`translate` is a different case and this doc is about it, because `translate` is
PURE, its answer is a STRING, and strings cross boundaries fine. So it is
answerable, and the only reason it is not written is that its consumer is
absent: what it emits is a regular expression in a dialect nothing on this path
compiles.

## The reason, measured

CPython 3.14's `fnmatch.translate` on this tree:

    $ python3 -c "import fnmatch; print(fnmatch.translate('*[a-c]*'))"
    (?s:(?>.*?[a-c]).*)\z
    $ python3 -c "import fnmatch; print(fnmatch.translate('a'))"
    (?s:a)\z

Three constructs in every answer, and `formal/hostmods/re.mojo`'s own docstring
lists what its engine has: "literals, `.`, classes with ranges and negation, the
`\d \s \w` shorthands and their negations, alternation, capturing /
non-capturing / named groups, and `* + ? {m,n}` in greedy and lazy form", plus
`\b`, `^`/`$` under MULTILINE, DOTALL and `(?P<name>…)`.

  * `(?s:...)` — an inline-flag group. Not in that list. DOTALL is supported as
    a FLAG argument, not as a group prefix.
  * `(?>...)` — an ATOMIC group, which 3.14's `translate` emits for every
    interior `*` ("For an interior `STAR fixed` pairing, we want to do a minimal
    `.*?` match followed by `fixed`, with no possibility of backtracking.
    Atomic groups allow us to spell that directly"). Not in that list, and not
    expressible by a backtracker over a compiled node array without a real
    atomic-group node.
  * `\z` — not in that list either (`re.mojo` is byte-oriented and anchored
    whole-string, so it does not need a spelled anchor, which is another way of
    saying the construct is absent rather than unimplemented).

So a `translate` here would be a function whose output nothing on this path can
compile, and the honest thing is to say so rather than to ship a regex nobody
can run. Note what that does NOT claim: the matcher does not go through
`translate` on this path, and does not need to — `match_core` walks the pattern
directly, which is why it is comparable with CPython answer for answer.

## The exact next step, for anyone taking it

1. **Decide whether `re.mojo` grows the three constructs.** If it does not,
   `translate` stays unwritten and this doc is closed with that answer recorded.
   If it does, that is a change to `re`, which is a bigger job than this one and
   belongs to whoever owns that module — and it is the job that would make
   `translate` worth having, since `(?s:…)`, `(?>…)` and `\z` are exactly what
   CPython's `translate` emits and nothing else in the tree emits them.
2. **The algorithm is settled and verified; only the transcription is missing.**
   CPython's is `fnmatch._translate(pat, '*', '.')` followed by
   `fnmatch._join_translated_parts(parts, star_indices)`. Two things about it
   are worth knowing before writing Mojo, and both were measured here:

   * **The `*`-compression and the atomic-group join.** `parts` is a list of
     strings with the star positions recorded beside it, which a list on this
     path cannot be (see above) — but the OUTPUT is one string, so the parts
     can be written into a `malloc`'d buffer as they are produced. With no
     stars the answer is `(?s:` + the parts + `)\z`; with stars, each interior
     star becomes `(?>.*?` + the parts up to the next star + `)`, and the tail
     is `.*` + the rest.
   * **The bracket body needs a list of chunks and does not have to.** That is
     the hard part of `translate`: it splits the set body at every `-` that is
     not part of a `X-Y` range, MERGES adjacent chunks whose boundary
     characters are out of order (`[b-a]` collapses to the empty set and
     becomes `(?!)`), then escapes each chunk and joins them back with `-`. A
     list of chunks is not expressible, and the merge deletes from the middle
     of the sequence.

     The shape that IS expressible was derived and verified on this tree before
     this doc was filed: build the raw body in ONE `malloc`'d buffer, with the
     chunk boundaries written into it as you go, remember the previous chunk's
     start offset, first byte, last byte and RAW length, and on a merge
     (`prev_last > next_first`) overwrite from `prev_start + prev_len - 1` with
     the new chunk minus its first byte — the cursor moves BACK by one, which
     is legal because nothing has been written after the previous chunk yet.
     Escape in a second pass (`\` → `\\`, `-` → `\-`, and `&`, `~`, `|` →
     `\<c>`), which is per CHUNK in CPython and so must not be done before the
     merges. Two subtleties the merge loop depends on: a previous chunk of
     length 1 that is merged leaves the new chunk's SECOND byte as the merged
     chunk's first, and CPython's own loop walks the chunks BACKWARDS (the
     merges are order-independent except for that case).

     Verified as an executable Python model against CPython's own
     `fnmatch.translate`: 20,053 patterns of 1-9 bytes over
     `abzAZ09-!]^~&|\./*?[`, plus every hand-written corner
     (`[a-c]`, `[!a-c]`, `[]]`, `[!]]`, `[a-z-]`, `[a-z-c]`, `[--/]`, `[--0]`,
     `[a-b-c]`, `[!-a]`, `[b-a]`, `[b-a-c]`, `[--]`, `[a--b]`, `[]-]`,
     `[\]]`, `[a\-c]`, `[a&&b]`, `[a~~b]`, `[|]`, `[~]`, an unterminated `[`,
     a trailing `-`, and 20,000 random patterns biased toward the bracket and
     set-operation characters) — **zero** differences.
3. **Where the answer would be tested.** `test_formal_fnmatch.py`'s `match`
   group already compares against CPython answer for answer over a masked
   corpus, and the `translate` answer is a STRING, so it is directly comparable:
   the same corpus, each pattern through `fnmatch.translate`, each string
   compared byte for byte with CPython's. That is a stronger assertion than the
   matcher gets (which is a bit) and it needs no new harness — `mask`/`unmask`
   already carry arbitrary bytes.