# FORMAL_a_subscript_on_a_frame_slot_is_a_pointer_dereference_and_the_two_backends_disagree: `s.d[0]` on an annotated field is a SIGSEGV on x86-64 and a refusal (or a SIGSEGV) on arm64

**Area:** FORMAL, both backends (the subscript choke point is shared; the
emitter gate is not). **Status: OPEN, measured on this tree, and it is the
worst failure mode this project has — an image that SEGFAULTS with no
diagnostic, and two architectures that disagree about the same source file.**
Found 2026-10-03 while landing the `DType`-annotated-field row of
`FORMAL_type_name_as_a_value.md` §5, whose own text names this operation: the
open item said that making a declared `DType` field a `TYPE_KIND` "would let
`len(self.t)` and `self.t[i]` take a new branch on a shape the corpus uses
(`std/testing/prop/random.mojo` and `func_attribute.mojo` both declare
`dtype: DType`)". `len()` turned out to be answered by the kind table. `self.t[i]`
turned out not to be answered by anything.

## What I ran

Every program is `s.<field>[0]` where `s` is a one- or two-field struct and
`<field>` is annotated with an integer type, so the slot holds a small number
and the subscript treats that number as a pointer.

    python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
        --no-prove --backend=<arch> -o .tmp/o .tmp/prog.mojo && ./.tmp/o; echo $?

| program | arm64 | x86-64 |
|---|---|---|
| `struct S: var n: Int = 5` ; `printf("%d", s.n[0])` | `build:` "subscript base must be a list/tuple name or literal on the formal arm64 path (got **IntLiteral**)" | **exit 139 (SIGSEGV)** |
| `struct S: var d: DType = 5` ; `printf("%d", s.d[0])` | same refusal, "got IntLiteral" | **exit 139 (SIGSEGV)** |
| `struct S: var d: DType = 5` **plus** `def __init__(out self, v: DType): self.d = v` ; `S(DType.int32)` ; `printf("%d", s.d[0])` | **exit 139 (SIGSEGV)** | **exit 139 (SIGSEGV)** |

CPython refuses all three (`TypeError: 'int' object is not subscriptable`), so
every row is a program no reader would write on purpose — which is the point:
the correct answer is a refusal on both machines, and one machine is
dereferencing a `5`.

**Row 3 is the sharp one: both architectures SEGFAULT, and arm64 does so only
because the field is constructor-established.** Rows 1 and 2 differ by
architecture; row 3 does not differ at all.

## Why arm64's message names `IntLiteral` and not the field

`formal/arm64_codegen.py`'s subscript gate accepts a base whose node is one of
`IdentExpr`, `CallExpr`, `ListExpr`, `TupleExpr`, `Comprehension`, `MemberExpr`,
`SubscriptExpr` and names anything else by its node type. `s.n` is a
`MemberExpr`, so the gate is not what refuses rows 1 and 2 — by the time the
gate is asked, the base has been rewritten. `formal/model.py`'s
`struct_field_kind` gate plus the one-field-struct rewrite (`_rewrite_self_fields`
and friends) turn `s.n` into the slot's **materialized default**, and the
message names the literal that default is. So the arm64 refusal is not "a
subscript on a frame slot is not lowered"; it is the residue of a base that
somewhere became a number, reported by the gate that happens to see it. That is
why the message is false about the file: the source says `s.n`, and `s.n` is a
field.

**A `DType` slot does not change this**, which is the measurement's other half
and the reason this is filed as its own defect rather than as a consequence of
the kind row: with the `DTYPE_TYPE_NAMES` row in place (the commit before this
one) all three rows are byte-identical to the rows without it.

## Where the fix belongs, and what it has to decide first

The subscript has a **shared** choke point — `ValueKinds.kind_of` is "asked from
both backends' single subscript/slice/membership/for-in choke point, so the two
architectures cannot come to disagree about which bases are containers" (its own
docstring). That is where the decision belongs, for the reason it is written
that way: a base whose kind is not a container must be refused **by name**, from
one place, before either emitter runs. Two things have to be settled by whoever
takes it, and neither can be settled by reading:

1. **Which reader answers "is this base a container".** `struct_field_kind` is
   gated on the slot holding something this path materializes (a literal default,
   a nested frame, or a constructor-established value), so it answers `None` for
   a field with no class-level default and no `__init__` — and `None` must stay
   the unclassified answer rather than becoming "not a container", or every
   unannotated field subscript in the corpus turns into a refusal that is about
   the analysis rather than about the program.
2. **What to do with `None`.** The corpus's own answer today is that a subscript
   on an unclassified base is a pointer dereference, which is right for
   `Pointer` and for `UnsafePointer` and wrong for everything else. That
   distinction is the whole of the fix: the refusal has to fire for every base
   kind EXCEPT the pointer ones, and the pointer ones need a row of their own
   (`POINTEE_WIDTHS` / `POINTEES_REFUSED` already exist for the pointee).

The narrower alternative — give x86-64 the arm64 emitter gate — is available and
is half a line, and it is **not sufficient on its own**: it would make the two
architectures agree on row 1 and row 2 and leave row 3 crashing on both.

## What is NOT the cause

* **Not `TypeKinds`/`TYPE_KIND`.** Measured with the `DType` row present and
  absent; all six answers identical.
* **Not the `DType` construct.** Rows 1 and 2 annotate the field `Int`, and row 1
  crashes on x86-64 with nothing type-value-shaped anywhere in the program.
* **Not the by-reference receiver.** `S` here is a one- or two-field struct read
  through a plain local; no method is involved.
* **Not a bounds check that could be taught the right answer.** A frame slot is
  one word and a subscript needs a pointer plus a stride; there is nothing in the
  slot to compute a stride from, which is why the answer is a refusal.

## The exact next step

1. Decide question 2 above by measurement, not by reading: take the repo's own
   `.mojo` files, find every `X.<field>[i]` whose base is a frame slot, and count
   how many have a base kind of `None` against a container kind. The count is
   what says whether "refuse every non-pointer base" costs coverage.
2. Add the refusal to the shared choke point, naming the base's spelling and its
   kind, and add it to `test_refusal_taxonomy.py`'s families.
3. Add the three rows above to `test_formal_x86_64_parity.py` as REFUSALS on both
   architectures, with row 3 as the one that crashes on both today.
4. Only then consider the arm64 emitter gate: with the shared refusal in place it
   is unreachable for these shapes, and leaving it costs nothing.