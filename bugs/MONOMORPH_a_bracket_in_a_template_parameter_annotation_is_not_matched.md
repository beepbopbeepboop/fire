# A bracket inside a template parameter's ANNOTATION ends the parameter list, and every instantiation of such a template is a parse error

**Area:** the shared monomorphizer — `monomorphize.py::_HEAD` (line 34) and the
four copies of the same rule in `elaborate.py` (lines 30, 32, 197, 225, 316,
550). Found 2026-10-03 on `work/formal18-1` while re-measuring
`bugs/FORMAL_a_generic_structs_parameters_are_never_bound.md`, whose §5 named
"a monomorphizer" as the wall behind it. **The monomorphizer exists and binds
the value parameter correctly; this is what stops it from being usable for the
parameter kinds that doc's own reproducer uses.** NOT FIXED here — see §4.

## What I ran

```console
$ python3 -c "import formal.monomorph as MO; \
    print(MO.instantiate(open('.tmp/ptd/m.mojo').read(), 'Box', ['Int', '[1, 2, 3]'])[1])"
struct Box_1_T_3_Int_4_keys_39__x005B1_x002C_x00202_x002C_x00203_x005D]:
    comptime length = len([1, 2, 3])

    def size(self) -> Int:
        return Self.length
```

with `.tmp/ptd/m.mojo` exactly the reproducer of that other doc:

```python
struct Box[T: AnyType, keys: List[T]]:
    comptime length = len(keys)

    def size(self) -> Int:
        return Self.length
```

**The substitution is right.** `len(keys)` → `len([1, 2, 3])`, and the mangled
name carries the argument injectively (`safe_suffix`'s `_x005B`-style escape).
So the machinery does what the doc said was missing.

## What I see

**The emitted source does not parse.** `monomorphize_source` does

```python
src = template_src[:m.start()] + f"{kind} {mangled}" + template_src[m.end():]
```

with `m` from `_HEAD = r'\b(fn|def|struct)\s+(\w+)\s*\[([^\]]*)\]'`. `[^\]]*`
cannot cross a `]`, so on `struct Box[T: AnyType, keys: List[T]]:` the match
ends at **`List[T]`'s** `]` and `m.end()` leaves `]:` behind:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o c .tmp/ptd/concrete.mojo
build: parse error: .tmp/ptd/concrete.mojo:1:70: Unexpected RBRACKET(']')
```

on both backends. A `struct Pair[T: AnyType]:` template — no bracket in any
annotation — emits `struct Pair_1_T_3_Int:` and is fine, so the defect is
narrow and specific: **a parameter whose declared type is itself a type
application.**

That is not an exotic shape. It is `keys: List[T]` and `*values: Trait` in
`std/collections/type_dict.mojo` — the very file the row was swept for — plus
`SIMD[dtype, width]` in every numeric template the compiled path instantiates,
and any `Dict[String, Int]`-shaped parameter anywhere in the corpus.

## Why it is not fixed here

`_HEAD` is the COMPILED path's monomorphizer, not the formal path's:
`formal/monomorph.py`'s own module docstring says the substitution is "the one
`monomorphize.py` already owns" and that teaching it about anything new is "a
change to a shared engine". Its regression surface is the whole
generic-instantiating corpus — `test_formal_monomorph.py`, `test_formal_imports.py`,
the compiled path's own generic suites, and a `make gate` — and this worker is
light. Landing a one-line change to the engine the compiled path's generics go
through, verified only by the formal suites, is exactly the trade the
surrounding docstrings argue against.

For the record, `test_formal_monomorph.py` on `master` is **9 PASS / 2 FAIL**
(`two demand sets are two libraries` is the other), and both failures are
pre-existing and unrelated to this: no test there instantiates a template whose
parameter annotation carries a bracket, which is why this has never been red.

## The exact next step

Replace the `[^\]]*` rule with a bracket-balanced match, ONCE, in the place both
copies can read — and note that `elaborate.py` has its own `_HEAD` /
`_FN_HEAD` (lines 30 and 32), so there are at least five copies of the same
`[^\]]*` today. A regex that matches one level of nesting

```python
r'\b(fn|def|struct)\s+(\w+)\s*\[((?:[^\[\]]|\[[^\[\]]*\])*)\]'
```

covers `List[T]` and `SIMD[dtype, width]` and is the smallest change that fixes
the reported shapes; a `def`-returning scan that walks to the MATCHING bracket
is the one that cannot go wrong at two levels, and `elaborate.py`'s
`_bracket_depth_by_line` is already a bracket-counting reader in the same
package, so either shape has a precedent to follow.

Then add to `test_formal_monomorph.py`:

* a template with a bracketed parameter annotation (`struct Box[T, keys: List[T]]`)
  — `instantiate` returns source that `fire_compiler.Parser` can parse, which is
  the assertion that is missing everywhere today;
* the CONTROL, a template with no bracketed annotation, so the fix cannot be
  "the parameter list ends at the first `]`" all over again;
* `std/collections/type_dict.mojo`'s own `struct TypeDict[…, keys: List[T], *values: Trait]`
  through `template_names` + `instantiate`, which is the file the row was
  swept for and the one whose 199-site family this unblocks.

Verify with `python3 tools/memslot.py --gb 8 --label mm -- python3
test_formal_monomorph.py`, `test_formal_imports.py`, and a full `make gate` —
the last one because the compiled path is a consumer of this engine.
