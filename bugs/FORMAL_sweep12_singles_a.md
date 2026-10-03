# FORMAL_sweep12_singles_a: the §3.2 single-file causes, first half — what landed on 2026-10-03 and what is left

**Claim** `sweep12:ctor-self-and-singles-a`. This is the state of ONE HALF of
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.2's single-file causes, plus the
two rows that map names separately. It is a STATUS document, not a queue entry:
every cause below is either fixed here, fixed by somebody else, blocked on a
cause another claim holds, or not makeable from a repository worktree — and the
last three are exactly the things the next reader would otherwise re-derive.

**Re-measured on the tree this ran on, both architectures**, because the map's
numbers are from `master` at `e7fbe6ef` and a file's terminal cause is the FIRST
refusal its walk reaches, so a cause can be overtaken by a refusal that did not
exist when the map was written. `python3 tools/formal_sweep.py <files> -j 1 -t 120`
per architecture; the arm64 lock was held by another worker for part of the
session, so the re-measurement is on x86-64 with a direct
`fire.py build --formal --no-prove` for the arm64 half.

## 1. Fixed here

| cause | files | what landed |
|---|---|---|
| a constructor body that reads `self` is not inlined | 2 (`module_spec_gen.py`, `mojo/backend_gimple/spec_gen.py`) | `model.init_receiver_rewrite` resolves the receiver against the block the construction reserved: a method call is lifted to a real call with that address as its receiver, a one-level field read is a load at `block + 8·slot`. Both emitters answer two new shared nodes. 9 cases in `test_formal_run.py` (4 CPython-pair, built and run on both architectures; 5 refusals for what is left). |
| `field(default_factory=F)`: nowhere to keep a per-instance value | 1 (`formal/x86_64_decode.py`) | `Insn.extra` was `field(default_factory=dict)` and is read and written NOWHERE in the repository — every `extra` in that module is a local counting bytes after a ModRM byte. Deleted. |

Both are `git rm`-free: neither had a doc of its own. The map named the first as
unowned (§5.2) and the second only as a line in §3.2's prose.

## 2. Fixed here, and it moved the file to a cause that is NOT mine

| cause | files | what landed | what the file hits next |
|---|---|---|---|
| struct construction: arity does not match the fields | `formal/x86_64_decode.py` (reached from the row above) | `DecodeError(msg)` is a construction with one argument and the struct declared no slot for it; it declares `args` now — the field CPython's `BaseException` already fills from those arguments and `str(e)` already reads, so the language never sees the declaration. | `Insn(offset=…, **kw)` — filed, see §5 |

**The row itself belongs to `sweep12:singles-b`** (`formal12-singles-b`), whose
example is `mojo/backend_gimple/device_glue.py`'s `LaunchError`. The fix is the
same one-line declaration and belongs to that file's owner; only `DecodeError` is
mine, because it is the one standing between my assigned file and a build. If
that owner lands the `LaunchError` half, the two are one rule and the docstring
in each should say so.

## 3. The file's TERMINAL cause is another claim's, so fixing my cause moves no number

This is the single most important thing in this document, and it is why two of my
rows produced no coverage.

| file | my cause (fixed or not) | the refusal that actually comes FIRST, on both architectures | that refusal is |
|---|---|---|---|
| `determinism_trace.py` | `_v == '1'` compares a number with a string | `os.environ reads 'environ' out of the imported module os` | `FORMAL_module_state_no_storage` (`formal8-7`) |
| `module_spec_gen.py`, `mojo/backend_gimple/spec_gen.py` | the constructor receiver (FIXED) | `` `FileNotFoundError` as e `` is a handler arm with a body this path cannot put in the image | an `except` arm: no unwinder, so no edge runs from a raise site into an arm. `formal8-5` holds a claim named `FORMAL_except_arm_is_never_emitted` — **and there is no such doc in this tree**, so the claim's switch cannot be checked; whoever holds it should either restore the doc or drop the claim |
| `formal/x86_64.py` | `base.value` on a `Reg` parameter | the same — it IS the terminal cause | filed here, §5 |

