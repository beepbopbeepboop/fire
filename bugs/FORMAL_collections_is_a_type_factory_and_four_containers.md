# FORMAL_collections_is_a_type_factory_and_four_containers: the blob route is half-open and the measurement is new

**Area:** FORMAL (host modules). **Status: OPEN, measured, not started.** Found on
`construct:sweep5:hostmods-core` (2026-10-02), whose brief was to add
`collections` to `formal/hostmods/` "as far as the model allows".

**This does not restate
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`, which owns
`namedtuple` and is the root cause; read that first.** What is new here is (a)
the sweep-file measurement re-taken on today's tree, and (b) the answer to the
question that document leaves open — whether `Counter`/`OrderedDict`/`deque`
could be served by the `os.listdir` BLOB pattern. (b) is a partial yes, and the
partial is the interesting part.

## What I ran

A stub `formal/hostmods/collections.mojo` on the search root, arm64, one build
per sweep row, plus a direct test of the blob route's two halves.

```console
$ for f in formal/lean.py tools/arm64_insn_audit.py tools/formal_sweep.py \
           tools/formal_sweep_causes.py tools/heapprof_report.py; do
    python3 fire.py build --formal --no-prove -o /tmp/x "$f"; done
lean.py                 → imports 'shutil'            (HOST_UNREACHABLE)
arm64_insn_audit.py     → imports 'subprocess'        (HOST_UNREACHABLE)
formal_sweep.py         → imports 'concurrent.futures'(HOST_UNREACHABLE)
formal_sweep_causes.py  → imports 'importlib.util'    (HOST_UNREACHABLE)
heapprof_report.py      → imports 'subprocess'        (HOST_UNREACHABLE)
```

**Every one of the five lands on a permanent tier.** So a `collections` module
converts **zero** files to a build and moves five diagnostics from one host module
to a different one. That agrees with the 2026-10-01 re-measurement (five files, one stubbed
`collections`, every one moving to a different host import) and it is reproduced
here, so the number is stable rather than a one-day artefact.

## The blob route: half-open, and the half that is open is not `Counter`

CPython's `collections` has exactly ONE module-level function and eight classes:

```console
$ python3 -c "import collections, inspect; \
  print([n for n in dir(collections) if inspect.isfunction(getattr(collections,n))]); \
  print([n for n in dir(collections) if inspect.isclass(getattr(collections,n))])"
['namedtuple']
['ChainMap', 'Counter', 'OrderedDict', 'UserDict', 'UserList', 'UserString', 'defaultdict', 'deque']
```

`namedtuple` is the type factory the sibling document owns. The other eight are
containers, and the obvious move is the one `formal/hostmods/os/__init__.mojo`
already makes for `listdir`: return a `malloc`'d blob and hand out accessors.
Measured, both halves of that:

```console
$ cat t.py
import enum
def main() -> int:
    counts = enum.bag_new(4)      # a Pointer[Int64] from inside the dylib
    counts[2] = 5                 # a SUBSCRIPT STORE from the caller
    printf("%lld\n", enum.bag_get(counts, 2))
    return 0
$ python3 fire.py build --formal --no-prove -o /tmp/t t.py && /tmp/t
get2=5
```

**So a caller CAN subscript-assign into a blob a hostmod returned**, and that is
the operation `counts[opcode] += 1` in `tools/arm64_insn_audit.py:94` is written
as. What it does not give is `Counter`:

1. **Word 0 is the blob's LENGTH**, by the convention every blob in this tree
   follows (`listdir`, `walk` — `listdir_len` reads it). A `Counter`'s key `0` is
   a perfectly ordinary key, so the two collide and the collision is silent:
   `counts[0]` reads the count rather than counting anything.
2. **`Counter` inserts on MISS with a default**, `__getitem__` returns 0 for an
   absent key, and `counts[k] += 1` on an absent key is defined to work. A blob
   has no dispatch, so the caller must pre-size and pre-test, and the source
   spells neither.
3. **`most_common`, `items`, `len`, `keys`, iteration, `+=`, `|`** are all method
   calls or operators on a value. A method call needs a type this image can see
   (`find_method_owner` refuses an ambiguous or unknown owner), and the blob's
   type is a `Pointer[Int64]` declared in another dylib.

So the blob route serves `counts[i] += 1` for a DENSE, PRE-SIZED integer key set
and nothing else in `Counter`. That is a new, smaller capability than the
document assumed — worth recording because it is the one part of the container
question that is genuinely open — and it is not `collections.Counter`, so
exporting it under that name would be the approximation
`bugs/FORMAL_hashlib_sha3_and_blake2s_absent.md` declined to ship.

## The exact next step

1. **Say the answer where the reader is**, which is step 1 of the sibling
   document and is not done: the host-import refusal for `collections` names the
   module and says nothing about `namedtuple`, so a reader moving one of these
   five files has to find this document to learn that the answer is "declare a
   struct". One line in the refusal naming `namedtuple` and the alternative
   converts zero files and is the difference between a reader who knows what to
   do and a reader who files the next bug doc about `collections`.
2. **A caller-subscriptable blob is now measured to work**, which is worth one
   line in the sibling document's `Counter` paragraph — it replaces "a dict is
   the blob question" with the sharper "a dict is the blob question AND the key
   space has to be dense and pre-sized". Whoever writes that paragraph should
   carry the `counts[2] = 5` measurement above rather than re-derive it.
3. **Nothing module-shaped.** `namedtuple` needs the reflection table; the
   containers need the key-space above. Neither is a `formal/hostmods/collections.mojo`.
