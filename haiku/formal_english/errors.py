class FormalEnglishError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.message = message
        self.line = line
        self.col = col
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.line > 0 or self.col > 0:
            return f"[line {self.line}, col {self.col}] {self.message}"
        return self.message


class LexError(FormalEnglishError):
    pass


class ParseError(FormalEnglishError):
    pass


class CodegenError(FormalEnglishError):
    pass
