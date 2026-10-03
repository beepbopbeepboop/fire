# FORMAL_subscripted_method_callee_and_three_level_nested_frames: row 12's four files are two unrelated gaps, and the three-level half is FIXED

**Status (2026-10-03, `work/formal8-11`): the THREE-LEVEL NESTED FRAME half is
FIXED — the doc's steps 1, 2 and 3 all landed, measured before and after on BOTH
architectures. The SUBSCRIPTED METHOD CALLEE half is untouched and still has the
measured ceiling of zero its own section records.** What was measured when this
file was written, and what is now true, in that order.

## What landed, and what each step turned out to be

**Step 2 (the walk) — done, and it was the whole of the diagnostics.** Both frame
arms spelled a chain's outer field as `chain.split(".")[-2]`, which is right for
a depth-2 chain and wrong for every deeper one: `o.inner.inner2.x` reported the
slot `o.inner2`. `formal/build.py`'s `_nested_frame_levels` now walks the layout
level by level through `_typed_nested_frame` — the one place
`struct_nested_frame_fields`' placement is decided — and returns the placed
frames in order plus the level it stopped at and why. One walk, asked by the
value-position read AND the method-receiver arm, so the two cannot disagree about
which level is the outer one. For a depth-2 chain the walk IS the old
heuristic's answer (one level, `parts[-2]`), which is why every existing message
is unchanged and why the depth-2 suite did not move.

**Step 1 (the third load) — done, and NO EMITTER ARM WAS NEEDED.** The doc's
worry was "a representation neither table has". There is one, and it was already
there: both `_load_var` and `_store_var` resolve a `_frame_nested_slots` key by
loading the chain with its last field removed and indexing the frame that leaves,
so a key whose own PREFIX is in a table is one more level of that recursion and
nothing else. Filling every prefix (`_fill_chain_levels`) is therefore the whole
of the depth-3 half — which is also why the three other readers of
`_frame_nested_slots` (arm64's `_collect_var_names` guard, x86-64's MemberExpr
store, its augmented-assign target) become correct for the deeper chain by the
same change rather than needing a decision each.

**Two CRASHES the doc did not know about, both found by RUNNING the result.** The
emitter's placement recursion unpacked FOUR values out of
`model.struct_nested_frame_fields`, which returns three, so it worked only while
no nested frame had a nested frame of its OWN — the list was empty and the unpack
never ran. A struct whose nested struct has a nested struct of its own raised
`ValueError: not enough values to unpack (expected 4, got 3)` from the
CONSTRUCTOR, on both architectures, which is the class a sweep files as a
compiler bug and which is reached by any depth-2 nest the moment the ACCESS path
stops refusing it. And `_emit_frame_return`'s re-basing read the FLATTENED
placement, which has no parent left in it, so a level-2 frame's address would
have been stored in the TOP object's slot at the grandchild's index — a silent
wrong layout behind the crash. Both loops are now recursions over a new
`model.struct_block_direct_children` (ONE level, with the parent in hand;
`struct_block_children` is written in terms of it, so the offset arithmetic
exists once and the bytes reserved are the bytes addressed).

