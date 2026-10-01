# FORMAL_subscripted_method_callee_and_three_level_nested_frames: row 12's four files are two unrelated gaps, and neither one is worth lifting

**Status: found, measured, NOT fixed.** Row 12 of
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
* **NOT measured: what `iterators.mojo` refuses on after a depth-3 fix.** The
  file was not swept past the first refusal, so its own ceiling is unknown; it
  imports `std.collections.string`, so the `codegen/dependency` chain below it is
  likely to be where it lands.
* **NOT measured: x86-64.** The map and the sweep behind it are arm64-only.
