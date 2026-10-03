# FORMAL_module_state_no_storage: a module cannot hold state, so `sys.argv`, `sys.path` and the stream objects cannot exist on this path

**Status (2026-10-02, the `sweep5:module-state` round): TWO MORE FIXES LANDED,
and the three things a slot cannot be are all still the remainder — nothing
below is superseded except where the new section says so.** The value model
could not classify two more expressions a use site has to decide about, and
`print()` is where a program meets both: a container's ELEMENT kind
(`print(d["a"])`, `print(L[0])`) and a constructed struct's FIELD kind
(`print(p.x)`). Both are facts the source states and the kind table did not
carry, and both are now answered from the evidence the emitters themselves use
— the container literal that filled the slot, and the `init_body_stores` call
that fills a field's. **`array_ops_jit.mojo` and `class_jit.mojo`, the two files
`tools/formal_sweep_causes.py` filed under "print() cannot classify the
argument's type", now build and run on BOTH architectures with answers
byte-identical to CPython.** The three refusals this document is actually about
— a call-computed global, `sys.argv`, and the export rule behind `sys.exit` —
are re-measured below, unchanged, with one correction to what this document
said about the last of them. Read "Re-measured 2026-10-02" next; everything
under it is a measurement and the rest of the file is the design history it
grew out of.