`determinism_trace.py`'s own row was worth fixing on its own merits and is worth
fixing at all, so here is the measurement: `_v = os.environ.get('MOJO_TRACE', '')`
leaves `_v` unclassified, a word is an `INT_KIND` by default, and `==` against a
string literal then reaches a `strcmp` that would dereference the integer.
Annotated (`var _v: String = …`) it lowers and answers CPython, measured. The
root cause is not the annotation, though — it is that an unannotated local bound
from a callee's return has no kind, which is `bugs/FORMAL_string_value_model.md`'s
recorded next step ("propagate the CALL SITE's argument kind into the callee …
or refuse `if <word>:` when the word is unclassified") and is
`bugs/FORMAL_string_value_model`'s holder's territory. **Not done here**, and it
should not be: annotating `_v` in one file would be a workaround in the source
for a gap in the kind table, which is the shape CLAUDE.md's "no special-casing
an input" rule exists to prevent.

## 4. Not makeable from a repository worktree

Four of the eight causes in this half are refused **in a stdlib file**, and the
stdlib is a separate checkout (`../new-modular/Mojo/stdlib/std`) that no worker
in this batch may edit. The map already says so (§5: "a stdlib edit"), and it is
repeated here per file because the fix for each is a specific edit and a future
reader should not have to re-derive it.

| stdlib file | the refusal | what the fix is |
|---|---|---|
| `std/builtin/float_literal.mojo` | `FloatLiteral.__init__()` both changes its receiver and returns a value, and on this path the word a one-field struct's mutating method hands back IS the receiver | split it into a method that changes the receiver and returns nothing and one that reads it — `formal/model.py`'s `receiver_writeback_name` names the rule. **FIXED 2026-10-03** (`work/formal15-mutator-return-abi` `11558f0d`): the one-field mutator's receiver is handed over by reference, so the return register carries the declared value and this refusal is gone. `test_formal_run.py`'s `one_field_mutator_with_a_return_value_is_refused` was the row that pinned it and no longer exists; the shape is now an ANSWER (`one_field_mutator_that_also_returns_a_value`). This file's verdict moved on to the next construct in its body — measured, arm64 and x86-64: `FloatLiteral___int__: self.__int_literal__().__int__(…) cannot be lowered: dispatch here is BY NAME`. |
| `std/builtin/len.mojo` | a `...` stands where this path needs instructions to emit | write the function, or declare it a `trait` method (a `...` in a trait method builds on both architectures) |
| `std/builtin/none.mojo` | `writer.write_string()` is a method on a `Writer` — a multi-field struct, so the receiver is a frame address, not a descriptor | a real lower, or the call written at the use site; lowering it as a write passes a frame address as `fd(2)` and the output goes missing rather than wrong-looking |
| `std/math/polynomial.mojo` | `comptime num_coefficients = …` does not fold to a compile-time constant | make the initializer literal, or bind it with `var` and read it at run time |

## 5. Filed from this session

- `bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md` — `S(a=1,
  **kw)`, found by clearing §4 of §2 above. Not in any list; the refusal is
  correct and the doc carries the minimal reproduction, both architectures, and
  the two ways out.
- `bugs/FORMAL_an_enum_typed_parameters_field_has_no_layout.md` — `base.value`
  on a `base: Reg` parameter, which is my §3.2 row for `formal/x86_64.py`.
  Measured at **1 file in 668**, with the four-step design written out, because
  the design is the deliverable and the sizing is what a reader needs first.

## 6. Not attempted, and why

**`a String method that returns a SHORTER string writes the receiver's bytes`**
(`strip`/`rstrip`; `mlir.py`, `mojo/middle/metal_ops.py` — 2 files, named in my
task as one of my two rows). The refusal is right and the doc that owns the
decision already says what the fix is: the string stays a bare `char *`, interned
into `__TEXT,__text` with `initprot 0x5` — read+execute, **no write bit** — so
`strip` needs a terminator written over the receiver's first trailing whitespace
byte and the receiver's bytes cannot be written. `bugs/FORMAL_string_value_model.md`
names the missing piece itself: "a one-character String is a two-byte object and
this representation has nowhere to put it … a missing buffer", and the family it
belongs to (`LENGTH_DEPENDENT_METHODS`) is refused rather than lowered.

That doc is **claimed** — `python3 tools/control.py claims` lists
`bug:FORMAL_string_value_model` against `formal10-5` — so editing it, or landing
a second string-representation decision beside it, is out of bounds for this
claim. What is missing is a writable per-call-site byte buffer, which is a
value-model change shared by both backends AND by the Lean proof, and it is a
project rather than a patch. Left alone deliberately.

## 7. What the integrator has to know about the merge

This branch's base is `c5ab524d`; `master` was at `0b6394ab` when the merge was
checked, and **both sides edited the same two functions** — `master` replaced
`_init_store_value`'s `_construction_arg_is_dead_blob` call with
`construction_arg_dead_blob_refusal` / `CalleeReturnTable`, and this branch
inserted the `init_receiver_rewrite` call immediately above the free-name check
in the same function.

Measured by patching this branch's diff onto a `git archive` of `master`:
**6 of the 7 files apply cleanly and 1 hunk of `formal/model.py` conflicts** —
that one hunk, and nothing else. The resolved form (what the merged tree runs,
and what passed below) keeps both sides:

```python
    lifted, receiver_refusal = init_receiver_rewrite(
        struct_def, value, call, decls or {})
    if receiver_refusal is not None:
        return (None, receiver_refusal)
    free = _init_free_names(struct_def, value)      # the ORIGINAL right-hand side
    if free is not None:
        return (None, free)
    refusal = construction_arg_dead_blob_refusal(   # master's half
        struct_def.name, "of this `__init__`", value, rets)
    if refusal is not None:
        return (None, refusal)
    return (lifted, None)
```

On that merged tree, with no other change: `test_formal_run.py` **769/769**
(master's cases plus this branch's nine), `test_refusal_taxonomy.py` 185/185,
`test_formal_method_param_field.py` 26/26, `test_formal_value_model.py` 43/43,
`test_dataclasses_formal.py` 63/63, `test_formal_specialization.py` 10/10,
`test_x86_64_decode.py` ok, `test_struct_formal.py` 178/178 (one earlier run of
it read 176/178 and is the known intermittent `calcsize` hang,
`bugs/FORMAL_a_calcsize_image_hangs_once_in_several.md` — three later runs all
178/178).

## Reproducing any row above

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- \
  python3 tools/formal_sweep.py formal/x86_64.py formal/x86_64_decode.py \
    determinism_trace.py module_spec_gen.py mojo/backend_gimple/spec_gen.py \
    -j 2 -t 120 --arch x86_64
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-7.txt   # §3 of the map
```
