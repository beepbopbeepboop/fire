# FORMAL_receiver_stored_in_a_field: a frame address in a struct field, and a parameter whose declared type no call site agrees with

**Status: row A is CLOSED. The delegating row builds, computes the right
number, and runs on both architectures; the 24 files were never a count of
what this blocked (see §0.1 for why they did not move). Row B is unmeasured
and is a different rule — its list needs a sweep, because the refusal compares
call sites inside one image and a parse-and-walk instrument cannot answer it.**

Both constructs were in the "other refusal" bucket until `fbaed39b` gave the
bucket markers for them, and both were unowned. They are one document because
they were measured together and they are the two rows a planner would otherwise
have to split by hand out of a 183-file bucket.

| row | files blocked | in-file | both arches | source |
|---|---|---|---|---|
| a receiver stored in a FIELD of a struct that outlives it | **24** | 24 | identical | `formal/build.py:4735` |
| a parameter's declared type contradicts every call site | **13** | 13 | identical | `formal/model.py:7110` |

## 0.1 What landed, 2026-10-03 (`work/formal13-6`): the PLACEMENT, and the
## three-step deadlock it was holding shut

Row A's rule (`_frame_field_store_is_sound`) was already in place and already
correct: `self.src = <a parameter>` is sound because the frame ARRIVED. What
§0 recorded as "the 24 files are still blocked, by a DIFFERENT and more
interesting rule" was a three-step deadlock between two decisions that were
each individually right:

1. `model.struct_nested_frame_fields` **PLACED** a nested frame in every field
   whose declared type names a framed struct of this module and whose only
   writer is `__init__` — the constructor reserving a block in the object's own
   block and storing that block's ADDRESS in the slot;
2. which made step 3's store **unsound**, so `_frame_field_store_is_sound`
   refused it — correctly, and with the more useful of the two messages;
3. and `_typed_nested_frame` answered `_REASSIGNED` at the read, because the
   placement list — the authority it consults, deliberately, so the emitter and
   the reader cannot disagree about which fields are placed — did not have the
   field in it.

**The constructor does not always BUILD a nested frame in the slot it was given
one for.** `self.src = r` where `r: R` is `__init__`'s own annotated parameter
stores the CALLER's frame, so the slot is a POINTER slot and reserving a block
for it is what made the store unsound in the first place. That is one predicate
over the constructor's own body, which is what §0 said the next step was.

```python
model.init_stores_a_parameter_struct(struct_def, name, decls)
```
— "every assigned value of `name` in `__init__` is a bare NAME of a parameter
annotated with a struct of this module". It is the evidence
`model.one_word_field_struct` was ALREADY asking for the same reason (a
delegating constructor is the commonest field shape in this repository's own
source), so that function calls it rather than the two walking `__init__` twice
and one of them learning a spelling the other does not. Unanimous-or-nothing,
and asked only AFTER `struct_nested_frame_fields`'s other three conditions, so
it can only ever REMOVE a placement and never invent one.

Two readers, and they need two different answers:

| | question | answer for a delegating field |
|---|---|---|
| `struct_nested_frame_fields` | does the constructor reserve a block here? | **no** — it stores an address, it does not fill a block |
| `_typed_nested_frame` | does a read of `holder.f.<field>` load `[slot + 8k]`? | **yes**, and it must answer with the STRUCT rather than `_REASSIGNED` |

`_REASSIGNED` would be the wrong ANSWER, not a cautious one: its own sentence is
"a frame belonging to whichever function ran the assignment", and for a
delegating field the only assignment is `__init__`'s and the frame in the slot
is the caller's. The caller is the frame the object is itself reached through,
and the two die together — which is the argument `_frame_field_store_is_sound`
already makes and which the placement was cancelling out.

Measured on **both architectures**, before and after:

```python
struct R:
    var a: Int
    var b: Int
struct Holder:
    var src: R
    var n: Int
    def __init__(self, r: R):
        self.src = r
        self.n = 1
    def total(self) -> Int:
        return self.src.a + self.n
def main(n: Int) -> Int:
    var r = R(); r.a = 7; r.b = 8
    var h = Holder(r)
    printf("%d %d", h.src.a, h.total())
    return h.src.a + h.n
```

```
before   build: a R receiver is stored in the field 'self.src', so it outlives
         the frame it names …   (both architectures, byte-identical)
after    printf: 7 8   exit 8   (both architectures)
```

Four cases in `test_formal_run.py`. The reader is a METHOD (`h.total()`) as well
as a field read (`h.src.a`), because the two go through different arms and a fix
that reached only the value-position read would leave the method receiver
refusing. One of the four is a case that **stopped being a refusal**:
`constr_refuse_an_init_store_over_a_placed_nested_frame` — the smallest source
that reaches the whole deadlock — is now
`constr_a_delegating_store_into_a_typed_nested_slot_builds` and asserts `6`,
because a reader who finds the placement predicate should be able to find in the
suite what it moved.

