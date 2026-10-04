# DOCS: `formal/build.py`'s early scalar-slot gate still names the reader
# `ba63213c` renamed, so a docstring points at a function that does not exist

**Area:** docs (a stale cross-reference in a docstring). **Status: OPEN, one
line, not fixed.** Found 2026-10-04 while merging `work/formal23-2` into
`work/merge-formal23`: that branch's `formal/model.py` and
`tools/formal_frame_slot_subscript_census.py` both name the pre-rename reader,
which the merge had to repoint, and one more reference to the same symbol
survives on `master` and is therefore the one this doc is about.

Not fixed because `formal/build.py` is edited by at least three workers' branches
and a merge is the wrong place to take a third edit to it — the cost of the
one-word fix is a conflict in a file everybody is touching, and the cost of not
making it is a stale name in a comment.

## What I ran

```console
$ grep -rn 'slot_container_operand_refusal\|_refuse_slot_container_operand' \
      --include='*.py' .
formal/build.py:10534:    emitters' own arm (`_refuse_slot_container_operand`, over what the
```

That is the only one left in the tree. The three that `work/formal23-2`
introduced (`formal/model.py`'s `frame_slot_element_refusal` docstring and
`tools/formal_frame_slot_subscript_census.py`'s header, twice) were repointed in
that merge's second commit, because a merge that renames a symbol has to leave
the tree consistent.

## What is stale, and what it is not

`formal/build.py:10534`, in `_refuse_container_operands_on_scalar_slots`'s
docstring:

```
and one of the two architectures dereferences
the `5`. So the question is asked here, where `s.n` is still `s.n`, and the
emitters' own arm (`_refuse_slot_container_operand`, over what the
substitution could not match) is the second line rather than the only one.
```

The symbol is `_refuse_scalar_container_operand` now, in both
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py`, and its model-side
reader is `scalar_container_base_evidence` (the same docstring names that one
correctly, at the end: "the census is in `model.scalar_container_base_evidence`"
— so the rename reached one half of one docstring and not the other).

**The claim itself is still true, and only the name is not.** The sentence says
this pass is asked one step EARLIER than the emitter's own, because
`_rewrite_class_constants` has by then replaced `s.n` with the literal its
class-level default holds. That is exactly what the widened reader still cannot
see — `scalar_container_base_evidence` is asked of the node the emitter is
handed, which is the substituted literal. `ba63213c`'s own docstring for
`scalar_container_base_refusal` says so ("The node that gate was handed is, by
then, the slot's MATERIALIZED default … which is why `build._refuse_container_
operands_on_scalar_slots` asks the same reader one pass EARLIER"). So renaming
the symbol in the sentence closes it; nothing else about it needs re-deciding.

## The exact next step

Replace the one symbol:

```console
$ python3 - <<'PY'
import pathlib
p = pathlib.Path("formal/build.py")
s = p.read_text()
assert s.count("`_refuse_slot_container_operand`") == 1
p.write_text(s.replace("`_refuse_slot_container_operand`",
                       "`_refuse_scalar_container_operand`"))
PY
```

and, in the same commit, note in the sentence that the reader now takes ANY
expression rather than only a field — `scalar_container_base_evidence`'s third
and fourth arms (a scalar literal, a `TYPE` value) are new since this docstring
was written, and "over what the substitution could not match" is narrower than
what it is now asked about.

## Reproducing

```console
$ grep -rn 'slot_container_operand_refusal\|_refuse_slot_container_operand' \
      --include='*.py' .
formal/build.py:10534:    emitters' own arm (`_refuse_slot_container_operand`, over what the
```