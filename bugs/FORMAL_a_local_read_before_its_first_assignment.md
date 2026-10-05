# FORMAL_a_local_read_before_its_first_assignment: the general rule, and why only the module-global case is enforced

**Status: the module-global case is FIXED (refused, both architectures, with the
filing's proposed correction). The general rule is NOT enforced, and this
document is the measurement that says what enforcing it would cost.**

The filing it corrects is `bugs/FORMAL_local_shadows_module_global` on
`work/merge2-formal`, and the correction matters more than the fix, so it comes
first.

---

## The filing's premise is false, and the fix it proposes would have made it worse

It says:

> CPython: the right-hand `G` resolves in **module** scope (nothing local is bound
> yet), so it reads 5, computes 6, and binds 6 as a **local**.

Measured, CPython 3.14, the same text:

```
G = 5
def bump():
    G = G + 1
    return G
print(bump())
```

```
UnboundLocalError: cannot access local variable 'G' where it is not associated
with a value
```

A name assigned **anywhere** in a function body is local to that body from its
**first line** — that is Python's rule and it is decided when the function is
compiled, not while it runs.  So the read has no home, CPython refuses to run
the program, and there is **no number it has**.

The filing's next step follows from the false premise: "make the gate
order-dependent rather than function-wide … `_module_global(name)` returns the
slot when `name` is in `_fn_bound_now` only if it is not one of the function's
declared `global` names".  That would make this path answer **6** — a number
CPython never produces, and a wrong answer that looks right, which is the worst
outcome this backend has.  The rule cannot be made order-dependent because
there is no order: a local is a local throughout.

## What this path did instead, measured

`G` is in the function's local set, so `_substitute_module_constants` correctly
leaves the read alone (a local shadows the module's name — that part of the
filing is right) and the emitter reads the name's **local** home, which has never
been initialised:

| | answer | the module's `G` |
|---|---|---|
| CPython | `UnboundLocalError` | 5 |
| arm64 | **78152773** | 5 (correct) |
| x86-64 | **11** | 5 (correct) |

Two architectures, two numbers, neither of them written by the source, and the
difference between them is register allocation — the signature of a value that
was never computed.

## What landed

`formal/build.py::_collect_shadowed_global_reads` +
`formal/model.py::shadowed_module_global_read_refusal`, parked and raised from
`check_shadowed_global_reads` at the two entry points (the sixth late check, for
the measured reason the other five are: `_prepare_functions` runs before
`_resolve_imports`, so a refusal from inside it preempts the import diagnosis).

## The scope limit, which is a measurement and not a preference

The language's rule is general — reading **any** local before its first
assignment raises.  Enforcing the general form was measured with a syntactic scan
(`_bound_before_first_statement` and `_assign_target_names` are the functions the
implementation reuses, and the scan's exclusions are the ones that decide the
number):

| rule | repo | stdlib |
|---|---|---|
| any local read before its first assignment | **233 sites in 57 files** | **8 sites in 5 files** |
| …and the name is also a module-level binding of this unit | **0 sites in 319 files** | **0 sites in 294 files** |

The scan already excludes a call's **callee** (not a read), a **`global`**
declaration (the name is not a local at all), every **loop / `with` /
comprehension target** (bound before the value is evaluated), and a **tuple
target's own name** (the value is evaluated before any store, so `a, a = 1, 2` is
legal while `a = a + 1` is not).  57 files of this repository is a coverage cost
of a different order from the one site the module-global rule fixes, and a
refusal that fires on 57 files without the full suite behind it is a worse risk
than the wrong answer it replaces.

With the name **also** bound at module level the collision is unambiguous: the
source is visibly asking about the module's binding, and the alternative reading
is the one CPython rejects.  So that is the rule that shipped, and it is the
filing's program.

### A FOURTH artifact class, found by fixing a different bug on 2026-10-02

The list above is the one the filing measured, and it is missing the class that
`read_before_store` itself walked into while fixing `with … as y:` — see
`FORMAL_arm64_slice_concat_and_with_refusal` §1 and commit 07b724f2.

A **`with … as y:` alias** is a binding that happens before the value the body
sees, exactly like a `for` target, and the read-before-store walk added it to
`stored` AFTER walking the body. So

```mojo
def main():
    x = 0
    with 7 as y:
        x = y
    return x
```

was REFUSED — on both architectures, not one — with a message naming
`UnboundLocalError` for a program CPython does not run at all (`with 7` is a
`TypeError: 'int' object does not support the context manager protocol`).  The
constructor is `formal/model.py`'s `read_before_store`, so it is a scan of the
SAME tree this rule is about, and it is the second time one of these shapes has
been counted wrongly rather than missed: a syntactic rule's whole difficulty is
the ORDER in which a name comes into existence, and `for` targets got it right
while `with` aliases did not.

