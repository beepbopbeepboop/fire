"""
Preprocessor for Formal English source code.
Removes markdown junk and other irrelevant syntax.
"""
import re


def clean_markdown(source: str) -> str:
    """
    Remove markdown syntax and formatting from source code.
    This allows Formal English code to be extracted from markdown files.
    """
    lines = source.split('\n')
    cleaned_lines = []

    for line in lines:
        # Remove markdown code block markers (```...```)
        line = re.sub(r'^```[a-z-]*$', '', line)

        # Remove markdown headers (# ## ### etc)
        line = re.sub(r'^#+\s+', '', line)

        # Remove HTML comments
        line = re.sub(r'<!--.*?-->', '', line)

        # Remove inline backticks (code markers) but keep the content
        line = re.sub(r'`([^`]+)`', r'\1', line)

        # Remove markdown bold (**text** or __text__)
        line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
        line = re.sub(r'__([^_]+)__', r'\1', line)

        # Remove markdown italic (*text* or _text_)
        line = re.sub(r'\*([^*]+)\*', r'\1', line)
        line = re.sub(r'_([^_]+)_', r'\1', line)

        # Remove markdown links [text](url)
        line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)

        # Remove markdown reference links [text][ref]
        line = re.sub(r'\[([^\]]+)\]\[.*?\]', r'\1', line)

        # Remove markdown inline code (kept as plain text)
        line = re.sub(r'`', '', line)

        # Remove markdown emphasis markers that might be left
        line = line.replace('**', '')
        line = line.replace('__', '')

        # Remove HTML tags
        line = re.sub(r'<[^>]+>', '', line)

        # Remove unicode arrows and dashes
        line = line.replace('→', '->')
        line = line.replace('←', '<-')
        line = line.replace('—', '-')  # em dash
        line = line.replace('–', '-')  # en dash
        line = line.replace('…', '...')  # ellipsis

        # Remove backslashes (often used in documentation)
        line = line.replace('\\', '')

        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def remove_markdown_structure(source: str) -> str:
    """
    Remove markdown structure elements to isolate code content.
    """
    lines = source.split('\n')
    result = []

    in_code_block = False
    for line in lines:
        # Track markdown code blocks
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            # Skip the marker line itself
            continue

        # Skip markdown-only lines
        if line.strip().startswith('#'):
            continue
        if line.strip().startswith('---'):  # Markdown divider
            continue
        if line.strip().startswith('___'):  # Markdown divider
            continue
        if line.strip().startswith('==='):  # Markdown underline header
            continue

        # Skip markdown bullet lists and numbered lists
        if re.match(r'^\s*[-*+]\s+', line):
            line = re.sub(r'^\s*[-*+]\s+', '', line)
        if re.match(r'^\s*\d+\.\s+', line):
            line = re.sub(r'^\s*\d+\.\s+', '', line)

        # Keep the line
        result.append(line)

    return '\n'.join(result)


def looks_like_formal_english(line: str) -> bool:
    """Check if a line looks like valid Formal English code (not documentation prose)."""
    stripped = line.strip()

    # Blank lines are fine
    if not stripped:
        return True

    # Formal English keywords that start statements
    formal_english_keywords = {
        'Define', 'Declare', 'Set', 'Increase', 'Decrease', 'Multiply', 'Divide',
        'If', 'Otherwise', 'While', 'For', 'Try', 'Except', 'Finally', 'With',
        'Return', 'Print', 'Raise', 'Pass', 'Break', 'Continue', 'Call',
        'Import', 'From', 'And', 'Or', 'Not', 'Else'
    }

    words = stripped.split()
    first_word = words[0] if words else ''

    # Only keep lines starting with a formal English keyword
    if first_word not in formal_english_keywords:
        return False

    # Additional filter: reject lines where keyword is followed by prose-like words
    # (e.g., "If Statements" or "While Loops" are headers, not code)
    if len(words) >= 2:
        second_word = words[1].lower()  # Case-insensitive comparison
        # Common prose patterns after keywords
        prose_indicators = {'statements', 'loops', 'blocks', 'expressions', 'declaration', 'declarations', 'type:', 'types', 'iterate', 'perform'}
        if second_word in prose_indicators:
            return False

    return True


def preprocess(source: str, aggressive: bool = True) -> str:
    """
    Preprocess Formal English source code to remove markdown junk.

    Args:
        source: Raw source code potentially containing markdown
        aggressive: If True, also removes markdown structure and prose; if False, only cleans formatting

    Returns:
        Cleaned source code ready for transpilation
    """
    # First pass: clean markdown formatting
    cleaned = clean_markdown(source)

    # Second pass: remove structure if aggressive mode
    if aggressive:
        cleaned = remove_markdown_structure(cleaned)

    # Third pass: aggressively filter out prose lines
    if aggressive:
        lines = cleaned.split('\n')
        filtered_lines = []
        for line in lines:
            if looks_like_formal_english(line):
                filtered_lines.append(line)
        cleaned = '\n'.join(filtered_lines)

    # Remove excessive blank lines (keep single blank lines for structure)
    cleaned = re.sub(r'\n\n\n+', '\n\n', cleaned)

    # Remove trailing whitespace from each line
    lines = cleaned.split('\n')
    lines = [line.rstrip() for line in lines]
    cleaned = '\n'.join(lines)

    # Strip leading/trailing whitespace from entire document
    cleaned = cleaned.strip()

    # If aggressive filtering removed everything (pure documentation), return empty
    # This will transpile to valid empty Python
    if aggressive and not cleaned:
        return ""

    return cleaned
