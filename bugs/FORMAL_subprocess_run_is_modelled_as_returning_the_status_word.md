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

**OPEN, with the refusal reproduced, the three options costed, and the DECISION
taken (option 3 — see below).** No code changed for the refusal itself: the
`functools` commit that found it (`version.py`) leaves `r.returncode` exactly as
it was, and `version.py` was already refused before that commit — on
`functools`, which is the module this tree does not need.

**Not closed by rewriting `version.py`.** `formal/hostmods/subprocess.mojo` is
claimed work; the caller-side substitution is deliberately NOT made, because the
one spelling that compiles on both sides (`rc = completed_process_returncode(r)`)
is option 3 and option 3 is the decision this doc is asking for.

**DECIDED 2026-10-08 (`work/formal224-docs`): option 3, and the decision is now
recorded in `formal/hostmods/subprocess.mojo`** (see its "WHAT `run` HANDS BACK"
section).  Two measurements were taken to decide it, and one of them removes
option 1 outright:

* **Option 1 is not available for `version.py` even if the model returned a
  struct, and not because of the one-word admitted ABI alone.**  `version.py`
  reads TWO fields off `r`: `r.returncode` (lines 83 and 89) and `r.stdout`
  (line 83).  `stdout` is a captured STREAM, which this target does not model at
  all, so a one-field `CompletedProcess` — the shape option 1 needs, since a
  formal value is one word — would move `version.py` onto `r.stdout` rather than
  past it.  A struct that carried `stdout` too is a frame blob, and an admitted
  host contract is one word wide
  (`bugs/FORMAL_admitted_contract_is_one_word_wide.md`).
* **The line references the doc quotes are stale**: the two files written the
  CPython way are `test_re_formal.py:661` and `test_x86_64_decode.py:440`, not
  `:607` and `:359` (both files have moved).  Neither is a caller that only
  reads `.returncode`.

Option 3 is the only one of the three that needs no capability change, and it is
the spelling the sibling capability doc reaches for the same family —
`bugs/FORMAL_a_call_result_field_access_has_no_representation.md` §5, whose
"the cheapest honest form is not a struct at all" is the same answer.

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
`_one_word_field_map` states for `var b = Box()`.

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
`_call_returns_one_word_struct` is a third source for both
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

**merged 2026-10-13 (merging `work/formal186-docs`): the branch carried a
parallel 2026-10-08 section for the same landed fix** (its one-word map read the
callee's declared return type through `M.call_result_type_name` instead of this
tree's `_call_returns_one_word_struct`, pinned by its own two rows); deduped
into the 2026-10-08 Status above. Its unique measurements, re-measured on the
merged tree: the same-image fix is NOT sufficient for `subprocess.run` because
`run` is MODULE-QUALIFIED, and both cross-module shapes are still refused at
the BINDING — `var r = libcp.make(7)` and `var r = make(7)` under
`from libcp import make`, each with a one-field `CP` whose `make` returns `CP`,
each refusing on `'r.returncode' is a field access through 'r', and this path
has no way to say what 'r' holds`. On the branch tree the import-from shape was
refused at the DYLIB stage instead (`libcp.mojo: make returns a frame address,
so it cannot be compiled into a dylib`); the merged tree stops earlier, at the
binding, so the dylib-stage sentence is a branch-tree fact and the binding
refusal is the merged-tree one.

## Status 2026-10-13 (`work/formal398-docs`): the cross-module BINDING half is
## landed — a callee's declared `-> T` is now read across the import boundary

The 2026-10-08 merge note above found the two cross-module shapes still refused
at the BINDING and named them as what option 1 still needs. **That half is
fixed**, as shared infrastructure rather than as this doc's symptom:

* `formal/imports.py::imported_function_defs` reads `{bound name: FunctionDef}`
  from the imported module's own source (`from libcp import make` binds `make`),
  following a re-export to the module that defines the name.
* `formal/imports.py::imported_module_function_defs` reads
  `{module local name: {function name: FunctionDef}}` for the module-qualified
  spelling (`import libcp; libcp.make`).
* `formal/build.py::_call_returns_one_word_struct` now reads a callee from
  either table, for a `MemberExpr` base that names an imported module and for a
  bare name; `_prepare_functions` folds the free functions into its by-name
  table (`extra_functions`, added only for names this unit does not define, so a
  local definition still wins and no existing answer moves) and threads the
  module table to the two binding analyses (`_seed_one_word_bindings` and
  `_one_word_field_map`). Gated on Mach-O, like `_imported_structs`.

Pinned by two rows, on both backends and against CPython:
`test_formal_monomorph.py::test_a_one_field_struct_from_an_imported_bare_call_
reads_through_its_field` and `…_from_a_module_qualified_call_reads_through_its_
field` — a `struct CP: var returncode: Int` with a `def make(n) -> CP` in
`pairlib.mojo`, read as `var r = make(7); print(r.returncode)` and as
`var r = pairlib.make(9); print(r.returncode)`, each answering CPython's 7 / 9.

**What this does NOT do, and the doc's symptom is untouched by it.** It removes
the BINDING refusal for a callee whose declared `-> T` IS a one-field struct.
`subprocess.run`'s declared return is still `int` — `formal/hostmods/
subprocess.mojo`'s `CompletedProcess` is a word — so `r = subprocess.run(…)`
is not a one-field-struct binding and `r.returncode` is refused exactly as
before, by the same `_field_access_refusal`. Closing the doc's symptom is still
option 1 (give `run` a `-> CompletedProcess` struct return), and its remaining
blocker is the one the 2026-10-09 Status names: twelve `@admitted` contracts
shaped `UInt64 → UInt64`, whose reshape is an integrator's Lean run and no light
worker's. **This section is the cross-module half of option 1's groundwork, not
option 1.**

## Status 2026-10-13, merged (`work/formal411-docs`): the SAME fix, measured
build-and-run, on one implementation

`work/formal411-docs` built this fix independently and its two
`test_formal_run.py` `CROSS_MODULE_CASES` rows land with this merge:
`cross_module_returned_one_field_struct_reads_through_its_field` and
`cross_module_dotted_returned_one_field_struct_reads_through_its_field`, which
run the `struct CP` / `def make(n: Int) -> CP` pair above through a REAL image on
both backends and compare the answer with CPython (`77` and `99`). The branch's
own mechanism — a build-pass `_imported_function_defs` table plus a
`_callee_declaration` helper — is NOT what the merged tree carries: the
2026-10-13 (`work/formal398-docs`) section above is, and it is kept because it
reads the declarations from `formal/imports.py::imported_function_defs` /
`imported_module_function_defs`, which follow a package RE-EXPORT and are
threaded through `_prepare_functions` rather than rebuilt per call site. The
branch's one fact that the kept implementation did not have is folded into it: a
`MODULE.member` chain is claimed only when no struct of THIS image declares
`member`, because a local `m` that shadows an imported module's name makes
`m.f()` a method call the lift owns.

**What this does NOT do is the same in both readings, and it is the doc's actual
symptom:** `run` still returns the STATUS WORD, so `r.returncode` is still a
field access on an integer. Closing it is still option 1 (give `run` a
`-> CompletedProcess` struct return), and its remaining blocker is the one the
2026-10-09 Status names: twelve `@admitted` contracts shaped `UInt64 → UInt64`,
whose reshape is an integrator's Lean run and no light worker's.

