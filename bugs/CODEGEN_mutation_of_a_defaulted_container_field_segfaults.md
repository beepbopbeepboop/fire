# CODEGEN: mutating a defaulted container struct field SIGSEGVs after printing the right default

**Area:** CODEGEN (`mojo/backend_gimple`). **Status: OPEN, measured
2026-10-18, PRE-EXISTING on `master`.** Found while fixing the
interpreter's half of the container-default question (a `List`/`Dict`/`Set`
field with no initializer is an empty container, not `None` — that fix
landed on `work/longcat-3bugs` as `ee52b7c7`, its doc deleted with it).
The interpreter fix is measured against the compiled path, and the
compiled path answers the default VALUE correctly and then dies on the
first mutation.

## What I ran

```
$ printf 'struct Box:\n    var xs: List[Int]\n\ndef main():\n    var q = Box()\n    print(q.xs)\n    q.xs.append(1)\n    print(q.xs)\n' > .tmp/pa.mojo
$ python3 fire.py --jit .tmp/pa.mojo
[]
JIT execution failed with code -11
```

The same shape for the other two container kinds:

```
$ printf 'struct Box:\n    var d: Dict[String, Int]\n\ndef main():\n    var q = Box()\n    q.d["a"] = 2\n    print(q.d)\n' > .tmp/pd.mojo
$ python3 fire.py --jit .tmp/pd.mojo
JIT execution failed with code -11
$ printf 'struct Box:\n    var st: Set[Int]\n\ndef main():\n    var q = Box()\n    q.st.add(3)\n    print(q.st)\n' > .tmp/ps.mojo
$ python3 fire.py --jit .tmp/ps.mojo
JIT execution failed with code -11
```

`print(q.xs)` before the mutation answers `[]` — the compiled path's
default value is RIGHT. The crash is on the first mutation through the
field: `append` (list), indexed store (dict), `add` (set).

## What is NOT the cause

An explicit initializer works fine, so this is not "container fields are
broken in structs":

```
$ printf 'struct Box:\n    var xs: List[Int] = []\n\ndef main():\n    var q = Box()\n    q.xs.append(1)\n    print(q.xs)\n' > .tmp/pa2.mojo
$ python3 fire.py --jit .tmp/pa2.mojo
[1]
```

and a plain local works fine too (`var xs = []; xs.append(1)` → `[1]`).
Only the NO-INITIALIZER field — the shape the interpreter fix just made
reachable — crashes. The empty container the compiled path synthesizes
for the default is not retained for mutation through the field: the field
ends up holding something that is not a valid owned `MojoList *`/
`MojoDict *`/`MojoSet *` by the time the mutation dereferences it.

Related, and NOT this bug: a defaulted `Deque[Int]` field reads as `0`
and also SIGSEGVs on mutation — same crash class, different missing
piece (Deque is not even allocated). That is a row in the interpreter
container-default fix's commit message (the fix for "a `List`/`Dict`/
`Set` field with no initializer is `None`"), not a separate doc.

## Why it matters

The interpreter fix makes `var xs: List[Int]` fields usable on BOTH
engines in the read-only shape, and any program that then mutates the
field gets a correct `[]` and a silent SIGSEGV — the compiled path's
plausible-answer-then-crash class, not a clean refusal. It is also why
the interpreter fix's pin (`container_field_default_is_empty` in
`test_runtime_diff.py`) asserts the default value only and does not
mutate: the mutation is the codegen bug this doc files.

## The exact next step

Find where the compiled path synthesizes the empty container for a
no-initializer container field (the same path that produces the correct
`[]` for `print(q.xs)`) and check the field STORE: the synthesized
value must be retained the same way an explicit-initializer field's value
is (`var xs: List[Int] = []` keeps the list alive across mutation, so
the store/ownership path exists and works — the default path is not
using it). Candidates: the struct-field default synthesis beside
`_struct_init_defaults` / the `_alloc_<Struct>` helper emission in
`mojo/backend_gimple/module_gen.py`, and the ownership tracking
(`_owned_free_candidates` / `_owned_stack_push_runtime_fn` in
`mojo/backend_gimple/emit_infra.py`) for a field whose constructor was
implicit rather than written. The cheapest measurement is the three
probes above through `fire.py --jit`: exit -11 before, exit 0 after.
