#!/usr/bin/env python3
import os
import sys

# Test against /Users/mrs/net/chatgpt/claude/modular
MODULAR_PATH = '/Users/mrs/net/chatgpt/claude/modular'
MOJO_STDLIB = os.path.join(MODULAR_PATH, 'mojo', 'stdlib')
if not os.path.isdir(MOJO_STDLIB):
    # Try alternative layout
    MOJO_STDLIB_ALT = os.path.join(MODULAR_PATH, 'stdlib')
    if os.path.isdir(MOJO_STDLIB_ALT):
        MOJO_STDLIB = MOJO_STDLIB_ALT

os.environ['MOJO_STDLIB'] = MOJO_STDLIB
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_loader import STDLIB_PATH
print(f'STDLIB_PATH: {STDLIB_PATH}')
print(f'Testing against: {MODULAR_PATH}')
