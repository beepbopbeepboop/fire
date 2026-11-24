"""Source-level types of the whole-closure type solver (bugs/GIR_type_solver.md, 2.1).

An `STy` is a SOURCE-level type: the lattice the solver computes over. It is
neither a GIR type (`mojo/ir/types.py`) nor a C spelling; `mojo/tsolve/lower.py`
is the one place that maps one to the other.

Rules (doc/GIR.md, rule 2): plain classes, every field annotated in `__init__`,
no closures, no lambdas, no `re`, no tuple unpacking, no `getattr`, no
generators. Every constructor interns its result, so two equal types are the
same object and `a.key == b.key` is the equality test.

`join` is the only place two types are combined. `dyn` is the top of the
lattice ("conflicting or unknowable"); `bot` is the bottom ("no information
yet") and the identity of `join`.
"""
from __future__ import annotations

KINDS = ('bot', 'none', 'bool', 'int', 'float', 'str', 'list', 'tuple', 'dict',
         'set', 'struct', 'func', 'dyn')

# Container nesting limit (bugs/GIR_type_solver.md, 2.1 `cap`). A container
# nested deeper than this becomes `dyn`, so the lattice has finite height and
# the solver terminates.
MAX_DEPTH = 3

# Kinds that are a nullable pointer in the C representation: `None` joined with
# one of these is that type (`None` is NULL), the rule in `join` below.
_POINTER_KINDS = ('str', 'list', 'tuple', 'dict', 'set', 'struct')


class STy:
    """One source-level type. Use the module constructors, never this one."""

    def __init__(self, kind: str, name: str, args: list):
        self.kind: str = kind      # one of KINDS
        self.name: str = name      # class name when kind == 'struct', else ''
        self.args: list = args     # list/set: [elem]; dict: [key, val]; tuple: slots
        self.key: str = _sty_spell(kind, name, args)

    def __repr__(self) -> str:
        return self.key


_INTERN: dict = {}


def _sty_spell(kind: str, name: str, args: list) -> str:
    if kind == 'struct':
        return 'struct:' + name
    if kind == 'list':
        return 'list[' + args[0].key + ']'
    if kind == 'set':
        return 'set[' + args[0].key + ']'
    if kind == 'dict':
        return 'dict[' + args[0].key + ', ' + args[1].key + ']'
    if kind == 'tuple':
        parts = []
        for a in args:
            parts.append(a.key)
        return 'tuple[' + ', '.join(parts) + ']'
    return kind


def _sty_intern(kind: str, name: str, args: list) -> STy:
    t = STy(kind, name, args)
    got = _INTERN.get(t.key)
    if got is not None:
        return got
    _INTERN[t.key] = t
    return t


BOT: STy = _sty_intern('bot', '', [])
NONE: STy = _sty_intern('none', '', [])
BOOL: STy = _sty_intern('bool', '', [])
INT: STy = _sty_intern('int', '', [])
FLOAT: STy = _sty_intern('float', '', [])
STR: STy = _sty_intern('str', '', [])
FUNC: STy = _sty_intern('func', '', [])
DYN: STy = _sty_intern('dyn', '', [])


def list_of(elem: STy) -> STy:
    return _sty_intern('list', '', [elem])


def set_of(elem: STy) -> STy:
    return _sty_intern('set', '', [elem])


def dict_of(key: STy, val: STy) -> STy:
    return _sty_intern('dict', '', [key, val])


def tuple_of(slots: list) -> STy:
    return _sty_intern('tuple', '', list(slots))


def struct_of(name: str) -> STy:
    return _sty_intern('struct', name, [])


def _sty_rebuild(t: STy, args: list) -> STy:
    if t.kind == 'list':
        return list_of(args[0])
    if t.kind == 'set':
        return set_of(args[0])
    if t.kind == 'dict':
        return dict_of(args[0], args[1])
    return tuple_of(args)


def _sty_cap_at(t: STy, level: int) -> STy:
    # `level` is the nesting level of `t` itself: the outermost type is 1.
    if not t.args:
        return t
    if level > MAX_DEPTH:
        return DYN
    new_args = []
    for a in t.args:
        new_args.append(_sty_cap_at(a, level + 1))
    return _sty_rebuild(t, new_args)


def cap(t: STy) -> STy:
    """Limit container nesting to `MAX_DEPTH`; a deeper container becomes `dyn`."""
    return _sty_cap_at(t, 1)


