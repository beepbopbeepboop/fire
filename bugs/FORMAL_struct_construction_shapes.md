# FORMAL_struct_construction_shapes: `S()`, `S(a, b, …)` and `S(x)`

Wave 5 (E2). The construction family. `S()` has lowered since wave 2; the other
two shapes had no lowering at all, and the three refusals that stood in for
them were **stale for the wrong reason** — a reason that was true before the
by-reference receiver gave a multi-field struct a block to fill, and stopped
being the reason at the moment that block landed.

**Status: all four shapes lower on both machines. `S()` is byte-identical to
before; `S(a, b)` and `S(x)` landed in wave 5; and a construction with arguments
on a struct that DECLARES an `__init__` — the fourth shape, added after this file
was written — lowers by inlining the selected constructor's stores at the
construction site. Every remaining refusal is named with the fact that is
actually wrong.** Two of wave 4's over-refusals are closed. The declared
`__init__` is why the arity message had to stop being a lie, and it is the
reason this file existed at all.

Wave 5's other groups are separate documents. This one is the construction
family and nothing else.

## The three shapes

| shape | before | after | why |
|---|---|---|---|
| `S()` | works | **works, byte-identical** | verified, not assumed: the `__TEXT,__text` disassembly of a two-field `Point()` program is the same 64 instructions (arm64) and 68 instructions (x86-64) before and after this change, and both binaries exit 5 |
| `S(a, b, …)` | refused: *"a struct is default-initialized and its fields assigned, and a 2-argument construction is not a shape this backend can honour"* | **works** — one store per argument at `base + 8k` in declaration order | the layout is `struct_frame_slots`; the block already exists |
| `S(x)` | refused: *"is a COPY CONSTRUCTION … What is missing is a lowering — on this path `R()` takes no arguments"* | **works** — a fresh block and an `n`-slot shallow copy | ditto |

The two refusals that were replaced are quoted above because their *reason* is
the finding: both said the shape did not exist, and both were wrong about a
program that had a block to fill since wave 3. `model.frame_constructor_refusal`
is **deleted** rather than reworded — a diagnostic whose whole content was a
missing feature does not become a diagnostic whose content is a different
missing feature.

## Why the other two are representable, and it is not a new instruction

A block built at a construction SITE belongs to the function the site is in, and
`_check_frame_escapes` refuses every channel by which it could leave that
activation: return, container, a field of another object, a non-first parameter
position. So the object is read only while its creator is on the stack, and a
word parked in one of its slots came from a live local of that function or of an
ancestor of it.

**This is also the difference from the assignment `o.inner = i`, which is
refused** — and the two look identical in the source, so the difference is worth
stating: in `o.inner = i`, `o` may be an object an ANCESTOR built, so the slot
outlives `i`'s creator and the next use of `o` reads reclaimed stack. At a
construction site the object is new here, so there is no such ancestor-built
object to be. Measured: a copy whose source arrived as a CALLEE's first
parameter is fine (`constr_copy_of_a_parameter_frame`), and the caller's own
fields are unchanged after the callee returns.

## The copy is shallow, and the evidence it does not alias

`constr_copy_does_not_alias`, run on both machines:

```python
struct Cell:
    var n: Int
    var m: Int
    var p: Int
    fn set(self, i, v): ...        # writes slot 0, 1 or 2
    fn get(self, i) -> Int: ...

def main(n: Int) -> Int:
    var a = Cell();  a.set(0, 3); a.set(1, 4); a.set(2, 5)
    var b = Cell(a)               # the copy
    b.set(0, 90); b.set(1, 91); b.set(2, 92)     # MUTATE THE COPY
    if a.get(0) != 3:  return 10 + a.get(0)      # 13 if the copy aliased
    if a.get(1) != 4:  return 20 + a.get(1)      # 24
    if a.get(2) != 5:  return 30 + a.get(2)      # 35
    if b.get(0) != 90: return 40 + b.get(0)      # 130 if the copy shared nothing
    if b.get(1) != 91: return 40 + b.get(1)
    if b.get(2) != 92: return 40 + b.get(2)
    return 7
```

```
$ python3 test_formal_run.py constr_copy_does_not_alias
  PASS  constr_copy_does_not_alias (7)
```

