# FORMAL_a_generic_structs_parameters_are_never_bound: `Self.<param>` in a class body has no value, and the two places that read it say so for the wrong reason

**Status: the DIAGNOSTIC is fixed (`d62016d6`) and so is the FIRST of the three
limits §0 measured (2026-10-04): a parameter whose declared TYPE is itself a
type application now instantiates, and the instantiation PARSES — which is the
assertion that was missing everywhere.**
**What is left is a comptime evaluator that can fold `len(<a literal>)` over a
substituted parameter, and the variadic half of the arity check; §"What is left"
is both, with the measurement for each.** Re-measured 2026-10-03 on
`work/formal18-1`; the bracket fix is on `work/formal19-1`.

Found by sweeping `std/collections` for `sweep14:std-collections`; see
`FORMAL_sweep14_std_collections.md` §4.2.

---

## 0a. The bracket fix, 2026-10-04: `keys: List[T]` instantiates, and the
## emitted file parses

A separate doc filed for this limit was fixed with it, and the fix is in the
place all five copies of the rule could read —
`monomorphize.head_match`, which finds a generic head with its brackets
**balanced** instead of stopping at the first `]` (`elaborate.py`'s two private
copies of that regex are gone, and its three parameter-list readers now split on
`fire_compiler.split_top_level_commas` rather than `split(',')`, because a
parameter may contain a bracketed type argument of its own).

| | before | after |
|---|---|---|
| `instantiate` on `struct Box[T: AnyType, keys: List[T]]` | emits `struct Box_1_…_x005D]:` — `parse error: Unexpected RBRACKET(']')` on both backends | emits `struct Box_1_…_x005D]:` → **parses**, with `List[Int]` substituted inside the annotation |
| `type_param_names` on `std/collections/type_dict.mojo`'s `TypeDict` | `['T', 'Trait', 'keys']` — stopped at `List[T]`'s `]` and lost `*values` | `['T', 'Trait', 'keys', '*values']` |
| `parse_bounds` on the same | the same truncation | `{'T': 'Equatable & Movable', 'Trait': 'type_of(AnyType)', 'keys': 'List[T]', '*values': 'Trait'}` |
| `instantiate` on `TypeDict[Int, AnyType, [1,2,3], String]` | refused (arity, because the parameter list was truncated to three) | emits a concrete `TypeDict_…` that parses, with `len(Self.keys)` folded to `len([1,2,3])` |

The third row is the one that matters for this document: **`TypeDict`'s whole
API is compile-time and every one of its parameters is a value**, so the
`keys: List[T]` line is not an edge case there, it is the middle of the
parameter list. The refusal this doc is about (`Self.length reads a comptime
class attribute … and what it reads is 'keys', a PARAMETER of Box`) is now
reached with the parameter actually BOUND — which is what §0 measured as missing
and what §5's option (1) asked for.

Verified with `test_formal_monomorph.py` (13 PASS), `test_formal_imports.py`
(70 PASS), `test_module_cache.py` (147 PASS), `test_dual_cpp_elaboration.py`
(6 PASS), `test_closure_capture_comptime_func_params.py` (4 PASS),
`test_comptime_bracket_params.py` (5 PASS). **This is a change to the compiled
path's shared monomorphizer and its full `make gate` is owed and was not run
here** (this worker is light); the integrator's gate is the check that matters
for it.

---

## 0. Re-measured 2026-10-03: the monomorphizer is here, and §5's advice has expired

Everything below was written before `formal/monomorph.py` landed. Three
measurements, and they change what this row's next step is.

**1. The value parameter IS bound.** `formal/monomorph.py`'s `instantiate`
substitutes it, for the doc's own reproducer:

```console
$ python3 -c "import formal.monomorph as MO; \
    print(MO.instantiate(open('.tmp/ptd/m.mojo').read(), 'Box', ['Int', '[1, 2, 3]'])[1])"
struct Box_1_T_3_Int_4_keys_39__x005B1_x002C_x00202_x002C_x00203_x005D]:
    comptime length = len([1, 2, 3])

    def size(self) -> Int:
        return Self.length
```

`len(keys)` became `len([1, 2, 3])`. So §5's option (1) — "bind the parameter
values at the instantiation site" — is BUILT, and the refusal below is no
longer standing in front of a missing mechanism.

