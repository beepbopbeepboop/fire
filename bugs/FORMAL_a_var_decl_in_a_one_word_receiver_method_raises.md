# A `VarDecl` inside a one-word receiver's method raises `AttributeError`, so a
# construct this path refuses is reported as a crash

**Area:** FORMAL — `formal/build.py`'s `_collect_receiver_frame_escapes`.
**Status: OPEN, measured on `master`, not fixed.** Found 2026-10-04 while
landing the byte-blob element width (a `bytearray` is now a blob with a
one-byte element, so `bytearray()` builds — the document that recorded the open
decision is deleted with that fix), by running the whole of
`test_formal_run.py` and reading its failures. It
is **pre-existing**: the two failing case names fail identically with that
change reverted (`git apply -R`, re-run, re-apply).

## What I ran

```console
$ for a in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label dbg -- \
    python3 fire.py build --formal --no-prove --backend=$a -o .tmp/dbg2_$a .tmp/dbg2.mojo; done
```

`test_formal_run.py`'s own case, `one_field_mutator_that_also_returns_a_frame_is_refused`:

```
    struct Pair:
        var a: Int
        var b: Int

    struct Cell:
        var _p: Pair

        def swap(out self) -> Pair:
            var old = self._p
            self._p = Pair()
            return old

    def main() -> Int:
        var c = Cell()
        c._p.a = 1
        var q = c.swap()
        printf("%d %d", q.a, c._p.a)
        return 0
```

## What I saw

**Identical on both architectures** — an uncaught `AttributeError`, not a
refusal and not an image:

```
  File "formal/build.py", line 4934, in _collect_receiver_frame_escapes
    target = node.target
             ^^^^^^^^^^^
AttributeError: 'VarDecl' object has no attribute 'target'
```

`formal/build.py:4931-4934` is:

```python
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = node.target
```

`F.VarDecl` has `.name` and `.value`; `F.AssignStmt` has `.target` and
`.value`. The guard admits both and the next line reads the attribute only one
of them has. `var old = self._p` is the statement that reaches it — a
**declaration** in a method whose receiver is a one-field struct whose field is
a frame.

## Why this is a bug and not a wrong answer

The function's own job is to set `fn._receiver_frame_escape`, and the caller
turns that into the refusal the test expects (`two hidden-word conventions`: a
method that both stores through a frame field and returns a frame). So the
program is one this path is *right* to refuse and the refusal is already
written — the analysis cannot reach it. What escapes instead is a Python
traceback out of the build, which is the `backend-crash` class in
`tools/formal_sweep.py`'s taxonomy: a file the sweep classifies by its crash
rather than by a construct, and an exception message that names an internal
attribute instead of saying anything about the source.

It also means `test_formal_run.py` is **red on `master`** for this row, and has
been for long enough that nothing noticed — the same shape as the two
gated-but-never-run registrations `CLAUDE.md` records.

## The exact next step

One line, and the shape the rest of this file already uses: read the target off
whichever shape the node has, or — better, and the reason it is written as a
next step rather than a patch here — use the shared reader this tree already has
for exactly this question. `formal/model.py::_binding_value(node, name)` (added
2026-10-04 by the byte-blob commit, beside `_literals_bound_to`) answers "what
value does this statement bind", and the receiver frame-escape check wants
"does this statement ASSIGN to the receiver's sole field", so:

```python
        if isinstance(node, F.AssignStmt) and isinstance(node.target, F.MemberExpr) \
                and node.target.member == field \
                and isinstance(node.target.obj, F.IdentExpr) \
                and node.target.obj.name == recv:
            ...
```

i.e. **ask `F.AssignStmt` for the attribute it has** and let a `VarDecl` be
what it is. A `var self._p = Pair()` is not a shape the parser produces, so
dropping the `VarDecl` arm loses nothing.

Then run `python3 tools/memslot.py --gb 8 --label t -- python3
test_formal_run.py one_field_mutator_that_also_returns_a_frame_is_refused` and
expect the `two hidden-word conventions` refusal on both backends. **The whole
file afterwards, not the one case**: this loop runs per method of every
one-field struct in the corpus, so the fix's blast radius is every program with
such a struct, and a case that passes is not evidence the loop's other arms
still do.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      one_field_mutator_that_also_returns_a_frame_is_refused
$ printf '%s\n' 'struct Pair:' '    var a: Int' '    var b: Int' '' \
    'struct Cell:' '    var _p: Pair' '' \
    '    def swap(out self) -> Pair:' '        var old = self._p' \
    '        self._p = Pair()' '        return old' > .tmp/dbg2.mojo
$ python3 tools/memslot.py --gb 8 --label dbg -- python3 fire.py build \
      --formal --no-prove --backend=arm64 -o .tmp/dbg2 .tmp/dbg2.mojo
```