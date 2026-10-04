# FORMAL_sweep_work_map_2026-10-02_repo-c: the repo's own `n-z`, `tools/` and `formal/`

**Slice:** `repo-c`. 211 files — the repo's own root `*.py` whose basenames
start `n`–`z` (150 of 181), plus every `tools/*.py` (40) and every
`formal/*.py` (21). Not `bugs/`, not `doc/`, not the stdlib: those are
`repo-a`/`repo-b` and `std-*`.

```
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 4 --no-stdlib -t 60 --allow-concurrent \
    <the 211 paths>
```

arm64 (the slice does not say x86), `--no-stdlib`, `-j 4`, `-t 60`,
`--allow-concurrent` because four other `formal4-sweep-*` workers were sweeping
the same architecture at the same time — see §6.

**Three fixes landed on this branch, and they are the first two rows of §3
below read backwards.** The headline: `formal/hostmods/` went from 14/15 to
**16/16**, and `formal/arm64.py` moved from a codegen gap in one method to a
codegen gap in one construct.

## 1. The run

| | |
|---|---|
| files | 211 |
| pass | **4** |
| codegen | 13 |
| codegen/dependency | 2 |
| not-answerable/host-import | 144 |
| not-answerable/unresolved-import | 1 (`pytest`) |
| tool | **47** |
| codegen coverage | 4/19 = **21.1 %** |
| CAS | 142 hit / 69 miss / 0 not cached |
| peak RSS, whole run | 0.5 GB across 10 procs (ceiling 8 GB) |
| wall clock | ~26 min at `-j 4` |
| log | `.tmp/sweep-final.txt` (this worktree) |

**The 47 `tool` rows are all `-t 60` timeouts and nothing else** — 9 of them
are the giant `formal/*.py` backend files (`build.py` 623 KB, `model.py` 1 MB,
`arm64_codegen.py` 432 KB, `arm64_proof_gen.py` 436 KB), and the rest are
`test_*.py` that each spawn many builds (`test_struct_formal.py`,
`test_formal_read_before_store.py` are two of them, and both of those PASS when
run directly — 168/168 and 66/66). So **the denominator of 19 is a floor set by
`-t`, not by the backend**, and the coverage number says as little about the
backend as a large `tool` count says about the source. A `-t 600` run over the
47 would turn most of them into verdicts; it is not free and it is the
integrator's, not this worker's.

**The 144 host-imports are not findings and are not in any rate.** By module:
`subprocess` x63, `importlib` x16, `collections` x5, `concurrent.futures` x5,
`glob` x5, `shutil` x5, `types` x5, `ctypes` x4, `enum` x4, `fcntl` x4,
`zlib` x4, … The tool splits them itself: **24 import a module a Mojo-side
implementation could in principle provide** (`collections`, `contextlib`,
`copy`, `enum`, `functools`, `glob`, `math`, `types`) and 120 need a host
process, an embedded interpreter or a kernel object this image does not have.

The shape of this slice is therefore: **the repo's own tooling is not a formal
corpus.** 144 of 211 are one line repeated (`subprocess`), and 47 more reach no
verdict at all. The 19 that could answer are 13 `formal/` files, 5 `tools/`
files and 1 root file. Anyone reading a coverage number off this slice should
read it as "the 19 that import only Mojo-side modules", which is a much more
useful denominator than 211 — and it is a much more useful denominator than the
623-file sweeps use, because here it selects the files that are actually about
the compiler.

## 2. Ranked causes (`tools/formal_sweep_causes.py --min 1`)

15 of 15 `codegen`/`codegen/dependency` lines accounted for, in 8 causes of 8.
`FILES BLOCKED` is an UPPER BOUND: a file's terminal cause is the first refusal
the walk reaches, so fixing one usually moves the file to the next with the count
unchanged. The three rows that moved this session are §3.

