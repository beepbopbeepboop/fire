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

## Status 2026-10-09 (`formal261-docs-r2-r2`): both cheap options priced by measurement

The three options' cost claims were narrower than the module actually is, and
each is now measured rather than assumed:

* **Option 3's "no capability change" is FALSE as literally stated.** CPython
  3.14's real `subprocess` module has no `completed_process_returncode`
  attribute (`hasattr(subprocess, "completed_process_returncode")` is False),
  so an "identical CPython definition" cannot live in the module the name is
  imported from. And the interpreter oracle resolves `import subprocess` to
  that REAL module — `fire.py run` of a program spelling
  `subprocess.completed_process_returncode(r)` raises
  `AttributeError: 'module' object has no attribute`, while the same program
  builds and runs under `fire.py build --formal`. So option 3 as written would
  make the corpus's differential oracle fail every file that adopted the shim
  spelling. It can only be made to work by ALSO putting
  `completed_process_returncode` somewhere the Python side imports — a new,
  tree-owned shim name, which is a capability change rather than the free
  option the doc called it.
* **Option 1's cost is the admission contract, not just a frame blob.**
  `formal/hostmods/subprocess.mojo`'s own module notes (`run`/`call`/`check_call`
  deliver "the child's exit status word") say the twelve admitted contracts are
  shaped `UInt64 → UInt64` ("the Lean declaration is UInt64 → UInt64"), so a
  struct return from `run` is not a word-shaped contract any more. Making
  `CompletedProcess` a struct reshapes every contract the file admits, and the
  `completed_process_returncode` accessor is then the field read — which is
  exactly the shape `formal/hostmods/struct.mojo` exists to say is a frame blob
  on this path.
* Option 2 (refuse `r.returncode` BY NAME, point at the word model) is the one
  option whose cost has not moved: it still rejects correct-under-CPython
  source, and the corpus's own `test_re_formal.py:607` /
  `test_x86_64_decode.py:359` spell it that way (verified present, still the
  CPython shape).

The doc's middle-row warning stands and is the reason none of this is a
spelling change: `rc = r` compiles and answers differently on a dirty tree,
and the whole point of `version.py`'s `-dirty` suffix is the input that is
wrongest under it.

**The decision is therefore not "which option", as the three stood.** It is
either "where may option 3's Python-side shim live" (a new tree-owned name the
corpus, the interpreter and the image all resolve) or "may `run`'s admitted
contract leave the `UInt64 → UInt64` shape" (option 1). Both are FOR
`formal/hostmods/subprocess.mojo` questions, which is the boundary this doc
already named; this update is the measurement that makes the boundary concrete.
`version.py` remains exactly as closed — refused at `r.returncode` — and no
caller-side substitution was made for the same reason the doc originally gave.

## Status 2026-10-13 (`work/formal371-docs`): option 1's stated mechanism is
## REFUTED — a call's result does not establish the binding, struct or not

All three options above rest on the same premise: that what stands between the
caller and `r.returncode` is the model's WORD return, so making `CompletedProcess`
a real one-field struct would let `.returncode` lower "through the one-field
convention (receiver IS its field)". **Measured, that is not what fires.** The
field-access refusal asks whether the base is bound by something the image can
see, and a CALL RESULT is not — even when the callee's declared return type is a
one-field struct declared in the same unit. Nine lines, built on BOTH
architectures, byte-identical wording:

```python
struct CompletedProcess:
    var returncode: Int

def make() -> CompletedProcess:
    var c = CompletedProcess(returncode=3)
    return c

def main() -> Int:
    var r = make()
    if r.returncode == 0:
        return 1
    return 0
```

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build \
      --formal --no-prove --backend=arm64 -o .tmp/subproc/t3.aout .tmp/subproc/t3.mojo
build: main: 'r.returncode' is a field access through 'r', and this path has no
  way to say what 'r' holds. … nothing this image can see about 'r''s binding
  establishes which … Bind the base from a constructor whose declaration THIS
  IMAGE can see (`x = S()`) …
# and on --backend=x86_64, identical
```

The SAME struct bound from a constructor builds and runs on both:

```python
def main() -> Int:
    var c = CompletedProcess(returncode=3)
    if c.returncode == 0:
        return 1                      # Built, both arches
    return 0
```

**So option 1 as priced above does NOT work: the one-field convention is
selected by the BINDING, and a call's result is not a constructor.** Making
`run` return a struct value changes the admitted contract shape and still leaves
`r.returncode` refused. (Passing the field into a constructor —
`CompletedProcess(returncode=r.returncode)` — is refused the same way, so the
constructor does not launder the binding either.)

**That moves the in-reach fix to the capability this family already owns, and
the doc's own option 3 is a spelling of it.** `r.field` on a call result is
exactly the `FIELD` column of
`bugs/FORMAL_a_call_result_field_access_has_no_representation.md` §0, whose
§5.1 next step is a reader of the form `fs_stat_mode(p, follow)` — an ACCESSOR
the caller re-spells, which for this row is `completed_process_returncode(r)`,
the accessor `formal/hostmods/subprocess.mojo` already exports (line 334). So
the honest options narrow to **option 2 (refuse `r.returncode` by name, pointing
at the word model) and the accessor spelling**, and option 1 is off the table
rather than merely expensive. The accessor's blocker is unchanged and is the one
the 2026-10-09 update measured: the name must resolve in the corpus, in
`fire.py run` and in the image, which is a tree-owned shim and not the real
`subprocess` module.

Reproducing: `.tmp/subproc/{t3,t4}.mojo` above are scratch; the two-line
constructor case and the six-line call-result case are the whole measurement,
and `python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal
--no-prove [--backend=x86_64] -o /dev/null <file>` is the command.