**Status: the storage half LANDED (2026-09-30, the `construct:module-global-storage`
claim); the rest is OPEN, and it is a property of the VALUE MODEL rather than a
gap in any one emitter. What is left is not "nowhere to put a module global" —
there is a `__DATA` slot per name that needs one, on both architectures and in
both containers — it is the three things a slot cannot be: a value computed
before the program runs, a value that lives in ANOTHER module's dylib, and a
value with a source this path does not have (`sys.argv`'s command line). Read
"What is left" before reading the rest; the measurements below are from the tree
this document was written on (`ca6e758`) and the landed half is described with
its own.**

**The DIAGNOSIS half of (2) landed 2026-10-01** (`construct:module-name-as-a-value`,
commit `663f174d`): a dotted READ of a module — `sys.argv`, `sys.stderr` — was
refused with a STORAGE claim about the module itself, and every clause of that
sentence was false about the name it named. It now names the attribute, states
what the boundary publishes, and prints what the module does publish. **No file
moved to pass and no capability was added** — the ceiling on folding these reads
is 0 of 6, measured per use, because none of the six uses is a compile-time fact
and `argv`'s source does not exist on this path. The measurement is the
"Re-measured 2026-10-01" block in "What moved"; the reword, and why the member
refusal is load-bearing rather than cosmetic, are in §(2).

Found while writing the `sys` module for the formal backend (2026-09-29, the
`module:sys` claim). Every measurement in "Measured" and "What this costs" is
from that tree; the sweep in "What moved" was re-measured on the landed tree and
says so.

---

## The rule, and it is one rule

`formal/model.py`, in the comment above `GlobalSymbol`, stated it: *"every value a
formal program can name lives in a function's own stack scratch (`_SCRATCH` …),
and that scratch is reclaimed when the function returns. This is the same lifetime
argument that makes a frame address in a field a use-after-free, and it is why
there is no `__DATA` block to put a mutable global in."*

**The last clause is superseded** — there IS a `__DATA` block for module state
now, and "WHAT LANDED" below is what replaced it. The first clause is still the
rule for everything else: a value that lives in a FRAME is dead when the frame
returns, and that is still why a frame address cannot be stored in a global, in a
struct field, or handed to another module.

Two consequences, and they are separate, so they are measured separately:

1. **A module-level name that is not a literal-only constant cannot be read, even
   inside the module that declares it.** `fold_literal_expr` substitutes a
   folded `int`/`str`/`bool` at every read site; anything else is refused by name.
   — **no longer true, and (1) below is the case that proved it**: a name with a
   `__DATA` slot is read by a load instead.
2. **A value cannot cross a dylib boundary at all unless it is one 64-bit
   word.** A list or a tuple is a blob carved out of the caller's frame, so
   handing one to another module hands over a frame address that is dead on
   return. — **still true for a WRITABLE word, and no longer true for a
   container**: a returned `[3, 14, 0]` now crosses and reads by subscript on
   both architectures (see (3) below), because it is `malloc`'d rather than
   frame-resident. What remains true is what this clause is really about: a
   slot fixes where a value LIVES, not how it is NAMED across a boundary, and a
   dylib publishes functions and folded constants rather than writable words.

## Measured

**(1) A module-level list, in the module itself.** `.tmp/exp1/g1.mojo`:

```mojo
G = [1, 2, 3]

def get():
  return G
```

```
build: get: 'G' is bound at module level, and this path has no module-global
storage for it: a formal value lives in a function's own stack scratch, and that
scratch is reclaimed when the function returns …
```

The same file with `G = 7` and `H = "hi"` builds and runs, because those are
literal-only and get substituted. So the refusal is about the VALUE, not about
module-level names as such.

**THIS ONE NOW BUILDS AND RUNS, on both architectures, and prints the list.**
`read_list_from_function` in `test_formal_globals.py` is that exact program
compared against the interpreter. The refusal text above is kept because the
DIAGNOSIS it made was right — the value was not a foldable literal, and a value
that is not a foldable literal is module STATE — and because the sentence that
carried the diagnosis ("there is no `__DATA` block") is what turned out to be
false. A reader who takes the first half and rejects the second half has the
right model.

**(2) A module-level name, read from ANOTHER module** — the shape `sys.argv` has.
`from mylib import PLAT` where `mylib.mojo` has `PLAT = "darwin"`:

```
build: main: 'PLAT' is imported from `mylib`, so it is a module-level name of
another module. This path compiles an import into a dylib, and a module-level
name is not exported as a word — there is no storage for it here
```

**HALF OF THIS LANDED (2026-09-30, the `construct:module-attribute-access`
claim), and it is the half that needed no storage at all.** A module-level name
the build FOLDED TO A LITERAL now crosses the boundary: `compile_formal_dylib`
records the folded values in the manifest's `constants`, and the importer
materializes the same literal in its own image
(`build._publish_imported_constants`, `model.dylib_module_constants`). So
`mylib.PLAT`, `from mylib import PLAT` and `pkg.PLAT` for a re-exported constant
all lower, on both architectures, and are pinned by
`test_formal_module_attr.py` against CPython's own answers.

The argument is the one this document already makes for the IN-unit case: a
folded module-level name has exactly one value in a whole program, because the
module-level sequence is its only writer and a function that assigns the name
binds a local that shadows it. There is nothing to store and nothing that can
change it, so a copy of the literal in each image is the same value rather than
a second one.

**What did not change is everything this document is actually about**: a name
whose value is NOT a literal is a real global, still refused, and still for the
reason below. `sys.argv` (a list), `sys.stderr` (an object) and `sys.modules` (a
dict) are all in that set, and the refusal message now says which of the two
kinds it is — a dylib publishes FUNCTIONS and folded CONSTANTS, and what it
cannot publish is a VARIABLE.

**The DOTTED spelling of this same boundary got its own message, and the reason
is that the old one was false about the name it named** (2026-10-01,
`construct:module-name-as-a-value`, commit `663f174d`). `sys.argv` was refused
as *"**`sys`** is imported from `sys`, and it is a module-level name of another
module … there is no storage for one here"*. Every clause is wrong about `sys`:
it is not a module-level name of `sys` — it **is** `sys`, the library on the
link line — and it is not a variable with nowhere to live, because a module is
not a value at all. The name with no representation is the ATTRIBUTE. The
refusal now names `sys.argv`, states what the boundary publishes, and prints
what the module DOES publish, so a reader can tell a capability `sys` lacks from
a name it simply does not have.

That is a re-wording of a REFUSAL, not a capability: 0 of the 6 files moved to
pass, and the next refusal is §(3)/(4) below in every case. What moved is that
the diagnostic is true, which is what the rest of this document is for.

A dotted CALL through a module already resolved by module identity before this
(`sys.exit(3)` is refused by `doc/ABI.md`'s export rule, not by a storage
story), so the read side was the only asymmetry, and it is one recogniser
(`model.dylib_module_reference`) asked one question later. **The member refusal
is load-bearing**: exempting the root alone is a SILENTLY WRONG ANSWER —
`ARM64Codegen._emit_expr` on `MemberExpr(IdentExpr('sys'), 'argv')` finds no
frame slot for `"sys.argv"` and falls to its "no object model, so the field
reads as 0" arm, so `print(sys.argv)` would build, print 0 and exit 0.
Pinned structurally in `test_formal_module_attr.py`.

The same pass found a real defect in the half that DID land: a published
constant was readable in only some positions. `_apply_imported_constant_sites`
re-entered the node walk on a store's value side instead of applying
`_rewrite_dotted_child` — the one test — to it, so `print(mod.K)` lowered while
`x = mod.K`, `var x = mod.K` and `x += mod.K` were refused with the sentence
above, about a name that is a folded CONSTANT the manifest already carries.
Fixed in the same commit; all three store kinds are pinned, and the store's
TARGET is still left alone (`mod.K = 5` writes another module's state, and
substituting it would trade a refused store for a dropped one).

**(3) A container crossing a dylib boundary — WAS a use-after-frame, printed as
a number; FIXED (2026-10-01).** A module returning `(3, 14, 0)`, printed by the
importer, used to give:

```
print(tupm.vi())   ->   6159887712
```

That is the frame address, printed as a number. The same program did not even
build when the call was in the same unit (`print() cannot tell whether
IdentExpr is a string or a number`).

**Measured again on this tree, both architectures:**

```
# tupr.mojo
def triple() -> List[Int]:
    return [3, 14, 0]

# tr.mojo
from tupr import triple
def main() -> Int:
    var t = triple()
    printf("%d %d %d\n", t[0], t[1], t[2])
    return 0

arm64   3 14 0     x86_64  3 14 0     CPython  3 14 0
```

So this is no longer a silent wrong answer, and it is the item on this list
that was the most dangerous to leave: a frame address printed as a plausible
number is indistinguishable from a computation, so every downstream read of it
was wrong rather than absent.

**What is still missing is narrower than the item claimed, and the narrowing
is measured:** a `malloc`'d blob crosses and reads by SUBSCRIPT, but `len()` of
one does not, because the path has no KIND that says "this word is a heap
allocation with a run-time length":

```
printf("%d\n", len(t))
    -> len() of a value classified as 'int', and an integer has no length:
       there is no count to read at offset 0, and the word there is the
       integer itself
```

That is item (1) of "What is still missing" below, unchanged, and it is the
`BLOB_KIND` annotation channel `dylib_export_return_kind` already reads for
`char *`. The representation is not the gap — the subscript works, so the blob
and its count-word are read correctly — the KIND is.

**(4) `sys.argv` additionally has no SOURCE on this path.** The entry stub
(`ARM64Codegen.compile`, and `X86_64Codegen`'s twin) loads the test input into
X0 and branches to the entry function:

```python
test_val = self.test_input
self.asm.emit(encode_movz_xn_imm(0, test_val))
self.asm.emit(encode_bl(0))
self.asm.emit_label_rel(first_func_name, here_offset=-4)
```

`argc`/`argv` arrive in X0/X1 from the kernel's start and are overwritten before
the first statement runs. So even with storage there would be nothing to read:
the command line is gone, not merely unreachable.

## Re-measured 2026-10-02 (the `sweep5:module-state` round)

The sweep that produced this round's ranking was taken at ~04:17 on 2026-10-02,
**before** the formal3/formal4 batches landed, so everything below was
re-verified on the tree as it stands, with the message quoted rather than
re-derived, and on **both** architectures. `python3 tools/formal_sweep_causes.py
<log>` files this round's four causes as 11 files; the ranking is unchanged by
what landed, and this is the whole census for the four:

| row | files | state on this tree, both architectures |
|---|---|---|
| a module-global name has no storage | 3 | **unchanged**, each a different shape — see (1) below |
| a module's ATTRIBUTE read as a value, across a dylib boundary | 3 | **unchanged** — `sys.argv`, §(4) |
| a linked module exports no such name | 1 (2 refusals) | **unchanged**, and one claim in this file about it is now MEASURED WRONG — see (3) |
| `print()` cannot classify the argument's type | 2 | **FIXED, 2 of 2 passing** — see "What landed" below |

### (1) the storage row is three unrelated shapes, and none of them is "no storage" any more

`formal/elf.py`, `mojo/middle/metal_ops.py` and `tools/bootstrap_verify.py`,
each still refused with the same sentence (`'ELF_MAGIC' / '_MSL_FLOAT_TYPES' /
'REPO' is bound at module level, and this path has no module-global storage for
it`). **That sentence is now false in a third way it was not false in when it was
written**, and the three names are three different remainders rather than one
family:

* `ELF_MAGIC = b"\x7fELF"` — a BYTES literal. Not a call and not a container:
  `_static_initializer` deliberately refuses to call one a string
  (`not getattr(value, "is_bytes", 0)`) and `_static_word` refuses it as a
  container element, because a bytes literal is a numeric buffer rather than
  text and this path has no `char[4]`. The repair is a BYTES value model, and
  `formal/elf.py` also wants it for `struct.pack("<4s…")`, so it is one piece
  of work serving both.
* `_MSL_FLOAT_TYPES = frozenset({'float', 'half'})` — a call into a BUILTIN
  (`frozenset`), and `frozenset` is not lowered at all. A slot is the easy half
  and it is already here: what is missing is both an initializer (the module's
  top level running before the read) and a `frozenset` that exists.
* `REPO = os.path.dirname(HERE)` — a call into ANOTHER MODULE's dylib. Even a
  perfectly folded slot cannot hold it, because the answer comes from a library
  this image links rather than from this module's own statements. This one is
  also the `os` host module's subject, which is a different claim.

So the honest reading of the row is the one this file already reached in 2026-09-30
and which has now been confirmed a third time: **these three files are not three
files about module storage.** They are one about a bytes value, one about a
builtin, and one about a dependency — and `tools/formal_sweep.py`'s "a file's
terminal cause is the FIRST refusal" means each has more behind it.

### (2) `sys.argv`, re-verified: the refusal is unchanged and the SOURCE is still gone

`t_argv.mojo`, `tools/ci_line.py`, `tools/detach.py`, all three still refused at
`sys.argv` with the reworded diagnostic, all three on both architectures, and
all three still with no storage behind them: this is §(4) plus the two other
remainders, and the entry-stub measurement in §(4) is still what it was —
`test_input` is loaded into X0 and the kernel's `argc`/`argv` are gone before
the first statement runs.

**The row's ceiling has not moved and cannot move by compiler work**, which is
the measurement that decides the next step and is unchanged from 2026-10-01:
none of the uses is a compile-time fact, and `argv`'s source does not exist on
this path. What has NOT been measured, and is the first thing whoever takes this
should measure, is whether items 2 and 3 of "the exact next step" compose:
an exported slot reached by an imported FUNCTION, and a command line that
survives the entry stub. The obstacle item 3 has to clear first is not storage
but the crossing: the `argc`/`argv` words are in the EXECUTABLE's image at
entry, and `sys` is a dylib, so `sys` cannot read them from there — no data
symbol is importable (`_emit_global_init`'s measurement), which is why the doc
puts an imported FUNCTION in the design. Nothing here has been built, and it is
an ABI change plus a stub change plus a value model for a returned blob's count
and element width, so it is a project and not a commit.

### (3) `sys.exit`: this file's explanation of it was wrong, and the correction is measured

The `sys.exit` row of both tables below says the cause is that
`doc/ABI.md`'s export rule does not advertise a C library symbol. **That is
half the cause, and the half that is not there does not matter for a name
published this way.** Measured:

```
exit in reflect._CLIB_SYMS:        True
exit in reflect._NO_MANGLE_FUNCS:  False
reflect._func_export_csym("exit", sig, "")   ->  mojo_exit_9f63a2
reflect._func_export_csym("exit", sig, "sys") ->  sys_mojo_exit_9f63a2
reflect.export_exclusions(sys.mojo)["exit"]  ->  (the module does not declare it)
```

Three facts, and together they change the next step:

1. `formal/hostmods/sys.mojo` does not define `exit` at all — its own module
   docstring says so, on purpose, citing `FORMAL_known_limits.md` §1.1. So
   `t1.mojo`'s refusal is first a MISSING FUNCTION, not an exclusion.
2. `exit` would be advertised as **`sys_mojo_exit_9f63a2`**, not `exit`:
   `_func_export_csym` qualifies every free function by its module prefix, and
   `exit` is not in `_NO_MANGLE_FUNCS` (`reflect.py:23`), so it is not exempt.
3. Therefore the hazard `_CLIB_SYMS`'s own comment documents — "an importer's
   `exit()` would bind the system's, silently" — **does not apply to a
   qualified symbol**, and the caller here is not a bare `exit()`: it is
   `sys.exit(3)`, which `model.dylib_module_reference` resolves by MODULE
   IDENTITY (`dylib_export_lookup(by_name, by_module, …)`), so it cannot reach
   any other library's `exit` whatever that library is called.

**The next step is therefore narrower than this file said, and it is NOT this
worker's to take**: the repair is one rule in `reflect.export_exclusions` —
exclude a C-library name only when the symbol it would be published under is
unqualified — plus a definition of `exit` in `sys.mojo` that does the honest
thing (`write_stderr` then the C library's own `exit`, or libSystem's `exit`
directly, which is what CPython's `sys.exit` ends up doing). Both halves are in
`reflect.py`, which builds the export table for **the gimple dylib as well as
the formal one**, so changing it changes what every dylib in the project
publishes and owes a full `make gate` — out of scope for a
`formal`-only claim, and reported here rather than taken.

### What landed: the two kinds `print()` could not get, and the two files that were blocked on them

Both are the same defect as this document's subject and not this document's
subject: **a use site that must decide before emitting had no way to ask what a
value holds, and the answer existed in the source the whole time.** `print()` is
the consumer that surfaces it because it is the one builtin with to choose
between two renderings before it emits anything.

* **A container's ELEMENT kind.** `model.container_literal_elem_kind`, asked of
  the literal that filled the slot — by `ValueKinds.kind_of` for a local and by
  `global_slot_kind` for a module global's `__DATA` initializer, so the two
  spellings cannot disagree. A DICT was the gap: it classified as a bare
  `LIST_PREFIX` where a list classified as `list:<elem>`, so `list_elem_kind`
  had nothing to hand a subscript.
* **A constructed struct's FIELD kind**, read off `model.struct_ctor_field_value`,
  which asks `init_body_stores` — the one function that decides what `S(a, b)`
  stores where — so the kind is read off the very expression the image
  evaluates into the slot. This is the case `class_jit.mojo` is: an
  UNANNOTATED two-field class, where the declaration is not merely gated by
  `struct_field_kind`'s "`S()` does not run `__init__`" rule but simply absent.

Measured, both architectures, on the two files the sweep filed under this row:

| file | before | after | and CPython says |
|---|---|---|---|
| `array_ops_jit.mojo` | `print() cannot tell whether SubscriptExpr is a string or a number` | **built and ran** | `Sum: 15 / Length: 5 / Value of a: 10` |
| `class_jit.mojo` | `print() cannot tell whether MemberExpr is a string or a number` | **built and ran** | `Point: 3 4` |

Four gates on the field kind, each a refusal and each pinned in
`test_formal_value_model.py` (which builds BOTH architectures and requires the
identical message, the only instrument that can see a defect the two backends
share): a store to the field after the construction retracts the claim —
**measured as a SIGSEGV, exit 139, on both architectures, from a green build**,
`%s` walking bytes at address 5 — an argument that is one of this function's own
unannotated parameters claims nothing, a method other than `__init__` writing
the field claims nothing, and two constructions that disagree claim nothing.
`test_formal_value_model.py` is 32/32 with them, `test_formal_run.py` 622/622,
`test_formal_globals.py` 20/20.

### And the stale row this file's owner had to decide

A `bugs/TEST_a_mutated_module_global_is_refused_is_stale_after_the_slot_landed.md`
doc (now deleted, with this section as its record) noted that `test_formal_run.py`'s
`a_mutated_module_global_is_refused` still
asserted a refusal the backend stopped owing when `formal-module-globals` gave a
written module-level name a `__DATA` slot — red on `master`, and that document
named this file's owner as the one who has to decide. Decided here, option 1 of
the two it offered: **the program is right, so the row asserts the number.**
`G = 5` with `global G; G = G + 1`, read back twice, is **exit 12 on both
backends**, which is CPython's (`G` goes 5 → 6, both reads see 6). The row is
now `a_mutated_module_global_is_read_back_from_its_slot`, and the TEST doc is
deleted with it.

## WHAT LANDED: option A, the `__DATA` block for module state

`construct:module-global-storage`, 2026-09-30. The model at the top of this
document — *"there is no `__DATA` block to put a mutable global in"* — is no
longer true, and every consumer of that sentence needed re-reading rather than
deleting, so this section is the record of what is now different and what is
still exactly as it was.

**A module-level name gets a `__DATA` slot** (`model.collect_global_slots`) when
the build cannot answer a read of it by folding, which is two cases:

* **a function WRITES it** — `global G; G = G + 1` changes G while the program
  runs, so there is no one value to substitute. This was a SILENTLY WRONG answer
  before, not a refusal: `G = 5` with `bump()` called twice printed `G=5` where
  CPython prints `G=7`, because the read was the folded 5 and the write went into
  a register nothing else named.
* **its value is a CONTAINER literal** — `[1,2,3]` is not a value the
  substitution path can express, but it IS static data: a flat blob of words
  whose first word is the count, which the linker places and the slot points at.

Everything else is still folded and still needs no storage, so **an ordinary
program's image is byte-for-byte what it was** — `has_globals` is false, no
segment is emitted, and no prologue grows a branch.

* Writable `.globals` in **all three Mach-O builders and the ELF one**, mapped
  at a FIXED `GLOBALS_VM`. Fixed rather than derived from `__TEXT`'s size,
  because `__TEXT`'s size is a function of the code and the code has to know
  where `__DATA` is. `_check_globals_do_not_overlap_text` refuses an image where
  they would ever meet, and the margin is an order of magnitude above the largest
  formal image in this tree.
* Both backends lower a slot read to one load and a slot write to one store, and
  `model.module_slot_for` — ONE place, shared — keeps a `global`-declared name
  out of register allocation, so there is exactly one home for the word.
* The addresses are filled by **CODE in a lazy per-function initializer**, not by
  a relocation. Measured: a well-formed classic `LC_DYLD_INFO_ONLY` rebase stream
  naming `__DATA` is parsed by dyld on macOS 26 and then silently NOT applied —
  the slot kept its link-time address and the first read segfaulted. ADRP/ADD
  and RIP-relative LEA are already proven against a real dyld here, so they are
  what computes the addresses, and a flag word set LAST makes it idempotent. The
  lazy form rather than a startup stub because a **dylib has no entry point**:
  `emit_startup=False` is precisely why, so a stub that runs once per process
  does not exist for half of where module state lives.
* A module-level **string**, and a string ELEMENT inside a container, point at
  the INTERNED literal rather than at a copy in `__DATA`
  (`GlobalDataImage.string_cells`). That is not an optimisation: a dict subscript
  is a raw 64-bit compare against the interned literal and two lists of `"a"`
  compare EQUAL, so a copy would make `D["a"]` miss and `L[0] == M[0]` false.
* A module-level **container store is not a top-level statement** — the value is
  in the image. `model.module_body`'s `_is_image_initialized`. This one is worth
  its own line because getting it wrong is not a missing value but a program that
  computes the right answer somewhere nobody looks: the module body IS the entry
  point, so a leftover store meant `main` was never called and the image exited 0
  printing nothing, on both architectures, with a green build.
* The **shape and kind** of a global come from its slot, so a use site can lower
  it: `model.global_slot_kind` (for `ValueKinds`, so `len(arr)` works),
  `global_slot_is_dict` (for a subscript, which is a key SCAN or an address
  computation and not a detail), `global_slot_is_string`.

Verified by EXECUTING images against CPython on both backends, three engines per
case: `test_formal_globals.py`, 17/17, `formal-globals` in `tools/suite.py`.

### What the storage half moved, measured

The six files the work map's row 11 ("a module-global name has no storage", 6
files) blocked, re-swept on `master` and on this branch with
`python3 tools/formal_sweep.py <the six>`, arm64:

| file | class before | class after | what stops it now |
|---|---|---|---|
| `mlir.py` | codegen — `MLIR_TYPES` no storage | **codegen** | `String.strip` returns a shorter string, which on a bare `char *` is writing a terminator over a byte. A value-model limit, an honest refusal, same on x86-64. |
| `formal/arm64.py` | codegen — `_SXT_BASES` no storage | **codegen** | `_cond`: a bare TYPE name in a value position (`isinstance(cond, int)`, and the `-> int` annotation), at two sites. The map's row 2 shape, `work/frontend-silent`'s. |
| `formal/macho_linker.py` | codegen — `ARCHES` no storage | **codegen** | `NOEXTERN_GLOBALS_ENTRYOFF = executable_entry_offset(…)` — a module global whose value is a CALL. `ARCHES` itself now lowers; what is left is (5) below. |
| `mojo/middle/metal_ops.py` | codegen — `_KERNEL_ARG_NARROW` no storage | **codegen** | `_MSL_FLOAT_TYPES = frozenset({…})` — again a call. `_KERNEL_ARG_NARROW` (`dict[str, str]`) now lowers. |
| `test_runtime_header_scan.py` | codegen — `RESULTS` no storage | **codegen** | `RUNTIME`, a module global built by a call. `RESULTS = []` now lowers. |
| `tools/bootstrap_verify.py` | codegen/dependency (`argparse`) | codegen/dependency (`argparse`) | unchanged — it never reached its own global. |

**0 of 6 reach `pass`, and the "no storage" family goes from 5 files to 1.** That
is the work map's §3 warning confirmed on its own row: a file's terminal cause is
the FIRST refusal, and these files have two to four behind it.

**One extension was measured and NOT built, because its ceiling is 0.** A nested
container initializer (`ARCHES` is a dict of dicts, whose values are names rather
than literals) is the only remaining gap in a container initializer, and hacking
it away in a scratch tree moved `formal/macho_linker.py` from
`no initializer: a container element is itself a container` to
`NOEXTERN_GLOBALS_ENTRYOFF` — a *different* module-global refusal, and still not
a pass. So the honest reading of that row after this change is not "6 files about
storage": it is **one file about a call-computed global, three about a
type-name or a module attribute, one about a string-length value model, and one
behind a dependency.**

### What is left, and it is three things a slot cannot be

1. **A value computed before the program runs.** `NOEXTERN_GLOBALS_ENTRYOFF`,
   `_MSL_FLOAT_TYPES`, `RUNTIME`: a module-level binding whose value is a call's
   result. A slot needs a value at build time and there is none, and a function
   writing the name later does not help — the name's value before that write is
   still the call's. The repair is running the module's top-level statements, or
   folding the call at compile time: `FORMAL_toplevel_statements_dropped.md` and
   the comptime story. Refused by name, as `"computed"`.
2. **A value that lives in ANOTHER module's dylib.** A slot in THIS image cannot
   hold another image's state; what a cross-module global needs is the other
   module's slot exported as a symbol, and `doc/ABI.md`'s export rule publishes
   functions and folded constants, not writable words. A folded constant crosses
   by substitution (the `module:sys` half above); a writable one has no
   mechanism. This is the honest remainder of (2) and (3) below, and it is what
   keeps `sys.stderr` and `sys.modules` out of reach: they are OBJECTS, and an
   object is a pair of words.
3. **`sys.argv`'s SOURCE**, which is (4) below and is not a compiler problem at
   all: the command line is overwritten by the entry stub before the first
   statement runs. Storage would give it somewhere to live and there would still
   be nothing in it. `sys.executable` is the same shape with a smaller gap —
   libSystem's `_NSGetExecutablePath` writes into a CALLER-SUPPLIED buffer, so
   what is missing is a place to put a path, and that IS this document's subject.

Two smaller remainders, both honest refusals rather than wrong answers, both
named by `static_initializer_refusal_reason`: a container element that is itself
a container or a call (`"nested_element"`), and a module global whose name is
imported from another module (`"imported"`).

## What this costs, by name

Of the `sys` surface this repository's own files use, measured with
`grep -o "sys\.[a-zA-Z_]*"` over the fourteen files the sweep listed for `sys`.
**The "blocked by" column is the pre-storage reading and is kept as the record;
"What is left" above is the current one, and the difference is that (1) is no
longer in it for any of them** — because a `sys` module global that is a mutable
list now HAS a slot. None of the names moved anyway, and the reason is the
column that did not change: (2), (3) and (4) are a boundary, a value model and a
missing source.

| `sys` name | uses | blocked by |
|---|---|---|
| `sys.argv` | 73 | (2)+(4) — a list, in another module, with no source |
| `sys.stderr` | 44 | (2)+(3) — a stream OBJECT, and there is no object |
| `sys.exit` | 33 | a **settled, different** reason: `doc/ABI.md`'s export rule does not advertise a C library symbol (`exit` is one), so no module dylib can be called by that name. Measured and closed in `bugs/FORMAL_known_limits.md` §1.1. The working spelling on this target is a bare `exit(code)`, which lowers today and exits 3 — pinned by `test_formal_sys.py`. |
| `sys.platform` | 7 | no honest value exists: one source file is compiled for Mach-O and for ELF, and nothing in the language asks the target which it is. A module-level `PLATFORM = "darwin"` would be a lie on the ELF build. (A module-level string global is now representable, so this is the one row where the obstacle really is only the lie.) |
| `sys.setrecursionlimit` + `getrecursionlimit` | 4 | (2) — but the module answers them as functions returning the honest value for a target with no interpreter stack |
| `sys.path` | 3 | (2) — a mutable list in another module |
| `sys.stdin` | 1 | (2)+(3) |
| `sys.modules` | 1 | (2)+(3) — a dict of live module objects |

So 117 of the 167 `sys` uses in those files are `argv` and `stderr`, and both are
the same missing capability. `sys.exit` is the next largest and is closed by a
different, already-settled decision.

Over the WHOLE tree (every `.py`/`.mojo` outside `doc/`, `bugs/` and `build/`)
the shape is the same and the two blocked names are bigger still:

| `sys` name | uses, whole tree | blocked by |
|---|---|---|
| `sys.exit` | 194 | the settled export rule, above — not this document |
| `sys.argv` | 167 | (2)+(4) |
| `sys.stderr` | 137 | (2)+(3) |
| `sys.path` | 103 | (2) — a mutable list of strings in another module |
| `sys.executable` | 43 | (4) one step on: libSystem's `_NSGetExecutablePath` answers it and writes into a CALLER-SUPPLIED buffer, so the missing thing is a place to put a path. Not a capability this target lacks. |
| `sys.platform` | 31 | no honest value; see the table above |
| `sys.modules` | 16 | (2)+(3) — a dict of live module objects |
| `sys.stdout` / `sys.stdin` | 24 | (2)+(3) |
| `sys.version_info` | 8 | (3) — a tuple |

`sys.executable` is worth its own line because it is the case where reading this
document would otherwise produce the wrong conclusion: the capability IS
reachable (libSystem has the call), and what was missing was storage for its
answer. That distinction is the whole difference between option A and option B
below, and **A is what landed** — so this row is now down to the buffer, and
`sys.platform` is now down to the lie.

## What `sys.mojo` does instead, and why it is not a dodge

`sys.write_stdout(s)` / `sys.write_stderr(s)` are `write(1|2, s, strlen(s))`
through the module's own exported function. That is a real operation on the real
descriptor, and it is the only spelling available: `sys.stderr` would have to be
an object, and (2)+(3) say an object cannot cross the boundary. The module says
so at each definition, names what it cannot do and why, and cites this document.

## What moved, measured, so nobody has to re-derive it

All fourteen files the sweep listed for `sys` at the start, swept from a CLEARED
CAS (see `bugs/FORMAL_sweep_cache_ignores_imports.md` for why that matters),
`python3 tools/formal_sweep.py --no-stdlib <the fourteen>`:

| file | class before | class after | what stops it now |
|---|---|---|---|
| `t1.mojo` | not-answerable/host-import (`sys`) | **pass** | nothing — but the pass WAS hollow: its body is top-level, so it exited 0 where it says `sys.exit(3)`. Fixed since, by `formal/build.py`'s `module_body`/`entry_function` |
| `t_argv.mojo` | not-answerable/host-import (`sys`) | **codegen** | this document: `sys.argv` |
| `tools/ci_line.py` | not-answerable/host-import (`sys`) | **codegen** | `f.readlines()` — a value method the path does not lower |
| `unescape_c.py` | not-answerable/host-import (`sys`) | **codegen** | `len(s)` where `s` classifies as an int |
| `fire.py`, `build_module.py`, `mojo.mojo`, `scripts/run_mojo_main.py`, `tools/compile_one.py` | not-answerable/host-import (`sys`) | not-answerable/host-import (**`os`**) | `os` — the `module:os` claim |
| `fire_main.py`, `mojo/middle/comptime.py`, `test_async_parsing.py`, `test_yield_parsing.py` | not-answerable/host-import (`sys`) | not-answerable/host-import (**`re`**, through `fire_compiler`) | `re` — **unclaimed** |
| `test_refactor_bugs.py` | not-answerable/host-import (`sys`) | not-answerable/host-import (**`os`**, through `gimple_codegen`) | `os` |

So three of the fourteen moved out of the `sys` refusal, and **eleven were never
blocked by `sys` alone** — they hit `os` or `re` first, which is the sweep
reporting the FIRST thing wrong with a file rather than every thing wrong with
it. `sys` was the whole of the answer for three files, and for the other eleven
it was one line among several.

`re` is worth calling out separately: it blocks four of the fourteen and no
worker holds it.

**Re-measured 2026-09-30** (the `construct:module-attribute-access` claim, arm64,
`tools/formal_sweep.py --no-stdlib` on a handful of these): the classes are
UNCHANGED — `t_argv.mojo` and `tools/ci_line.py` are still `codegen` on
`sys.argv`/`sys.stderr`, `unescape_c.py` still on `len(s)`, and the three
host-import files are still host-import (`shutil`, `subprocess`, `re`). The
constant half of (2) does not move them, and it was not expected to: none of
these four reads a name whose value is a literal. What the re-measurement does
show is that the tree has moved under the table — `determinism_trace.py`, which
this document's author listed as reaching the module-attribute refusal, now
stops earlier at `_f.write()` (a name classified as `int` where the C library's
`write(2)` needs a descriptor), and `analyze_benchmarks_types.py` stops at a
name that "holds a frame address in more than one shape". Both are real
findings and both are somebody else's construct.

**Re-measured 2026-10-01** (`construct:module-name-as-a-value`, commit
`663f174d`), the six files the re-sweep's `other refusal` bucket made visible,
on BOTH architectures and with the message verbatim rather than re-derived:

    $ python3 tools/formal_sweep.py --no-stdlib mojo.mojo t_argv.mojo \
        tools/ab_filelist.py tools/audit_determinism.py tools/ci_line.py tools/detach.py
    [arm64] 6 files: PASS=0 not-pass=6      <- codegen  x6

Before: all six refused with ONE message, naming `sys`, claiming no storage.
After: all six still refused, with the message naming the ATTRIBUTE and
printing what `sys` publishes:

| file | refused at | attribute | and the next refusal is |
|---|---|---|---|
| `mojo.mojo` | `main:` | `argv` | §(4) — the command line is gone before the first statement |
| `t_argv.mojo` | `main:` | `argv` | §(4), same |
| `tools/ci_line.py` | `__module_body__:` | `argv` | §(4), same |
| `tools/detach.py` | `main:` | `argv` | §(4), same |
| `tools/ab_filelist.py` | `__module_body__:` | `stderr` | (2)+(3) — an object is a pair of words |
| `tools/audit_determinism.py` | `__module_body__:` | `argv` | §(4), same |

`tools/formal_sweep_causes.py` now files these under their own row, "a module's
ATTRIBUTE read as a value, across a dylib boundary", with `names: argv x5,
stderr x1` — previously they were filed as "a module-level name of ANOTHER
module is not exported as a word", whose `names:` column was empty of
attributes because the message never named one. Both rows are live: the bare
spelling (`from sys import argv` then `argv`) still produces the old message and
still belongs to the old row.

**WHICH OF THE SIX USES ARE COMPILE-TIME? None of them — and that is the
measurement that decides between the two repairs, so it is recorded per use
rather than as a total.** Grepped from the six files, not from this document:

| file | every `sys.` use | compile-time? |
|---|---|---|
| `mojo.mojo` | `len(sys.argv)`, `sys.argv[1]`, `sys.argv[2]` | no — a list, and §(4) says its SOURCE is gone |
| `t_argv.mojo` | `len(sys.argv)`, `sys.argv[0]`, `sys.argv[1]` | no — same |
| `tools/ci_line.py` | `len(sys.argv)`, `sys.argv[1]`, `sys.argv[2]`, `sys.exit(1)` | no — and `sys.exit` is a CALL, already answered by the export rule |
| `tools/detach.py` | `len(sys.argv)`, `sys.argv[1]`, `sys.argv[2:]`, `sys.stderr`, `sys.exit(main())` | no — and `sys.exit` likewise |
| `tools/ab_filelist.py` | `sys.path.insert(0, REPO)`, `sys.stderr` | no — a mutable list in another module; an object |
| `tools/audit_determinism.py` | `sys.exit(main(sys.argv[1:]))` | no — a slice of `argv`, and `exit` is a call |

So the "fold the member read into the import" repair — substitute the value at
the read because a folded constant needs no storage — has a ceiling of **0 of
these 6**, and it is 0 for a reason no amount of compiler work changes: the
value is not known before the program runs, and for `argv` there is nothing in
it to know (§(4)). Folding would produce a well-formed WRONG answer, which is
the failure mode this whole backend's refusals exist to prevent. That is why
what landed is the diagnostic and the one recogniser, and why the honest next
step is unchanged.

Also measured, because it is what a reader would otherwise assume was tried:
`sys.exit(...)` was ALREADY resolved by module identity before this commit —
`sys.exit(3)` is refused by `doc/ABI.md`'s export rule ("`sys` is a linked
module but it exports no `exit` … What it does export: api_version, byteorder,
…"), not by anything about storage. So the dotted CALL side of this boundary
has been working; only the dotted READ side did not, which is exactly the
asymmetry `model.dylib_module_reference` removed.

## The exact next step, for whoever takes it

**Read "Re-measured 2026-10-02" first**: it re-verifies all four of the sweep's
rows on the current tree on both architectures, records the two fixes that
landed since this section was written (a container's element kind and a
constructed field's kind, `print()`'s two refusals — neither of which is any of
the three items below), and CORRECTS item 3's sibling: the `sys.exit` row's
stated cause is half the cause, and the other half is a missing function in
`sys.mojo` rather than an ABI rule, with the rule's own documented hazard
measured not to reach a module-qualified symbol.

**A is DONE** — see "WHAT LANDED". What follows is B, and then the three things
A could not reach, which are the actual next steps and are all value-model work
shared by the two backends and the Lean proof.

**B. Keep the model and give the module a protocol (opens nothing on its own).**
A module that needs to publish a computed value exports a FUNCTION that
recomputes it, and the importer calls the function. That is what `sys.mojo` does
for everything it provides, and it is honest as long as the value is a pure
function of the target — which is why `byteorder`, `maxsize` and `hexversion` are
in it and `argv` is not. Cost: nothing in the compiler, and it does not close
`argv`, `path` or the streams. It is also, after A, no longer the *only* honest
option for a value a call computes: a module-level call-computed binding has a
`__DATA` slot already if any function writes it, and what it lacks is an
initializer — so the gap is narrower than it was and B is no longer the answer
for a value that never changes.

The three remainders, in the order the sweep reaches them:

1. **A module-level sequence that RUNS.** `NOEXTERN_GLOBALS_ENTRYOFF =
   executable_entry_offset(…)` and `_MSL_FLOAT_TYPES = frozenset({…})` want the
   module's top level to execute before anything reads the name. The machinery
   is `model.module_body` plus `entry_function` — the body already IS the entry —
   so what is missing is that the entry's stores land in the SLOTS rather than in
   its own frame, and that a body which runs cannot be the entry when the program
   declares a `main`. Both are this document's subject and both are bigger than
   one commit; `FORMAL_toplevel_statements_dropped.md` is where the semantics
   live.
2. **An exported slot.** A writable module global that another module reads needs
   its `__DATA` word published as a symbol, and `doc/ABI.md`'s export rule
   publishes functions and folded constants. Cost: a symbol kind, a relocation
   the loader honours (which the measurement in `_emit_global_init` says is not
   available for `__DATA` on this target, so an exported slot has to be reached
   by an imported FUNCTION rather than by a data symbol), and a lifetime story
   in the proof.
3. **A command line.** `sys.argv` needs the kernel's `argc`/`argv` to survive
   the entry stub, which is a change to the stub and to the test-input
   convention, not to storage. (4) above is the measurement. **And it has to
   clear a crossing this item does not mention**: the `argc`/`argv` words are in
   the EXECUTABLE's image at entry and `sys` is a dylib, so item 2's
   "reached by an imported FUNCTION" is a prerequisite rather than an
   alternative. Nothing has been built; the composition is unmeasured.

The option NOT recommended, unchanged: a `sys.argv` that returns a fabricated
one-element list, or a `sys.stderr` that is a struct wrapping the integer 2.
Both build, both run, and both compute something other than what their name says,
which is the failure mode this whole backend's refusals exist to prevent. Note
that the storage half made this *more* available, not less — a fabricated
`sys.argv` is now a list in a real `__DATA` slot, so it would be a well-formed
wrong answer rather than a refused one.
