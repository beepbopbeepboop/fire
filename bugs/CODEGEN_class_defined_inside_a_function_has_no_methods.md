# CODEGEN: a `class` defined INSIDE a function has no working methods — every call is stubbed to the receiver's own value

**State: OPEN, found 2026-10-01 while closing
`CODEGEN_call_through_subscript_callee_stubbed.md`, mechanism located at the
call site, not fixed.** It is a silent wrong value with exit 0, and it is not
the subscript-callee bug it was found next to.

## What I ran and what I saw

```python
def run():
    class Inner:
        def __init__(self, v: int):
            self.v = v
        def twice(self):
            return self.v * 2
    i = Inner(21)
    return i.twice()

print(run())
```

| | CPython | compiled |
|---|---|---|
| `run()` | `42` | **`21`**, exit 0, no diagnostic |

`21` is `i`'s own field, so the method body never ran: the call was replaced by
the receiver. The generated C says so outright:

```c
_t3 = _t2;  /* int64_t.twice() stubbed */
```

Moving the `class` to module scope makes it correct with no other change, and so
does calling the method on a module-level class from inside a function — the
trigger is where the `StructDef` is *written*, not where it is used.

A second symptom, with the class written inside `main` and a bool-annotated
field (found while chasing the subscript callee, and it is the same root cause
at the other end):

```python
def main():
    class C:
        def m(self, x):
            return x * 2
    c = C()
    print(c.m(4))          # CPython 8   ->  compiled 0
    dd = {}
    dd['m'] = c.m
    print(dd['m'](4))      # CPython 8   ->  AttributeError: m, exit 1
```

The `AttributeError` is the honest half and the more useful clue: the bound
method `c.m` never became a `MojoBoundMethod *` at all (it stayed a plain
`int64_t` receiver word, and `_note_dict_callable_ret` had nothing to record —
`value_ctype` was `int64_t`, not `MojoBoundMethod *`), so the later
`dd['m'](4)` lowered to a `d['m']` read followed by a generic attribute lookup
on a value that is not a `C`.

## Mechanism

`gen.struct_field_types` has no entry for a `StructDef` nested in a function
body. `_lower_MemberExpr`'s method-call arm resolves the receiver's struct from
that table (`emit_exprs.py`'s `_pst` lookup and `emit_methods.py`'s candidate
search both key on `name in gen.struct_field_types`), finds nothing, and falls
into its stub branch — which yields the receiver, so the answer is "right" for
the zero-argument case by accident and wrong for every other one.

The pass that seeds the table iterates `all_struct_defs`, so the question is
whether a function-body `StructDef` is in that collection at all.
`gimple_codegen.py`'s struct collection walks module-level statements; a
`StructDef` nested inside a `FunctionDef.body` is not one of them. That also
explains why the CONSTRUCTOR works — `Inner(21)` lowered fine, so the ctor is
found by a different route than the methods are.

## Exact next step

1. Confirm the collection: print whether the nested `StructDef` appears in
   whatever `all_struct_defs` is built from
   (`module_gen.gen_module_impl`, the loop that seeds
   `self.struct_field_types[_s_name] = {}`). If it is absent, that single fact
   is the whole bug and the fix is to collect nested `StructDef`s into the same
   list, hoisting them to a module-level struct name the way
   `_gmi_collect_self_assigns` already folds a nested class's fields onto the
   ENCLOSING struct (`mojo/middle/module_shared.py`'s explicit `StructDef`
   descent, and its comment on why `_walk_ast` does not recurse into a nested
   `StructDef` reliably self-hosted — the same descent has to be written out
   here).
2. That fix should make `c.m(4)` work on its own. The `dd['m'](4)`
   `AttributeError` is the follow-on: once `c.m` really is a
   `MojoBoundMethod *`, `_note_dict_callable_ret`'s `MojoBoundMethod *` source
   records the container and the subscript callee lowers through
   `mojo_fnptr_call_N`. Check that rather than assuming it.
3. **A nested class's name must not collide** with a module-level one of the
   same name (`class Inner` in two different functions). Whatever hoisting
   scheme is used has to disambiguate, the way `_struct_cname_by_id` /
   `_selfhost_register_gimplegen` already do for same-name structs across
   modules.

## Why it is worth a session

A class defined inside a function is ordinary Python, and it is how a factory
that needs a closure over local state is usually written. Today every method
call on such an object returns the receiver, silently, at exit 0 — so a program
using one is wrong in a way no test in the tree notices, because nothing
compiles one.

## Scope note

This is a compiled-path gap, so a fix owes a full `make gate`; the repro needs
no imports, no collision and no build, so nothing heavier than
`test_gimple_runner.py` is needed to check it. Regression belongs there as
`test_gimple_stdout("gimple_nested_class_methods", ...)` with CPython's exact
text — and the `dd['m']` line in the second program in it, so the two halves
stay together.

Not filed as a duplicate of `CODEGEN_lambda_in_nested_def_body_never_emitted.md`
(claimed elsewhere): that one is a nested `def` holding a lambda, and it fails
at LINK time with an undefined symbol. This one is a nested `class`, it builds
and runs, and it fails at RUN time with a plausible number.
