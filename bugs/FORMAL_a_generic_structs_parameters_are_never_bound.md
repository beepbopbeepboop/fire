# FORMAL_a_generic_structs_parameters_are_never_bound: `Self.<param>` in a class body has no value, and the two places that read it say so for the wrong reason

**Status: the DIAGNOSTIC is fixed (`d62016d6`, this branch). The wall is not, and
it is a monomorphizer.** What is left is stated here with the family's size and
the one measurement that says which half is which, because the previous refusal
named a repair that cannot be carried out and a reader following it would edit
the wrong line forever.

Found by sweeping `std/collections` for `sweep14:std-collections`; see
`FORMAL_sweep14_std_collections.md` §4.2.

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

1. **Bind the parameter values at the instantiation site.** Every
   `C[args]` / `C[T=…, args]` in an importing unit would compile the struct
   again with `Self.<param>` substituted. This is the same project
   `FORMAL_binary_heap_mojo_after_the_len_value.md` §2 costs at (a) a
   monomorphizer, (b) a mangling function, (c) CAS keying by
   `(template-id, type args, comptime params)`, (d) a naming decision for
   `ReflectedFn.display_name` — **weeks**, and `doc/ABI.md` §Generics already
   makes each instantiation the boundary symbol, so the ABI is ready and only the
   compiler is not.
2. **A comptime evaluator** that can run `len(list)`, `try_index` and `.or_else`
   over a parameter-supplied list. This alone is NOT enough and should not be
   started for this row: `TypeDict`'s value is a *function of the instantiation
   arguments*, and an evaluator that can fold `len([1,2,3])` still cannot say
   which list it was handed, because the class body never learns it.

**Do not start (2) for this row.** The refusal is correct and the diagnostic now
says why; what is missing is (1), and (2) without (1) moves 0 files.

## 6. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
mkdir -p .tmp/ptd && cat > .tmp/ptd/m.mojo <<'EOF'
struct Box[T: AnyType, keys: List[T]]:
    comptime length = len(keys)

    def size(self) -> Int:
        return Self.length
EOF
python3 fire.py build --formal --no-prove -o .tmp/ptd/m.aout .tmp/ptd/m.mojo
python3 fire.py build --formal --no-prove --backend=x86_64 \
  -o .tmp/ptd/m.x86 .tmp/ptd/m.mojo

# and the stdlib file
python3 fire.py build --formal --no-prove -o .tmp/td \
  ../new-modular/Mojo/stdlib/std/collections/type_dict.mojo

# the tests
python3 test_formal_run.py comptime_binding_reading_a_struct_parameter_is_its_own_refusal \
  comptime_binding_reading_a_variadic_parameter_is_its_own_refusal \
  comptime_binding_with_a_literal_value_still_builds
```
