# FORMAL_env_family_next_terminal: where the 55-file family stands, and what the next reader needs

**Status: SUPERSEDED IN PART (2026-10-05, `formal37-2`).** The terminal recorded
below has **moved**: `binary_heap.mojo` is no longer in `env.mojo`'s refusal at
all, and the family now stops on two *present* surfaces rather than on an absence.
Read **§"Re-measured 2026-10-05"** at the end first — it has the current
terminal, and it records that the 172-file import closure resolves completely,
so this is no longer a transitive-import problem. The measurement this document
originally carried is kept below for the same reason the model-fuzz ledger keeps
its own: it is what a reader has to check the new one against.

**Original Status (2026-10-02, `work/formal8-5`): the family's own terminal has
NOT MOVED since 2026-10-02, and it is a file whose own document was deleted for
measuring at a ceiling of ZERO. What is left in this document is a measurement,
not a defect.** Re-measured 2026-10-02 on `work/formal8-5`, arm64, on the real
stdlib file:

```
$ python3 tools/memslot.py --gb 8 -- python3 fire.py build --formal --no-prove \
      --backend=arm64 -o .tmp/p/env_mojo.out \
      <stdlib>/std/os/env.mojo
build: env.mojo imports 'std.ffi', which cannot be built either:
       binary_heap.mojo: formal dylib has no public functions:
       binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares
       only the generic struct template(s) BinaryHeap, and a parametric type has
       no single boundary layout either.
```

Identical to the terminal the previous Status recorded, `unsafe_ptr` and
`_CPointer[UInt8, UntrackedOrigin[…]]` still absent from it. So the answer to
"what is left here" is: **`binary_heap.mojo`**, whose `len(self._data)` on a
`List[Self.T]` slot has no representable value.

**And the document that recorded why that file is not worth working is gone.**
`“FORMAL_dylib_export_gate_ceiling: the 38-file row is not 38 problems”` measured three candidate fixes for
`binary_heap.mojo` at a ceiling of ZERO files across all three, and was deleted
rather than worked — so the ceiling-zero measurement now lives only here, and
this file is what a reader needs in order to know that `env.mojo` is not one
patch away. It is worth being explicit about that, because the deletion rule
("a doc for a fixed bug is deleted") reads as "the problem went away" and this
one did not: it means the problem was measured and priced.

## The three steps, and where each stands

1. **DONE (2026-09-30, `4ad34f3`)** — `external_call["setenv", T]`'s bracket
   list is a template application rather than a container index. This closed the
   55-file family: `external_call` is what all 55 reach.
2. **DONE (2026-10-02)** — a type argument in ANY bracketed generic position is
   not read as a value: `model.type_position_nodes` excludes a bracket list in a
   type position from the runtime question rather than asking it and refusing
   (`FORMAL_external_call_a_multiparameter_type_in_the_bracket`,
   deleted with its fix).
3. **NOT DONE, and not this session's** — re-run

   ```
   python3 tools/formal_sweep.py --stdlib-subtrees=base64,bit,builtin <stdlib>/std
   ```

   and read `not-answerable/unresolved-extern` (56 when the table was taken) and
   the top entry of `codegen/dependency by family`, which should now be
   `info.mojo`'s MLIR constructs rather than anything this document describes. A
   whole-tree sweep is tens of minutes and hundreds of builds; it belongs to
   whoever runs the gate.

## The classification bug, which is still live and still not this file's

The sweep files any `symbol(s) that nothing provides` as
`not-answerable/unresolved-extern` (`tools/formal_sweep.py`'s
`_EXTERN_BUILD_MARK` rule), a class excluded from the coverage denominator and
from `DIRTY`. Its comment is right about the case it was written for — a
genuinely unlinkable image — and wrong about the one this family produced: the
backend is NOT right to refuse, because the symbol was a method of a struct in
the same image and the reason it was unbound was that a method call was never
rewritten. So a real 55-file codegen gap sat in the class that says "a fact
about the target, not a gap in the backend", and `codegen coverage` read 10.2%
instead of something lower for the wrong reason.

