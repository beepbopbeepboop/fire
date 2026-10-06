#!/usr/bin/env python3
"""Unescape C code strings for bootstrap."""
import sys

def unescape_c(s):
    """Unescape C escape sequences."""
    # Replace escaped sequences
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            next_char = s[i + 1]
            if next_char == 'n':
                result.append('\n')
                i += 2
            elif next_char == 't':
                result.append('\t')
                i += 2
            elif next_char == 'r':
                result.append('\r')
                i += 2
            elif next_char == '\\':
                result.append('\\')
                i += 2
            elif next_char == '"':
                result.append('"')
                i += 2
            else:
                result.append(s[i])
                i += 1
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)

if __name__ == '__main__':
    content = sys.stdin.read()
    print(unescape_c(content), end='')