**And the "24 files" never moved, which is the finding worth more than the fix.**
Four of the 14 census sites are not this shape at all, and §5's census is
syntactic while the refusal's evidence is a derived holder set, so its count was
always an upper bound. The 24 was never a promise of 24 unblocked files: the same
caution `formal_sweep_causes.py` states as "FILES BLOCKED IS AN UPPER BOUND". What
the fix changes is that the SHAPE is now lowerable, which is what any of the 11
files that reaches it needs; **the number of them is a `tools/formal_sweep.py`
delta and that is the integrator's measurement, not this document's claim.**

**What did not change.** `self.f = t` where `var t = R()` was BUILT HERE is still
refused — `init_stores_a_parameter_struct` asks whether the store is a NAME of an
`__init__` parameter and a construction is not one — and a slot whose `__init__`
writes only some other field is still PLACED, which
`a_constructed_nested_frame_is_still_placed` pins (two objects, two frames,
because a placement that were shared would answer the first guard and fail the
second).

Verified: `test_formal_run.py` PASS=810 FAIL=0, and green on the placement's own
readers — `formal-frame-len`, `formal-returned-frame` (unchanged from its
measured 23/13 baseline, all 13 x86-64), `formal-cross-module`,
`formal-value-model`, `formal-x86-parity`, `formal-method-param-field`,
`formal-dylib`, `formal-bracketed-method-field-set`, `formal-receiver-position`,
`formal-read-before-store` (140), `formal-receiver-spelling`, `formal-toplevel`
(108), `formal-globals`, `formal-admitted`, `formal-frame-return-overloads`,
`formal-typed-flag`.

---

## 1. Row A: a frame address stored in a field — 24 files


### Smallest reproducer (12 lines, both arches)

```mojo
# .tmp/probe/f8.mojo
struct R:
    var a: Int
    var b: Int

struct Holder:
    var src: R
    var n: Int

    def __init__(out self, r: R):
        self.src = r
        self.n = 1

def main(n: Int) -> Int:
    var r = R(); r.a = 7; r.b = 8
    var h = Holder(r)
    return h.src.a + h.n
```

```
$ python3 fire.py build --formal --no-prove .tmp/probe/f8.mojo
build: a R receiver is stored in the field 'self.src', so it outlives the frame
it names by however long that object lives: the slot belongs to the function
that created THAT frame, and nothing here can say the two lifetimes agree on
this path: the receiver of a multi-field struct is the ADDRESS of a frame of
8-byte slots that belongs to the function which created it, so it can only be
read, written, copied, or passed as a method's receiver.
bugs/FORMAL_wide_receiver_by_reference.md records the design and what is still
open about it
```

**x86-64 refuses with byte-identical wording** (`--backend=x86_64`), which is
the point of the message being in `formal/model.py` / `formal/build.py` and not
in a backend: one construct, one answer, two machines.

The same program under CPython prints `8`.

### What it is NOT — three shapes that look like it and are already lowered

Measured while finding the reproducer, because the obvious three-line versions
all build and a reader will try them first and conclude the row is stale:

| shape | result |
|---|---|
| `h.src = r` where `h` is a plain local and `r` a parameter (`f4.mojo`) | **builds**, runs, exit 7 — correct |
| `h.src = R()` then `h.src.a = 7` (`f5.mojo`) | refused, but by a **different** message — `reads a field of a field through the receiver h` |
| `def keep(r: R) -> R: return r` with a `Pair()` local (`f1.mojo`) | **builds**, runs, exit 15 — correct |