**A narrower form of the marker than a substring is the fix**, and it is still
not written. It is in `tools/`, it is a classification rule rather than a
construct, and no bug document claims it.

## What this worker verified about the construct itself

`test_formal_external_call.py` (29 cases) is the test of the closed half, and it
includes the whole of `std/os/env.mojo`'s three functions transcribed, run and
compared against `os.environ` in CPython — so the file's own remaining blocker is
a dependency, not its body. **Re-measured here, unchanged**, which is the reason
this document is a record and not a queue item: the family's own text is three
constructs closer to building and the next construct is another file's.

## Status, 2026-10-05 (`formal31-3`): the classification bug is fixed, and it is
## the only thing in this document that was ever a defect

The section "The classification bug, which is still live" is now closed. Its
last sentence — *"A narrower form of the marker than a substring is the fix, and
it is still not written"* — is what landed.

### What the narrower form is

`tools/formal_sweep.py::_EXTERN_BUILD_MARK` is still the substring it has always
been, because `formal/build.py::_unaccounted_report` cannot tell the two cases
apart: its bind audit sees one unaccounted name either way, and no amount of
sharpening there can know whether the definition was supposed to be on a link
line. **The sweep is the only layer that has both ends**, so the narrowing lives
there and is asked BEFORE the class is chosen:

  * `_UNPROVIDED_NAMES_RE` reads the symbol list out of the message's own
    sentence — `_unaccounted_report` spells it as a comma-joined list between
    `so it could not be loaded: ` and the next full stop, and a symbol cannot
    contain a stop (`_c_export_name` admits only `[A-Za-z0-9_]`).
  * `_declared_method_symbols(path)` asks **`formal.build._struct_methods`**,
    which is the function that decides which of a struct's methods are lifted
    into the compiled set at all and names each one. Re-deriving the
    `<Struct>_<method>` shape in `tools/` would be a second answer to a question
    `formal/` already answers.
  * `_own_unprovided_methods` intersects the two and returns a **LIST**, because
    the two causes really do coexist in one image — a dangling call to an
    unlowered builtin AND a method this file never emitted — and a rule that
    answered "codegen" for the whole message on the strength of one of them
    would file the other as a gap in the target.

The reason it prints is the sweep's own sentence rather than the build's,
because the build's own sentence is about the link line and would be the one
thing a reader must not take at face value here. It keeps the symbol NAMES (the
actionable half) and the count of the ones that were the link line's business.

### Both ranking instruments got the row, which is the same two-part argument
### `…_b12.md` §5.2 made

`_REFUSAL_FAMILIES` gains `a method of this file's own struct was never
emitted` and `formal_sweep_causes.py::CAUSES` gains `a method of this file's own
struct was never emitted into the image`. Without them a file in this row would
read as `other refusal` — the bucket both tools' docstrings define as "nobody
has looked" — and this document exists because that is exactly where a real
55-file codegen gap once sat.