def join(a: STy, b: STy) -> STy:
    """The least upper bound of two source types (bugs/GIR_type_solver.md, 2.1)."""
    # 1. `bot` is the identity; equal types join to themselves.
    if a.kind == 'bot':
        return b
    if b.kind == 'bot':
        return a
    if a.key == b.key:
        return cap(a)
    # 2. `None` joined with a nullable pointer is that pointer (None is NULL).
    if a.kind == 'none' or b.kind == 'none':
        other = b if a.kind == 'none' else a
        if other.kind in _POINTER_KINDS:
            return other
        return DYN
    if a.kind == 'dyn' or b.kind == 'dyn':
        return DYN
    ka = a.kind
    kb = b.kind
    # 3. Same container kind joins elementwise.
    if ka == 'list' and kb == 'list':
        return cap(list_of(join(a.args[0], b.args[0])))
    if ka == 'set' and kb == 'set':
        return cap(set_of(join(a.args[0], b.args[0])))
    if ka == 'dict' and kb == 'dict':
        return cap(dict_of(join(a.args[0], b.args[0]), join(a.args[1], b.args[1])))
    if ka == 'tuple' and kb == 'tuple':
        if len(a.args) == len(b.args):
            slots = []
            for i in range(len(a.args)):
                slots.append(join(a.args[i], b.args[i]))
            return cap(tuple_of(slots))
        return cap(list_of(_join_all(a.args + b.args)))
    if (ka == 'tuple' and kb == 'list') or (ka == 'list' and kb == 'tuple'):
        tup = a if ka == 'tuple' else b
        lst = b if ka == 'tuple' else a
        return cap(list_of(join(lst.args[0], _join_all(tup.args))))
    # 4. Everything else (bool with int, int with float, str with list, a
    # struct with another struct, ...) is `dyn`.
    return DYN


def _join_all(types: list) -> STy:
    out = BOT
    for t in types:
        out = join(out, t)
    return out


# ── from_annotation ─────────────────────────────────────────────────────────

def split_top(text: str, sep: str) -> list:
    """Split `text` on `sep` where it is not nested in brackets or parentheses."""
    parts = []
    depth = 0
    cur = ''
    for ch in text:
        if ch in '[(':
            depth += 1
        elif ch in '])':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def _bare(name: str, class_names) -> STy:
    if name in ('int', 'Int', 'Int64'):
        return INT
    if name in ('float', 'Float64'):
        return FLOAT
    if name in ('bool', 'Bool'):
        return BOOL
    if name in ('str', 'String', 'StringLiteral'):
        return STR
    if name in ('list', 'List', 'tuple', 'Tuple'):
        return list_of(DYN)
    if name in ('dict', 'Dict'):
        return dict_of(DYN, DYN)
    if name in ('set', 'Set'):
        return set_of(DYN)
    if name in class_names:
        return struct_of(name)
    return DYN


def from_annotation(text, class_names) -> STy:
    """Parse an annotation string into an `STy` (bugs/GIR_type_solver.md, 2.1).

    `class_names` is any container of the closure's class names (a set or a
    dict). A name in it is `struct_of(name)`; any other unknown name is `dyn`.
    The text is split with a small scanner, not a regex.
    """
    if text is None:
        return DYN
    s = text.strip()
    if s == '':
        return DYN
    bars = split_top(s, '|')
    if len(bars) > 1:
        out = BOT
        for p in bars:
            out = join(out, from_annotation(p, class_names))
        return out
    if s == 'None':
        return NONE
    lb = s.find('[')
    if lb < 0:
        return _bare(s, class_names)
    if not s.endswith(']'):
        return DYN
    head = s[:lb].strip()
    args = split_top(s[lb + 1:-1], ',')
    if head == 'Optional' and len(args) == 1:
        return join(from_annotation(args[0], class_names), NONE)
    if head in ('list', 'List') and len(args) == 1:
        return cap(list_of(from_annotation(args[0], class_names)))
    if head in ('set', 'Set') and len(args) == 1:
        return cap(set_of(from_annotation(args[0], class_names)))
    if head in ('dict', 'Dict') and len(args) == 2:
        return cap(dict_of(from_annotation(args[0], class_names),
                           from_annotation(args[1], class_names)))
    if head in ('tuple', 'Tuple') and len(args) == 2 and args[1] == '...':
        return cap(list_of(from_annotation(args[0], class_names)))
    if head in ('tuple', 'Tuple') and len(args) >= 1:
        slots = []
        for a in args:
            slots.append(from_annotation(a, class_names))
        return cap(tuple_of(slots))
    return DYN
