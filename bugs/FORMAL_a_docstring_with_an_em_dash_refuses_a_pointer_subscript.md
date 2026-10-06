# FORMAL_a_docstring_with_an_em_dash_refuses_a_pointer_subscript: `import shlex` is
# refused because 31 DOCSTRINGS in `formal/hostmods/os/_syscalls.mojo` contain `—`

**Area:** FORMAL (the text-encoding block — `formal/model.py`'s
`non_ascii_strings_in` / `non_ascii_strings`, and the string-subscript refusal
that consults them). **Status: MEASURED, red on master, not fixed.** Three rows of
`test_formal_imports.py` fail on this tree because of it and they are the only
failures in that file.

Found 2026-10-04 on `work/formal25-5` while measuring a different defect
(`bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §0.3) and
deliberately not fixed: it is the string model's own decision, in
`bugs/FORMAL_string_value_model.md`'s area, and the next step below needs a
reachability argument this bug does not make on its own.

## What I ran

```console
$ printf 'import shlex\n\ndef main():\n  return 0\n' > .tmp/shlexchk/prog.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/shlexchk/a.out .tmp/shlexchk/prog.mojo
build: prog.mojo imports 'shlex', which cannot be built either: _syscalls.mojo:
d[i] is refused on a string whose text is not ASCII. … This image holds a string
literal that is not ASCII, so some string in it can have a character `base + 1`
walks into. …
```

and the three red rows, all carrying that message:

```console
$ python3 test_formal_imports.py
  FAIL  a function-local import is a dependency
  FAIL  widening the imported list widens nothing else
  FAIL  a standard-library module in no tier is not reported as a typo
formal imports: PASS=72 EXPECTED=0 SKIP=0 FAIL=3
```

**Pre-existing, not this tree's work:** the same three fail with the change that
prompted the search disabled (`formal/imports.py::_KIND_HOPS = 0`, which is the
one-file kind reader it replaced), so they are master's state and not a
regression. `test_formal_run.py` (PASS=1024 FAIL=0), `test_formal_dylib.py`
(24/24) and `test_formal_link_accounting.py` (263/263) are green, so the shape is
narrow: it needs a module dylib built out of `formal/hostmods/os/_syscalls.mojo`.

## The cause, measured rather than guessed

`d[i]` is not a string subscript at all. `formal/hostmods/os/_syscalls.mojo:1153`:

```mojo
def fs_dirent_name(e: Pointer[UInt8]) -> str:
    var d: Pointer[UInt8] = str_alloc(1024)
    i = 0
    while e[21 + i] != 0 and i < 1023:
        d[i] = e[21 + i]      # <- refused as a CHARACTER read
```

`d` is a declared `Pointer[UInt8]` and that file's own comment says the
annotation is load-bearing ("it is what makes `e[21 + i]` a one-byte load rather
than a list-blob walk"). So the refusal fires on a question about the IMAGE:
`model.string_element_refusal`'s only condition is `non_ascii_strings()`, and its
own docstring states the argument — *"no literal with a byte >= 0x80 anywhere
means no string in the image can have one, so every element read is a
character"*.

**And what puts a non-ASCII literal in the image is 31 DOCSTRINGS:**

```console
$ python3 -c "import sys; sys.path.insert(0,'.'); import formal.imports as I, \
    formal.model as M; \
    print(len(M.non_ascii_strings_in(I.module_statements('formal/hostmods/os/_syscalls.mojo'))))"
31
$ …    # and every one of them is a docstring:
'The value of the kernel string MIB `name`, or `""` if there is no such.\n\n    `sysctlbyname…'
'1 if `name` is `.` or `..` — the two entries a listing drops.\n\n    BYTE VALUES and not `na…'
```

The characters are `—`, `…` and `§`, which is what this repository's prose is
written with; there is not one non-ASCII CHARACTER LITERAL in the file. A
docstring is a string literal on this path, and a three-line program with no
non-ASCII literal of its own is refused for it:

| program | `printf("%d", s[0])` with `s = "abc"` |
|---|---|
| ASCII only | builds |
| a FUNCTION docstring carrying `héllo — …` | **refused** |
| a MODULE docstring carrying `héllo — …` | **refused** |

## The one thing that decides the fix, and it is NOT "are docstrings interned"

The obvious question is whether a docstring reaches the image's string pool, and
**it does** — measured, by looking for the bytes in the emitted image rather than
by reading the emitter:

```console
$ printf 'def f() -> Int:\n    """MARKER-TEXT-12345 and a few more words."""\n    return 1\n\ndef main() -> Int:\n    printf("hi")\n    return 0\n' > .tmp/ascii/doc.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/ascii/doc.aout .tmp/ascii/doc.mojo
Built: .tmp/ascii/doc.aout  [arm64/macho]
$ grep -c MARKER-TEXT-12345 .tmp/ascii/doc.aout
1
```

(a control image carrying a real literal finds its own marker the same way, so
this is the pool and not an artefact of the search.) **So "a docstring is not in
the string pool" is FALSE, and a fix written on that premise would be wrong in
its argument while looking right in its effect.**

**The question that decides it is REACHABILITY, and the tree already answers most
of it.** The refusal's soundness argument needs "no string in the image can hold
a character `base + 1` walks into", and a docstring's interned bytes are not a
string any program can SUBSCRIPT: a docstring is not addressable as a value on
this path. `formal/model.py`'s module-body classifier already says so in its own
comment — *"a module DOCSTRING — a bare string `ExprStmt` — is not body. Python
stores it in `__doc__` and runs nothing … there is nothing to execute and nothing
to lose"* — and `module_body` drops it by that test. A FUNCTION docstring is the
same node in a body that lowers to nothing, and nothing here lowers `__doc__` to
a pointer.

So the filter the block wants is **"a string literal in docstring position is
interned but never read as a string"**, and there are two places to put it, with
different payoffs:

1. **`non_ascii_strings_in` skips docstring-position literals** — one predicate on
   one walk, pure function of statements, testable with no build at all. It fixes
   every refusal in the block (the string subscript is only one of its readers)
   and changes nothing about what is emitted.
2. **The emitters stop interning docstrings** — which also removes dead bytes
   from every image, and is the change that makes (1)'s premise TRUE of the pool
   rather than merely of the reader. `_intern_string` is reached only from the
   sites that emit a literal as a value (`printf`'s operand, a string value, a
   fold), so this is a question about the walk that collects them, not about the
   interning function.

**The cost of being wrong is named here rather than left to the next reader:** if
a docstring IS reachable as a value on some path (a `__doc__` read that lowers,
a reflection consumer), then (1) re-admits a wrong-but-exit-0 byte read and (2)
would break the consumer that reads it. So grep for the readers before taking
either — the measurement above is about the pool, and the question is about the
readers.

**The corpus number is cheap and worth taking first**, because it decides whether
this is one file or a whole class: over this repository and the stdlib, how many
of the non-ASCII literals are docstrings, and how many units have ONLY
docstrings among them. `_syscalls.mojo` is the case that hurts because it is
imported by `os`, and therefore by `shlex`.

## What a fix owes the suite, so the next reader knows when it is done

`test_formal_imports.py`'s three rows go green when `import shlex` builds again,
and that is the measurement to quote. Two more rows worth adding at the same
time, because the defect is an IMAGE-level condition and nothing pins it as one:

* a build whose closure contains a non-ASCII **docstring** and whose program
  subscripts a `Pointer[UInt8]`, which must be refused while the reader question
  is open and must build once it is closed — the anti-rot direction;
* `formal/model.py`'s own `non_ascii_strings_in` over a unit whose only non-ASCII
  literal is a docstring, which is a pure-function assertion and costs nothing.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ printf 'import shlex\n\ndef main():\n  return 0\n' > .tmp/shlexchk/prog.mojo
$ python3 tools/memslot.py --gb 8 --label sh -- \
      python3 fire.py build --formal --no-prove -o .tmp/shlexchk/a.out .tmp/shlexchk/prog.mojo
$ python3 tools/memslot.py --gb 8 --label sh -- python3 test_formal_imports.py
$ python3 -c "import sys; sys.path.insert(0,'.'); import formal.imports as I, formal.model as M; \
    print(len(M.non_ascii_strings_in(I.module_statements('formal/hostmods/os/_syscalls.mojo'))))"
```