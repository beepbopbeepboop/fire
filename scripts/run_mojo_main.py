#!/usr/bin/env python3
"""Run mojo_main.mojo as Python code (with transitive closure)."""
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

# Import tokenizer to follow transitive closure
from fire_compiler import py_tokenize

def collect_transitive_files(entry_path, visited=None):
    """Collect all files in transitive import closure."""
    if visited is None:
        visited = set()

    path = os.path.realpath(entry_path)
    if path in visited:
        return []
    visited.add(path)

    results = []
    base_dir = os.path.dirname(path)
    project_root = os.path.dirname(base_dir) if base_dir.endswith('/mojo') else base_dir

    # Parse the file to find imports
    try:
        with open(path) as f:
            src = f.read()
        tokens = py_tokenize(src)

        # Simple import detection
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind == 'KW' and tok.value in ('import', 'from'):
                # Found an import statement
                i += 1
                if i < len(tokens) and tokens[i].kind == 'NAME':
                    module = tokens[i].value
                    # Only follow .mojo files (stubs are parseable; real .py files aren't)
                    candidates = [
                        os.path.join(base_dir, module + '.mojo'),
                        os.path.join(project_root, module + '.mojo'),
                    ]
                    for candidate in candidates:
                        if os.path.exists(candidate):
                            results.extend(collect_transitive_files(candidate, visited))
                            break
            i += 1
    except:
        pass

    results.append(path)
    return results

def mojo_to_python(src: str) -> str:
    """Convert Mojo syntax to Python-compatible syntax."""
    import re

    # Convert 'struct' to 'class'
    src = re.sub(r'\bstruct\b', 'class', src)

    # Convert 'fn ' to 'def ' (but not in strings)
    lines = src.split('\n')
    result = []
    for line in lines:
        # Simple heuristic: convert fn at start of line or after indent/decorator
        if re.match(r'^(\s*)(fn|@.*\n\s*fn)\b', line):
            line = re.sub(r'\bfn\b', 'def', line)
        result.append(line)
    src = '\n'.join(result)

    return src

# Collect all files in transitive closure
files = collect_transitive_files(mojo_file)

# Import and execute mojo_main to run the parser
try:
    # Add mojo directory to path so imports work
    mojo_dir = os.path.dirname(os.path.realpath(mojo_file))
    sys.path.insert(0, mojo_dir)

    # Execute files in dependency order (dependencies first)
    # Order: ast_nodes, tokenizer, parser, codegen, mojo_main
    order_priority = {
        'ast_nodes.mojo': 0,
        'tokenizer.mojo': 1,
        'parser.mojo': 2,
        # 'codegen.mojo': 3,  # Skip codegen for now (has undefined references)
        'mojo_main.mojo': 4,
    }

    # Skip codegen since it references undefined symbols
    skip_files = {'codegen.mojo'}

    # Sort files by priority
    def get_priority(path):
        name = os.path.basename(path)
        return order_priority.get(name, 100)

    files = sorted(files, key=get_priority)

    # Read and execute mojo_main.mojo with transitive closure
    import types
    modules = {}
    namespace = {}

    for filepath in files:
        # Skip codegen for now
        if os.path.basename(filepath) in skip_files:
            continue
        with open(filepath) as f:
            src = f.read()
        # Convert Mojo syntax to Python
        src = mojo_to_python(src)

        # Create a module for this file
        module_name = os.path.basename(filepath).replace('.mojo', '')
        module = types.ModuleType(module_name)
        module.__file__ = filepath
        sys.modules[module_name] = module

        # Execute in the module's namespace
        exec(src, module.__dict__)
        modules[module_name] = module
        namespace.update(module.__dict__)

    # Run main() which will call parse() and output AST
    if 'main' in namespace:
        try:
            namespace['main']()
        except SystemExit:
            pass  # Ignore sys.exit() calls
except Exception as e:
    print(f"/* error: {e} */")
    import traceback
    traceback.print_exc()
    sys.exit(1)