Observed, both architectures: **exit 7.** An implementation that handed back the
source's address — which is what `c = a` on a frame *is*, and so the reading a
frame design invites — returns 13, and a copy into a fresh zero block returns
130. Each field has its own return code, so a regression says which slot moved.
`constr_copy_reads_back_what_the_source_read` and
`constr_copy_in_a_loop_reuses_the_site` cover the other two directions (a copy
that reads back what the source read, and a copy at a site reused by a loop).

**Shallow is correct, not a shortcut.** A slot holds one word; a word that is a
frame address or a blob address copies as the address it is, which is what a copy
of a value-typed struct does in every language this path stands in for. Two
cases make the shallowness the ASSERTION rather than the absence of a decision:

* `constr_copy_of_a_nested_frame_shares_it` — the copy of a struct with a
  PLACED NESTED FRAME shares it, so `b.bump_inner()` is visible through `a`
  (231 → 331 on both). A "helpful" deep copy would make `a`'s nested frame read
  23 still. This is the language's semantics and the two objects are the same
  nested object, exactly as in Python.
* the blob case below, where the shared region is a container.

## The blob-in-a-field invariant, after a copy

**D2's premise covers the copy, and I had to add to it — one door.**

The hazard the brief names is real: a copy is the most likely place to
reintroduce a slot holding a dead blob. So the three doors onto one were
enumerated rather than assumed closed:

| door | state |
|---|---|
| **(B1)** an executed method writes a container into a field | refused, `check_frame_field_blob_premises` — D2's, unchanged |
| **(B2)** `__init__` assigns one | does not run — D2's premise, unchanged |
| **NEW: a construction argument that is a container returned by a CALLEE** | **refused by name** — `model.construction_dead_blob_refusal` |

The new door is the one this change opens, and it is refused on a *declared
return type*, not a guess:

```python
def mklist() -> List[Int]:
    var xs = [1, 2, 3]
    return xs

struct Bag2:
    var items: Int
    var n: Int

def main(n: Int) -> Int:
    var b = Bag2(mklist(), 5)     # refused
```

```
build: constructing Bag2 with the call to 'mklist' as field 'items' is refused
on this path: mklist() is declared to return a container, and a container on
this path is a bump-allocated region of the CALLEE's own reserved scratch, so by
the time the constructor stores it the bytes are reclaimed — …
```

**What is allowed, and why it is the same argument.** A container LITERAL
(`Bag2([1, 2, 3], 5)`) and a name bound here or in a caller are allowed: the
region is built by a function that is still running, so it outlives every read
of the slot. That is the confinement argument, not a gap — and
`frame_field_premise_note` now prints it as the premise's **third door**, so a
reader of a blob refusal can see all three rather than two.

**The residual, stated.** A call with **no declared return type** is allowed, and
this is the one place the tie-break runs the OTHER way from the copy's, on
purpose. A function that declares `-> Int` puts an integer in the slot whatever
it did internally, and refusing every unannotated call would refuse essentially
every positional construction in a real program (`Triple(2 + 3, scale(2) + 4,
scale(4))` is `constr_positional_expression_arguments`). An absent answer has to
be the permissive one HERE because a wrong word in a slot is a value the source
did not write, while a missed blob is only reachable if some method later
mutates the container through the slot — and **that is refused on its own terms
today**: `constr_append_through_a_field_is_still_refused` pins
`list.append() is not lowered on the formal … path` (the room an append needs
has to be known where the list is built, and a slot is not a list literal). The
day the append is lowered, that case is visibly false rather than quietly stale,
which is why it is a test and not a comment. What closes the gap properly is the
VALUE KIND of a call's result — `ValueKinds`' question, not a re-derivation.

## Wave 4's D5 over-refusals: both closed

**`String()` — CLOSED.** A zero-operand conversion was refused on a word COUNT.
It is answerable, and the reason is a property of strings and of nothing else
on this path: a literal is interned and NUL-terminated, so the address of `""`
**is** the empty string, `strlen` of it is 0 and `%s` of it prints nothing.
`String("")` already built and already had `len` 0, so `String()` is the same
word by another spelling.

```python
def main(n: Int) -> Int:
    var s = String()
    if len(s) != 0: return 20 + len(s)
    var t = String("")
    if len(t) != 0: return 30 + len(t)
    printf("[%s]", s)
    return 7
```

Observed, both architectures: **exit 7, stdout `[]`.**