So the refusal is specific: it fires when the stored thing is a **frame address
of a multi-field struct** (`self.src = r` inside a method, where `r` arrived as
this method's frame-holder parameter) and the target is a field of an object
that outlives the call. It is not "a struct in a struct", and not "a field of
a struct" — the first is a different row (`a field of a field`) and the second
lowers today.

### Why it is refused, and what would close it

`formal/build.py:4728` is a branch of `_prepare_functions`' holder-use walk:

```python
elif isinstance(node, F.AssignStmt) and isinstance(node.target, F.MemberExpr) \
        and isinstance(node.value, F.IdentExpr):
    _refuse_holder_use(fn, node.value, holders, by_name,
                       f"is stored in the field {_member_chain(node.target)!r}, …")
```

A multi-field struct's receiver is the ADDRESS of a frame of 8-byte slots
belonging to the function that created it (`FORMAL_wide_receiver_by_reference.md`).
Storing that address in `self.src` makes the slot outlive the frame by however
long the object lives, and nothing at the store site can say the two lifetimes
agree — the frame may have been created by the constructor and the object may
outlive the constructor by an unbounded amount.

The neighbouring `q[0] = r` (subscript store) branch of the same walk is
**RECORDED, NOT RAISED**, with its measured consequence in the comment there: a
subscript store built, ran, and returned **0** where the source says 7. The
field store is raised because the same store is measurable as a wrong answer
too; the difference is that the subscript store is common enough in the stdlib
that raising it cost 14 files a correct `not-answerable/host-import` class.

**The next step is the one `FORMAL_wide_receiver_by_reference.md` already
names**: a field store of a frame address is sound exactly when the object's
lifetime is inside the frame's, i.e. when the field's owner is itself a
frame-bounded value (a local, a parameter copy) rather than something returned
or heap-allocated. That is a placement question with a decidable answer in the
cases that matter, and the 24 files are worth measuring against it before any
of it is attempted — see §3.

## 2. Row B: a parameter's declared type contradicts every call site — 13 files

### Smallest reproducer (7 lines, both arches)

```mojo
# .tmp/probe/d4.mojo
struct Cell:
    var a: Int
    var b: Int

def fill(c: Cell) -> Int:
    return c.a

def main(n: Int) -> Int:
    var raw = 5
    return fill(raw)
```

```
$ python3 fire.py build --formal --no-prove .tmp/probe/d4.mojo
build: fill() declares 'c' as Cell, so it is compiled with 'c' as the ADDRESS
of a frame of 8-byte slots, where every field is a load at `base + 8k` — and
every call site in this image hands it something else: fill(raw) passes a name,
'raw'. Reading a field through a word that is not the thing the declaration
promised is a load from wherever that word points, which is a wrong answer
rather than a failure, so it is refused rather than emitted. Call fill() on a
Cell value at every call site — a local built from Cell(), or a field declared
as Cell — which is the same program with a value this path can place
```

**This one is load-bearing and the refusal is right.** Lifted, `c.a` is a load
at `[word + 8k]` where the word is the integer 5 — the same family
`formal/model.py:6795`'s sibling documents as *measured, builds, runs, and dies
with SIGSEGV (exit 139)*.

**Note what this reproducer is: a program CPython already rejects**
(`AttributeError: 'int' object has no attribute 'a'`). That is deliberate for
the message — it is the smallest source that makes the declaration and the call
site disagree — and it is exactly why §3 says to measure the 13 for
correctness BEFORE measuring them for coverage. A row of programs that are
already wrong is a stdlib bug, not a compiler gap, and the two want different
work. It is the declared-type half of a pair:

| rule | compares | message | files here |
|---|---|---|---|
| the call sites with **each other** | `frame_holder_disagreement_refusal` | `One parameter, two kinds of value` | 2 |
| the call sites with the **declaration** | `frame_declared_parameter_refusal` | `every call site in this image hands it something else` | 13 |

The second rule exists because the first cannot answer this case, and the
docstring at `formal/model.py:7085` says why: the first needs at least one
call site that passed a frame to compare the others against, and a parameter
classified purely by its annotation (`Slice.__eq__(self, other: Self)` in a
module where nothing calls it) leaves that list empty — and "empty" read as
agreement compiles a field read into `ldr [word, #8k]`. It is a **different
rule, so it is a different cause**, and that is why they are two rows in the
map and two samples in `test_refusal_taxonomy.py`.

**The 13 files are not 13 bugs.** The refusal fires on a *contradiction*
between a declaration and its call sites, so it needs a program that is
already inconsistent — in `std/base64/base64.mojo` it is
`b64encode(input_bytes: ImmSpan[Byte, _], mut result: String)` called as
`b64encode(input_bytes, result)`, i.e. the annotation and the call disagree
about what `result` is. Before investing, measure how many of the 13 are a
contradiction in the source (CPython raises or returns nonsense) versus a
correct program the walk has mis-classified. **That is the first thing to do,
and it is cheap:** for each of the 13, the terminal message already names the
function and the parameter.

## 3. What must be measured before either is fixed

Per the standing instruction on this work (`FILES BLOCKED` is an upper bound),
neither row's 24 or 13 is a promise:

* **Row A, 24 files.** Lift the field-store branch behind a temporary guard,
  re-sweep the 24, and record where each lands. The `builtin_slice.mojo` row is
  the precedent for what to expect: 20 files that move onto
  `self.step.or_else() is an Optional unwrap`, which is a true fact about the
  same line and was tracked in `FORMAL_struct_construction_shapes.md` (`git rm`'d
  2026-10-03 when the construction family closed). Expect a
  similar landing, and expect the ceiling to be well under 24.
  **Still open after §0.1, and still the integrator's measurement:** the fix
  removes the SHAPE's blocker, and how many of the 24 reach it is a sweep delta
  this document does not claim.
* **Row B, 13 files.** Cheaper and prior to any change: for each of the 13,
  check whether CPython raises on the same source. A file whose program is
  already wrong is not blocked by a backend gap, and a row of those is a stdlib
  bug rather than a compiler one.

Both measurements are small sweeps (13 and 24 files) and belong to whoever
picks up the enqueued claim.

## 4. Reproducing every number here

```console
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove .tmp/probe/f8.mojo      # row A, arm64
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove --backend=x86_64 .tmp/probe/f8.mojo
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove .tmp/probe/d4.mojo      # row B
$ python3 tools/formal_sweep_causes.py --min 4 .tmp/sweep-arm-b3.txt    # both rows
$ python3 tools/formal_sweep_causes.py --min 4 .tmp/sweep-x86-b3.txt    # identical counts
```
## 5. Row A measured without a sweep: the shape is a DELEGATING CONSTRUCTOR

§3 asks for the 24 to be lifted behind a guard and re-swept. A sweep is a
30 s timeout per file over 630, and this question does not need one: the
refusal fires in `_prepare_functions`' holder-use walk, so parse plus one
method walk answers it — the same instrument
`bugs/FORMAL_read_before_store_what_is_left.md` used, and for the same reason
(a file refused for an import never reaches this check).

    `recv.field = <a name that can hold a multi-field frame>`:
      14 sites in 11 files   (this repository + the stdlib, 667 files)
        13  the value is a PARAMETER of the method
         1  the value is neither a parameter nor a local (myinterpreter.py:303)

and **13 of the 14 are an `__init__`**:

    std/builtin/builtin_slice.mojo:203   __init__   self._inner = other
    std/collections/deque.mojo           __init__   self._deque = _deque
    std/collections/dict.mojo            __init__   self._dict = _dict
    std/collections/interval.mojo:392    __init__   self.interval = interval
    std/collections/linked_list.mojo     __init__   self._list = _list
    std/collections/list.mojo            __init__   self._list = _list
    std/collections/span.mojo            __init__   self.src = src
    std/memory/alloc.mojo:248            __init__   self._layout = _layout
    std/python/_cpython.mojo             __init__   self.version = version
    std/benchmark/bencher.mojo           __init__   self.metric = metric
    (and one more, `std/python/python_object.mojo:76`)

**That decides the question §3 called a lifetime analysis.** The hazard is a
field outliving the frame it names; here BOTH sides are the CALLER's: the
owner is the receiver, which arrived as this method's own parameter, and the
value is another parameter of the same method. Neither frame belongs to the
method that stores it, so neither dies at its `return`, and the store is sound.
The rule the measurement selects is therefore decidable and short:

> A field store of a frame address is sound when the field's owner and the
> stored frame are both frame-bounded in the SAME function — which, for a
> method, means both are parameters of it.

**NOT FIXED HERE, and the reason is the verification rather than the rule.**
Lifting the branch needs the holder set (`fn._frame_holders`), which exists
only for a file that survives everything checked before it, and the payoff has
to be measured by BUILDING the 11 files on both architectures — a sweep, which
is the integrator's and not a light worker's. A narrower rule landed without
those 11 builds would be a change to what the compiler accepts with no
evidence behind it, which is the trade `FORMAL_read_before_store_what_is_left.md`
warns about in the other direction.

**The instrument's one weakness, stated because it decides how the 11 is
read.** A name "holds a frame" here means it is a parameter annotated with a
multi-field struct of its own file, or is assigned from a construction of one.
The refusal's own evidence is the holder set, which is derived rather than
syntactic, so **11 is an upper bound** and the real number is ≤ 11 — the same
direction as the doc's 24, and for the same reason. A first cut of this census
used "the name has a method called on it" and reported 52 sites in 19 files,
of which 28 were a word (`.strip()` on a string is not a frame); that is
recorded because it is the mistake a syntactic census of this shape invites,
and the tightened filter is what makes the 13 readable. The instrument is
`tools/formal_frame_field_census.py`, and both filters are named in its
docstring so the next reader starts from the tightened one.

Row B is unchanged and unmeasured here: `frame_declared_parameter_refusal`
compares a parameter's annotation with what the CALL SITES in the same image
pass, so its list is an image-level fact and no parse-and-walk instrument can
produce it.

```console
$ python3 tools/formal_frame_field_census.py     # the census above; 14 sites in
                                                # 11 files, 13 of them a
                                                # delegating __init__
```
