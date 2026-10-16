# FORMAL_sweep_singles_second_half: four of §3.2's eight remaining single-file causes are not patches, measured

**Status 2026-10-05 (`work/formal29-4`): TWO of the four rows have closed — §4's
last paragraph by a fix on this branch, and §2's by a lift that landed earlier and
is pinned in `test_formal_globals.py`.** §4 ended by naming its own residual as
"the same reader one level deeper" and recording why it was not taken
("Transitive propagation would be a real fix; it is not taken here"). It is taken
now, as a FIXPOINT over the image's names in the one reader both emitters already
ask (`formal/model.py::parameter_kinds_by_call_site`), not as a per-caller
`ValueKinds` — which is the mechanism that reader's own header warned against, and
the answer is therefore independent of which function the emitter reached first.
**§2's "static frame in `__DATA`" also exists** (`GlobalSlot`'s `("frame", …)`
initializer plus `formal/build.py`'s `module_frame_slot_holders` edge), so the
holder disagreement this section measures is gone and `module_loader.py` stops one
level later, at another claim's row (§2a has the measurements, both
architectures). **The row count does not move: 0 of the 20 files reach `pass`,
because the next wall is an f-string literal — and §1 and §3 are refusals that are
RIGHT whose remedies are both projects.**

**Status: filed 2026-10-03 from the sweep map
the `b7` round of `bugs/FORMAL_sweep_work_map.md` §3.2/§5, claim
`sweep12:singles-b`. Three of the eight rows in the second half of that list
were fixed on `work/formal12-singles-b` (the repetition one as a root-cause fix
that also removed a SIGSEGV, the class-constant-reference one, and the
`test_llm/dumb_gemm.mojo` row's true blocker); this file is the five that were
NOT, each with the message measured on this tree, whether the refusal is
CORRECT, and what the next step would be.**

**Re-measured 2026-10-03 (`work/formal14-sweep-b8`, claim `sweep14:sweep-b8`),
and the file is one row smaller than its title says.** §2's row turned out to be
**20 files and unowned**, with its next wall measured (`os.environ`), so it is now
a paragraph with a measurement rather than "ANOTHER LANE'S"; the citation §2 carried
pointed at a doc deleted with its fix, and that dangling reference is gone; and
§6's `stdlib_core.mojo` row is **closed** — the file builds and passes on both
architectures in `bugs/sweeps/sweep-arm-8.txt` — so the section and its citation are
retired. **Four rows remained, and one more is now closed too:** §2's
"one parameter, two kinds of value" row is **FIXED** — `fd396597` landed the
static `__DATA` frame this file said was "not started", so the section is retired
below (`work/formal115-docs`, 2026-10-07). **Three rows remain, none of them a
patch.**

The measurement is one build per row with the row's own file, arm64, and the
x86-64 build where the row could plausibly differ:

    $ export PATH=/opt/homebrew/bin:$PATH
    $ python3 fire.py build --formal --no-prove -o /tmp/x <the file>

## 1. `field(default_factory=F)` — `formal/x86_64_decode.py` — CORRECT refusal

    build: Insn.extra: `field(default_factory=F)` calls F once per instance, and
    this path has nowhere to keep the result: a module-level name has no storage
    (formal/model.py's no-storage rule, the same one that refuses a module-level
    list), and a local built in the constructor's frame is reclaimed when the
    constructor returns.

The refusal is right and its two options are both large, which is why this is a
doc rather than a change: (a) give the per-instance value a slot in the frame
the constructor allocates — a frame-layout change shared by both backends and
the ~40 passing Lean proofs; or (b) read the field through the class-level
default when the instance slot is empty — which contradicts the
read-before-store stance this backend takes everywhere else. Already measured,
with the same reasoning, in the `repo-c` round of `bugs/FORMAL_sweep_work_map.md`
§4.4. **Not the sweep's next step, and not cheap either way.**

**CORRECTED 2026-10-12 (`work/formal313-docs`): the refusal is unchanged and
still CORRECT, but `formal/x86_64_decode.py` no longer exhibits it, so the
`build:` line above cannot be reproduced from this section's file.** Commit
`1613607b` ("`formal/x86_64_decode.py`: two declarations the formal backend
cannot build") DELETED `Insn.extra: field(default_factory=dict)` because nothing
in the repository read or wrote it, so this file's first refusal is now a
different construct entirely — measured, both architectures:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/x86dec formal/x86_64_decode.py
build: an f-string literal on line 133 is refused on this path: its value is its
INTERPOLATED text, and this path has no buffer to compose one in. …
```

which is `FORMAL_string_composition_has_no_buffer`'s row, not this one. **The
construct is still refused** by `formal/dataclass_transform.py:472-474` and is
still pinned — `test_refusal_taxonomy.py`'s
"`` `field(default_factory=F)`: nowhere to keep a per-instance value ``" row and
`tools/formal_sweep_causes.py`'s cause table both name it verbatim — so the row
is a live "correct refusal" and only its EXAMPLE moved. A reader re-deriving
§1 from the file this section names gets a message about f-strings; the next
worker should reproduce it from the taxonomy row (or a fresh two-line dataclass)
rather than from `formal/x86_64_decode.py`.

## 2. "one parameter, two kinds of value" — `module_loader.py` — FIXED 2026-10-03, so this section is retired

**The row is FIXED**, by `fd396597` ("formal: a module-level struct value is a
frame in the IMAGE, not a body block"), which is exactly the change this section
described as `What would make it work … **Not started here.**` — the new
`GlobalSlot` `init` kind `("frame", struct, words)`, laid out in `__DATA`, with
`module_frame_slot_initializer` deciding when it is expressible. The commit moved
the STORAGE rather than lifting the refusal, which is what this section's own
paragraph ("Teaching the holder fixpoint … would convert this refusal into a
SIGSEGV") correctly warned against.

Measured 2026-10-07, both architectures, a module-level `Loader()` with a method
reached through BOTH `self` and the global:

```python
struct Loader:
    var a: Int = 0
    var b: Int = 0
    var c: Int = 0
    fn load(self, name: Int) -> Int:
        return self.a + name
    fn again(self, name: Int) -> Int:
        return self.load(name) + self.b + self.c
_ml = Loader()
def main(n: Int) -> Int:
    return _ml.load(1) + _ml.again(2)
```

`Built: … [arm64/macho]` and `… [x86_64/macho]`, both run and answer `3`, the
same as `fire.py run` — the SIGSEGV this section recorded is gone. The
`two-kinds-of-value` message no longer appears for this shape.

**The row's next wall is not this row and is not stated here any more.**
`module_loader.py` now stops earlier than the two-kinds refusal, at the f-string
on its line 108 (`FORMAL_string_composition_has_no_buffer`); behind that is the
`os.path` read out of the imported `os` (`FORMAL_module_state_no_storage`). The
per-file ranking this section carried is the `b8`/`b9` rounds of
`bugs/FORMAL_sweep_work_map.md`, which supersede it.

### 2a. Status 2026-10-05 (`work/formal29-4`): the next step above LANDED, and this
### row's refusal is GONE — measured on both architectures

**The paragraph above is the record of what was asked for, and every part of the
ask is now in the tree.** The `GlobalSlot` `init` kind is `("frame", struct, w)`
(`formal/model.py`), `module_frame_slot_initializer` produces it,
`build_data_image`'s `("blob", "frame")` branch lays the words out with the fixup
that makes the slot word an address, and the holder seeding that makes it safe is
`formal/build.py`'s `module_frame_slot_holders` edge — whose own comment names
this exact case ("`_check_holder_agreements` would stop refusing
`ModuleLoader_load_module(self, …)` beside `ModuleLoader_load_module(_module_loader, …)`
… **This is why the fix is a new `init` kind in `build_data_image` rather than a
rule in this analysis**: the holder tables answer 'is this word an address', and
the answer is only safe if something guarantees the address outlives every
reader"). The lifetime objection in the paragraph above is therefore answered, not
worked around: the frame is in `__DATA` and lives as long as the process.

Measured on this tree, both architectures, byte-identical output:

```python
class Pair:
    var a: Int
    var b: String
    def __init__(self):
        self.a = 3
        self.b = "x"
    def get(self) -> Int:
        return self.a
P = Pair()
def direct(p):
    return p.get()
def via_global() -> Int:
    return P.get()
def main(n):
    var q = Pair()
    printf("%d %d\n", direct(q), via_global())
```

```
arm64  3 3  exit 0        x86_64  3 3  exit 0
```

`direct(q)` hands the method a LIVE frame and `P.get()` hands it the image's, and
**that is the disagreement this row is named for**: before the lift it was refused
with "One parameter, two kinds of value", and the refusal's own measurement (that
the two-call-site shape "builds, runs, and dies with SIGSEGV") is why it was right
to refuse rather than to assume. Three is `self.a`'s value read both ways.

**This row was already pinned and its pin is the reason the answer was findable
without re-deriving it**: `test_formal_globals.py`'s `FRAME_CASES` carries both
halves — `frame_global_read_and_mutated_from_functions` is the two-spelling
disagreement ("`_g.first()` hands a LIVE frame and `_g.first()` hands the image's
— and it is also the only thing here that would print a wrong number if the frame
were the body's") and `frame_global_with_an_init_assigned_field` is the
`ModuleLoader` shape ("`_bump` is a free function rather than a method on purpose:
it is the `ModuleLoader_load_module(_module_loader, …)` call site"). Both run
against `fire.py run` as well as both images, and `FRAME_REFUSALS` keeps the two
inputs the lift must NOT take — a field computed by a call, and a global a
function writes through `global` — with the needle **`One parameter, two kinds of
value`**, so the refusal this section documents is still pinned as a refusal
where it belongs. **Nothing needed a new test, and that is the finding: the fix
and its pin were both landed and this section is the only thing still describing
the row as open.**

**And the 20 files moved, which is the number this section exists to report.**
`module_loader.py` no longer stops at the holder disagreement; it stops one level
later, and the file it stops at belongs to another claim:

```
$ python3 fire.py build --formal --no-prove -o .tmp/ml module_loader.py
build: an f-string literal on line 108 is refused on this path: … Made of 2
field(s) — `checkout`, `rel` …                       # both architectures, identical

$ … tools/compile_one.py                              # one of the 19 dependents
build: compile_one.py imports 'module_loader', which cannot be built either:
module_loader.py: an f-string literal on line 108 …
```

The f-string row is `bugs/FORMAL_an_f_string_literal_is_refused_and_is_the_first_
refusal_in_x86_64_decode.md` (`formal59-docs`), so **the 20 files are still 0 to
`pass` and the count this section reports has not moved** — which is the same
answer it gave for `os.environ` one round earlier, arrived at from the other side.
What has moved is the WALL: this row no longer has a next step of its own, and a
reader who wants the 20 files should start at the f-string rather than at
`_check_one_callee`.

## 3. a slot holding a frame address rebound — `regex_compile.py` — CORRECT refusal

    build: atom is assigned _Parser_parse_atom(self) in _Parser_parse_repeat(),
    and atom also holds the address of a Repeat frame — Repeat() binds it to
    one, and this path has no way to say that a later binding changes what the
    name is. … measured, the program builds, runs, and dies with SIGSEGV (exit
    139) on both architectures.

The refusal names the three representations a name may have (a construction of a
framed struct, a copy of another holder, a parameter of a method of a framed
struct) and `atom` is none of them. Same conclusion, same three options, in
the `repo-c` round of `bugs/FORMAL_sweep_work_map.md` §4.5. **A source change to
`regex_compile.py` would be a workaround for a value-model gap; the gap is the
work.**

## 4. `len()` of a value classified as an int — `unescape_c.py` — FIXED, and the
## map's guess about it was refuted by a measurement

`unescape_c.py` does not reach this row on this tree: it stops earlier at

    build: __module_body__: sys.stdin reads 'stdin' out of the imported module
    `sys`, and a module is not a value this path can place …

which is `FORMAL_module_state_no_storage`'s row (`formal8-7-r2`). **The `len(s)`
refusal this section used to carry behind it is GONE**, and the reproducer the
section itself quotes is the row that says so:

```python
def unescape(s):
    var n = 0
    while n < len(s):
        n = n + 1
    return n
```

    build: len(s) is len() of a value classified as 'int', and an integer has
    no length: …                     # what this section recorded

    Built: … [arm64/macho]           # what it says now, on BOTH architectures
    Built: … [x86_64/macho]

The cause is `model.string_parameters_by_call_site`, the same reader
`ValueKinds`' `param_kind` hook uses: an unannotated parameter takes the kind of
its call site's argument, agreed over every site of the name in the image, so
`unescape("abc")` classifies `s` as a string and `len(s)` is a `strlen`. It is
the mechanism `bugs/FORMAL_string_value_model.md` records as landing on
2026-10-03 for the truthiness case, and this section is where the `len()` reader
was never re-measured after it.

**Pinned by `test_formal_run.py::BOTH_ARCH_CASES::len_of_an_unannotated_parameter_from_a_string_literal`**,
which builds and runs `count("a")`, `count("abcd")` and `count("")` on **both**
architectures and requires `1 4 0`. It is in that group rather than beside the
truthiness rows because the kind table is one `formal/model.py` reader both
emitters consult — the two machines cannot disagree about it — so the row is
about the reader and not about an instruction.

**And the map's guess about this row stays refuted, which is the half of this
section still worth carrying.** `…_repo-c.md` §4.1 says "this one is a case
where `s` *has* an annotation the analysis is not reading, or where the value
flows from a call the analysis cannot follow" — `def unescape(s)` has NO
annotation, so the first half is false, and there is no annotation to read.
What was left was a real inference: the only evidence that `s` holds text was
its USES (`s[i] == '\\'`, `result.append(s[i])`). **That inference is now made,
and from the CALL SITE rather than from the uses** — the better of the two
answers, and the one this path can reach without type inference.

**One shape beside it is still refused, and it is the same reader one level
deeper** — named so that a reader does not take this section as "the parameter
kind is settled":

```python
def helper(t):
    return len(t)

def outer(s):
    return helper(s)

def main(n):
    return outer("qq")     # len(t) is refused, identically on both machines
```

`string_parameters_by_call_site` reads the argument's own SHAPE, and a bare name
says nothing, so `helper`'s `t` claims no kind. Annotating `outer`'s `s` does
not help; annotating `helper`'s `t` does. **That is the reader's documented
limitation and not a gap in it** — `formal/model.py` lists it ("the CALLER's
`ValueKinds`, so `f(some_local)` where `some_local` holds a string is still
unclassified … reading it would mean building a ValueKinds per caller from
inside the callee's, which is the recursion `func_kind` already guards with a
depth limit"), for the reason it gives: a kind that depends on which function
the emitter reached first decides whether `printf("%s", s)` formats a pointer
or bytes. Transitive propagation would be a real fix; it is not taken here.

**§4a below is that fix, and it closes this paragraph — annotating `outer`'s `s`
now does help, and so does annotating nothing at all.** The text above is left as
the record of the measurement, including the mechanism it warned against; what
changed is that the propagation is a fixpoint in the shared table rather than a
per-caller `ValueKinds`, which is what makes it order-independent.

## 4a. Status 2026-10-05 (`work/formal29-4`): §4's residual is CLOSED, by the
## reader itself rather than by a caller-side lookup

The paragraph above is the record of what was measured, and its last sentence —
"Transitive propagation would be a real fix; it is not taken here" — is what this
update takes. All three shapes it names now build and answer CPython on **both**
architectures (`fire.py build --formal --no-prove`, the same command §4 quotes):

```python
def size(t):                 # §4's reproducer, verbatim apart from the name
    return len(t)
def outer(s):
    return size(s)
def main(n):
    printf("A %d", outer("qq"))
    return 0
```

```
arm64  A 2  exit 0        x86_64  A 2  exit 0        # was: build: len(t) is len()
                                                    # of a value classified as 'int'
```

`2` is `len("qq")` and **not** what a one-byte read of the pointer's address
says, so a callee that loaded the wrong width is caught rather than agreeing with
itself.

**The mechanism is a FIXPOINT in the one reader both backends already consult,
and NOT the per-caller `ValueKinds` the reader's own header warned about.**
`formal/model.py::parameter_kinds_by_call_site` now treats a bare-name argument as
a REFERENCE to that name in the caller instead of as an expression with no shape,
and resolves it against three pieces of evidence — the name's own call sites when
it is a parameter, its declared annotation when it has one, and the statements
that bind it (`_binding_values`) when it is a local. Every resolution is
memoised over the image's `(function, name)` pairs, so the answer does not
depend on which function the emitter reached first, which is the whole of the
objection the header raised; a cycle claims nothing and a chain past
`MAX_PARAMETER_KIND_DEPTH` claims nothing, so both are refusals rather than a
recursion. **The disagreement rule did not move, and that is the half worth
noticing**: one parameter handed a string at one call site and a list at another
is still a word and is still refused with the same sentence, pinned as
`refuse_parameter_kind_where_two_call_sites_disagree`.

**Three things this update had to answer that the paragraph above did not ask
about**, and each is a decision rather than an omission:

  * **A bare blob prefix and an element kind are not a disagreement.** With an
    annotation in the evidence, one site can state `list:int` (a literal) while
    another states `list` (a `: List[Int]` the reader cannot see inside), and
    unanimity over the two would have vetoed the parameter on a program that is
    perfectly ordinary. `_agreed_parameter_kind` keeps the representation and
    withholds the element kind when the sites disagree about the elements —
    the same direction as `_parameter_argument_shape`'s own bare prefix, and the
    one that makes `subscript_element_kind` refuse rather than guess. Pinned as
    `parameter_kind_merges_a_bare_blob_with_an_element_kind`.
  * **A body rebinding of a PARAMETER is not evidence** about what the caller
    passes. `var u = t + 1` inside the callee writes a word this reader cannot
    state, and unioning the callee's own bindings into its parameter row would
    have retracted the kind of every call site that hands it a string. A local's
    bindings ARE evidence; a parameter's are not.
  * **`printf("%s", s)` was the risk the paragraph named, so it is a case.**
    `printf_percent_s_of_a_parameter_reached_through_a_name` prints the TEXT and
    not an address, on both machines — the wrong branch here would be a pointer
    formatted as a number rather than a refusal, which is the failure mode the
    header predicted and the reason the fix was not taken the first time.

Six answered cases and two refusals in `test_formal_run.py`'s `BOTH_ARCH_CASES`
(that group because the cause is one `formal/model.py` reader both emitters
consult, so the two machines cannot disagree about it): the reproducer, a local
one level deeper, a TWO-HOP chain through two names, the annotation, the bare
blob merge, and the `printf`; then the disagreement veto and a `ping`/`pong`
cycle, which is pinned as a refusal because the alternative to the recursion
guard is a hang.

**What this does NOT do**: it changes no representation, closes no file, and
refuses nothing new. §1, §2 and §3 of this document are untouched and §2's
20-file row still ends at `os.environ` (`FORMAL_module_state_no_storage`'s
`formal71-docs`), which is the measurement §2 gives and the reason the count of
files this row moves stays **0**.

### 4a.1 That nothing else moved, which is the evidence and not the new cases

The new cases passing is not the evidence — `parameter_kinds_by_call_site` runs
for every function of every image, so the question is whether anything ELSE
changed. `tools/formal_proof_breadth.py --no-check --arch both`, the same
sample on the same tree, with `formal/model.py` before and after (the file
swapped in place, both ledgers kept):

```
over the 208 items the two runs have in COMMON (the sample itself moves — the
census doc §0.6.1's own warning, because this commit edited a repository file
the selector reads):

class        before   after        detail changed: 0     proof_lines changed: 0
codegen-refused    82      74
proof-emitted      97      97
proof-refused      17      17
refused-builtin    12      12
```

**97 of those are `proof-emitted`, and each row carries the line count of the
proof the generator wrote** — so "the detail did not change" is 97 generated
proofs of identical length, which is a far stronger statement than a class
column. The eight class changes the census reports on the FULL sample are all
`refused-harness-call`, which is the sibling commit's census change and not this
one; §0.10 of `FORMAL_proof_coverage_census_2026-10-03.md` is where that is
written down.

The census is the instrument this document's own sibling is built on, it needs no
Lean, and it runs in two seconds at 0.3 GB.

## 5. a method call on a value receiver — `std/format/repr.mojo`, `std/utils/_serialize.mojo` — needs a repr model, as the map says

    build: value.write_repr_to() is a method call on a value, and this backend
    lowers only append, close, write (on a file descriptor) and the string
    methods count, endswith, find, lstrip, startswith — the receiver is a name
    on this path, and 'write_repr_to' is not one of those methods of those
    receivers, so adding it to either table would be a guess about what it means
    on 'int'. Refused rather than emitted as a call to a symbol spelled
    'value.write_repr_to', which is what this used to do: the image built and
    then died in the loader.

Two DIFFERENT methods on two different receivers (`write_repr_to` takes a
writer object; `p.unsafe_load()` is a pointer load), so they are one row and not
one fix. The map's own next step is right: a `repr` model for a non-string
receiver, which means deciding what `repr` means for a struct whose value is a
frame address — the same question `FORMAL_pointer_value_model.md` and
`FORMAL_frame_receiver_handoff.md` each answer for their own receiver kind, and
neither of those is a `repr`. **Also note both files are stdlib, so the probe
is a stdlib edit and not makeable from a repository worktree.**

## 6. `stdlib_core.mojo`'s `StringRef` — FIXED 2026-10-03, so this section is gone

`stdlib_core.mojo` **builds and PASSES on both architectures** in the 2026-10-03
sweep (`bugs/sweeps/sweep-arm-8.txt`, `bugs/sweeps/sweep-x86-8.txt`; it is one of
the two paths that left the non-pass set against `-7`, where it read
`constructing StringRef has no representation on this path`). The doc this section
used to point at was deleted with its fix, in this project's rule for a fixed bug,
so **the row and its citation are both retired here** rather than left standing as a
measurement of something that no longer refuses. The remaining `StringRef` question
is a value-model one and belongs to whoever next needs it, not to a section whose
premise has stopped being true.

## What this file is for

A sweep row whose next step is "measure it first" should not be measured twice,
and the messages above are what future sessions would otherwise re-derive. Two of
them (`default_factory`, the frame rebind) are refusals that are RIGHT and whose
remedies are both projects; one (`len` of an int) has a wrong guess recorded about
it in another document; one (`two kinds of value`) is 20 files with its next wall
measured and its write set unowned. **None of the four is a patch that was
available, and saying so is the finding.** The fifth (`StringRef`) is fixed and its
section is retired above.

**§4a adds the sixth thing this file measured, which is a patch that WAS
available and was not taken for a stated reason**: the reader's own documented
limitation, "the CALLER's `ValueKinds`", was a mechanism question and not a
capability question. And **§2a records a row that was already fixed and pinned**,
which is the other half of what a stale measurement costs a reader. So the
headline stands — four rows, none of them a patch available at the time — with the
count of files this document's rows move still **0**, which §2a and §4a each say
in the same words their predecessors used, and with the two rows that are now
closed named rather than left as the next step.