`std/format/repr.mojo`'s `var string = String()` is the corpus site, and it is
no longer the first thing wrong with that file. A zero-operand conversion of any
OTHER type is still refused — 0 is not the empty `Pointer` and not the empty
`Int` in any sense this one-word value model can state.

**`DType` — CLOSED, and the hand-kept name list no longer masks the arity
rule.** `UNREPRESENTABLE_TYPE_CTORS` is a hand-kept list of NAMES, and a name in
it was refused outright — *"constructing DType has no representation on this
path"* — without anybody asking what the file being compiled DECLARES about
`DType`. In a file that declares `struct DType`, that declaration is the only
thing in hand that says what the name means. The list is a statement about types
this path cannot represent *abstractly*; a struct of one field is a plain word,
which is the most representable thing there is.

So the rule that was masked is the ordinary one, and **ARITY applies it**: a
call whose argument count matches the local declaration's field count is a
construction of that struct, and one that does not match is not.
`model.type_constructor_prefers_local_struct`, and the two exclusions are both
measured:

* only `UNREPRESENTABLE_TYPE_CTORS` is overridden, never the identity or the
  integer tables. `Pointer` is a struct some files here declare **and** an
  identity conversion, and `Pointer(to=stat)` over a struct's frame is the one
  hand-off in the whole family that is correct. Preferring the declaration there
  would change a program's MEANING rather than its verdict.
* the field count must match, so `Error()` in a file declaring a two-field
  `Error` keeps its refusal (`constr_refuse_undeclared_name_in_the_unrepresentable_list`
  is the negative guard, and it does not need that file to exist: arity decides).

Every change here is a change of VERDICT in one direction only — the
`unsupported` branch is a refusal today, so preferring the local struct can turn
a refusal into a lowering and can never change the meaning of a program that
already built.

## What must stay refused, and the one that was not in the brief

| refusal | the fact it names |
|---|---|
| arity | the argument count is not the field count, and the struct declares no `__init__` for it to call instead — the FIELD LIST is in the message, because it is the answer to "which argument is missing" |
| keyword | `S(x=1)` is a call the language spells positionally; reading a keyword as positional would make the program's meaning depend on dict order. **What would close it is named in the message**: match each keyword against `struct_frame_slots`, let the positionals take the rest in declaration order, require an exact cover. Decidable, and deliberately not done here |
| copy of another struct | a copy is a slot-for-slot copy, so it is defined only between two objects of the SAME layout |
| copy of an unrecognised word | nothing here can say the argument is a frame. **This is the refusal whose absence would be the worst outcome available**: `q` is a plain `Int` local, and copying slot 0 out of the word `7` would copy seven bytes of a stack frame and a count field. The program would build, run, and return a number nobody wrote. Absent answer IS the answer |
| copy from an ambiguous name | two candidate layouts and no path sensitivity, so there is no one layout to copy — `struct_frame_slot_candidates`'s question one level in, same answer |
| a frame address as a ONE-WORD struct's whole value | a framed object has a BLOCK and a block is confined; a one-field struct has no block, its receiver IS the field, and a plain word is passed around with no frame-lifetime check seeing it |
| an argument on a PLACED NESTED FRAME's slot | the constructor placed a frame in that slot, in the object's own block; storing a word over it leaves a value where `self.<field>.<field>` computes a frame base |
| a container returned by a callee | see the blob section above |
| **a declared `__init__`** | lowered, by inlining the selected overload's stores — and what the inline cannot supply is four separate refusals, see below |

### `__init__` — the refusal the brief did not ask for, and what closed it

This one was found by **running the sweep, not by reading the rule.** With the
arity check in place, `std/builtin/builtin_slice.mojo` reported

```
constructing Slice with 2 argument(s) does not match its fields
(3 field(s): start, end, step)
```

and that sentence is **false about the program in front of the reader.**
`Slice` declares TWO `__init__` overloads — a two-parameter one that assigns
`self.step = None` itself, and a four-parameter one with a defaulted fourth —
and the corpus writes `Slice(6, len(lst))`, `Slice(start, end)` and
`Slice(start, end, step)`. So `Slice(a, b)` is a call to the two-parameter
constructor, not a two-field construction of a three-field struct.

It was also the first blocking fact for **twenty stdlib files**, replacing a
correct deeper message with a false one. So `model.struct_init_overloads` reads
the shapes and the declared-`__init__` check fires BEFORE the arity one — as a
refusal first:

