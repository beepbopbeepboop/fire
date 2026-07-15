from enum import Enum, auto
from dataclasses import dataclass


class TT(Enum):
    # Structural
    INDENT = auto()
    DEDENT = auto()
    NEWLINE = auto()
    EOF = auto()

    # Literals
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    BOOL = auto()
    NONE = auto()
    SELF = auto()

    # Names
    NAME = auto()

    # Punctuation
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    COLON = auto()
    DOT = auto()
    ARROW = auto()
    WALRUS = auto()
    SEMICOL = auto()

    # Arithmetic
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    DSTAR = auto()
    SLASH = auto()
    DSLASH = auto()
    PERCENT = auto()
    AT = auto()

    # Bitwise
    AMP = auto()
    PIPE = auto()
    CARET = auto()
    TILDE = auto()
    LSHIFT = auto()
    RSHIFT = auto()

    # Comparison
    EQ = auto()
    NEQ = auto()
    LT = auto()
    GT = auto()
    LTE = auto()
    GTE = auto()

    # Assignment
    ASSIGN = auto()
    PLUSEQ = auto()
    MINUSEQ = auto()
    STAREQ = auto()
    SLASHEQ = auto()
    DSLASHEQ = auto()
    PERCENTEQ = auto()
    DSTAREQ = auto()
    AMPEQ = auto()
    PIPEEQ = auto()
    CARETEQ = auto()
    LSHIFTEQ = auto()
    RSHIFTEQ = auto()

    # Special
    APOSTROPHE_S = auto()
    ELLIPSIS = auto()
    DISCARD = auto()


@dataclass
class Token:
    type: TT
    value: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, {self.line}, {self.col})"
