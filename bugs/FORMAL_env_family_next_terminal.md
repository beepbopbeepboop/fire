# FORMAL_env_family_next_terminal: where the 55-file family stands, and what the next reader needs

**Status: the family's own terminal has NOT MOVED since 2026-10-02, and it is a
file whose own document was deleted for measuring at a ceiling of ZERO. What is
left in this document is a measurement, not a defect.** Re-measured 2026-10-02 on
`work/formal8-5`, arm64, on the real stdlib file:

```
$ python3 tools/memslot.py --gb 8 -- python3 fire.py build --formal --no-prove \
      --backend=arm64 -o .tmp/p/env_mojo.out \
      <stdlib>/std/os/env.mojo
build: env.mojo imports 'std.ffi', which cannot be built either:
       binary_heap.mojo: formal dylib has no public functions:
       binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares
       only the generic struct template(s) BinaryHeap, and a parametric type has
       no single boundary layout either.
```

Identical to the terminal the previous Status recorded, `unsafe_ptr` and
`_CPointer[UInt8, UntrackedOrigin[…]]` still absent from it. So the answer to
"what is left here" is: **`binary_heap.mojo`**, whose `len(self._data)` on a
`List[Self.T]` slot has no representable value.

**And the document that recorded why that file is not worth working is gone.**
`bugs/FORMAL_dylib_export_gate_ceiling.md` measured three candidate fixes for
`binary_heap.mojo` at a ceiling of ZERO files across all three, and was deleted
rather than worked — so the ceiling-zero measurement now lives only here, and
this file is what a reader needs in order to know that `env.mojo` is not one
patch away. It is worth being explicit about that, because the deletion rule
("a doc for a fixed bug is deleted") reads as "the problem went away" and this
one did not: it means the problem was measured and priced.

## The three steps, and where each stands

1. **DONE (2026-09-30, `4ad34f3`)** — `external_call["setenv", T]`'s bracket
   list is a template application rather than a container index. This closed the
   55-file family: `external_call` is what all 55 reach.
2. **DONE (2026-10-02)** — a type argument in ANY bracketed generic position is
   not read as a value: `model.type_position_nodes` excludes a bracket list in a
   type position from the runtime question rather than asking it and refusing
   (`bugs/FORMAL_external_call_a_multiparameter_type_in_the_bracket.md`,
   deleted with its fix).
3. **NOT DONE, and not this session's** — re-run

   ```
   python3 tools/formal_sweep.py --stdlib-subtrees=base64,bit,builtin <stdlib>/std
   ```

   and read `not-answerable/unresolved-extern` (56 when the table was taken) and
   the top entry of `codegen/dependency by family`, which should now be
   `info.mojo`'s MLIR constructs rather than anything this document describes. A
   whole-tree sweep is tens of minutes and hundreds of builds; it belongs to
   whoever runs the gate.

## The classification bug, which is still live and still not this file's

The sweep files any `symbol(s) that nothing provides` as
`not-answerable/unresolved-extern` (`tools/formal_sweep.py`'s
`_EXTERN_BUILD_MARK` rule), a class excluded from the coverage denominator and
from `DIRTY`. Its comment is right about the case it was written for — a
genuinely unlinkable image — and wrong about the one this family produced: the
backend is NOT right to refuse, because the symbol was a method of a struct in
the same image and the reason it was unbound was that a method call was never
rewritten. So a real 55-file codegen gap sat in the class that says "a fact
about the target, not a gap in the backend", and `codegen coverage` read 10.2%
instead of something lower for the wrong reason.

**A narrower form of the marker than a substring is the fix**, and it is still
not written. It is in `tools/`, it is a classification rule rather than a
construct, and no bug document claims it.

## What this worker verified about the construct itself

`test_formal_external_call.py` (29 cases) is the test of the closed half, and it
includes the whole of `std/os/env.mojo`'s three functions transcribed, run and
compared against `os.environ` in CPython — so the file's own remaining blocker is
a dependency, not its body. **Re-measured here, unchanged**, which is the reason
this document is a record and not a queue item: the family's own text is three
constructs closer to building and the next construct is another file's.