`test_refusal_taxonomy.py` gets a sample in **both** tables: 272 checks, 46
families, 67 causes. **Those two samples are QUOTED and not built, and the file
says why in place**: every other sample there is a message `formal/` words and
is built by calling the function that words it, but this message is written by
`tools/formal_sweep.py` itself — there is no `formal/` function that words it —
so a hand-copy and the classifier are two statements of the same clause. **The
RULE is therefore tested where it can be built**, in
`test_formal_sweep.py::TestClassify`'s
`test_a_method_of_this_files_own_struct_is_a_codegen_finding`, which asks
`formal/build.py::_unaccounted_report` for the message (two unprovided symbols,
one of which is a method of the fixture's own struct) and then runs the
classifier over it, plus
`test_a_symbol_this_file_does_not_declare_stays_not_answerable` for the control:
no path, or a file declaring no such struct, and the message is
`not-answerable/unresolved-extern` exactly as it was. **135 tests, 0 failures.**

### What this document's other half still is

Nothing here moved the family's TERMINAL, and nothing was going to:
`env.mojo` still stops on `binary_heap.mojo`'s export gate, whose ceiling of
ZERO files is recorded in the section above and is the reason the document
recording it was deleted. Step 3 — re-running
`python3 tools/formal_sweep.py --stdlib-subtrees=base64,bit,builtin <stdlib>/std`
and reading `not-answerable/unresolved-extern` and the top of
`codegen/dependency by family` — is still not done, and still belongs to whoever
runs the gate: a whole-tree sweep is tens of minutes and hundreds of builds.

**Measured about that class on the committed b12 log, so a reader does not have
to run the sweep to know the rule is presently unfired:**
`bugs/sweeps/sweep-arm-12.txt` contains **zero** `not-answerable/unresolved-extern`
rows and the summary block has no such line at all — 115 `host-import`, 10
`unresolved-import`, 5 `target-limit`, and nothing else in the not-answerable
bucket. So the fix is hardening against a class that has not recurred since the
55-file family it was written for, which is a real thing to say about it and not
a reason to skip it: a misclassification that is never exercised is a rule that
will be wrong the first time it fires.

## Re-measured 2026-10-05 (`formal37-2`): the terminal MOVED, twice over, and the
## old one is gone from the message entirely

Re-ran this document's own reproduction against the real stdlib file
(`/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/std/os/env.mojo`,
arm64, `--no-prove`). The Status above says the terminal is **`binary_heap.mojo`**,
quoted as `binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares
only the generic struct template(s) BinaryHeap`. **That string is not in the
message any more.** What is there now:

```
build: env.mojo imports 'std.ffi', which cannot be built either: `dealloc` is
  called, and it is imported from `std.memory.alloc`, so the call has to bind a
  symbol `std.memory.alloc` exports. That module does not export it …
  A generic template's instantiations ARE compiled into that module's library
  when an importer asks for them (`formal/monomorph.py`), so this call is one that
  asked for none … Mojo infers a template call's type arguments, so `dealloc(…)`
  with no bracket is correct code … and this path does not infer them yet.
```

**So the family moved a whole layer, and in the direction this document wanted.**
`binary_heap.mojo` still does not build, but it no longer refuses for the reason
recorded here — built on its own it now reaches the `self.unsafe_ptr()` method
refusal, which is *deeper* in the same file:

```
build: self.unsafe_ptr() is a method call on a value, and this backend lowers
  only append, clear, close, write … and the string methods count, endswith,
  find, lstrip, startswith — the receiver is a name on this path, and
  'unsafe_ptr' is not one of those methods of those receivers …
```

Both refusals mention `unsafe_ptr`, so the Status's claim that it "is still absent
from it" is **no longer a distinguishing detail** — the family is no longer
stopped by an absence but by two *present* surfaces, each with its own message
naming its own gap.

### The new terminal is a CLAIMED doc, which is why this is a measurement and not a queue item

The new refusal names its own owner:
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`,
which **exists in this tree** (not deleted with a fix), and it states the 123
measured files the inference is worth. So a reader does not have to work out what
to do with `env.mojo`: the terminal is another worker's claim, with the count
attached.

**The closure itself is clean, which is worth recording separately** because it is
the part that has to hold for either refusal to be the *whole* story. Walked with
`formal/imports.py`'s own `resolve_module_path` against both roots:

```
closure files: 172
unresolved:    {}
binary_heap in closure:       True
std.memory.alloc in closure:  True
```

Every module `env.mojo` reaches **resolves**, including `binary_heap.mojo` and
`std.memory.alloc`. So nothing here is a missing file any more — which is exactly
the shape the host-import work closed for `version.py`, and it means this
family's remaining cost is two capability questions in the emitter, not a
transitive import problem.

### What is now true, and what a reader should not conclude

**True:** the family is not one patch from `env.mojo`; it is two *named*
capability questions, each with an owner, and the import closure is not among
them. **Not concluded:** that the 55-file family is closed. Step 1's
"`external_call` is what all 55 reach" was measured for `external_call` and is
untouched by this; nothing here re-measures the 55, and step 3 (the
`formal_sweep.py --stdlib-subtrees` re-run) is still not done — it remains the
gate runner's, for the reason this document gives: tens of minutes and hundreds
of builds.