```
build: constructing Slice with 3 argument(s) is a call to a user-defined
`__init__`, not a field-filling construction: Slice declares 2 `__init__`
overloads (2 required (start, end); 3 required and 1 defaulted (start, end,
step, __slice_literal__)), and in Mojo a declared `__init__` is what `Slice(...)`
calls. This path does NOT run it — S() does not run __init__ — so every field of
a fresh Slice comes up at its class-level default …
```

The overload SHAPES are spelled, because "it has a constructor" is not actionable
and `Slice`'s two shapes are. `constr_zero_arg_still_ignores_a_declared_init` is
the guard on the other side: `S()` on a struct with an `__init__` is premise (B2)
and must keep working.

**That refusal is now a lowering.** The sentence "this path does NOT run it" was
true, and the conclusion drawn from it — that a construction with arguments is a
call whose body nothing here has lowered — did not follow. **A constructor does
not have to be CALLED to be RUN.** A body that is a straight line of
`self.<field> = <expr>` stores is the same program as the construction followed
by those stores, and the construction-followed-by-stores is a shape this path
has emitted since wave 5. So the argument COUNT selects the overload — the only
thing a call site carries, since nothing on this path resolves by type — and the
selected body's stores are the plan, emitted into the same fresh block at the
same site. `model.CONSTRUCTION_INIT` is the fourth shape.

Three things in `Slice` decide whether the family is answered, and all three are
in the source rather than in a general mechanism:

* the two-parameter overload's `self.step = None` is **the language's own
  singleton reaching an inlined body as a name** — not a parameter, not a local.
  `model._INIT_SINGLETON_NAMES` lets it past the free-name refusal, and both
  backends already materialize it to a word before `_load_var` is reached;
* the four-parameter overload's `__slice_literal__` is a parameter the caller
  omits and the body never reads, so the arity window is `required ..
  required + defaulted` and not the parameter count;
* a field the body does not assign **keeps its class-level default**, which is
  the language's rule (the object is default-initialized before the constructor
  runs) and is what `CONSTRUCTION_INIT` leaves by bringing every slot up first,
  exactly as `S()` does.

`StridedSlice.__init__` (`self._inner = Slice(start, end, stride)`) is the shape
that had to be got right in the other direction: that `Slice(…)` is a call in the
body of a method the backend emits in its own right, so it lowers as an ordinary
construction with its own reserved site, and nothing about it needs the inline.

**What is still refused is what the inline genuinely cannot supply**, each with
its own message and its own fix: a count no declared arity admits; a count TWO
overloads admit, which is a refusal rather than a choice because nothing here
resolves by type and picking either would be running a constructor the program
did not choose; a body that is not only those stores; a read of the receiver or
of a name the body binds, neither of which exists in the calling function; and a
construction of a framed struct, whose receiver block is reserved per call SITE
in the prologue of the function whose body names the call.

Measured on the 294-file stdlib sweep, before and after: **21 findings move out
of this family and no verdict changes class in either direction** (pass 24,
codegen 88, codegen/dependency 181, not-answerable 1, both runs). The 20
`builtin_slice.mojo` dependents land on the same single next fact —
`Slice___eq__`'s `other.start`, a field read through a method parameter — and
the twenty-first (`std/gpu/host/func_attribute.mojo`, the one in-file finding)
lands on the module-level symbol table gap, both recorded where they belong:
`bugs/FORMAL_method_param_field_access.md` and
`formal/build.py::_check_frame_escapes`'s own argument loop.

## Two wrong answers found and fixed, both from running things

**1. A refusal raised from the wrong place, as a `backend-crash`.** The
construction check was first written inside `_prepare_functions`, next to
`_check_frame_escapes`. Two things were wrong with that and neither was visible
without a sweep:

* it **preempted the import diagnosis** for **14 of this repository's 284
  files**, every one of them a file that imports a CPython host module, and all
  14 moved `not-answerable/host-import` → `codegen` — 14 unbuildable files into
  the measured denominator, the same drift D2 measured for
  `check_frame_field_blob_premises` and in the same direction. So it moved LATE,
  beside `check_frame_field_blob_premises`, at the two entry points where both
  facts are known (`formal/build.py`'s `check_construction_shapes`, two marked
  call sites);
