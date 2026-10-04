"""`ctypes` — the type table and the buffer helpers, with the loader admitted.

CPython's `ctypes` is a FOREIGN-CODE INTERFACE: it loads a shared library with
`dlopen`, calls into it with the platform's ABI, and hands back objects that
proxy C data.  Loading one is the operation this target cannot do -- a formal
image links libSystem and nothing else, and a `dlopen` of anything else would
contradict that premise (`formal/imports.py`'s rule for what "unreachable" means)
-- so `CDLL` is an ADMITTED CONTRACT.

WHAT IS DECIDED HERE, AND IT IS MOST OF THE MODULE
--------------------------------------------------
`ctypes` looks like one thing and is three, and only the first is a loader:

  1. **the type table** -- `c_int8` … `c_uint64`, `c_float`, `c_double`,
     `c_bool`, `c_char_p`, `c_void_p`, and each one's SIZE and its two
     conversions.  Those are numbers this tree can compute, so they are computed
     and `test_formal_admitted.py` checks every one of them against CPython's own
     `ctypes.sizeof` and against the value it round-trips.

  2. **the buffer helpers** -- `create_string_buffer`, `string_at`, `cast`'s
     refusal rules, `sizeof`, `byref`, `addressof`, `memmove`, `memset`.  The
     first and last of those need only `malloc` and `memcpy`, which are in
     libSystem and which `formal/hostmods/os/_syscalls.mojo` already binds, so
     they are real.

  3. **the loader** -- `CDLL`, `PyDLL`, and every call THROUGH a loaded library.
     That is the admitted part, and it is one call (`cdll_open`) plus the
     per-call contract, because a library handle is a pointer into the dynamic
     loader's own tables and the calls through it are the foreign code itself.

WHAT THE ADMITTED CONTRACT SAYS, AND WHY IT IS THAT NARROW
-----------------------------------------------------------
`cdll_open` returns a HANDLE, and the honest contract is that it is either 0
(no library with that name on this target) or a non-zero word the caller may pass
back to the other `cdll_*` calls.  Nothing about WHICH libraries exist, what they
contain, or what any of their functions computes is assumed -- and
`formal/admitted.py`'s `contract_text_is_scoped` refuses an admission that grew a
word like "always" or "deterministic", because those are claims about a host this
project has no model of.

The per-call contract is separate from the handle's for a reason worth stating:
a file that opens a library and never calls through it trusts less than one that
does, and lumping them would make the trust line say the same thing for both.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `Structure`, `Union`, `Array` as BASES, and with them field layout, `_fields_`,
    `_pack_`, `_anonymous_`.  A `ctypes.Structure` subclass is a Python CLASS with
    a compiler-generated descriptor table; the formal front end's
    `dataclass_transform` is the only thing that turns a class declaration into
    fields, and it refuses a base class it does not know
    (`bugs/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md`
    is the same refusal seen from the other side).  What IS here is the SIZE and
    ALIGNMENT arithmetic such a struct needs, as functions over its field list,
    because that half is pure and the half that is not is the subclass.
  * `py_object`, `py_function`, `c_wchar_p` beyond the size: they need the
    embedded CPython this image does not have.
  * `_pointer_type_cache`, `sizeof` over a Python object: `sizeof(obj)` reads
    `obj.__sizeof__` off a live interpreter object, which is the same limit that
    took `gc` and `dis` out of reach.

THE LIBC WRAPPER IS IMPORTED, NOT RE-SPELLED

`create_string_buffer` and `string_at` need `malloc`, `memcpy` and `strlen`, and
all three live in `formal/hostmods/os/_syscalls.mojo`, whose own docstring says it
is where every call into libSystem is spelled "once, and nowhere else".  So this
module IMPORTS them rather than writing a second `str_dup`: a second one would be
a second implementation of a routine whose entire value is being the same one
everywhere, and the two would be free to disagree about what `malloc` returns.

WHAT IS ASSUMED OF THE HOST — the two contracts, in one place
-------------------------------------------------------------
  * `cdll_open`  — the handle is 0, or a non-zero word this target's loader owns.
  * `cdll_call`  — whatever the named foreign function returns is one word; its
                   value is not assumed to be anything in particular.
"""

