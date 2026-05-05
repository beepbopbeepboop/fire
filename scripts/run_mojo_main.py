#!/usr/bin/env python3
"""Run mojo_main.mojo as Python code."""
import sys
import os

# Add project root to path so imports work
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

if len(sys.argv) < 2:
    print("/* no input */")
    sys.exit(1)

mojo_file = sys.argv[1]
sys.argv = ['mojo', mojo_file]

# Read and execute mojo_main.mojo as Python
try:
    with open(mojo_file) as f:
        code = f.read()
except:
    print("/* cannot read file */")
    sys.exit(1)

# Execute in a namespace
namespace = {}
try:
    exec(code, namespace)
    if 'main' in namespace:
        namespace['main']()
except Exception as e:
    print(f"/* error: {e} */")
    import traceback
    traceback.print_exc()
    sys.exit(1)