* it **escaped as a raised exception** rather than a `FormalBuildError`, because
  both late call sites sit outside their function's `except CodegenError`. That
  is classified `backend-crash` — a verdict for a compiler bug, on a construct
  that is a refusal — and `std/gpu/host/func_attribute.mojo` measured it. Both
  call sites are now wrapped, which also fixes the same latent hole in
  `check_frame_field_blob_premises`'s dylib call site.

And a third thing about where the check lives, which is about ORDER rather than
diagnosis: a struct-constructor call has to be **skipped** by the escape check's
argument-position loop, because `S(a, r)` has a frame address in a non-first
position and that loop would refuse it as *"a position whose meaning this path
cannot see"* — a sentence about a construct that is a perfectly ordinary
positional construction.

**2. `AttributeError: 'SubscriptExpr' object has no attribute 'name'`, on four
stdlib files.** The dead-blob check read `arg.func.name` after a guard that only
covered `F.IdentExpr`, and `List[Self.T]()` has a `SubscriptExpr` callee. Four
files went to `backend-crash` — 4.4% of the stdlib's 71 `codegen` findings
briefly mis-binned. Fixed by refusing the whole shape (a subscript callee is a
type or an expression whose result this path does not follow, so nothing here
knows it is a container). It is the third wrong answer in this project's history
to come from a node-shape assumption rather than from a rule.

## Per-file status, the construction family

| file | scope | before | after |
|---|---|---|---|
| `regex_compile.py` | repo | `a Repeat frame address is passed to Repeat(), which is a COPY CONSTRUCTION … What is missing is a lowering` | `a Repeat receiver is returned from the function that created it` — the stale refusal is GONE and the next real fact is reported. D4's site |
| `stdlib_core.mojo` | repo + stdlib | `constructing StringRef has no representation` | same verdict, message now says *this image has no declaration of StringRef to construct* and names the local-declaration rule |
| `device_graph.mojo` | stdlib | `a DeviceGraphBuilder frame address is passed to _DeviceGraphBuilderEnqueuer(), which is a COPY CONSTRUCTION …` | `a _DeviceGraphBuilderEnqueuer, _DeviceGraphBuilderEnqueuer receiver is passed to DeviceFunction__call_with_pack_checked() in argument position 1` — the stale refusal is GONE. D4's second site |
| `repr.mojo` | stdlib | `String(...) takes exactly one value to convert on this path (got 0 argument(s))` | `value.write_repr_to() is a method call on a value` — D5's over-refusal CLOSED |
| `builtin_slice.mojo` (+20 dependents) | stdlib | `self.step.or_else() is an Optional unwrap` | `constructing Slice with 3 argument(s) is a call to a user-defined __init__` — a true fact about the same line, replacing a false one |
| `func_attribute.mojo` | stdlib | `writer.write() lowers to the C library's write(2) …` | `constructing FuncAttribute with 2 argument(s) is a call to a user-defined __init__` |
| `random.mojo` (+2 dependents) | stdlib | `constructing Error has no representation on this path` | same verdict, message names the reason (`this image has no declaration of Error to construct`) |

Nothing in the family newly compiles, and the honest reason is the same as
wave 3's and wave 4's: the file's first blocking fact moved one step down the
list, and the step it moved to is a different, true statement about the same
line.

## Open, with the next concrete step

Re-read on 2026-10-01, against the tree this branch is on. Two of the three
bullets this section used to carry are closed, and the third is the only thing
here that still earns the file its place in the queue.

