# FORMAL_argparse_memset_constants_comment_is_stale: the module says a `memset` byte "is REFUSED with 'PAT_DASH' has no home", and it is not

**Status: OPEN, and it is a comment rather than a defect.** Found while landing
`FORMAL_folded_module_constant_as_memset_argument.md`'s fix (commit `9dcee987`).
`formal/hostmods/argparse.mojo` builds and passes; what is wrong is that its own
source tells the next reader a falsehood about this backend.

## What it says

`formal/hostmods/argparse.mojo:292-300`:

```
# A BYTE WRITTEN WITH `memset` IS SPELLED INLINE, and these names are only for
# the places module-constant folding does reach (a call argument, a return).
# The reason is measured and it is not a subtlety: `memset(pat + i, PAT_DASH, 1)`
# is REFUSED with "'PAT_DASH' has no home: the register allocator collected no
# home for it, so the emitter and the allocation walk disagree about this
# function's locals", while the identical call with `45` written inline builds
# and runs. A name that reads well is not worth a build that does not compile,
```

That measurement was true when it was taken. It is false now, and the reason is
in the deleted doc: a module-level name whose value the build FOLDS is
substituted at every read by `build._substitute_module_constants` **before any
emitter runs**, so it never needs a register, a spill slot or a `__DATA` slot.
There is nothing for the allocator to run out of.

## Measured, on this tree

`formal/hostmods/argparse.mojo` with its own two `memset` bytes restored to the
named spelling — `memset(pat + i, PAT_A, 1)` and `memset(pat + i, PAT_DASH, 1)`
at lines 2307 and 2309, exactly the calls the comment names:

```
$ python3 .tmp/w/modbuild.py formal/hostmods/argparse.mojo
OK …/argparse.….arm64.dylib
```

The module builds with the named constants folded, which is the whole claim.
The same shape as a standalone program, checked through `memcmp` against a
buffer filled the inline way (so a wrong value cannot pass):

```
arm64    Built; memcmp == 0
x86-64   Built; memcmp == 0
```

and pinned from then on by `test_formal_run.py`'s
`folded_module_constant_as_a_memset_byte`, with `memset_byte_spelled_inline_is_unchanged`
as the guard.

## Why it was not fixed in that commit

Three reasons, and the third is the one that matters:

1. It is `argparse`'s file. `module:argparse` was a real claim in this tree's
   history, and a 4000-line host module does not belong in a commit about the
   substitution walk.
2. The change is not only the comment. Every byte in the module is spelled
   inline, so restoring the names means editing ~60 `memset` sites, and each one
   is a place the byte value becomes a name — a readability change to somebody
   else's module, with its own review.
3. **The comment is load-bearing as a WARNING even though its reason is
   wrong.** "Spell the byte inline here" may still be the right instruction for
   this module for a reason the deleted doc did not identify, and rewriting a
   careful author's stated reason without knowing what replaced it would be the
   worse outcome. Whoever does this should establish what the inline spelling
   actually buys today before removing the reason.

## Next step

1. Measure (2): restore the names at a sample of the `memset` sites, build on
   both architectures, and diff the resulting behaviour against the inline
   spelling. If it is identical, the inline spelling is pure readability and the
   comment's claim is simply obsolete.
2. If it is identical, delete the comment's *reason* and keep the instruction, or
   restore the names — whichever `argparse`'s owner prefers — and re-run
   `test_formal_argparse.py` for the module's own values.
3. If (2) shows a difference, this is a REAL defect again and the substitution
   walk does not reach something in this module; the reproducer is
   `memset(pat + i, PAT_DASH, 1)` in a module dylib, which is one shape the
   standalone case above does not have.