**2. The refusal's own sentence is now FALSE about the tree, and that is a
defect in its own right.** It still says "This path compiles one image for every
instantiation — `doc/ABI.md` §Generics makes each instantiation a separate
boundary symbol and there is no monomorphizer here — so at the class body there
is no instantiation". Both halves of that are untrue now: `formal/monomorph.py`
is exactly that mechanism and its module docstring says it is `doc/ABI.md`
§Generics' "Stage 5". A refusal that names a repair the tree already has is the
`refuse_without:` class of defect (`test_formal_run.py`'s own note on a
reworded refusal), and it sends a reader to build the thing that exists. The
honest sentence is the next step, and it is short: **the binding happens in
`formal/monomorph.py`, which is DEMAND-DRIVEN and reaches only the
instantiations an importing unit asks for, so a class body's `comptime` binding
is folded only when some consumer writes `Box[…]` — and a module that declares
the template and never instantiates it is not reached at all.**

**3. What the monomorphizer cannot yet do, for THIS family — two limits, both
measured here, and the first is a bug rather than a project.**

* **A parameter whose ANNOTATION contains a bracket is not instantiable at
  all.** `keys: List[T]` is the reproducer above, and `monomorphize.py`'s `_HEAD`
  is `\b(fn|def|struct)\s+(\w+)\s*\[([^\]]*)\]`, which stops at the first `]` —
  `List[T]`'s. So the concrete source it emits is

  ```
  struct Box_1_..._x005D]:
  ```

  with a stray `]`, which is a **parse error** (`either_proof`-class: the
  instantiation is produced and then cannot be compiled). Filed separately then,
  and **FIXED with §0a** — the head is now found with its brackets balanced
  (`monomorphize.head_match`), and `elaborate.py`'s three parameter-list
  readers split on top-level commas rather than `,`, which is what a parameter
  whose type is a type application needs. It was not fixed on the branch that
  first measured it because the matcher is the COMPILED path's monomorphizer too
  and its regression surface is a full `make gate`, which is the integrator's —
  §0a is what was verified in its place.
* **A VARIADIC value parameter is refused by the arity check.** `*values` is a
  parameter `type_param_names` reports and `instantiate` will not accept an
  argument for:

  ```
  MonomorphError: Pair[Int, 1, 2, 3] supplies 4 type arguments but `Pair`
  declares 2 (T, *values); an instantiation is one template specialized for
  exactly the arguments it declares
  ```

  Every element of `args` is treated as a TYPE argument, so the second shape in
  §2 (`struct Pair[T, *values: T]`, and `std/collections/type_dict.mojo`'s
  `*values: Trait`) has no instantiation at all. The message is the right shape
  — a refusal rather than a guess — and it is `type_arg_text`'s rule that the
  variadic half has to grow into.

**So the remaining work is §5's option (2) — a comptime evaluator that can run
`len(<a literal>)` over a folded parameter — and it is now the WHOLE of what is
left rather than "not enough on its own".** The doc's warning still holds and is
the reason the order is what it is: an evaluator that can fold `len([1,2,3])`
still cannot say which list it was handed, because the class body never learns
it — except that it NOW does, because `instantiate` wrote the list into the
class body. That is the whole difference, and it is why the fix this row wants
is the `_HEAD` bug rather than anything here.

---

## 1. What the stdlib file does, and what it was told

`std/collections/type_dict.mojo` — the only stdlib module whose whole API is
compile-time:

```mojo
struct TypeDict[
    T: Equatable & Movable,
    Trait: type_of(AnyType),
    //,
    keys: List[T],
    *values: Trait,
](TrivialRegisterPassable):
    comptime length = len(Self.values)
    comptime _index[key: Self.T] = Self.keys.try_index(key)
    comptime get[key: Self.T] = Self.values[
        Self._index[key].or_else(Self._assert_key_is_present[key]())
    ]
```

Was refused with this, byte for byte on both architectures:

```
build: Self._index reads a `comptime` class attribute of TypeDict, whose value
is `Self.keys.try_index(key)` — and a formal value is one 64-bit word with
nowhere to keep a non-literal one: a `comptime` binding's value is written in
the class body and is often a CALL or a COMPUTATION rather than a literal, and
this path has no comptime evaluator to run one. Write the value at the use site
(a literal, or an assignment the compiler can see), which is the same program
with a representation
```

