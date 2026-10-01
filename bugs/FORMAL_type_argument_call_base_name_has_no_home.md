# FORMAL_type_argument_call_base_name_has_no_home: `List[Int]()` is reported as a NAME that cannot be placed

**Status:** found, not fixed. It is the terminal cause behind the 35 sweep files
that `len()` on a frame address used to be, and it is a name-resolution
question, not a codegen one — so it is a different lane's file and this
document is the hand-off rather than the work.

## What is wrong

A `TYPE-ARGUMENTED` type constructor — `List[Int]()`, `list[Int]()`,
`Slice[2, 3]()` — is refused with

```
main: 'List' has no home: the module-level symbol table is empty for this unit,
and the reading function declares no local or parameter by that spelling. This
path places a name in a register or a spill slot allocated for THIS function, a
receiver field's frame, or a module-level constant the build folded …
```

Reproduced, both architectures, nothing lifted:

```
$ cat a.mojo
def main(k: Int) -> Int:
    var xs = List[Int]()
    return 0
$ python3 fire.py build --formal --no-prove a.mojo -o a.arm64
build: main: 'List' has no home: …
$ python3 fire.py build --formal --no-prove --backend=x86_64 a.mojo -o a.x86
build: main: 'List' has no home: …
```

The BARE spelling of the same constructor does not say this:

```
$ cat c.mojo
def main(k: Int) -> Int:
    var xs = List()
    return 0
$ python3 fire.py build --formal --no-prove c.mojo -o c.arm64
build: constructing List has no representation on this path: this image has no
declaration of List to construct …
```

Both wordings are refusals, and the verdict is the same either way, so nothing
is silently wrong. But they are not the same DIAGNOSIS, and the first one is
false about the program: `List` is not a name that needs a home at all. It is a
TYPE, and the source says so twice over — it is the base of a subscript whose
argument is a type name, and it is the callee of a call, which is the language's
spelling of "construct this type". The diagnostic is
`model.unresolved_name_refusal`, and it is reached by the name-placement walk in
`formal/build.py` (the loop that ends at `raise CodegenError(
M.unresolved_name_refusal(…))`, just above `_prepare_functions`'s
`_method_owners`), which visits the `IdentExpr` that is the subscript's base and
finds it in none of the three places a VALUE can be.

That is the defect this document is about, and it is the one
`bugs/FORMAL_frame_receiver_handoff.md` §4 calls the worst outcome: **a refusal
whose stated reason is entirely false.** A reader sent to the register allocator
for a type name goes and looks at `_load_var`, and the empirical result of that
errand is "the name is fine, the walk is asking the wrong question". A file
whose only construct is `List[Int]()` is filed as a register-allocation problem
when it is a type-constructor spelling problem.

## Why the same walk is right about `List` in every other position

The walk has to place a bare `IdentExpr` as a VALUE, and `List` as a value is
exactly as unplaceable as the message says. What is wrong is that a name in
CALLEE position, under a subscript, is a TYPE and not a value. The walk already
has a hook for "this name is not a value": `model.name_resolves_without_a_local`
and the `callees` / `bracketed` sets it collects higher up. The subscript base
of a call callee needs to join them, and today it does not — which is why the
subscript is the only spelling that misfires, and why both `List` and `list`
misfire (`a.mojo` and `b.mojo` above).

Worth stating so the next person does not "fix" it by exempting every name in
callee position: `f(x)` where `f` is a genuinely undeclared function must keep
refusing, and it refuses downstream at the emitter's own
"which this module does not compile" arm. The exemption is narrow and is about
the SUBSCRIPT, not the callee position: a bare `f` is a name, `f[Int]` is a
type application.

## The exact next step

`formal/build.py`, the name-placement walk in `_prepare_functions`, together
with the set of names it already exempts as callees. A subscript whose base is
a bare `IdentExpr`, whose index is a TYPE name, and which is itself the callee
of a call, contributes its BASE to that exempt set — the same treatment
`_callee_wants_a_value` and `_rewrite_method_calls` give the other callee
spellings, and in the same file so there is one recogniser of "a name that is
not a value" rather than two.

Then the answer becomes the emitter's, which is the honest one and is a
DIFFERENT question with a real next step of its own: `List` is in
`model.BLOB_TYPE_CTORS` but `type_constructor_kind("List")` answers
`("unsupported", None)`, so `List()` needs either a declaration in hand or a
lowering as an empty counted blob. `len` on the result is already answered
(`LEN_FROM_BLOB_FIELD`), so a blob constructor is the piece that is missing, and
it is worth knowing which of the two this document has actually unblocked.

## Why this is the terminal cause for 39 sweep files

`std/collections/binary_heap.mojo` is the file the whole
`std/collections` subtree imports, and it is refused at
`BinaryHeap___init__` on `self._data = List[Self.T]()`. Measured on this tree,
on both architectures, 39 stdlib files move from the `len()`-on-a-frame-address
refusal to this one, and the sweep's family tally moves accordingly:

| family | before | after |
|---|---|---|
| `frame address passed where a value is wanted` | 54 | 15 |
| `construction with arguments needs __init__` | 21 | 22 |
| `receiver passed as an argument` | 23 | 25 |
| `other refusal` | 201 | 237 |

PASS is unchanged (108 on arm64, 105 on x86-64, over 599 files) and the
coverage rate is unchanged (108/418 and 105/416), so nothing here flatters a
number: the files are not answering yet, they are answering something else.

## Verification of the diagnosis

* `List[Int]()` and `list[Int]()` — the same refusal, base name named.
* `List()` — reaches the emitter and gets the type-constructor refusal.
* `struct Bag: var xs: List[Int]` with the field assigned in the caller — the
  annotation is fine; only the CONSTRUCTOR call is refused, so the walk's
  subscript exemption must not be extended to a type in a non-callee position.
* Both architectures, from `fire.py build --formal --no-prove`, with nothing
  else changed.
