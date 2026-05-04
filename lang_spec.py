"""Language Specification AST."""
from __future__ import annotations
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Literal definitions
# ---------------------------------------------------------------------------

@dataclass
class IntForm:
    name: str
    base: int
    prefixes: list
    digit_re: str

    def full_re(self) -> str:
        if not self.prefixes:
            return self.digit_re
        alt = '|'.join(re.escape(p) for p in self.prefixes)
        return f'(?:{alt}){self.digit_re}'


@dataclass
class FloatForm:
    name: str = 'float'
    digit_re: str = (r'\d+\.\d*(?:[eE][+-]?\d+)?'
                     r'|\.\d+(?:[eE][+-]?\d+)?'
                     r'|\d+[eE][+-]?\d+')

    def full_re(self) -> str:
        return self.digit_re


@dataclass
class BoolForm:
    name: str = 'bool'
    values: list = field(default_factory=lambda: ['True', 'False'])


@dataclass
class LiteralDef:
    kind: str
    forms: list       # list of IntForm | FloatForm | BoolForm
    constraints: list


# ---------------------------------------------------------------------------
# Operator definitions
# ---------------------------------------------------------------------------

@dataclass
class OperatorDef:
    symbols: list
    category: str
    precedence: int
    assoc: str


# ---------------------------------------------------------------------------
# Control flow definitions
# ---------------------------------------------------------------------------

@dataclass
class ControlFlowDef:
    kind: str
    primary_kw: str
    alt_kws: list
    has_condition: bool
    description: str


# ---------------------------------------------------------------------------
# Function declaration
# ---------------------------------------------------------------------------

@dataclass
class FunctionSpec:
    keyword: str = "def"
    return_arrow: str = "->"
    decorators: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Simple statements
# ---------------------------------------------------------------------------

@dataclass
class SimpleStmtDef:
    kind: str
    keyword: str
    has_value: bool
    optional: bool


# ---------------------------------------------------------------------------
# Import statements
# ---------------------------------------------------------------------------

@dataclass
class ImportDef:
    keyword: str = 'import'
    from_keyword: str = 'from'
    alias_kw: str = 'as'
    has_wildcard: bool = True


# ---------------------------------------------------------------------------
# Assignment statements
# ---------------------------------------------------------------------------

@dataclass
class AssignmentDef:
    declaration_kw: str          # 'var'
    aug_ops: list                 # ['+=', '-=', ...]
    has_destructuring: bool = True


# ---------------------------------------------------------------------------
# Expression constructs
# ---------------------------------------------------------------------------

@dataclass
class ExpressionDef:
    kind: str        # 'list','dict','set','tuple','member_access',
                     # 'subscript','ternary','comprehension','walrus'
    description: str = ''


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@dataclass
class TryStmtDef:
    keywords: list
    binding_kw: str


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@dataclass
class WithStmtDef:
    keyword: str = "with"
    alias_kw: str = "as"


# ---------------------------------------------------------------------------
# Compile-time control flow
# ---------------------------------------------------------------------------

@dataclass
class ComptimeDef:
    prefix: str
    kinds: list


# ---------------------------------------------------------------------------
# Layout / tokenization rules
# ---------------------------------------------------------------------------

@dataclass
class LayoutDef:
    has_indentation:    bool   # indentation defines block scope
    indent_size:        int    # spaces per indent level (typically 4)
    continuation_char:  str    # line-continuation character (e.g. '\\')
    stmt_separator:     str    # in-line statement separator (e.g. ';')
    comment_char:       str    # comment introducer (e.g. '#')


# ---------------------------------------------------------------------------
# Argument conventions (ownership / value passing)
# ---------------------------------------------------------------------------

@dataclass
class ArgConventionDef:
    conventions: list   # e.g. ['read','mut','var','ref','out','deinit']


# ---------------------------------------------------------------------------
# Struct specification
# ---------------------------------------------------------------------------

@dataclass
class StructSpec:
    decorators: list    # e.g. ['fieldwise_init']
    traits: list        # e.g. ['Copyable','Movable',...]
    has_fields: bool


# ---------------------------------------------------------------------------
# Trait specification
# ---------------------------------------------------------------------------

@dataclass
class TraitSpec:
    has_where_clause: bool
    builtin_traits: list  # e.g. ['Copyable','Movable','Sized',...]


# ---------------------------------------------------------------------------
# Value lifecycle (constructors / destructors / transfer sigil)
# ---------------------------------------------------------------------------

@dataclass
class LifecycleDef:
    has_transfer_sigil: bool    # ^ sigil
    has_copy_constructor: bool
    has_move_constructor: bool
    has_destructor: bool


# ---------------------------------------------------------------------------
# Compile-time parameters  ([])
# ---------------------------------------------------------------------------

@dataclass
class ParameterDef:
    syntax: str           # '[]'
    has_infer_only: bool  # // separator
    has_default: bool


# ---------------------------------------------------------------------------
# Pointer types
# ---------------------------------------------------------------------------

@dataclass
class PointerDef:
    types: list   # e.g. ['Pointer','OwnedPointer','ArcPointer','UnsafePointer']


# ---------------------------------------------------------------------------
# Python interoperability
# ---------------------------------------------------------------------------

@dataclass
class PythonInteropDef:
    import_fn: str       # 'Python.import_module'
    wrapper_type: str    # 'PythonObject'
    add_to_path_fn: str  # 'Python.add_to_path'


# ---------------------------------------------------------------------------
# TODO: GPU programming (codegen deferred)
# ---------------------------------------------------------------------------

@dataclass
class GPUDef:
    device_type: str    # 'DeviceContext'
    buffer_types: list  # ['DeviceBuffer','HostBuffer']
    index_vars: list    # ['block_idx','thread_idx','global_idx',...]


# ---------------------------------------------------------------------------
# Testing framework
# ---------------------------------------------------------------------------

@dataclass
class TestingDef:
    suite_type: str       # 'TestSuite'
    assertion_fns: list   # ['assert_equal','assert_true',...]


# ---------------------------------------------------------------------------
# Collection types
# ---------------------------------------------------------------------------

@dataclass
class CollectionTypeDef:
    types: list   # e.g. ['List','Dict','Set','Optional','Tuple','Variant']


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------

@dataclass
class LanguageSpec:
    literals:         list = field(default_factory=list)
    operators:        list = field(default_factory=list)
    control_flow:     list = field(default_factory=list)
    functions:        list = field(default_factory=list)
    simple_stmts:     list = field(default_factory=list)
    imports:          list = field(default_factory=list)
    assignments:      list = field(default_factory=list)
    expressions:      list = field(default_factory=list)
    try_stmts:        list = field(default_factory=list)
    with_stmts:       list = field(default_factory=list)
    comptime:         list = field(default_factory=list)
    layout:           list = field(default_factory=list)
    arg_conventions:  list = field(default_factory=list)
    structs:          list = field(default_factory=list)
    traits:           list = field(default_factory=list)
    lifecycle:        list = field(default_factory=list)
    parameters:       list = field(default_factory=list)
    pointers:         list = field(default_factory=list)
    python_interop:   list = field(default_factory=list)
    gpu:              list = field(default_factory=list)
    testing:          list = field(default_factory=list)
    collection_types: list = field(default_factory=list)