from os._syscalls import str_alloc, str_dup, str_copy, str_len


# ── the type table ───────────────────────────────────────────────────────────
# CPython's exact values, checked name by name (size AND round-trip) by
# `test_formal_admitted.py` against `ctypes.sizeof` and the live types.
#
# A module-level name is folded at every read on this path, so each of these is a
# zero-argument function for the reason `os.sep` is one
# (`formal/hostmods/os/__init__.mojo` says why at length), and the VALUE form is
# a separate function because `c_int32(7)` is a construction and `c_int32` alone
# is a type -- two different questions, and CPython answers them differently.

def size_c_int8() -> int:
    """`sizeof(ctypes.c_int8)`: 1."""
    return 1

def size_c_uint8() -> int:
    """`sizeof(ctypes.c_uint8)`: 1."""
    return 1

def size_c_int16() -> int:
    """`sizeof(ctypes.c_int16)`: 2."""
    return 2

def size_c_uint16() -> int:
    """`sizeof(ctypes.c_uint16)`: 2."""
    return 2

def size_c_int32() -> int:
    """`sizeof(ctypes.c_int32)`: 4."""
    return 4

def size_c_uint32() -> int:
    """`sizeof(ctypes.c_uint32)`: 4."""
    return 4

def size_c_int64() -> int:
    """`sizeof(ctypes.c_int64)`: 8."""
    return 8

def size_c_uint64() -> int:
    """`sizeof(ctypes.c_uint64)`: 8."""
    return 8

def size_c_float() -> int:
    """`sizeof(ctypes.c_float)`: 4 -- an IEEE-754 single."""
    return 4

def size_c_double() -> int:
    """`sizeof(ctypes.c_double)`: 8 -- an IEEE-754 double."""
    return 8

def size_c_bool() -> int:
    """`sizeof(ctypes.c_bool)`: 1, and its only value is 0 or 1.

    A byte rather than a word, which is the one place in this table where the
    C type is NARROWER than a value on this path.  That is not a problem here
    because nothing crossing a dylib boundary is a `c_bool`: `c_bool` is a field
    of a struct, and a struct is a frame blob
    (`bugs/FORMAL_module_state_no_storage.md`).
    """
    return 1

def size_c_char_p() -> int:
    """`sizeof(ctypes.c_char_p)`: 8 -- a POINTER, not a character.

    The reason this table has no `c_char` row despite CPython having one: a
    `char *` is an ADDRESS, and its size is the pointer's.
    """
    return 8

def size_c_void_p() -> int:
    """`sizeof(ctypes.c_void_p)`: 8."""
    return 8

def c_int(value: int) -> int:
    """`ctypes.c_int32(v).value`: `v` truncated to 32 signed bits, then read back.

    The truncation is the conversion, and it is what makes this decidable rather
    than admitted: CPython stores the low four bytes and `c_int32(...).value`
    reinterprets them as a signed number, so `(2**31)` comes back as `-2147483648`
    and `test_formal_admitted.py` requires exactly that, against the live type.
    """
    return sign_extend_32(value)

def c_uint(value: int) -> int:
    """`ctypes.c_uint32(v).value`: `v` truncated to 32 UNSIGNED bits.

    The unsigned sibling, and a separate function because the two disagree on
    every input with bit 31 set -- which is the whole reason `c_int` and `c_uint`
    are both in CPython's table and neither is a spelling of the other.
    """
    return truncate_32(value)

def c_int64_value(value: int) -> int:
    """`ctypes.c_int64(v).value`: `v` truncated to 64 signed bits."""
    return sign_extend_64(value)

def truncate_32(value: int) -> int:
    """The low 32 bits of `value`, as an unsigned number in 0..2**32-1."""
    return value % 4294967296

def sign_extend_32(value: int) -> int:
    """`value` truncated to 32 bits and read back as SIGNED.

    This is `formal/hostmods/struct.mojo`'s `pack_i32`/`unpack_i32` arithmetic,
    and it is deliberately NOT imported from there.  The difference is with
    `str_dup` above, and it is the whole difference: `struct.mojo` models a
    MODULE (`struct`) and its functions take a FORMAT STRING first, so importing
    them here would make `sign_extend_32` mean "unpack a 4-byte field at the
    offset this format string names" -- a five-argument function behind a name
    that reads as one.  Two call sites want the same ARITHMETIC and do not want
    the same FUNCTION, and duplicating four lines of modulo is cheaper than
    either a rename of `struct.mojo`'s API or a module that lies about what it
    exports.
    """
    low = value % 4294967296
    if low >= 2147483648:
        return low - 4294967296
    return low