**Step 3 (a case per level) — done, four of them in `test_formal_run.py`:**
`byref_three_level_nested_frames_read_and_write`,
`byref_three_level_nested_frames_two_objects_no_alias` (two objects, because "the
innermost frame is shared" is the wrong answer a single object cannot see),
`byref_three_level_chain_through_a_one_field_struct` (a struct of ONE field at
the third level, where the chain is not a frame access at all and the one-word
rewrite collapses it — the case that caught a fill putting the collapsed key in
the wrong table), and `byref_three_level_chain_with_the_type_assigned_in_init`
(the type coming from the nested struct's `__init__`, which is `struct_field_type`
's "assigned" evidence rather than its "declared" one).

Measured, both architectures, before and after:

    o.inner.inner2.x = 5; o.inner.inner2.y = 6; o.inner.z = 7; o.w = 8
    printf("x=%d y=%d z=%d w=%d", o.inner.inner2.x, o.inner.inner2.y,
           o.inner.z, o.w)

| | before | after |
|---|---|---|
| arm64 | REFUSED: `… the word in the slot o.inner2 is a value, not a struct …` | `x=5 y=6 z=7 w=8`, exit 0 |
| x86-64 | REFUSED, identical message | `x=5 y=6 z=7 w=8`, exit 0 |

**`std/collections/string/iterators.mojo` was still not swept past the new
refusal boundary** — this session was not permitted to run a `formal_sweep`, so
its own ceiling stays unknown and the doc's claim that the fix is worth its cost
for that file is still unmeasured. Everything below about the SUBSCRIPTED
callee is unchanged and is the other half of this row.

## What the four files actually are

Row 12's terminal message is `… reads '<name>' out of a nested <Struct> frame, and
that struct's <fields> has no such field`, raised at `formal/build.py`'s
depth-2 value-position arm. Read as a message that is "a nested frame has no
such field". Read as a program it is three distinct shapes:

| file | the construct | next refusal once the first is lifted |
|---|---|---|
| `std/runtime/asyncrt.mojo` | `self._handle._get_ctx[_AsyncContext]()` — a **subscripted callee** | `_REASSIGNED` on `self.counter`: `TaskGroup` ASSIGNS that field |
| `std/memory/arc_pointer.mojo` | `self.strong.fetch_add[ordering=Ordering.RELAXED](1)` — same shape | `codegen/dependency` on `std.atomic` → `_assembly.mojo` `inlined_assembly` + a private-name export rule — **both documented true limits** |
| `std/utils/index.mojo` | `self.data.get[idx]()` — same shape | receiver passed in argument position 0 of 2 — row 4 of the map |
| `std/collections/string/iterators.mojo` | `self._slice._slice._data += n` — a **three-level nested frame read** | not measured; the depth itself is the gap |

## The measurement, and what it rules out

Lifting the call-receiver misrecognition in a scratch copy — teaching
`_call_receivers` to also treat `CallExpr(func=SubscriptExpr(obj=MemberExpr))` as
a call on that MemberExpr — and re-sweeping the three subscripted files:

```
$ python3 tools/formal_sweep.py ../modular/.../arc_pointer.mojo \
      ../modular/.../asyncrt.mojo ../modular/.../index.mojo
CODEGEN/DEPENDENCY: arc_pointer.mojo  (std.atomic → _assembly.mojo: inlined_assembly …
                                            + the private-name export rule, §1.1/§1.2)
CODEGEN:             asyncrt.mojo    (self.counter … a method of TaskGroup ASSIGNS that field)
CODEGEN:             index.mojo      (an IndexList receiver is passed … in argument position 0 of 2)
[arm64] 3 files: PASS=0 not-pass=3
```

**0 of 3, and none of the three next refusals is the shape being lifted.** One is
a permanent limit of the target (`inlined_assembly` is a gimple-C runtime
construct, and the export rule is `doc/ABI.md`'s), and the other two are row 4 and
row 9 of the same map — the receiver-position and frame-lifetime families, each
bigger than this. So row 12's measured ceiling is zero, the same result rows 2, 3
and 10 produced, and the honest reading of row 12 before this was "one message
bucket covering a recogniser gap, a permanent limit, and a three-level frame
chain".

The scratch patch was **not** landed, and the reason is not just the zero: the
bracket arguments are not one thing. `recv.m[ordering=X](1)` is a keyword
argument, `recv.get[idx]()` is a compile-time TEMPLATE parameter, and a
recogniser that accepts both has to know which — a decision about Mojo's call
syntax, not about the frame layout, and one this path has no table for.

## The depth-3 gap, re-measured on both architectures (2026-10-01)

The file's measurement was arm64-only and its "NOT measured" list had two
entries; one is now closed and the other is closed for the construct (though not
for the one stdlib file that decides whether the fix is worth its cost).

**Depth 2 works, on both architectures:**

```
struct Inner:   var x: Int; var y: Int
struct Outer:   var inner: Inner;  var w: Int
o.inner.x = 5; o.inner.y = 6; o.w = 7; printf(…, o.inner.x, o.inner.y, o.w)
    ->  x=5 y=6 w=7        arm64 AND x86-64
```

**Depth 3 is refused, on both architectures, with the same message from each:**

```
struct Inner2:  var x: Int; var y: Int
struct Inner:   var inner2: Inner2;  var z: Int
struct Outer:   var inner: Inner;     var w: Int
o.inner.inner2.x = 5
    ->  build: o.inner.inner2.x reads a field of a field through the receiver o:
        a frame slot holds one 64-bit word, and the word in the slot o.inner2 is
        a value, not a struct, so there is no second layout to …
```

**The message is about the wrong LEVEL, which is the "exact next step" below
confirmed as a live defect rather than a note.** The source spells
`o.inner.inner2.x`; the refusal reports the slot `o.inner2`, which is not a
spelling the source uses and is not the slot whose layout was consulted. Depth 3
is TWO layout questions — does the slot `inner` hold a frame, and then does the
slot `inner2` of THAT frame hold one — and the refusal collapses them into one
and names the second level's field as if it were the first. `formal/build.py`
reconstructs the outer field as `chain.split(".")[-2]`, which is a string
operation standing in for a walk of `struct_nested_frame_fields`, and the walk
is what has to replace it: a depth-3 chain reports the wrong level precisely
because the outer level is spelled out of the chain rather than read from the
layout.

So the next step is unchanged and its ORDER is now the measured one: **step 2
before step 1**, because while the heuristic stands a depth-3 fix looks like it
did nothing.

## The three-level chain is the one with real work in it

`iterators.mojo` is not a recogniser problem. `self._slice` is declared
`var _slice: StringSlice[Self.origin]` — a nested frame, placed — and
`StringSlice._slice` is another, so `self._slice._slice._data` is three loads:
the outer slot, the middle slot, and `_data` out of the innermost placed frame.

The machinery is already built for three: `struct_frame_block_bytes` recurses,
`MAX_NESTED_FRAME_DEPTH` is 4, and `struct_nested_frame_fields` recurses. What
is one level deep is the ACCESS path. `_frame_receivers` builds

* `_frame_slots["<holder>.<field>"]` — ONE load, and
* `_frame_nested_slots["<holder>.<field>.<field>"]` — two,

because a `_frame_slots` entry is one load and the emitter's `_load_var`
intercepts one. A three-load access needs a representation neither table has, and
the code says so where the tables are built: "a `_frame_slots` entry is one load
and this is two, and a two-load access with a one-load table entry is a wrong
answer rather than a failure."

Note also that `build.py`'s depth-2 arm reconstructs the outer field as
`chain.split(".")[-2]`, with the comment "the chain is spelled rather than
reconstructed because `self.a.b.c`'s outer field is `b`, not `a`". For
`self.a.b.c` that heuristic reads the wrong slot, and the refusal it produces
(`StringSlice … has no such field`) is about `self._slice._slice` rather than
about `self._slice` — a message about the wrong two levels of the chain.

## The exact next step — LANDED 2026-10-03 (`work/formal8-11`)

Kept verbatim as written on 2026-10-01, because what it asked for is what landed
and the reasons it gave are the reasons it worked:

1. ~~A `_frame_nested_chain` table, keyed `"<holder>.<f1>.<f2>.<f3>"` → the ordered
   slot list, filled by walking `struct_nested_frame_fields` recursively rather
   than twice, and a `_load_var` arm that consumes the chain in one place.~~ **The
   table is `_frame_nested_slots` with every PREFIX filled, and the `_load_var`
   arm turned out not to be needed** — its nested branch already recurses through
   the prefix. See "What landed" above.
2. ~~Replace the `split(".")[-2]` heuristic with the same walk.~~ **Done, and
   first, as this said it had to be:** `_nested_frame_levels`.
3. ~~A case per level … typed by an ANNOTATION first, then the same with the type
   coming from `__init__`, each with two objects.~~ **Done, four cases** (the
   one-field third level is a fifth shape the list did not have, and it is the
   one that is not a frame access at all).

**What is left of this file is the SUBSCRIPTED CALLEE recogniser**, whose next
step is unchanged and still unclaimed: `recv.m[ordering=X](1)` is a keyword
argument, `recv.get[idx]()` is a compile-time TEMPLATE parameter, and
`recv.f()[k](x)` is a subscript of a call's result — a recogniser that accepts
them all has to know WHICH, which is a decision about Mojo's call syntax and not
about the frame layout, and its measured ceiling on this corpus is zero.

## What was measured, and what was not

* The table above and the re-sweep, on arm64, on this tree plus the
  `__init__`-assignment change.
* **STILL NOT measured: what `iterators.mojo` refuses on after a depth-3 fix.**
  The file was not swept past the first refusal, so its own ceiling is unknown;
  it imports `std.collections.string`, so the `codegen/dependency` chain below it
  is likely to be where it lands. Sweeping it is a `formal_sweep` run, which this
  session was not permitted to do, so it stays open — and it is the entry that
  decides whether step 1 is worth its cost.
* **x86-64 — MEASURED for the construct, 2026-10-01.** The map and the sweep
  behind it are arm64-only; the ACCESS PATH is not. A three-level nested frame
  read is refused on x86-64 with the IDENTICAL message arm64 gives, because
  `_frame_nested_slots` and the depth-2 value-position arm live in
  `formal/build.py` and are shared. That is the property step 1 needs and it now
  has it measured: a `_frame_nested_chain` table filled by walking
  `struct_nested_frame_fields` recursively belongs in `formal/model.py` for the
  same reason `struct_frame_block_bytes` does, both backends read it, and so
  neither can disagree about how deep a chain goes.
