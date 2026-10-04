# FORMAL_a_value_typed_bracket_argument_is_refused_as_a_subscript

**Area:** `formal/monomorph.py::type_arg_text` (the refusal), and for the fix
whichever layer decides what a bracket ARGUMENT may be ·
**found by** closing
`the variadic bracket arity and the `len(<display>)` fold (landed in e72a5f93)` (deleted with its
fix), whose own use site is the reproducer · **both architectures** (the reader
is shared and pre-codegen) · **filed 2026-10-04, NOT fixed**

## What this is

One layer out from a fix that landed. `std/collections/type_dict.mojo` is the
stdlib module whose whole API is compile-time, every one of its parameters is a
VALUE, and its use site is

```mojo
comptime td = TypeDict[T=Int, Trait=AnyType, [1,2,3], Int, String, Float64]
```

`[1,2,3]` is a value parameter's argument. The monomorphizer now binds both the
`*values` half of the arity and folds `len(<display>)`, and `instantiate`
produces the concrete source — called directly, with those six arguments, it
emits a `TypeDict_…` that parses. **A consumer cannot get there**, because the
bracket is read long before that:

```
$ python3 tools/memslot.py --gb 8 --label g -- python3 fire.py build --formal \
      --no-prove -o .tmp/gm/main .tmp/gm/main.mojo
# .tmp/gm/main.mojo:  from lib import Box
#                     var b = Box[Int, [1, 2, 3]]()
build: Box[Int, ListExpr] is a compile-time explicit-parameter list on a
generic, not a subscript: the brackets name types and comptime values, none of
which is a runtime word. This path has no type or comptime parameter to bind, so
what the call means depends entirely on which parameters were passed. Refused
rather than read as an index — a binding for `size_of[type, target]` would have
to come from a target description this backend does not have, and a plausible
constant is a fabricated answer.
```

`type_arg_text`'s docstring says the boundary itself: "`F.IntLiteral` and every
expression form are refused, which is also what …" — so a value argument is out
of scope BY DECISION, not by oversight, and the decision is the thing to look
at.

## Why this is not a small patch

A bracket argument is currently an ABI SYMBOL: `type_arg_text` returns "the ABI
spelling of a type argument" and the mangled name is built from it, so a value
argument needs a mangling that is stable, legal as a symbol fragment, and
DISTINCT — two instantiations differing only in a value argument must be two
symbols or the second overwrites the first. That is the same problem the type
argument already solved, with a different input.

And the argument is not only a display: `keys: List[T]` binds a LIST while
`*values: Trait` binds a SEQUENCE of them, so the two spellings have to produce
different manglings from the same bracket.

A narrower alternative that is defensible: accept ONLY a literal display whose
elements are literals (`[1, 2, 3]`, `(Int, String)`), because those have one
closed-form spelling and the monomorphizer already substitutes them into the
body textually. That covers `type_dict.mojo`'s own use site exactly and is the
shape the folder landed for.

## What is NOT the cause

* **Not the arity check** — measured, fixed, and pinned by
  `test_formal_monomorph.py`'s `a variadic bracket parameter takes the extra
  arguments`. Six arguments against four names now instantiates.
* **Not the folder** — `len(<a literal display>)` folds now, pinned by
  `test_formal_run.py`'s `comptime_len_of_a_literal_display_folds` on both
  architectures.
* **Not `instantiate`** — called directly with those six arguments it emits a
  `TypeDict_…` that parses.

## The exact next step

Decide the mangling (the narrow literal-display answer above is the one to try),
teach `type_arg_text` the accepted value spellings with their mangling, and add
a `test_formal_monomorph.py` case that is a LIBRARY plus a PROGRAM — the file's
own docstring says why: every behavioural case there crosses a dylib boundary,
which is the only place a consumer's bracket reaches the monomorphizer.

`TypeDict` itself will still refuse, and by a different and already-documented
limit: `monomorphize: type parameter 'T' is used as a value/binding name` —
`instantiate`'s own comment says a template whose body binds `T` as a value
cannot be textually instantiated, and `type_dict.mojo`'s `comptime _index[key:
Self.T]` is exactly that. So the reachable end of this row is a template whose
value parameters are not also used as binding names, and a taker should measure
whether that is `type_dict.mojo` alone or a family before promising the file.

## Reproducing

    export PATH=/opt/homebrew/bin:$PATH
    python3 -c "import formal.monomorph as MO; \
      print(MO.instantiate(open('../new-modular/Mojo/stdlib/std/collections/type_dict.mojo').read(), \
        'TypeDict', ['Int','AnyType','[1, 2, 3]','Int','String','Float64']))"
    # …raises the `type parameter 'T' is used as a value/binding name` limit.
    # The CONSUMER-side refusal is the one to read, from a two-file tree:
    #   lib.mojo   struct Box[T: AnyType, keys: List[T]]: comptime length = len(Self.keys)
    #   main.mojo  from lib import Box   /   var b = Box[Int, [1, 2, 3]]()