# FORMAL_a_method_export_publishes_no_c_declaration: `signature: "Point.sum"` is a lookup key, so no client can write the declaration doc/ABI.md's method row promises

**Area:** FORMAL (both backends; the manifest row is written by one function)
· **Status:** OPEN, measured 2026-10-05 on `work/formal30-interop` at `77b24183`.
· **Found by:** `test_formal_interop.py`, which builds a formal dylib for both
architectures and has to bind four methods to call them at all.

**A method export's `signature` is the string `"<Struct>.<method>"`, which is a
LOOKUP KEY and not a declaration.** The free functions beside it publish a real
one — `int64_t int_add (int64_t, int64_t)` — so a client reads the manifest,
generates a declaration for every entry, and gets a syntax error for the methods:

```console
$ python3 -c "import json; m=json.load(open('lib.dylib.manifest.json')); \
    print([(e['name'], e['signature']) for e in m['exports'] if e['kind']=='method'])"
[('Point_sum', 'Point.sum'), ('Point_bump', 'Point.bump'),
 ('Cell_get', 'Cell.get'), ('Cell_bump', 'Cell.bump')]
```

## 1. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label interop -- python3 test_formal_interop.py
#   FAIL  the receiver rule is the documented one
#   ...
# §2 and §3, the two arms of the same measurement:
python3 tools/memslot.py --gb 8 --label link -- \
  clang -o .tmp/t .tmp/t.c .tmp/libinterop.arm64.dylib -Wl,-rpath,.tmp
python3 tools/memslot.py --gb 8 --label x86dylib -- python3 test_formal_x86_64_dylib.py
```

## 2. Where the row is written, and why it is not one line

`formal/build.py::_formal_exports` writes `f"{st.name}.{m.name}"` for a method
(`_method_exports`) and takes a free function's `signature` verbatim from
`reflect.collect_exports_src`. `reflect` CAN spell a method: its `collect_exports`
builds `f"{cret} {msym} ({', '.join(cparams)})"` with `cparams = [f"{s.name} *"] +
[_mt(t) for n, t in m.params if n != 'self']`. So `reflect` has a declaration
and the formal path does not publish it.

**Two things then have to be true at once, which is why this is not a one-line
change, and both are load-bearing.**

* **`reflect`'s spelling is the COMPILED path's and is wrong for the formal
  backends in one measurable case.** It writes the receiver as `Struct *`,
  which is right there (a real C++ `Struct *self`) and wrong here for a
  one-field struct's plain `self`, which the formal backends pass BY VALUE.
  Measured, arm64, `Cell.get`:

  ```
  0x100000678:  add x19, x0        # the receiver IS argument 0, not &argument 0
  0x10000068c:  add x0, x19
  0x100000690:  add sp, sp, #0x20, lsl #12
  0x10000069c:  ret
  ```

  and from C, `corpus_Cell_get(10)` is 10 while `corpus_Cell_get(&c)` is
  `6126726256`. So the formal declaration is `int64_t Cell_get (int64_t)` — the
  receiver's shape is `struct_is_one_field(struct) or receiver_writeback_name(meth)`
  (`formal/model.py`), which is doc/ABI.md's third row.
* **`formal/imports.py::linked_struct_owners` READS this exact field** for the
  struct name, by `signature.rpartition(".")` — and says so in its own
  docstring: *"The struct name is the `signature` up to its last `.`, because
  that is what `_formal_exports` writes there — `f"{struct}.{method}"`, so
  `Bag.__len__` and `My_Bag.add` both yield the struct and neither yields a
  fragment of it."* Change the field to a C declaration and that reader returns
  nothing, so a build-pass refusal stops knowing which structs a linked library
  provides — a REGRESSION in the constructor refusal
  `check_construction_shapes`'s `undeclared_linked_struct_refusal` arm, in
  exchange for a nicer manifest row.

## 3. The exact next step

1. Add a NEW manifest field for a method, `declaration`, and leave `signature`
   alone. Additive, so `linked_struct_owners` keeps working with no edit, and a
   client reads `declaration` when it is there and `signature` otherwise.
2. Spell it in `formal/build.py` with `model.formal_boundary_signature` applied to
   `reflect`'s method signature, and with the receiver replaced per §2's rule.
   `formal/model.py` should own that spelling — it is the module both backends
   ask about a receiver, and `test_formal_interop.py`'s
   `METHOD_DECLARATIONS` table is a transcription of it that would then become a
   second answer to check against.
3. In `test_formal_interop.py`, generate the method declarations from
   `declaration` instead of from the table, and keep the table as the DOCUMENTED
   shape it is today, so the reader changes and the documented contract does not
   move in the same commit.

**While it is unfixed, a client writes a method's declaration by hand** from
doc/ABI.md's receiver table, which is what `test_formal_interop.py` does — and
that file's `test_the_receiver_rule_is_the_documented_one` is what keeps the
hand-written copy honest, by re-deriving it from `reflect`'s own method signature
and from the emitter's own receiver rule.