**So the class is not "a callee, a `global`, and a binding that happens before
the value" — it is every construct that BINDS before the value it exposes, and
the ones already handled are `for` and `with`.** The next candidates, neither
measured here: a `match` statement's capture pattern, and a comprehension's
`async for` target. Both are the same question asked of a shape the scan does
not yet descend into, and both are cheap to check by extending the scan's
exclusion list rather than by reasoning about them.

**The re-measurement this implies, and it is not free:** the 233 sites were
counted with a scan that did not know about the `with` alias, so the number is
now an OVERCOUNT by however many `with … as y:` bodies read `y`. That direction
is safe — it means the true figure is lower — and it is one of the three things
to redo before the 233 means anything.

### A FIFTH artifact class, and it is not about a statement shape at all: an
### EDGE the CFG has that the language does not (FIXED, 7633d9e4)

The four classes above are all "a name is bound somewhere this scan did not
count".  This one is the opposite: no binding is involved, and the analysis
invents a PATH.

`formal/model.py::_build_cfg` ended with

```python
entry = new([])
entry.succs += run(body, [], [entry.index])
```

`run` returns the blocks that **fall off the end** of a run.  Inside the body
that list is exactly what a caller needs — they are the join's predecessors. At
the TOP level it has no use at all, because control leaves the function there,
and attaching it to `entry.succs` invented an edge from the entry block to every
block the function can end in.  The entry block's OUT set is `seed` and nothing
else: the parameters the CALLER stores.  `_definitely_stored` intersects
predecessors, so the entry's set erased everything the body had stored, and every
read at the END of a function was reported.

The shape that reached the corpus is a **trailing `for`**, because a loop's
`latch` is a fall-through whenever the loop is the last statement — so every read
of a loop target inside the body of a trailing loop was refused:

```python
def resolve_extern(self, target_addrs):
    for sym_name, pos, instr_len, kind in self.extern_refs:
        if sym_name not in target_addrs:      # refused: 'sym_name' at line 775
            raise ValueError(...)
```

That is `formal/arm64.py`'s `Assembler.resolve_extern`, verbatim, and it is why
`formal/arm64.py`, `formal/macho.py` and `formal/macho_linker.py` were all
`codegen` / `codegen/dependency` behind one method.  The same edge also refused
`if n: p = 1 else: p = 2` followed by a bare `sink(p)`, and `try`/`with` whose
bodies all store followed by a bare read.

**Why every existing case missed it: they all end in `return`.**  `return` has no
successor, `run` returns `[]`, and there is no edge to invent.  The gap is
invisible in a table of shapes precisely because the table is made of `return`s.

**Why dropping it is the sound direction, and not a weakening:** the edge could
only ever REMOVE a name from a set, so it could only ever invent a refusal and
never miss one.  `test_formal_read_before_store.py` gained ten rows in the same
direction, including the two that must STAY refused — a trailing loop's body
store read after the loop (`range(0)` reaches the read) and a trailing `while`'s
— so "this removed a false refusal" and "this did not weaken the rule" are
pinned in the same file rather than one of them being argued.

## The sibling the filing did not mention: `global` and no storage

```
G = 5
def bump():
    global G
    G = G + 1
    return G
def rd():
    return G
```

This one the language **allows**, and the value model has nowhere for it.  There
is no `__DATA` slot to redirect a write into — a formal value lives in a
function's own stack scratch, reclaimed when the function returns — so both
emitters treat `global` as a no-op and the assignment lands in a local:

| | `bump()` | `rd()` |
|---|---|---|
| CPython | 6 | 6 |
| arm64 | **10601485** | 5 |
| x86-64 | **11** | 5 |

Four wrong numbers, two of them architecture-dependent, from a program whose
every line is ordinary.  `model.mutated_module_global_refusal` reports it, in the
same pass.  This is the "a module-level name the build cannot fold is a real
mutable-or-computed global with nowhere to live, and is REFUSED BY NAME" family —
applied to the case where the name *is* foldable and the program nonetheless
writes it, which is the same fact seen from the other side.

## What still has to keep working, and is pinned

A local that shadows a module global **without declaring `global`** is correct on
this path and must not be refused: the local gets its own home and the module's
value is untouched, which is exactly what Python does.  Pinned as
`a_local_may_shadow_a_module_global_and_the_module_keeps_its_value` —
`s=99 r=5 g=5`, CPython's answer, on both architectures.

## A SIXTH artifact class, and it is not a binding at all: a COMPREHENSION has
## no scope here, so its target reads as an unstored local (FIXED, 2026-10-02)

The five classes above are all "a name is bound somewhere this scan did not
count". This one is the opposite shape twice over: the name IS bound, in a
scope of its own, and counting it as a binding of the ENCLOSING function is what
made the analysis wrong.

```python
G = 5

def f(rows):
    var out = [G for G in rows]     # the comprehension's own G
    return G + out[0]               # the MODULE's G: CPython answers 6
```

