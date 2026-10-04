# FORMAL_string_composition_has_no_buffer: 115 files stop at `f"…"`, and the ceiling of closing them is 0 passes

**Area:** FORMAL (both backends; the refusal is shared and lives in
`formal/model.py`, asked from `formal/build.py`'s one pipeline)
· **Status:** OPEN, measured 2026-10-04 on `master` at `65b88dab`, over
`bugs/sweeps/sweep-arm-11.txt` and `bugs/sweeps/sweep-x86-11.txt` (722 files
each, `-j 4 -t 120`, both arms to completion with no file unclassified).

**The construct is string COMPOSITION and the missing thing is a BUFFER.** It is
not the string *value model*, which is decided and landed
(`bugs/FORMAL_string_value_model.md` §"The decision": a formal value is one
64-bit word, and a string on this path is a bare `char *`). Composition needs a
place to put the new bytes, and there is none: not at compile time, because a
field may be a runtime value, and not at run time, because this path has no heap
for a program's own string. `formal/model.py` says this in all three wordings —
the interpolated literal's own message calls it *"the same missing buffer
`string_concat_refusal` names"*, `string_concat_refusal` names the heap, and
`LENGTH_DEPENDENT_METHODS` (`upper`, `replace`, `join`, `strip`, …) is the third
spelling of it.

**It is the largest unowned codegen row in the corpus and it is five days old.**
The refusal landed 2026-10-03 (`9b40c019`, *"an f-string literal is REFUSED, not
printed as its own spelling"*), which replaced a wrong-but-exit-0 answer. Both
instruments that rank refusals had no row for it until this round's commit added
one, so the sweep reported the largest construct in the tree as `other refusal`
— the bucket `tools/formal_sweep_causes.py`'s own docstring defines as *"nobody
has looked"*.

## 1. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-11 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-11.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm-11 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-11.txt  2>&1

python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-11.txt   # §2
python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-11.txt \
                             bugs/sweeps/sweep-x86-11.txt                   # §3
# §5, the ceiling: one build per file, with the `f` prefix removed from a scratch
#   COPY (`.tmp/ceiling/`, never committed) so the refusal is gone and the NEXT
#   one is visible.  The rewrite is semantically wrong on purpose — the question
#   is what is behind the row, not what the row should say.
python3 tools/memslot.py --gb 8 --label ceil -- python3 fire.py build \
  --formal --no-prove --backend=arm64 -o .tmp/ceiling/out.bin .tmp/ceiling/cas.py
```

## 2. The measurement

| | arm64 | x86-64 |
|---|---|---|
| files swept | 722 | 722 |
| findings carrying this sentence | **115** | **115** |
| …of them a refusal IN the swept file | 45 | 45 |
| …of them a refusal in a module the file imports | 70 | 70 |
| rank in `tools/formal_sweep_causes.py --min 3` | **2 of 17** | 2 of 17 |

`354 of 354` codegen findings accounted for, so nothing is hidden in the bucket
any more. **114** of the 115 are the interpolated-literal wording and **1** is
`'+' on two strings` (`test_relaxed_imports.mojo`); both are in one row because
`formal/model.py` says in both messages that they are one missing thing.

The 70 dependency findings, by the module that refused:

| refusing module | files | `uses:` — how many of them name anything it declares |
|---|---|---|
| `cas.py` | 40 | **3 of 40** (`_hash`, `_inst_hash`, `_list_py_files`) — 37 are closure |
| `module_loader.py` | 21 | 0 of 21 — closure |
| `tools/memslot.py` | 5 | 0 of 5 — closure |
| `type_system.py` | 2 | 0 of 2 — measured 0 |
| `determinism_trace.py` | 2 | 0 of 2 — closure |

**The construct is not one bad line repeated; it is 114 lines in 114 files, and
38 of them are 63 files.** The two concentrations are copy-pasted helpers, and
both sit at the SAME LINE NUMBER in every copy, which is how a duplicated block
looks:

| files | the literal | where it is written |
|---|---|---|
| **41** | `f"{platform.system()}/{platform.machine()}"` | **line 451** of 41 repo files — `toolchain_fingerprint`, copied whole |
| **22** | `f'/Users/mrs/net/chatgpt/claude/{checkout}/{rel}'` | **line 108** of 22 repo files |
| 7 | `f"--backend={backend}"` | 7 files, 7 distinct lines |
| 6 | `f'ledger-{name}.json'` | 6 files |
| 3 | `f"{_iota} {h}\n"` | `determinism_trace.py` and 2 through it |
| 3 | `f"int64_t<opaque->{self.base}*>"` | `type_system.py` and 2 through it |
| 29 | 28 further literals, one file each | |

The interpolated fields across all 114 are **48 distinct expressions** in 199
places: 99 are a bare name or attribute (`checkout`, `rel`, `name`, `backend`,
`i`) and 100 contain a call, an index, a slice or a conversion
(`platform.system()`, `lay['hash_size']`, `proc.stdout!r`).

## 3. Both architectures say the same thing

`tools/formal_sweep_parity.py` over the two logs: **577 files classified on both
arms, 0 with a different class, 0 that are a row on one arm only, and 0 with a
changed reason.** Not one architecture-dependent verdict in 722 files, so the
114 files are 114 files and not 228, and the fix is one shared change in
`formal/model.py` rather than two.

## 4. What the refusal cost, measured: 54 files went DARK, not fixed

The refusal is asked over the whole module body
(`formal/model.py::refuse_interpolated_literals`, from
`formal/build.py::_prepare_functions`) — **before any emitter runs**, so a module
with an f-string never reaches the construct-level refusals at all. It landed
five days ago, and it landed in front of two rows:

| row | `-10` | `-11` | what happened to the files that left it |
|---|---|---|---|
| a handler arm with a body | **30** | **1** | **29 dark** — every one now refused on an f-string |
| a module's ATTRIBUTE read as a value | **30** | **4** | **25 dark**, and **1 passes** (`build_mojo_cli.py`) |
| a bracketed specialization of a callee this unit does not compile | 3 | **0** | 3 dark behind `module exports no public functions` |
| `frame address passed where a value is wanted` | 3 | **0** | 3 dark |
| a slot holding a frame address is rebound | 1 | **0** | 1 dark |
| a module-global container has no initializer | 1 | **0** | 1 dark |
| a module-level name of another module is not exported | 1 | **0** | 1 dark behind the export gate |

**This is `FILES BLOCKED IS AN UPPER BOUND` arriving as a queue's blind spot
rather than as a caveat.** A row that empties because a refusal landed *in front
of it* reads as a fix in every table that counts rows, and 54 files are the price
of this one. It is also why `other refusal` went **14 → 121** on this corpus
while the backend got measurably better: the same 46 findings the new refusal
created are 94 % of a bucket whose name says nobody has looked. The row this
branch adds is what makes the rest of that bucket (6 files) readable.

## 5. The ceiling, measured: 0 passes, and the walls behind it are other rows

The question a planner asks is what closing this row is worth. Measured, by
building nine files with the `f` prefix stripped from a scratch copy — 5 of the
modules that refuse the other 70, and 4 of the 45 in-file findings:

| file | files it blocks | what it lands on with the f-strings gone |
|---|---|---|
| `cas.py` | 40 | a **handler arm with a body** (line 131, `except OSError`) — a refusal that is **correct**: `formal` has no unwinder, so every statement in an arm would be absent from the program that runs |
| `module_loader.py` | 21 | `os.environ` read as a **module attribute** — `FORMAL_module_state_no_storage.md` §(2): an exported slot is a symbol kind, a relocation the loader honours, and a lifetime story in the proof |
| `tools/memslot.py` | 5 | a **handler arm with a body** (line 507) — correct, as above |
| `type_system.py` | 2 | a frame address passed where a value is wanted (`isinstance()`), `FORMAL_known_limits.md` |
| `determinism_trace.py` | 2 | `os.environ.get()` — a call **through a value**, the value-model half of the same module-state doc |
| `tools/md2html.py` | in-file | a **handler arm with a body** (line 366) — correct |
| `formal/elf.py` | in-file | a container built in a frame and read after the call that made it — frame lifetime |
| `test_formal_glob.py`, `test_formal_stat.py` | in-file | still `cas.py:451` — their own f-strings were never their terminal |

**0 of 9 reach `pass`, and not one of the nine lands on another missing buffer.**
The row's own construct is not what stands behind 45 of its 115 files: a refusal
that is CORRECT stands behind them, and an ABI/value-model project stands behind
another 23. **A worker should therefore not read this row as the top priority to
implement** — the reading that is right is that it is the top priority to *know
about*, and that the largest single wall behind it is the handler arm (45 files)
rather than the buffer (115).

## 6. What is NOT the fix, each measured rather than argued

* **Folding an f-string that interpolates nothing.** 0 of the 114 have no
  interpolation field (`{` … `}` parsed out of each literal, `{{`/`}}` honoured):
  every one has at least one, so the cheap half of the feature is worth 0 files
  here even though it is correct in itself.
* **Deduplicating the 41 copies of line 451** (and the 22 of line 108). Tempting
  and it is what `CLAUDE.md` asks for in general — *"if two files do the same
  thing, merge them"* — but it buys **0 files** here, and the reason is the
  closure measurement in §2: the refusal is asked over a module's body, so the
  41 files would each still import the one remaining copy and still be refused by
  it. Worth doing on its own merits; not a step towards this row.
* **The advice the message gives** — *"Print the parts as separate operands"* —
  is **wrong**, and following it would produce a wrong-but-exit-0 answer:
  `print("n=", n)` inserts a separator between its operands, so it is not the
  same text. This is why the row's marker is the missing buffer and not that
  sentence; a fix deletes the advice rather than keeping it.
* **A `char *` buffer in the frame scratch.** A formal value lives in a
  function's own stack scratch and is reclaimed when the function returns, so a
  composed string whose value outlives the frame that composed it has nowhere to
  live — which is the same reason `FORMAL_module_state_no_storage.md` §(2) is a
  project and not a patch.

## 7. The exact next step, for whoever takes it

**Do not start with an f-string.** Start with the ONE case that has a decidable
answer and no lifetime question, measure it, and only then decide whether the
general case is worth a project:

1. **A buffer with a compile-time-known bound, in the frame scratch, for a value
   that does not escape the frame.** `f"--backend={backend}"` and
   `f'ledger-{name}.json'` are the shape: literal chunk, one integer-shaped
   field, literal chunk, and the result consumed by the next call in the same
   function. The bound is computable at compile time (chunk lengths are known;
   a field's width is its declared type's), so this needs no heap and no
   ownership story. **It inherits two obligations** that are written down and
   not to be rediscovered: `formal/model.py::LENGTH_DEPENDENT_METHODS`'s note
   that a string literal's bytes are interned into `__TEXT,__text` mapped
   read+execute and **cannot be written** (so the composition must go in
   scratch, never over a literal), and
   `bugs/FORMAL_string_value_model.md` §"The cost": *"whoever adds the first
   method which can build a string at run time inherits the obligation"* — a
   composed string must carry its LENGTH, because `len()` on a bare `char *` is
   a `strlen` walk and the composed text is not NUL-terminated until it is
   written, and because **a string value here cannot contain a NUL**, which is
   latent today and stops being latent the moment a buffer exists.
2. **Then measure the residue with the same method as §5**: the ceiling of step 1
   is the number of the 115 files whose composed value does not escape its frame,
   and the residue is what decides whether step 1 was worth landing. Do not
   project it.
3. **A t-string's fields are TEMPLATES, not values.** `INTERPOLATED_LITERAL_PREFIXES`
   carries `t"` in the same set as `f"`, and a t-string's `{name}` is evaluated
   as a `text`/`format` template. Whatever answers an f-string has to say what it
   does with those, and refusing them is better than answering them as an
   f-string. **0 corpus files are affected today** (no `t"` literal appears in any
   of the 114), so this is a correctness note for step 1 rather than work.
4. **Both emitters, and the proof.** `formal/arm64_codegen.py` and
   `formal/x86_64_codegen.py` lower separately, and every decision of this kind
   in this backend lives in `formal/model.py` precisely so the two cannot answer
   differently about one source file. A composition decided in one emitter is a
   composition the other architecture silently spells differently.

## 8. Whose

**Unowned.** No live claim in `tools/control.py claims` and no other doc in
`bugs/` covers composition: `FORMAL_string_value_model.md` is about what a string
IS and is claimed (`formal16-7`), and its §"The cost" is where the NUL and length
obligations above come from. The instrument rows this branch added are in
`tools/formal_sweep.py::_REFUSAL_FAMILIES` and
`tools/formal_sweep_causes.py::CAUSES`; neither file is claimed.

**The two walls behind this row are not this row's to fix.** The bigger one — the
handler arm, 45 of the 115 files — is a refusal that is **correct**, and §5
measures that rather than asserting it: `formal` has no exception unwinder, a
`raise` flushes the enclosing `finally` clauses and exits, so no edge runs from a
raise site into an arm and every statement in an arm's body would be absent from
the program that runs. Its doc was deleted with the fix that established that,
and the claim `formal8-5` still carries its name; there is nothing to work on.
The other wall, `FORMAL_module_state_no_storage.md`, is **unowned** — the `-10`
map recorded it as `formal19-4`'s, and that branch has landed and released the
claim, so the 23 files behind `module_loader.py` are waiting on a project (an
exported slot: a symbol kind, a relocation the loader honours, and a lifetime
story in the proof) that nobody holds. The instrument rows this branch added are
in `tools/formal_sweep.py::_REFUSAL_FAMILIES` and
`tools/formal_sweep_causes.py::CAUSES`; neither file is claimed. The map for this
round is `bugs/FORMAL_sweep_work_map_2026-10-04_b11.md`.