* **A keyword construction — CLOSED.** `StringSlice(unsafe_from_ptr=p)` lowers.
  `model.keyword_construction_stores` matches each keyword against the field
  list BY NAME (the reading that cannot depend on dict order, which is what the
  old blanket refusal's reason was actually about), the positionals take the
  remaining fields in declaration order, a field neither reaches keeps its
  class-level default, and `CONSTRUCTION_KEYWORD` is the new plan kind — its own
  because the positional shape covers every field and this one need not. The
  three ways resolution can fail each have their own sentence: a keyword naming
  no field (the field list is in the message), a field given twice (CPython's
  `got multiple values for argument x`), and a declared `__init__` — which is
  not a rule left out but a shape the resolution cannot fix, because
  `CONSTRUCTION_INIT` selects the overload by argument COUNT and picking the
  widest or the first would be running a constructor the program did not choose.
  Measured before and after on both architectures: `P3(x=1, y=2)` built and
  printed `x=1 y=2` where the tree refused it; `P3(y=9)` with `x` defaulted to
  4 printed `x=4 y=9`; `P3(1, y=2)` printed `x=1 y=2`; and `W3(v=42)` on a
  ONE-field struct built too, which the emitters' pre-plan guards had been
  refusing. Seven cases in `test_formal_run.py` — four value rows, three
  refusals — replaced `constr_refuse_keyword_arguments`.
* **A declared `__init__` is not run — this bullet is STALE and the premise is
  gone.** The `__init__` section above records the landing: a body that is a
  straight line of `self.<field> = …` stores is inlined at the construction
  site, `Slice(6, len(lst))` lowers, and `Slice(a=1)` cannot because overload
  selection is by arity. What is left of premise (B2) is the four shapes the
  inline genuinely cannot supply, each with its own message, and they are in
  the `__init__` section rather than here.
* **The unannotated-callee residual** in the dead-blob check (above) — **still
  the one open item in this file, and as of 2026-10-03 (`work/formal8-11`) it is
  known NOT to be a change to `_kind_of_call`, which is what the next reader
  would try.** Closes with the value kind of a call's result, which is
  `ValueKinds`' question and not a re-derivation to be smuggled into the
  construction pass. It is a deliberate tie-break rather than an oversight (the
  refusal's own docstring argues the permissive direction at length), and
  `ValueKinds.own_shape_kind` wants the same provenance — the difference between
  a callee's DECLARED return type and the fallback word — so the two should be
  one change.

  **Measured, and it is a PLUMBING boundary rather than a table.** The check runs
  in `formal/build.py`'s `check_construction_shapes`, at PREPARE time, and every
  `ValueKinds` hook is owned by an EMITTER: `int_names`/`string_names` are
  `formal.types`' vocabularies, but `func_kind` needs `_vkinds_for`, which needs
  the emitter's own `_structs`, `_frame_candidates` and dylib tables, and
  `_callee_kind` is where a callee's return kind is decided — recursion-guarded
  against `_functions` and the image's export manifests. So `build.py` cannot ask
  the question without either duplicating `_callee_kind` (the one thing CLAUDE.md
  forbids, and the failure `_frame_candidates` exists to prevent) or the check
  moving to where a `ValueKinds` exists. Extracting `_callee_kind` into
  `formal/model.py` as one function both backends and the build pass call is the
  real shape of it, and it is a change to the kind path rather than to this
  family.

  **The residual is INERT today, which is why the cost of leaving it is a
  diagnostic surface rather than a wrong answer:** reaching it needs a method
  that mutates the container through the slot, and `list.append()` is refused on
  its own terms (`constr_append_through_a_field_is_still_refused`), so the day
  the append is lowered the case is visibly false rather than quietly stale.

  **What the same provenance question looks like when it CAN be answered**, since
  it is the shape of the fix and it is measured: `printf("[%s]", str(c))` on a
  one-field struct was a SIGSEGV for the same reason — a CALL's kind is not
  evidence, and `_own_shape_of` counts every call as none — and it closed by
  asking the OPERAND (`model.identity_conversion_operand` +
  `model.printf_arg_text_evidence`, 2026-10-03). That is the same "distinguish
  declared from inferred" rule with a reader that had the table to hand; the
  construction pass has no such reader, and that is the whole of the difference
  between the two.
* **No proof-side lemma was added or specified as needed.** NOT a bug and not a
  residual — a note, kept because it is the one thing on this list a reader of
  the generated proof would want and would not find. The copy is a load/store of
  `n` slots, so `Frame.frameRead_frameWrite_same` /
  `frameRead_frameWrite_ne` and the constructor's existing
  `frameWrites_window_preserved` fold already describe it — with ONE thing worth
  stating on the Lean side, which is a corollary rather than a new theorem and
  is specified here because `lib/` belongs to another group this wave:

  > `Frame.frameCopy_slots` — for `dest` and `src` frames of the same struct
  > that do not alias, writing slot `k` of `dest` from slot `k` of `src` leaves
  > every slot of `src` unchanged, and leaves every slot of `dest` other than
  > `k` unchanged.
  >
  > It follows from `frameRead_frameWrite_ne` and `frameRead_frameWrite_same`
  > plus the source/target disjointness already in
  > `frame_frames_no_alias_neqn`, so it is a corollary and not an induction.
  > It is worth having as a named statement because the emitter's copy is an
  > unrolled sequence of `LDR`/`STR` pairs and a reader of the generated proof
  > wants one lemma for the whole loop rather than `n` instances of the
  > per-instruction one — and because it is the property the aliasing evidence in
  > this document is an empirical argument for, which is a weaker kind of
  > evidence than a theorem.

* **`struct_constructor_sites` still reserves a block per site for a COPY,
  nested frames included, and a copy does not use them.** NOT a bug — the bytes
  are reserved and simply not written, and the alternative (sizing the
  destination's block from the shape) would make the block size depend on the
  call's arguments, which is a second layout decision for no gain. Recorded
  because the second half of the reason is the one that decides it and it is not
  obvious from the waste.

## Verification

Judged by the `detail` text, not the class label: the class labels moved under
this change four times before settling.

| command | before (wave 4, `/tmp/s6_*.txt`) | after |
|---|---|---|
| `python3 test_formal_run.py` | `PASS=162 FAIL=0` | **`PASS=196 FAIL=0`** (34 added; 31 of the 34 fail on the pre-change tree) |
| `python3 test_formal.py -j 12` | `PASS=40 KNOWN-GAP=3 FAIL=0` | unchanged |
| `python3 test_formal.py --backend x86_64 -j 12` | `PASS=43 KNOWN-GAP=0 FAIL=0` | unchanged |
| `python3 test_formal_dylib.py` | `PASS=11 FAIL=0` | unchanged |
| `python3 test_formal_imports.py` | `PASS=26`, 3 EXPECTED | `PASS=37 EXPECTED=0 FAIL=0` — **not this change**: `reflect.py` and `test_formal_imports.py` are E1's, mid-flight |
| `python3 test_formal_sweep.py` | `55 tests, OK` | unchanged |
| `python3 formal/x86_64_model_test.py` | `agree 43 WRONG 0` | unchanged |
| `python3 test_suite.py` | `43 passed, 0 failed` | unchanged |
| `tools/suite.py check` | `7/7` | `7 passed, 0 failed` |
| `tools/suite.py gate` | `15 passed, 5 skipped, 3 expected-failure` | **`15 passed, 0 failed, 5 skipped, 3 expected-failure`** (155 jobs, 231.7 s, peak 10.5 GB) |
| `stdlib-syntax` (`compile_stdlib.py`) | `FAILED: 0 (0 expected, 0 unexpected)` | **`FAILED: 0 (0 expected, 0 unexpected)`**, `PASSED: 664` — `U` did not increase, it is zero |
| `stdlib-dylib` | skip count 0 | **skip count 0** |
| `formal_sweep.py --no-stdlib -t 300 -j 10` | 284 files, `PASS=80`, coverage **80/120 = 66.7%** | 284 files, `PASS=80`, coverage **80/120 = 66.7%**; **0 class moves**, 2 detail changes, both this change's |
| `formal_sweep.py --no-stdlib --arch x86-64` | 284 files, `PASS=79`, 0 of 204 differing | **`PASS=79`, coverage 79/119, 0 of 204 shared files differ in detail text** |
| `formal_sweep.py -t 300 -j 10` | 578 files, `PASS=105`, coverage 105/403 = 26.1% | 578 files, `PASS=104`, coverage **104/403 = 25.8%**; 0 gained, 0 lost, 7 class moves all `CODEGEN/DEPENDENCY` → `CODEGEN` and **all E1's** (the `__mlir_attr` fix making a module refuse correctly instead of fabricating a value) |
| `formal_sweep.py --arch x86-64 -t 300 -j 10` | 578 files, `PASS=103`, 92 of 473 differing | **`PASS=102`, 59 of 471 differing — 0 of them construction-family**; all are the pre-existing `ptr.value()` x86-64 gap |

**The one lost stdlib pass is not this change's.** `std/builtin/type_aliases.mojo`
was a **false pass** in wave 4's 105 — wave 4's own report says so, naming it as
the file whose `__mlir_attr` refusal never fired — and it now has a real
`codegen` finding. `reflect.py` is modified in the working tree; that is E1's.

**24 of the 71 stdlib detail changes are this change's**, resolving to the seven
root files in the per-file table above; 47 are concurrent (`44` clearly E1's
`__mlir_attr` / export-rule work, `3` not this change's and not attributable from
the text). **Zero files gained a pass and zero lost one** in either scope and on
either architecture.