**Every clause of the repair is impossible here.** `_index` reads `keys`, a
PARAMETER. The use site is

```mojo
comptime td = TypeDict[T=Int, Trait=AnyType, [1,2,3], Int, String, Float64]
```

so the values ARE at the use site — as ARGUMENTS to an instantiation, which is a
different thing from a literal, and there is nothing in the class body to move
anywhere else. `length` is worse: `len(Self.values)` reads a VARIADIC
parameter's arity, which is not knowable at all without the instantiation.

## 2. The two shapes, measured, both architectures

```
struct Box[T: AnyType, keys: List[T]]:        struct Pair[T: AnyType, *values: T]:
    comptime length = len(keys)                   comptime length = len(Self.values)
```

Both refused, both for the reason above. Both are now refusals of their own
(`model.struct_parameter_not_bound_refusal`, asked from
`_apply_constant_sites` after the MLIR arm and before the value's own sentence):

```
build: Self.length reads a `comptime` class attribute of Box, whose value is
`len(keys)` — and what it reads is 'keys', a PARAMETER of Box. A parameter's
value belongs to an INSTANTIATION: the use site supplies it as an argument
(`Box[…, <value>, …]`), and that argument is a value, not a literal written in
this class body, so there is nothing here to write somewhere else. This path
compiles one image for every instantiation — doc/ABI.md §Generics makes each
instantiation a separate boundary symbol and there is no monomorphizer here — so
at the class body there is no instantiation, and `Self.keys` names a parameter
nothing has supplied.
```

The CONTROL that keeps this from being a blanket ban is in
`test_formal_run.py` as `comptime_binding_with_a_literal_value_still_builds`: the
same class body with `comptime length = 3` builds, runs and prints `3`, on both
architectures.

## 3. The reader, and what it is careful about

`model.comptime_binding_reads_a_field(struct_def, value)`.

A struct PARAMETER is a FIELD in the tree — `_parse_struct_params_as_fields`
(`48c480b1`) puts `keys: List[T]` in `StructDef.fields`, so `struct_field_names`
already knows the name and nothing new had to be taught about the AST. The walk
asks each node what it can answer about itself, because `iter_nodes` has no
parent: a bare read is an `IdentExpr`, and `Self.keys` is a `MemberExpr` whose
`member` is a **string** and whose `obj` is the receiver spelling. Only `Self` /
`self` / `cls` / `this` bases count, so `other.FIELD` — a read of some other
class — is not reported as this struct's parameter, and a name that is neither a
field nor a constant (`N` in `comptime LIMIT = N + 4`) falls through to the
value's own sentence, which is correct for it.

## 4. How big is the family

`grep`-able, and the honest answer is an UPPER BOUND with the split stated,
because a regex cannot tell a TYPE parameter from a VALUE one:

**199** `comptime` bindings in `../new-modular/Mojo/stdlib/std` have a
right-hand side that reads `Self.<name>` / `self.<name>`, counted by a command a
reader can run:

```sh
grep -rEn '^[[:space:]]*comptime[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*(\[[^]]*\])?[[:space:]]*(:[^=]*)?=' \
  ../new-modular/Mojo/stdlib/std | grep -cE '\b(Self|self|this|cls)\.[A-Za-z_]'
```

The majority are TYPE-level — `comptime Element = Self.T`,
`comptime DTYPE = Self.dtype`, `comptime _Mask = SIMD[.bool, Self.length]` — and
a type read as a value already has its own home (`model.type_value_tag`, the
fourth of the four a module-attribute walk accepts) and its own refusal
(`FORMAL_type_name_as_a_value.md`). **The subset this doc is about is the
value-typed parameters** — `Self.length`, `Self.keys`, `Self.element_types`,
`Self.ParamListType.values` — and the grep does not separate them. The files with
the densest clusters are `utils/variant.mojo` and `utils/coord.mojo` (19 each),
`builtin/variadics.mojo` (15), `simd.mojo` (14),
`collections/optional.mojo` (12) and `builtin/_format_float.mojo` (12).

**None of those files is refused by this arm today**, because each of them is
stopped by an earlier wall in its own import closure. That is the same "FILES
BLOCKED IS AN UPPER BOUND" caveat the b7 map §3 gives, and it is why this doc
quotes the family as a bound and not as a file count.

## 5. What closing it costs, and what it is NOT

**It is a monomorphizer, or something narrower.** The two halves:

1. ~~**Bind the parameter values at the instantiation site.**~~ **BUILT**
   (`formal/monomorph.py`, 2026-10-03), and its one gap — a parameter whose
   annotation is a type application — is closed (§0a). The rest of what that
   half was cost at is also done or not needed: the mangling is
   `monomorphize.mangle` (`(b)`), `demands_key` carries the type arguments so
   two demand sets are two artifacts (`c`), and the instantiation is published
   under the mangled name rather than `ReflectedFn.display_name` (`d`).
2. **A comptime evaluator** that can run `len(list)`, `try_index` and `.or_else`
   over a parameter-supplied list. **This is now the whole of what is left,
   and §0a is what made it reachable**: the class body now learns WHICH list it
   was handed, because `instantiate` wrote it there. The warning this section
   used to carry — "an evaluator that can fold `len([1,2,3])` still cannot say
   which list it was handed, because the class body never learns it" — no longer
   applies.

   **So the next step is a folder, and it is a narrow one.** The value the
   corpus wants folded is `len(<a literal the instantiation supplied>)`, which is
   the ONE shape §0a's table ends on (`len(Self.keys)` → `len([1,2,3])` in the
   emitted concrete body). `formal/comptime_runner.py` is where a comptime
   expression is evaluated today; the question a taker has to answer is whether
   its evaluator can fold `len` over a literal LIST — a closed-form function of
   a constant — which is a much smaller thing than "`try_index` and `.or_else`
   over a parameter-supplied list", and is what `TypeDict`'s `length` and
   `_index` need before anything else does.