| files | in-file | cause | example | next step |
|---|---|---|---|---|
| 3 | 1 | **`len()` of a value the source does not classify** — `len(self.sections['text'])`, one construct | `formal/arm64.py` (and `formal/macho.py`, `formal/macho_linker.py` behind it) | §4.1 |
| 3 | 3 | a module-global name has **no storage** (`ELF_MAGIC`, `HERE`, `REPO`) | `formal/elf.py`, `tools/bootstrap_verify.py` | §4.2 |
| 3 | 3 | a module's **ATTRIBUTE read as a value**, across a dylib (`sys.argv` x3) | `tools/ci_line.py`, `tools/detach.py`, `tools/audit_determinism.py` | §4.3 |
| 2 | 2 | a module-global **container has storage but no initializer** (`MOVES`, `EXTRACT`) | `tools/wave1_move_shared.py`, `tools/wave2_extract_shared.py` | §4.2 |
| 1 | 1 | `field(default_factory=F)`: nowhere to keep a per-instance value | `formal/x86_64_decode.py` | §4.4 |
| 1 | 1 | a **frame-holder slot rebound** by a later assignment | `regex_compile.py` | §4.5 |
| 1 | 1 | a linked module **exports no such name** (`sys.exit`) | `tools/detrace_diff.py` | §4.3 |
| 1 | 1 | `len()` of a value classified as `int` | `unescape_c.py` | §4.1 |

**Read as groups, not as eight things.** Three of the eight rows are ONE
missing capability with three spellings — a value this path cannot name
(§4.1, §4.2, §4.3 together are 9 of the 15 files). One is a dataclass feature
with a documented refusal (§4.4). One is a *correct* refusal of ordinary Python
(§4.5). So the real menu is: **one value-model project, one module-global
project, one hostmod-attribute project, one dataclass project, and one file's
own source.**

## 3. What landed, and the A/B that says it was worth it

Three commits. The measurement is one tool, one tree, one file list, run twice
with the two trees of source swapped in and out of the worktree.

### 3.1 `formal/model.py::_build_cfg` invented an edge the language does not have