def sign_extend_64(value: int) -> int:
    """`value` truncated to 64 bits and read back as SIGNED."""
    low = value % 18446744073709551616
    if low >= 9223372036854775808:
        return low - 18446744073709551616
    return low


# ── the decidable half: buffers ──────────────────────────────────────────────
# `create_string_buffer` and `string_at` need `malloc`, `memcpy` and `strlen`,
# and all three are libSystem symbols this target binds -- which is why they are
# real here and `create_string_buffer` is absent from the module's own docstring
# list of absences.  What they do NOT do is decide whether the pointer they were
# handed is one they may read, and that is a refusal, not a guess.

def create_string_buffer(source: str, size: int) -> str:
    """`ctypes.create_string_buffer(init, size)`: a NUL-terminated copy in malloc'd memory.

    CPython's own semantics, which are three rules and not one: the buffer is
    `size` bytes; `init` is copied in and NUL-terminated WITHIN it; and a
    `create_string_buffer(n)` with an integer `init` makes an all-zero buffer of
    `n` bytes rather than a copy.  The first two are here; the third is
    `create_zeroed_buffer` below, because "an int means a length, a bytes means
    content" is a dispatch on the argument's TYPE and a value on this path is one
    word with no tag to dispatch on.

    It copies `min(strlen(init), size)` bytes and terminates inside the buffer,
    which is `str_copy` and nothing else -- `str_copy` takes a COUNT, so handing
    it `size` when `init` is shorter reads PAST THE END of a read-only text
    section.  Measured: an image built from the first version of this function
    SEGFAULTED (exit 139) on `create_string_buffer("ab", 5)`, where CPython
    answers `b'ab\x00\x00\x00'`.  CPython does not silently truncate an over-long
    init either -- it raises `ValueError: byte string too long` -- so the refusal
    is `validate_buffer` below and this function's job is the copying.
    """
    var n = str_len(source)
    if n > size:
        n = size
    var p: Pointer[UInt8] = str_alloc(size)
    return str_copy(p, source, n)

ARG_OK = 0
ARG_BUF_TOO_LONG = 1
ARG_BUF_SIZE_NEGATIVE = 2

def validate_buffer(init_len: int, size: int) -> int:
    """`create_string_buffer(init, size)`'s own check: `ARG_OK`, or which error.

    A SEPARATE function from `create_string_buffer` because CPython REFUSES an
    init longer than the buffer -- `ValueError: byte string too long`, measured on
    this tree's CPython 3.14.6 -- and this path has no exception mechanism
    (FORMAL.md phase 7).  So the refusal is a value a caller asks for and the
    constructor does the copying; folding them together would mean one function
    returning either a string or an error code, and a value on this path is one
    64-bit word with no room for a sum type.

    The length is passed IN rather than measured: a caller holding a `char *`
    asks `str_len` for it, and this is then a pure function of two numbers, which
    is what `test_formal_admitted.py` can check against CPython's own
    `create_string_buffer` over a table of (init, size) pairs.
    """
    if size < 0:
        return ARG_BUF_SIZE_NEGATIVE
    if init_len > size:
        return ARG_BUF_TOO_LONG
    return ARG_OK

def create_zeroed_buffer(size: int) -> str:
    """`ctypes.create_string_buffer(n)` for an integer `n`: `n` zero bytes.

    The integer case of the same constructor, split out for the reason
    `create_string_buffer`'s docstring gives: this path cannot tell an integer
    from a byte string at the call site, so the two are two names.
    """
    return str_alloc(size)

def string_at(pointer: str) -> str:
    """`ctypes.string_at(addr)`: the NUL-terminated string AT an address.

    Dereferences, which is the operation `bugs/FORMAL_string_value_model.md`
    describes: a string on this path is a bare `char *` into a read-only text
    section, and reading the bytes at an arbitrary word is a fact about the
    address rather than about the value.  It is real rather than admitted
    because `strlen` and the byte load are both libSystem calls this target
    binds -- what is NOT assumed is anything about WHICH string is there.
    """
    return str_dup(pointer)


