# FORMAL_subprocess_run_is_modelled_as_returning_the_status_word: `.returncode` is a field access on an integer

**Found 2026-10-05** (`formal37-2`) while closing the `functools` row in
the thirteen-row host-import doc (deleted in 12774624) — removing that
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

## Status 2026-10-08 (`work/formal165-docs`): option 1's blocker is GONE, and its
## stated cost was wrong about a one-field struct

**This doc called option 1 ("make the model return a struct") the CPython-
matching one and priced it at "a frame-allocated struct per `run`". The price is
wrong for `CompletedProcess`: a ONE-field struct has no frame at all — its value
IS its only field (`model.struct_is_framed` is False), so `.returncode` lowers to
the identity and no block is reserved.** That is the same fact
`formal/build.py::_one_word_field_map` states for `var b = Box()`.

**The real blocker was one layer below the model, and it was measured.** The
backend could not read a field off a name bound from a CALL at all, whatever the
callee's declared return type named. Both architectures, before this session:

```python
struct Box:
    var v: Int = 0

def make_box(n: Int) -> Box:
    var b = Box()
    b.v = n
    return b

def main() -> Int:
    c = make_box(5)
    return c.v
```

    build: main: 'c.v' is a field access through 'c', and this path has no way to
      say what 'c' holds. … Bind the base from a constructor whose declaration
      THIS IMAGE can see (`x = S()`)

— a sentence that is false about this program: the image had just compiled the
constructor the declaration names. So `r = subprocess.run(...); r.returncode`
fails on the BINDING, not on any of the three options this document costed.

**Fixed this session, as shared infrastructure rather than as this doc's fix.**
`formal/build.py::_call_returns_one_word_struct` is a third source for both
one-word tables, beside a construction and a declared parameter: a local bound
from a callee whose declared `-> T` names a one-field struct of this image is
that struct. Three shapes are refused rather than claimed (a type-constructor
conversion, a struct that is not one field, and a one-field struct whose sole
field is itself a FRAME — the holder tables own that word). Pinned by two
`test_formal_run.py` BOTH_ARCH_CASES rows on both backends:
`both_arch_one_field_struct_returned_by_a_call_reads_through_its_field` and
`both_arch_one_field_struct_returned_by_a_call_dispatches_eq`.

**What is left is now a one-line model change and a decision this doc still
owns.** A `subprocess.run(...) -> CompletedProcess` whose `CompletedProcess` is a
one-field struct makes `r.returncode` lower; every int-shaped use of `run`'s word
is unchanged, because the struct's value IS the word (measured: `r != 0` still
branches as it did; `printf("%d", r)` already took a word). **The one fact the
decision turns on is which of CPython's four `CompletedProcess` attributes the
one field is, and the measured answer is `returncode`** — it is the only one of
the four any of the 547 call sites reads (§5's own census). It is NOT taken here
because `formal/hostmods/subprocess.mojo` is `@admitted`, and a struct-returning
admitted function changes the proof obligation the integrator's Lean run has to
check; a light worker may not run Lean. The three options are now two: option 1
is cheap and this session removed its blocker, and option 2 (forbid the
spelling) is the only remaining alternative.