REFUSED on both architectures, with a sentence that is false about CPython in the
strongest available way — *the program runs*:

    build: f: 'G' is read at line 5 before anything in this function stores it,
    and CPython raises UnboundLocalError for that program

**The cause is that `_names_bound_in` was answering two questions.** The register
allocator's `bound_names_in_order` reports a comprehension's target — correctly,
because the emitter gives that name a home — and `_names_bound_in` is the reader
of "does this name shadow a module binding", which has a different answer: a
comprehension is its own scope in Python 3, so its `for … in` target binds
nothing in the enclosing body. Two readers now, and the split is the whole fix:

* `_names_bound_in(fn)` — what the body WRITES. Unchanged, because
  `placed |= _names_bound_in(fn)` needs the comprehension's target in it.
* `_function_locals(fn)` — what SHADOWS a module binding:
  `_names_bound_in(fn) - _comprehension_scoped_names(fn)` plus the parameters
  back. Read by `_substitute_module_constants`, `_apply_imported_constant_sites`
  and the `own` set of the read-before-store check.

**Subtracting inside `_names_bound_in` instead is the mistake worth recording**,
because it looked equivalent and broke ten cases: `test_formal_run.py`'s
`compr_single`, `compr_nested`, `compr_nested3`, `compr_over_literal`,
`compr_condition`, `compr_in_for`, `truthy_comprehension_guard` and three more
all lost their loop variable's HOME and were refused with "a name in none of them
is refused rather than read out of whatever register the allocator left
behind". Placement and shadowing are different questions and they need different
sets; that is the lesson, and it is measured rather than argued.

**The second half is not optional, and it was masked rather than absent.**
`_apply_module_constant_sites` reached inside a comprehension, so once the name
stopped counting as a local the substitution would have rewritten the
comprehension's ELEMENT — `[5 for G in rows]`, a different program. The
generator targets now come off the site table for the comprehension's own
subtree, which is what makes `[G for G in rows]` mean the loop variable and
`[G for x in rows]` mean the constant: two programs, one name, and the
difference is entirely in the target. Both are cases in
`test_formal_globals.py` now, in both directions.

**The interpreter had the same bug and is filed separately**, because it is a
different file and a different risk. `fire.py run` answered 3 where CPython
answers 6: `eval_Comprehension` evaluated a list/set/dict comprehension in the
ENCLOSING scope, so the comprehension's target leaked out and shadowed the
module global. Its own docstring called that "a known minor fidelity gap" — a
`known` with no reproducer is the kind of note that outlives its reason. Fixed
2026-10-04 (`eval_Comprehension` now pushes a child scope for the walk, the
shape `_generator_expression` already used); pinned by
`test_interp_oracle.py`'s
`a_comprehension_does_not_shadow_a_module_constant`, and this file's own case
below got its third engine back when it did. The compiled path has the same
defect by a different mechanism — the comprehension's target becomes a plain
local of the enclosing function — and that half is
`bugs/CODEGEN_a_comprehension_target_is_a_local_of_the_enclosing_function.md`.

### The two candidates this section named, measured

* **A `match` statement's capture pattern: NOT APPLICABLE on this front end.**
  `fire_compiler.py::MatchStmt` is switch-style equality dispatch and its
  docstring says so — "Deliberately not full PEP 634 … Real Python match
  statements treat a bare lowercase name in a pattern as an irrefutable capture"
  is explicitly declined, with ONE exception (an unbound bare name is treated as
  a capture by `myinterpreter.py`, for a guard clause to have something to test).
  So a capture is not a binding this scan can be blind to, because there is only
  the one narrow exception and it binds nothing the enclosing function reads.
* **A comprehension's `async for` target: NOT EXPRESSIBLE.**
  `[x async for x in rows]` does not parse: `fire_compiler.py:5331`
  `_expect("RBRACKET")` → `Expected RBRACKET got NAME('async')`. There is no such
  target to count, which is a stronger answer than an exclusion would have been.

## Next step for the general rule, in the order it should be done

1. **Make the scan cheap enough to run on every file, every time.** The three
   artifact classes above are the difference between 233 and a real count, and
   they are exactly the places a syntactic rule has to be careful: a callee, a
   `global` declaration, and a binding that happens before the value.  A third
   artifact class is likely — a nested `def`/lambda inside the body has its own
   locals and must not be attributed to the outer one, which
   `model.iter_nodes` does not distinguish from an ordinary walk.
2. **Then measure again, and split by what the name is.** `x = x + 1` with no
   module binding anywhere is far more likely a typo in ordinary code than a
   scoping question, and a refusal on it would be defensible but expensive; the
   same shape on a name that IS a module binding is a real collision.  The 233
   sites need that split before the number means anything.
3. **Do not make the gate order-dependent.** See the premise section: there is no
   order.