3. **The variadic half of the arity check** (`*values: Trait`). Every element of
   `args` is one type argument, so a use site that writes one argument per
   VALUE — `TypeDict[T=Int, Trait=AnyType, [1,2,3], Int, String, Float64]` — is
   refused for arity where the declaration says `*values`. The message is the
   right shape (a refusal, not a guess — `type_arg_text`'s rule) and the fix is
   `type_arg_text` growing a variadic form: the first `n - k` arguments after the
   declared ones are the variadic ones, and the rest is the identity of the
   instantiation. §"what is not covered" in
   `bugs/FORMAL_generic_monomorph_scope.md` is where the ABI half of it belongs.

## What is left, in one line each

* a comptime folder for `len(<literal list>)` over a substituted parameter
  (§5 item 2) — `formal/comptime_runner.py` is the place to look;
* the variadic arity rule (§5 item 3);
* `make gate` for the shared-engine change in §0a, which is the integrator's.

## 6. Reproducing

The bracket fix, which is §0a — write `.tmp/ptd/m.mojo` as:

```python
struct Box[T: AnyType, keys: List[T]]:
    comptime length = len(keys)

    def size(self) -> Int:
        return Self.length
```

then

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.monomorph as MO, fire_compiler as F; \
    src = open('.tmp/ptd/m.mojo').read(); \
    name, out = MO.instantiate(src, 'Box', ('Int', '[1, 2, 3]')); \
    print(out); F.Parser(F.py_tokenize(out)).parse_module(); print('PARSES')"
python3 -c "import elaborate as E; \
    print(E.type_param_names(open('../new-modular/Mojo/stdlib/std/collections/type_dict.mojo').read()))"
python3 tools/memslot.py --gb 8 --label mm -- python3 test_formal_monomorph.py
```

and the refusal that is still there, with the parameter now bound:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/ptd/m.aout .tmp/ptd/m.mojo
build: Self.length reads a `comptime` class attribute of Box, whose value is
`len(keys)` — and what it reads is 'keys', a PARAMETER of Box. …
```

and the three rows that pin the refusal and its control, which still pass with
the substitution in place:

```sh
python3 tools/memslot.py --gb 8 --label t -- \
  python3 test_formal_run.py comptime_binding_reading_a_struct_parameter_is_its_own_refusal \
    comptime_binding_reading_a_variadic_parameter_is_its_own_refusal \
    comptime_binding_with_a_literal_value_still_builds
```
