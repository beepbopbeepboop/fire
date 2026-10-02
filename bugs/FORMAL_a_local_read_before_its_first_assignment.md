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