# ── the admitted half ────────────────────────────────────────────────────────

ADMITTED_EXIT_STATUS = 125
"""The status an admitted call exits with.

The same 125 as `formal/hostmods/subprocess.mojo`, and the same CORRECTED reason:
it is INSIDE `0..255`, so it cannot be read as an exit status a foreign function
produced is NOT what makes it safe — nothing can, because the kernel masks every
exit code into 0..255.  What makes it safe is that it is nonzero and reserved by
this tree, and that `_admitted` prints the contract that stopped the call; the
diagnostic is the channel, the number is the marker.  Repeated rather than
imported for the reason the file gives for not importing `struct`'s arithmetic --
`ctypes` is imported alone, and a shared constant across two hostmods is a second
thing to keep in step.
"""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted."""
    printf("ctypes: %s is an ADMITTED contract on this target\n", what)
    printf("ctypes: this image links libSystem and nothing else, so there is\n")
    printf("ctypes: no foreign library to load and no foreign code to call.\n")
    exit(ADMITTED_EXIT_STATUS)
    return 0

@admitted("the loader handle is 0 when dlopen(3) failed: the file may be absent, may not be a loadable image, or a symbol may be unresolvable, and CPython raises OSError for all three, or else a non-zero word this target's dynamic loader owns")
def cdll_open(name: str) -> int:
    """`ctypes.CDLL(name)`: load a shared library and return a handle.

    The one call in this module that cannot be computed here, and it is a single
    declaration rather than one per spelling because `CDLL` and `PyDLL` differ
    only in a symbol-lookup flag that has no meaning without a library to look
    in: `PyDLL` is `CDLL` plus `RTLD_GLOBAL`, and with no handle neither flag has
    anywhere to act.  A file that wants the difference has a library this target
    cannot load, which is the same statement.

    The contract is about the HANDLE'S SHAPE, and that is all it may be: whether
    a library of that name exists is a fact about the host's filesystem.  The
    admission used to cross that line — "0, meaning no library of that name is on
    this target" — and it was not merely out of scope, it was FALSE, which the
    audit measured: a file that exists and is not a loadable image makes
    `dlopen` fail and `ctypes.CDLL` raise `OSError: slice is not valid mach-o
    file`, so handle 0 does not mean the library is absent.  The text now says
    what `dlopen(3)` actually promises, which is a fact about an API rather than
    about this filesystem.
    """
    return _admitted("ctypes.CDLL")

@admitted("under ctypes' default restype of c_int the foreign function's answer is one word, and nothing is assumed about which value it is; a caller that sets restype, to a struct or to None, is asking a question this declaration does not answer")
def cdll_call(handle: int) -> int:
    """`lib.func(...)`: call a function in a loaded library.

    ONE parameter, the handle, and the SYMBOL NAME IS NOT CARRIED.  That is the
    same arity rule `formal/hostmods/subprocess.mojo` states and for the same
    reason: `MojoExpr.call` in `lib/ProofLib.lean` has a single `UInt64`
    argument, so a two-word contract cannot be applied without one of its words
    being silently dropped -- and a contract that quietly drops an argument is a
    claim about the host the model is not making.  A file that needs a second
    symbol calls `cdll_open` again, which is also what makes the handle
    single-purpose rather than a table this model would have to represent.

    The contract says the answer is one word and nothing else.  What a foreign
    function takes and returns is exactly the thing the loader's caller is
    supposed to know and this tree does not, so there is no prototype to state
    and no prototype is guessed.

    "One word" is bounded by the DEFAULT `restype`, and the admission says so
    because the audit found the unbounded version false twice: set
    `lib.getpid.restype = None` and CPython answers `None`, not a word, and a
    function declared to return a struct has no word at all.  `ctypes`' default is
    `c_int`, which is a word, so the default case the model serves is the one the
    contract covers.

    This is a separate contract from `cdll_open`'s on purpose: a file that opens
    a library and calls nothing through it rests on one admission, one that calls
    rests on two, and the `trust:` line says which.
    """
    return _admitted("a call through a ctypes library handle")
