# FORMAL_a_method_call_on_a_module_level_container_reaches_the_link_audit: `H.append(v)` on a module global is refused as a DANGLING SYMBOL, not by name

**Area:** FORMAL, both backends — the call lowering's receiver test
(`formal/arm64_codegen.py::_is_value_receiver`, `formal/x86_64_codegen.py`'s
twin) and `model.module_slot_for`. **Status: OPEN, measured 2026-10-14 on
`work/formal415-docs`; a refusal-with-the-wrong-message, not a wrong answer.**

## What I ran

```python
G = 0
H = [1, 2, 3]


def bump():
    global G
    G = G + 1
    return G


def push(v):
    global H
    H.append(v)
    return len(H)


def main(n):
    printf("a=%d b=%d c=%d@@", bump(), bump(), G)
    printf("p=%d q=%d@@", push(4), H[3])
    return 0
```

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build \
      --formal --no-prove --backend=arm64 -o p.arm64 p.mojo
build: p.mojo: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: H.append. Nothing on this link line defines it: not the C
library, and not any library this program linked. … (Provider check: asked the
C library (dlsym).)
```

Byte-identical on x86-64. **CPython answers `p=4 q=4`; the image does not
build.**

## Why it is the wrong message, and what is actually answerable

The message is a claim about the LINK LINE, which is not what is wrong with it:
`H` is a module-level list, it has a `__DATA` slot
(`bugs/FORMAL_module_state_no_storage.md`'s "WHAT LANDED"), and the operations
that HOLD the slot are answered on both architectures. Measured, the same tree,
arm64 (the backend the row above used):

| construct | answer |
|---|---|
| `NUMS[1] = 99` then `return NUMS[1]` (a subscript STORE on the global) | `v=99`, exit 0 |
| `len(NUMS)` for `NUMS = [10, 20, 30]` | `n=3`, exit 0 |
| `G = G + 1` through `global G` | `1 2 2`, exit 0 |
| **`H.append(v)` through `global H`** | **refused, naming `H.append` as a symbol nothing provides** |

So the gap is exactly METHOD-CALL-ON-A-MODULE-GLOBAL. `_is_value_receiver` is
the test that decides `obj.m(...)` is a method call rather than a dotted extern
call, and it answers for a local, a string literal, a frame slot, a call result
and a bound function value — **not for a module global**, because that name is
not one of the function's own register/spill homes and its value lives in a
`__DATA` slot rather than in the frame. The chain then falls through to
`_callee_symbol`, which flattens it to the dotted name `H.append`, and the
extern path emits a `BL` to a symbol no library defines — which is what the
build pass reports four stages later.

## The exact next step

**Two ways, and the choice is whether the method should WORK:**

1. **Refuse by name, at the call lowering**, beside the other receiver-shaped
   refusals (this is the cheap, safe half and it is the one this document
   recommends first): when the callee is a `MemberExpr` whose base is a name
   `model.module_slot_for(base, self._fn_local_names)` answers a slot for, raise
   a message that says the construct — `H` is a module-level list and a METHOD
   call on a module global is not lowered while a subscript store and `len` are,
   with the same `H[i] = v` / `len(H)` / accessor advice the other rows give.
   A shared `model.module_global_method_refusal` keeps the two backends' words
   the same, which is the rule every row beside it follows.
2. **Or lower it.** A module-level list's blob is the slot's static data, and
   `append` already writes into a frame blob with a compile-time capacity (the
   append-site count); a global's capacity is the same count from its
   initializer, so an in-place `append` on a `__DATA` blob is the same store
   with a different base address — and the slot pointer is NOT reassigned, so
   there is no write-back to get wrong. The reason this is second is that it is
   a capability change with a re-measure of the corpus, while the refusal is one
   predicate and one message.

Pinned by a row this document asks for in `test_formal_globals.py` (which owns
the module-global cases and currently asserts the READS and the int writes) or
`test_formal_module_attr.py` (which owns the by-name refusals): a case asserting
the construct's own sentence, plus the two controls above that already pass, so
a rule that refused every method on every global cannot satisfy the row alone.

## What is NOT this document's subject

The dotted method chain on a module EXPORT used as a value (`os.environ.get(k)`)
is the same SHAPE and a different path, already refused by name by
`model.dylib_value_member_refusal` — see
`bugs/FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it.md` §5. This
document is the VARIABLE-receiver twin, and the two do not share a reader
because one is about a module's export table and the other about a `__DATA`
slot.
