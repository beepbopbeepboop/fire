# The ASSIGNED-TYPE evidence has no end-to-end case left

## Status

**Found while merging, not fixed.** The rule itself works and is now pinned
directly; what is missing is a program that exercises it end to end, and the
reason it cannot have one is written down here.

`model.struct_init_field_types` (and the `struct_field_assigned_type` wrapper
that reads it) infers a field's type from what `__init__` ASSIGNS it, for a
class that declares none of its fields. It is the second evidence source behind
`model.struct_field_type` and the one that made `Interpreter.scope` /
`ARM64Codegen.asm` / `Tail._chunks` lowerable instead of refused by name.

## What was measured

On the merged tree (formal-land + work/formal-cross-module), every program that
gave this evidence end to end now refuses:

    struct Inner:
        var a: Int
        var b: Int
        var c: Int
        fn total(self) -> Int:
            return self.a * 100 + self.b * 10 + self.c

    struct Outer:
        var tag: Int
        var pad: Int
        fn __init__(self):
            self.in1 = Inner()          # <- the only evidence shape
        fn go(self) -> Int:
            return self.in1.total() + self.tag

    def main(n: Int) -> Int:
        var o = Outer()
        o.tag = 5
        o.in1.a = 1
        o.in1.b = 2
        o.in1.c = 3
        return o.go()

    $ python3 test_formal_run.py assigned_type_refuse_a_nested_frame_constructed_in_init
      PASS  assigned_type_refuse_a_nested_frame_constructed_in_init
            (a construction of a struct whose receiver is a frame)

Before `work/formal-cross-module` (`dba31760`, "S() on a struct whose __init__
takes no required parameter RUNS it") that program built and answered 128 —
exit 0, nothing refused, nothing printed.

## Why

Two rules now cover the same shape, and they disagree.

1. `model.struct_construction_plan` reads `struct_init_shapes` BEFORE the
   zero-argument case, so `Outer()` selects the zero-required `__init__` and
   INLINES its body at the construction site. That is the language's answer and
   it is what fixes 34 stdlib files that silently read a zero.

2. `model.init_body_stores` refuses a body whose right-hand side constructs a
   FRAMED struct of this unit, because "its block is reserved per call SITE in
   the prologue of the function whose body names the call, and a body inlined
   into a construction elsewhere has no such site".

`self.x = T()` for a framed `T` is the ONLY shape
`model.assigned_value_base_name` classifies as a nested frame, so (2) removes
the only way to reach (1)'s evidence on a program that runs. There is no
alternative spelling that keeps the inference and lowers:

* declaring the field (`var in1: Inner`) types it — but from the DECLARATION,
  so the constructor evidence is not what types it any more;
* `Outer(1)` with a required parameter inlines the body just as eagerly, and
  hits the same refusal;
* a constructor parameter (`self.in1 = x`) is not classifiable by
  `assigned_value_base_name` — only literals, the three Python singletons and a
  construction of a name in `decls` are;
* a one-field `Inner` is not framed (`struct_is_framed` is False for those), so
  the store lowers — but then the evidence names a one-word struct, which is a
  different question, and none of the corpus's real cases (`Scope`,
  `Tail._chunks`, `Report`) has that shape.

## What was done about it, in this merge

* The seven end-to-end cases are rewritten to the spelling the refusal
  recommends — the nested frame DECLARED, the constructor storing words — so the
  placement guarantee they were really about (one block per construction SITE,
  writes through a nested frame, two objects not aliasing) is still pinned.
  `assigned_type_a_declaration_still_wins` became the refusal it now correctly
  is.
* The evidence itself is asked DIRECTLY, in
  `test_formal_run.py`'s `check_assigned_type_evidence`, over five parsed
  classes: the positive row, a row that classifies to nothing beside one that
  does, two rows that disagree, `decls` absent, and the literal row. Direct is
  the honest level for a rule about what an inference infers.

So the rule is tested, and the row it was originally written for — a class that
assigns a nested frame in `__init__` and declares nothing, which is what
`scripts/stage2_mojo_interpreter.mojo` and several stdlib classes are — is not
reachable. That is a real capability loss and not a cosmetic one.

## Next step

One of these, and the first is the smaller:

1. **Accept the redundant store.** When `Outer` DECLARES `var in1: Inner`,
   `struct_nested_frame_fields` already places an `Inner` block in `Outer`'s own
   and `Outer()` brings it up, so `self.in1 = Inner()` in a constructor stores
   the value the slot already holds. `model.init_body_stores` could drop that
   one store (and `struct_construction_plan` its `placed` check would stop
   firing) — the same value, the same program. That makes the DECLARED spelling
   work, but it still needs the declaration, so it does not by itself restore
   the assigned-type evidence; it only removes the refusal for the classes that
   happen to declare the field.

2. **Type the field from the constructor and place it anyway.** That is the
   original promise of this evidence source, and it needs a real layout
   decision: a nested frame constructed in `__init__` belongs in the CONSTRUCTOR
   OWNER's block (as the declaration's placement already puts it), not in a
   block reserved for the construction site, and `init_body_stores` would have to
   emit `Inner`'s own constructor stores into that placed slot rather than at
   the site. That is a generator change in both backends plus the frame-slot
   bookkeeping, and it is the change that makes a class like `Interpreter` lower
   again.

3. **Sweep the rows that are now refused and file the ones that are not the
   shape above.** `formal-sweep`'s "other refusal" table on the merged tree
   will say how much of the 616-file corpus each of these costs; the
   cross-module branch measured 34 zero-argument `S()` sites that this made
   refusals, of which the nested-frame ones are this doc's subject.
