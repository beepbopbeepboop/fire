from .lexer import Lexer
from .parser import Parser
from .codegen import CodeGenerator
from .preprocessor import preprocess
from . import type_map
from .errors import FormalEnglishError, LexError, ParseError, CodegenError


def transpile(source: str, preprocess_markdown: bool = False) -> str:
    """
    Transpile Formal English source to Python source string.

    Args:
        source: Formal English source code
        preprocess_markdown: If True, remove markdown junk before transpiling

    Returns:
        Valid Python source code
    """
    type_map._needs_any = False

    # Optionally preprocess to remove markdown
    if preprocess_markdown:
        source = preprocess(source)

    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    return CodeGenerator().generate(ast)


__all__ = ["transpile", "FormalEnglishError", "LexError", "ParseError", "CodegenError"]
