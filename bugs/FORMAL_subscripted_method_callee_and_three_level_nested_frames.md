# FORMAL_subscripted_method_callee_and_three_level_nested_frames: row 12's four files are two unrelated gaps, and neither one is worth lifting

**Status: found, measured, NOT fixed — and the depth-3 half re-measured on
2026-10-01 on BOTH architectures, which is the measurement this file was
missing.** Row 12 of
`bugs/FORMAL_sweep_work_map_2026-09-30.md` — "a field of a nested frame that the
struct does not declare", 4 files — filed 2026-09-30 with the measurement that
settles it. The map's row is a bucket of MESSAGES, not a construct: these four
files are two different constructs, and both are behind something else.

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

## The exact next step

1. A `_frame_nested_chain` table, keyed `"<holder>.<f1>.<f2>.<f3>"` → the ordered
   slot list, filled by walking `struct_nested_frame_fields` recursively rather
   than twice, and a `_load_var` arm that consumes the chain in one place. Both
   backends read it, so it belongs in `formal/model.py` beside
   `struct_frame_block_bytes` — the same reason that one does.
2. Replace the `split(".")[-2]` heuristic with the same walk, so the depth-2 and
   depth-3 arms cannot disagree about which level is the outer one. Do this
   BEFORE step 1: while the heuristic stands, a depth-3 chain reports a refusal
   about the wrong level and a fix looks like it did nothing.
3. A case per level: `struct Inner/Inner2/Outer` with `var a: Inner2` typed by an
   ANNOTATION first (which lowers today), then the same with the type coming from
   `__init__`, each with two objects so a shared innermost frame would show.

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
