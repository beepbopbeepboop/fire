# FORMAL_sweep_singles_second_half: four of §3.2's eight remaining single-file causes are not patches, measured

**Status: filed 2026-10-03 from the sweep map
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.2/§5, claim
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
retired. **Four rows remain, none of them a patch.**

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
with the same reasoning, in `bugs/FORMAL_sweep_work_map_2026-10-02_repo-c.md`
§4.4. **Not the sweep's next step, and not cheap either way.**

## 2. "one parameter, two kinds of value" — `module_loader.py` — 20 FILES, UNOWNED, and its next wall is measured

    build: ModuleLoader_load_module() takes a ModuleLoader receiver at argument 0
    — 'self' — at ModuleLoader_load_module(self, module_name) here, and
    something that is not a frame address at
    ModuleLoader_load_module(_module_loader, module_name). One parameter, two
    kinds of value: … Measured on both architectures with nothing lifted: the
    two-call-site shape builds, runs, and dies with SIGSEGV (exit 139).

**Re-measured 2026-10-03 (`work/formal14-sweep-b8`, claim `sweep14:sweep-b8`). Three
things in the paragraph above are now stale and the row is bigger than one file.**

**The cited doc is GONE.** This section used to point at
`FORMAL_frame_by_value_ceiling_zero.md` in `bugs/`, and that file does not exist on
this tree — its bug was fixed and the doc deleted with it, which is this project's
rule for a fixed bug. (Named without the `bugs/` prefix on purpose:
`tools/dangling_doc_refs.py` counts any citation of a doc that is not there, and
re-introducing one to say it is missing would put this file back on its own census.)
So the mechanism's record is this section and
`bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §4.2, and **the dangling citation was
the defect `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md` exists to
catch.** `formal10-3` has also exited, so "ANOTHER LANE'S" in this section's heading
was true when written and is false now.

**The row is 20 files, not one.** `module_loader.py` blocks **19** dependents plus
itself, on both architectures, byte-identically, and **0 of the 19 name anything it
declares** — they are refused for having imported it. It is the fourth-largest cause
row in `bugs/sweeps/sweep-arm-8.txt` and **no live worker holds it**
(`python3 tools/control.py claims`: no `FORMAL_*` doc for it is claimed).

**Its next wall is measured, and it is not this row.** With
`_check_one_callee`'s disagreement refusal lifted and nothing else changed
(`.tmp/probe_after_two_kinds.py`, which prints each refusal it lifted so the number
is not a guess), `module_loader.py` refuses at

    build: _find_stdlib_path: os.environ reads 'environ' out of the imported module
    `os`, and a module is not a value this path can place …

which is the **12-file** "a module's ATTRIBUTE read as a value" row, whose doc
(`bugs/FORMAL_module_state_no_storage.md` §(4)) makes it an exported slot or a
command line. **So fixing this row moves 0 of the 20.** That is the same lesson
`bugs/FORMAL_binary_heap_mojo_after_the_len_value.md` records for the 165-file row,
and the reason this is a measurement rather than a patch.

**The root cause, stated so the obvious fix is visibly wrong.** `_module_loader =
ModuleLoader()` at module level puts the address of a **three-field frame** in a
`__DATA` slot. Since the load-time initializer landed, the module body runs at load,
builds the three `dict` fields in **its own** frame and stores that frame's address —
so `self` (line 1011) is a live frame and `_module_loader` (line 1063) is an address
into a frame that has already been returned from. **Teaching the holder fixpoint
that a `__DATA` slot of framed-struct type is a frame address would convert this
refusal into a SIGSEGV**, which is why it has not been done and why the
disagreement check is right to fire.

What would make it work: a **static frame in `__DATA`** for a module-level global
whose value is a construction of a multi-field struct — a new `GlobalSlot` `init`
kind plus the field layout in `build_data_image` (shared by both backends, and its
`nested_element` machinery is the precedent). Nothing in either emitter moves,
because the read is already a load from the slot. `ModuleLoader`'s three fields are
all empty dicts, so it is expressible; a general struct needs the "every field is
itself a static initializer" rule, which is `static_initializer_refusal_reason`'s
existing `computed_element` boundary moved one level out. **Not started here.**

## 3. a slot holding a frame address rebound — `regex_compile.py` — CORRECT refusal

    build: atom is assigned _Parser_parse_atom(self) in _Parser_parse_repeat(),
    and atom also holds the address of a Repeat frame — Repeat() binds it to
    one, and this path has no way to say that a later binding changes what the
    name is. … measured, the program builds, runs, and dies with SIGSEGV (exit
    139) on both architectures.

The refusal names the three representations a name may have (a construction of a
framed struct, a copy of another holder, a parameter of a method of a framed
struct) and `atom` is none of them. Same conclusion, same three options, in
`bugs/FORMAL_sweep_work_map_2026-10-02_repo-c.md` §4.5. **A source change to
`regex_compile.py` would be a workaround for a value-model gap; the gap is the
work.**

## 4. `len()` of a value classified as an int — `unescape_c.py` — a value-model question, and the file is behind another refusal

`unescape_c.py` does not reach this row on this tree: it stops earlier at

    build: __module_body__: sys.stdin reads 'stdin' out of the imported module
    `sys`, and a module is not a value this path can place …

which is `FORMAL_module_state_no_storage`'s row (`formal8-7-r2`). The `len(s)`
refusal is still there behind it, and a four-line reproducer reaches it:

```python
def unescape(s):
    var n = 0
    while n < len(s):
        n = n + 1
    return n
```

    build: len(s) is len() of a value classified as 'int', and an integer has no
    length: there is no count to read at offset 0, and the word there is the
    integer itself. …

identical on x86-64. **The map's guess about this row is refuted by
measurement**: `…_repo-c.md` §4.1 says "this one is a case where `s` *has* an
annotation the analysis is not reading, or where the value flows from a call the
analysis cannot follow" — `def unescape_c(s)` has NO annotation, so the first
half is false and there is no annotation to read. What is left is a real
inference: the only evidence that `s` holds text is its USES (`s[i] == '\\'`,
`result.append(s[i])`), and deriving a parameter's kind from its uses is type
inference, not a missing hook. **A note in `repo-c.md` §4.1 would save the next
reader the probe.**

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