`entry.succs += run(body, [], [entry.index])`. `run` returns the blocks that
**fall off the end** of a run — what a caller inside the body needs (they are its
join's predecessors) and what the top level has no use for, because control
leaves the function. Attaching it to `entry` invented an edge from the entry
block, whose OUT set is `seed` and nothing else, to every block the function can
end in; `_definitely_stored` intersects predecessors, so the entry's set erased
everything the body had stored.

The shape that reached the corpus is a **trailing `for`**, because a loop's
latch is a fall-through whenever the loop is the last statement. Every read of a
loop target inside the body of a trailing loop was refused. Measured on this
slice, two modules died on it:

* `formal/arm64.py`'s `Assembler.resolve_extern` — `for sym_name, pos,
  instr_len, kind in self.extern_refs:` then `if sym_name not in target_addrs:`,
  refused as *"'sym_name' is read at line 775 before anything in this function
  stores it"* for a program CPython runs;
* `formal/hostmods/re.mojo`'s `_p_alt` — the same shape, `pend` at line 1401.

`re.mojo` is the load-bearing one: it is imported by three files in this slice,
so its refusal was the terminal cause on all three.

**Every existing case missed it because they all end in `return`.** `return` has
no successor, `run` returns `[]`, and there is no edge to invent — which is why a
table of 56 shapes in `test_formal_read_before_store.py` stayed green.

### 3.2 `formal/hostmods/struct.mojo`: `pack`'s five value slots were REQUIRED

`def pack(fmt: String, v0, v1, v2, v3, v4)` — six required arguments. This ABI
has no `*args`, so a six-wide signature is the only way to spell "up to five
values", and `bind_call_arguments`' arity check runs **at the call site**:
`struct.pack('<I', insn)` is 2 of 6 and was refused with `missing required
argument 'v1'` before the body ever ran.

This is the shape the corpus is written in: `formal/x86_64.py` alone has fifteen
`struct.pack("<i", x)` sites, `formal/macho.py` and `formal/arm64.py` more, and
`formal/x86_64_decode.py` reads with `struct.unpack_from`. So `formal/` was
unbuildable behind one declaration, and `test_struct_formal.py` had been padding
every call out to `pack("<I", 7, 0, 0, 0, 0)` to get past it — a shape no caller
writes, which hid the gap rather than pinning it.

The fill is `0`, for the reason `pack_into`'s own three slots give two functions
up in the same file: the loop only touches `v0 .. _nvalues(fmt)-1`, so a slot
past the format's value count is never read.

### 3.3 `test_formal_run.py`: one stale expectation, now CPython's answer

Not a backend change — the module-global `__DATA` slot landed
(`formal-module-globals`) and `formal-module-globals`' own gate
(`writable = declared_globals & assigned - set(M.module_slots() or ())`) stopped
reporting a name that has a slot, but this row was left behind.
`TEST_a_mutated_module_global_is_refused_is_stale_after_the_slot_landed`
recorded it as stale on `master` too and named two consistent outcomes; this
took outcome (1) and asserts the measured answer: **exit 12 on arm64 AND on
x86-64**, which is CPython's.

### 3.4 The A/B

Same 15 files (every file in §2), same tool, same tree, the two source trees
swapped in and out of the worktree:

| | pre | post |
|---|---|---|
| pass | 0 | 0 |
| codegen | 10 | **13** |
| codegen/dependency | 5 | **2** |
| coverage | 0/15 | 0/15 |

and `formal/hostmods/`:

| | pre | post |
|---|---|---|
| pass | 14 | **16** |
| codegen | 1 (`re.mojo`) | 0 |
| tool | 1 (`os/__init__.mojo`, foreign-arch dylib probe) | 0 |
| coverage | 14/15 = 93.3 % | **16/16 = 100 %** |

**Read the 0/15 honestly: no file reached `pass`, and the coverage rate did not
move.** What moved is *depth*: the three files that were blocked by another
module's refusal now report a refusal in themselves (`re.mojo`'s importers), and
`formal/arm64.py` went from "one method, one bug class" to "one construct, one
missing capability" (§4.1). `formal/hostmods/` reaching 16/16 is the number that
says the two fixes were load-bearing rather than cosmetic: `re.mojo` and
`struct.mojo` are the two modules half this slice's `formal/` files import, and
both were unbuildable for unrelated reasons before.

`test_formal_run.py`, the 581-case build-and-run floor that every change to the
shared model is measured against: **PASS=580 FAIL=1 before (the stale row),
PASS=581 FAIL=0 after.**

### 3.5 Every narrow suite that covers the changed code, on this branch

| suite | result |
|---|---|
| `python3 test_formal_read_before_store.py` | PASS=66 FAIL=0 (56 before; +10 new rows) |
| `python3 test_struct_formal.py` | 168/168 (148 before; +10 cases in one new test) |
| `python3 test_formal_run.py` | PASS=581 FAIL=0 |
| `python3 test_formal_globals.py` | PASS=19 FAIL=0 (the module-global capability the row in §3.3 belongs to) |
| `python3 test_formal_specialization.py` | PASS=7 FAIL=0 (named by `_unstored_read`'s own comment as the case a generic's parameters must not be refused for) |
| `formal_sweep.py formal/hostmods` | 16 files, 16 pass, 100 % |

**No gate was run** — this is a light worker and `make gate` is the integrator's
over everyone's work. `formal/model.py` is shared by every formal build, so the
integrator's `gate` is the thing that has to say these three fixes are safe
across the 37 other jobs in the `proofs` bucket; the six rows above are the
narrowest set that touches the changed code, and they are all green.

## 4. The remaining causes, each with its next step

### 4.1 `len()` of a value the source does not classify — 3 files, 1 construct

`formal/arm64.py:672,682,687,699` are all `len(self.sections["text"])`, where
`self.sections: dict[str, bytearray]` is a field declared on the struct. The
message is *'len(self.sections['text']) — the source does not say what this
operand holds'*, and it is FALSE about a declaration, which is the same defect
`ValueKinds`' `declared_kind` hook was added for and does not yet reach.

Measured, and this is the part that sizes it: **it is not about struct fields.**
A plain local fails identically.

```mojo
def main():
    d: dict[str, bytearray] = {"text": bytearray()}
    d["text"].extend(1)
    x = d["text"]
    printf("%d\n", len(x))     # build: len(x) is len() of a value classified as 'int'
```

**Next step.** A dict subscript has no VALUE KIND on this path. That is one
capability, and it needs three cooperating pieces: (a) `declared_type_kind` (or
a sibling) answering `dict[K, V]` with `V`'s kind rather than `None`; (b)
`ValueKinds.kind_of` gaining a `Subscript` arm that reads the base's element
kind; (c) `BLOB_TYPE_CTORS` carrying `bytearray` so `V` is a list of ints. The
gate to design before writing it is `struct_field_kind`'s: a declared type is a
fact about the type and the word in the slot is a fact about the constructor,
and that function's docstring records that claiming the kind from the annotation
alone BUILT and then died with SIGSEGV on both architectures. A dict's element
word is written by the subscript store, not by the constructor, so the same
danger applies and the same gate is the answer — `len` of a dict subscript whose
slot has not been written is a count read from address 0. **Do this as one change
with both arms of the test suite**, not as a lowering tweak.

The other `len()` row is the same capability with a different spelling and it is
cheaper: `unescape_c.py`'s `len(s)` where `s` is a parameter. An unannotated
parameter is seeded `INT_KIND`, and `kind_of` already asks `declared_kind` for a
name in `_param_names` — so this one is a case where `s` *has* an annotation the
analysis is not reading, or where the value flows from a call the analysis cannot
follow. Worth one probe to tell those apart.

### 4.2 A module global bound to a non-literal — 5 files, two messages

| file | name | initializer |
|---|---|---|
| `formal/elf.py` | `ELF_MAGIC` | `b"\x7fELF"` |
| `tools/bootstrap_verify.py` | `REPO` | a `os.path…` call |
| `tools/audit_selfhost_struct_fields.py` | `HERE` | `os.path.dirname(os.path.abspath(__file__))` |
| `tools/wave1_move_shared.py` | `MOVES` | a container literal whose ELEMENTS are not static |
| `tools/wave2_extract_shared.py` | `EXTRACT` | likewise |

Two distinct messages over one gap. `formal/model.py::module_slots` grows a
table for a name a function **WRITES** and for a name whose value is a
**container LITERAL**; everything else is folded, and a name that is neither
foldable nor in the table is refused by `module_global_refusal`. So:

* a scalar bound to a CALL has no slot — there is no value to substitute at the
  read and nowhere to keep the computed one;
* a container literal whose words `_static_container_words` cannot compute gets a
  slot with `("unknown", …)` and is refused by name at the read.

**The infrastructure this needs already exists and is unused here.**
`GlobalDataImage.string_cells` exists precisely so that "only the CODE can carry
out the initialisation, because only the codegen interns", and
`initialization_is_lazy` is the flag that orders the overwrite before the first
read. A module-level *expression* — `os.path.dirname(...)`, `b"\x7fELF"` — is
exactly what a lazy initializer is for, and it is the one shape that mechanism
does not yet accept, because `_static_initializer` is deliberately exhaustive
over what a `__DATA` word can hold statically.

**Next step, in the order it should be done.** (a) Extend the lazy initializer
to run the module-level expression at the first read and write the slot, for a
restricted and decidable subset — a call to an imported Mojo-side function, and
arithmetic over literals — and refuse everything else as it does now. (b) Only
then, `b"…"` as a literal: a bytes literal is a blob whose words are the bytes'
own, which `_static_container_words` may already be able to compute once told a
bytes literal is a static run rather than an unclassifiable value. (c) The
container case is its own question and should not be bundled: `_static_container_words`
says why it gave up, and that message is the thing to read first.

**The doc that owns this measurement is stale and should be corrected:**
`FORMAL_module_global_string_elements_is_a_storage_decision` states as
fact that "there is no `GlobalDataImage`, no lazy initializer, and no `__DATA`
block". All three now exist. That is not this branch's doc to delete (the claim
is `FORMAL_module_state_no_storage`'s), but a reader following its four-step next
step would be building machinery that is already there.

### 4.3 A linked module's attribute / missing export — 4 files

`sys.argv` x3 (`tools/ci_line.py`, `tools/detach.py`, `tools/audit_determinism.py`)
and `sys.exit()` (`tools/detrace_diff.py`). This is `formal/hostmods/sys.mojo`
plus the cross-dylib attribute rule: `formal/imports.py` refuses a module
attribute read across a dylib boundary (`"sys.argv reads 'argv' out of the
imported module sys, and a module is not a value"`), and `sys.mojo` exports no
`exit`.

**Next step.** These are four small, decidable additions to `sys.mojo` and its
contract rather than a value-model project, which is why they are ranked below
§4.1 despite being nearly as large a row. `argv` needs a representation that
outlives the call that produced it (the same storage-lifetime argument as §4.2's
container case — read that one first); `exit` needs a declaration plus whatever
the emitters do with a call that does not return. `sys.mojo` is `formal/`'s, and
no `sweep:*` claim holds it, so this is unclaimed work — but it is adjacent to
§4.2 and the two share a mechanism.

### 4.4 `field(default_factory=F)` — 1 file, and the refusal is right

`formal/x86_64_decode.py:68`, `extra: dict = field(default_factory=dict)`.
`formal/dataclass_transform.py`'s `lower_field` refuses it by name with a correct
storage argument: a factory is a call PER INSTANCE, and there is nowhere to keep
the result. The same doc's `field(default=LITERAL)` half is implemented.

**Next step.** Not a lowering tweak. Either (a) a field's per-instance container
gets a slot in the frame the constructor allocates for the instance, which is a
change to the frame layout both backends and the ~40 passing Lean proofs share;
or (b) `x.extra` is read through a method that consults the class-level default
when the instance slot is empty, which changes `dataclass_transform` and the
field-slot evidence machinery rather than the layout. **Read
`FORMAL_dataclass_partial_construction` and
`bugs/FORMAL_dataclass_runtime_reflection.md` before starting** — one of them may
already have made the decision.

### 4.5 `regex_compile.py` — 1 file, and the refusal is right

`atom` is assigned `_Parser_parse_atom(self)` (a frame address) in
`_Parser_parse_repeat()`, and also assigned a value on another path, and every
field access through `atom` is already lowered as `[base + 8·slot]` on the
strength of the first binding. Measured: builds, runs, SIGSEGV 139 on both
architectures. `model.holder_rebound_from_a_word_refusal` reports it, with the
three legal rebindings named.

**Next step: fix the source, not the backend.** `regex_compile.py` is ordinary
CPython in this repo's own slice; a different name for the word, or copying the
value out first, is the documented repair and is a one-line change. It is listed
here rather than fixed because it moves one file and nothing else, and a source
change to a live compiler module is the integrator's call. Note
`FORMAL_holder_rebound_from_a_word` does **not** exist on this tree even
though `model.holder_rebound_from_a_word_refusal` does, so the refusal's evidence
lives only in the function's docstring.

## 5. What this document does not establish

* **It does not claim a cause's value.** `FILES BLOCKED` is an upper bound. The
  only way to price §4.1 is to give a dict subscript a value kind and re-sweep
  `formal/`; the only way to price §4.2 is a lazy initializer.
* **It does not measure the 47 `tool` files at all.** Every number above is over
  19 files. A `-t 600` run would move the denominator and possibly the
  numerator, and it is not this worker's to spend.
* **It does not rank the slice against any other slice.** `repo-a`, `repo-b` and
  the `std-*` slices swept concurrently on the same machine; their logs are
  theirs and no comparison here is against them.
* **It does not re-verify the rest of `test_formal_run.py`'s neighbourhood.**
  The floor was run twice (580/1 and 581/0) and nothing else in the `proofs`
  bucket was touched, so `formal-run` being green says nothing about the other 37
  jobs in that bucket.

## 6. SURPRISES worth the next reader's time

* **`--allow-concurrent` was necessary and it is safe for reads.** Four other
  `formal4-sweep-*` workers held the arm64 lock for the whole run. The lock is
  `flock` on `~/.gmojo/cas/formal-sweep-arm64.lock` and the documented hazard is
  a half-written JSON manifest — which is the `tool` class
  `FORMAL_sweep_tool_json_decode_error` is about. **No
  `json.decoder.JSONDecodeError` appeared in 211 files**, and all 47 `tool` rows
  are timeouts, so the race did not fire here. It is still a real race with
  another worker's run on the line.
* **`pkill -f formal_sweep.py` kills every worker's sweep.** The processes share
  one command line. A worker that wants to stop its own run cannot, and killing
  it also corrupts the shared `verdict history`, which is why §1's run reports
  `backend-crash -> …` for all 211 files: the history was diffed against a run
  this worker interrupted. The class counts are unaffected; the history line is
  noise.
* **`FILES BLOCKED` did move this session**, which the tool's own docstring says
  has never happened: 3 files went `codegen/dependency` → `codegen` with the
  count of files blocked by a named module going 5 → 2. That is because the fix
  was to a MODULE (`re.mojo`) rather than to a construct, and a module's refusal
  was the terminal cause on three files at once. Worth knowing before reading
  "fixing one usually moves the file to the next with the count unchanged" as an
  absolute.
* **A test this project already fixed was not REGISTERED.** The new
  `test_pack_omitted_value_slots_are_filled` was written, and `test_struct_formal.py`
  still reported 148/148 — because `main()` runs a hand-maintained list of test
  functions and the new one was not in it. It is in it now, and the count is
  168/168. This is the same class as
  `bugs/COMPILE_FAIL_estate_check_red_for_eleven_formal_suites.md`: a test file
  that is green because half of it never ran.
* **`test_struct_formal.py` and `test_formal_read_before_store.py` time out at
  `-t 60` and both pass when run directly** (168/168 and 66/66). A `tool` row for
  either is a statement about `-t`, and reading it as a source finding costs a
  reader a build.
