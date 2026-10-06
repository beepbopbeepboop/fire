# FORMAL_subprocess_run_is_modelled_as_returning_the_status_word: `.returncode` is a field access on an integer

**Found 2026-10-05** (`formal37-2`) while closing the `functools` row in
`bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md` — removing that
module from `version.py` moved the file two subjects further before it stopped,
and this is where it stops. **NOT FIXED, and not fixable by the corpus**: it is a
divergence between what the host module models and what the Python source means,
so fixing it means changing one or the other deliberately.

## The symptom

`version.py` is three constructs in and refuses on the third, identically on
arm64 and x86_64:

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/vpy_arm64 version.py
build: version: 'r.returncode' is a field access through 'r', and this path has no
  way to say what 'r' holds. A field is lowered three ways and which one applies
  is decided by the BINDING of the base, not by a type: a one-field struct's
  receiver IS its field, a multi-field struct's receiver is the address of a
  frame, and an ordinary word is an integer — and nothing this image can see about
  'r''s binding establishes which, so a store to the field with no home lands in
  a register the next function reads as its first parameter. …

real 2.16
```

The refusal message is CORRECT and the reason it fires is that the model's
`subprocess.run` does not return what CPython's does.

## Why: `run` is modelled as returning the status word

`formal/hostmods/subprocess.mojo` models `CompletedProcess` as **a word that IS
the `returncode`**, not as a struct:

```python
def CompletedProcess(args, returncode, stdout=0, stderr=0) -> int:
    """… the returned word is `returncode` exactly as it was passed …"""
    return returncode
```

and `run` returns that word (`formal/hostmods/subprocess.mojo:472`), with
`completed_process_returncode` (line 333) stating the same fact as a pure
function. So in the image:

| | what `r` holds | what `r.returncode` is |
|---|---|---|
| CPython | a `CompletedProcess` object | an `int` attribute |
| the model | an `int` (the status) | a field access on an integer |

There is nothing in the image that establishes `r`'s binding as a struct, which
is exactly what the refusal asks for. It is not a lowering bug: the same message
names the three conventions and says which one would apply if the binding were
knowable.

## Why the corpus cannot fix it by rewriting the call site

It can be *written around*, and that is the trap. The three shapes all change
what the Python means:

```python
r = subprocess.run([...])
rc = r.returncode          # CPython: correct.  Model: field access on a word.
rc = r                     # Model: correct.  CPython: a CompletedProcess object,
                           # so `r == 0` is False and `r != 0` is True ALWAYS —
                           # the `-dirty` suffix silently disappears and
                           # 'unknown' is never returned.
rc = completed_process_returncode(r)   # CPython: NameError.  Model: correct.
```

The middle one is the dangerous one: it compiles, runs, and returns a
**different answer on a dirty tree**, which is precisely the input the `-dirty`
suffix exists to catch. So a rewrite here is not a style change, it is a silent
behaviour change on exactly the case `version.py` is most load-bearing for.

The same argument is why this is filed rather than worked: the honest fix is a
DECISION about which side gives, and it is not a call this tree can make for
itself.

## The three options, and what each costs

1. **Make the model return a struct.** `CompletedProcess` becomes a real
   one-field struct, and `.returncode` lowers through the one-field convention
   (receiver IS its field). This is the option that makes the model match
   CPython, and it is the one `formal/hostmods/subprocess.mojo` line 126 gestures
   at when it says a class on this path is a frame blob — so the cost is a
   frame-allocated struct per `run`, in every file that calls `subprocess.run`,
   and the blast radius is every such file rather than `version.py` alone.
2. **Keep the word and forbid the spelling.** `r.returncode` is refused BY NAME
   with a message pointing at the word model, and callers read `r`. Sound, but
   it rejects correct Python in files that are correct under CPython, and the
   corpus's own `test_re_formal.py:607` / `test_x86_64_decode.py:359` are written
   the CPython way today.
3. **Add a shim the model and CPython agree on.** `completed_process_returncode`
   already exists on the model side; giving it an identical CPython definition
   makes `rc = completed_process_returncode(r)` correct on both. Cheapest, and it
   changes what a reader sees — the source stops reading like CPython, which is a
   cost paid on every such call site forever.

Option 3 is the one this doc would argue for, and the argument that keeps it
from being a decision rather than a doc is that **it is the only one of the three
that needs no capability change**: it adds a function that already exists on one
side and not the other, rather than moving a struct boundary or rejecting
correct code. But "should" is not "may", and this is a question about what
`formal/hostmods/subprocess.mojo` is FOR, which is not a call a bug-fix session
makes unilaterally.

## Status

**OPEN, with the refusal reproduced and the three options costed.** No code
changed for this: the `functools` commit that found it (`version.py`) leaves
`r.returncode` exactly as it was, and `version.py` was already refused before
that commit — on `functools`, which is the module this tree does not need.

**Not closed by rewriting `version.py`.** `formal/hostmods/subprocess.mojo` is
claimed work; the caller-side substitution is deliberately NOT made, because the
one spelling that compiles on both sides (`rc = completed_process_returncode(r)`)
is option 3 and option 3 is the decision this doc is asking for.

## Next step, exactly

Decide between 1, 2 and 3 above, and record it in
`formal/hostmods/subprocess.mojo`'s module docstring either way — because the
docstring is currently silent on whether `run`'s word return is a deliberate
simplification or an accident of modelling `CompletedProcess` as a word, and
`version.py` is not the only file that will need to know.