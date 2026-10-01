# FORMAL_binding_a_module_level_constant_to_a_local_is_refused: `A = 34` then `y = A`

**Status: OPEN, and it is a refusal rather than a wrong answer.** Found while
writing `formal/hostmods/json.mojo` (2026-09-30, the
`module:copy+collections+io+json+pathlib+typing+builtins` claim); the
allocator is in `formal/arm64_codegen.py`, which that claim does not own, so
it is filed rather than applied. It is a small gap in a tree that is
otherwise careful about this, which is why it is worth a document: the refusal
is correct in what it says and the construct is a thing every module here
wants to write.

---

## What I ran

```console
$ cat > .tmp/p/A.mojo
A = 34

def k1(x) -> int:
    var y = 0
    if x == A:
        y = A
    return y

def k2() -> int:
    var y = 0
    y = A
    return y

def k3() -> int:
    var y = A
    return y

def k4() -> int:
    return A

def main() -> int:
    printf("k1=%d k2=%d k3=%d k4=%d\n", k1(34), k2(), k3(), k4())
$ python3 fire.py build --formal --no-prove -o .tmp/p/A .tmp/p/A.mojo
```

```
build: k1: 'A' has no home: the register allocator collected no home for it, so
the emitter and the allocation walk disagree about this function's locals. This
path places a name in a register or a spill slot allocated for THIS function, a
receiver field's frame, or a module-level constant the build folded — and a
name in none of them is refused rather than read out of whatever register the
allocator left behind, which is how one program returned 10 on arm64 and 0 on
x86-64 where the source says 5
```

and the same message for `k2` and `k3` when they are built alone.

## What I saw, and what is NOT wrong

Four spellings, each built on its own, measured:

| spelling | result |
|---|---|
| `if x == A:` (a read in a comparison) | **works** |
| `return A` (a read as the answer) | **works** |
| `f(A)` — a module-level constant as an ARGUMENT | **works** |
| `var y = A` / `y = A` (binding it to a local) | **refused** |

So the constant is not lost and the name is not unreadable: it reads in a
comparison, it reads as a return value, and it reads as a call argument. Only
the binding to a local is refused, and the refusal says the register allocator
"collected no home for it" while the emitter's allocation walk expected one —
which is the honest diagnosis of a two-walk disagreement rather than a
missing feature.

`var f: Pointer[UInt8] = malloc(8)` is the same shape and works, and so is
`var one: Pointer[UInt8] = malloc(1)`. So it is specifically an INTEGER (or
other scalar) module-level constant that has no local home.

## Why it matters here, and where it is currently worked around

`formal/hostmods/json.mojo` wanted a table of byte values and could not spell it
the obvious way. Three workarounds are in that file, and each says at its
definition that it is one:

1. `escaped_byte(s, p)` takes the six short escapes as NUMBERS (`98`, `102`,
   `110`, …) rather than as a module-level `ESC_B = 98`, because
   `b = ESC_B` is a local binding.
2. `suffix_of` / `stem_of` take a NAME and do the `lstrip('.')` / `rfind('.')`
   arithmetic inline rather than reaching for a table.
3. `put_hex4` reads `HEX`, a module-level STRING constant, at a subscript —
   which works, and is the evidence that only the scalar case is affected.

The same workaround is in `formal/hostmods/hashlib.mojo`, which writes its
rotations and its `MASK64` arithmetic without a module-level scalar table, and
`formal/hostmods/os/_syscalls.mojo` writes `"/"` and `".."` as literals rather
than as `SEP` and `DOTDIR` names. So three existing modules pay a small
readability cost for this, which is the measure of how much it is wanted.

## The exact next step

`formal/arm64_codegen.py`'s allocation walk treats a module-level constant that
appears on the RIGHT of a `=` (or in a `var y = <const>` initialiser) as a
local reference, finds no slot for it in the function's frame, and then hands
the emitter a name it has not allocated. Two small things are worth separating,
and the first is the one to check first:

1. **Does the allocation walk run over `AssignStmt` targets at all?** If it
   collects homes for the names a function BINDS and not for the names it
   READS, then a read in a `y = A` is being mistaken for a binding — and the
   fix is to run the same expression walk it already runs for a `return A` (a
   read that works) over an assignment's right-hand side. `test_formal_run.py`
   already has a case for a related disagreement (`'self' has two kinds of value
   across call sites`), so the walk is the place to look.
2. **If the walk is right and the emitter is wrong**, then the emitter needs to
   substitute the folded constant for a name whose only binding is a module
   level, the way it already does for "a module-level constant the build
   folded" — which the refusal's own wording says it does.

Either way the test belongs with the change, and the shape is the one
`test_formal_json.py` already has: a module-level scalar constant, a function
that binds it to a local, a function that reads it in a comparison, and a
function that takes it as an argument — because the second and third currently
pass and a fix that broke them would be worse than the refusal.

**Not fixed here.** `formal/hostmods/json.mojo` and the two other host modules
carry the workarounds above, each marked at its definition, and the modules are
correct as they stand — every one of their values is checked against CPython.
