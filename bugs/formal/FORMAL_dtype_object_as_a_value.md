# FORMAL_dtype_object_as_a_value: the runtime TYPE OBJECT of `DType` has no representation

**Status 2026-11-02:** the defect this doc was filed for (a bare TYPE name in a
value position refused as "a name with no register") is FIXED. A type is a
64-bit tag (`formal/model.py` `type_tag`, `TYPE_VALUE_NAMES`), and:

- `def f(t): if t == bool: ...` / `printf("a=%d", f(bool))` builds on
  `fire.py build --formal --no-prove` and prints `a=1` (CPython agrees).
- The regression rows are in `test_formal_run.py` (`TYPE_VALUE_CASES`,
  `TYPE_VALUE_DTYPE_CASES`, `TYPE_VALUE_REFUSALS`, `TYPE_VALUE_NUMBER_CASES`,
  `TYPE_VALUE_TAG_CASES`), with the answers taken from CPython and the interpreter.
- The subscript-of-a-`DType`-field SIGSEGV: per commit f0df70b2 (subject: a subscript of a field declared a number is refused on both backends). Not re-measured in the 2026-11-02 round.

What remains is NOT the old defect. It is two limits, and both are true refusals
about a thing this image cannot represent. Recorded here so they stay visible.

## 1. `DType` as the type OF a type (the type object)

Measured 2026-11-02, `fire.py build --formal --no-prove`:

```
def main(n):
    t = DType
    printf("a=%d", n)
```

exit 1 with: `DType is the type OF a type, and a type object is not something
this path has: a formal value is one 64-bit word, and there is nothing in this
image for a word to point at that would answer 'what type is this'.` The sentence
points at the supported spellings (`DType.int32`, and a `DType`-annotated
parameter), which is correct.

**Why it stays a limit:** a type object (`DType(Int32)`, `dtype.name`,
`dtype.is_signed()`) is a pointer to a runtime descriptor. The value model is one
word and has no storage for descriptors.

**Next step:** an owner decision, not a patch. Either (a) add a descriptor table
to the image (a static read-only blob indexed by tag, with `name`/`is_signed`
answered from it), or (b) keep refusing and leave it. Option (a) is a value-model
feature; it belongs with the string value model (`FORMAL_string_value_model.md`).

## 2. `DType(Int32)` — constructing a type

Measured: `d = DType(Int32)` is refused with `constructing DType has no
representation on this path: this image has no declaration of DType to construct`.
This is accurate: `DType` is not a struct declared in the unit, and the emitter
does not invent a call to an undefined symbol (that path built and then failed to
load). **Next step:** the same decision as §1; construction is only meaningful once
a descriptor exists.

## What is NOT in this doc any more

- The "no home" / "no register" diagnostic for a type name: fixed (above).
- The `DType`-annotated field classification (`DTYPE_TYPE_NAMES`): closed.
- The float8/float4/uint128 spellings (`TYPE_VALUE_NAMES`): closed.
