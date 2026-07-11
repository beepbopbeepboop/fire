#!/usr/bin/env python3
"""Build Mojo modules to shared libraries with symbol extraction."""

import sys
import os
import subprocess
import json
import argparse
from pathlib import Path

from gimple_codegen import compile_to_gimple_cached, compile_to_gimple, GimpleGen
from mojo_compiler import py_tokenize, Parser, FunctionDef, StructDef
from build_config import find_gcc


def extract_symbols(stmts):
    """Extract function and struct definitions for symbol table."""
    symbols = {
        'functions': {},
        'structs': {},
        'exports': []
    }

    for stmt in stmts:
        if isinstance(stmt, FunctionDef):
            ret_type = 'int'  # Default
            if stmt.return_type:
                gen = GimpleGen()
                ret_type = gen._resolve_type(stmt.return_type)
            symbols['functions'][stmt.name] = {
                'return_type': ret_type,
                'params': len(stmt.params),
                'c_name': stmt.name
            }
            symbols['exports'].append(stmt.name)

        elif isinstance(stmt, StructDef):
            fields = {}
            methods = {}

            for field in stmt.fields:
                if hasattr(field, 'name'):
                    fields[field.name] = 'int'  # Type info

            for method in stmt.methods:
                ret_type = 'int'
                if method.return_type:
                    gen = GimpleGen()
                    ret_type = gen._resolve_type(method.return_type)
                methods[method.name] = {
                    'return_type': ret_type,
                    'params': len(method.params)
                }

            symbols['structs'][stmt.name] = {
                'fields': fields,
                'methods': methods,
                'c_name': stmt.name
            }
            symbols['exports'].append(stmt.name)

    return symbols


def build_module(input_file, output_so, output_symbols=None):
    """Compile a Mojo module to a shared library."""

    # Read source
    with open(input_file) as f:
        source = f.read()

    # Parse and validate
    tokens = py_tokenize(source)
    stmts = Parser(tokens).parse_module()

    # Extract symbols before compilation
    symbols = extract_symbols(stmts)

    # Compile to GIMPLE
    c_code = compile_to_gimple_cached(source, do_imports=False)

    # Write temporary C file
    temp_c = output_so.replace('.so', '.c')
    with open(temp_c, 'w') as f:
        f.write(c_code)

    # Compile to shared library
    cc = find_gcc()
    cmd = [
        cc, '-fgimple', '-fPIC', '-shared',
        '-I', 'runtime',
        '-o', output_so,
        temp_c, 'runtime/mojo_runtime.c'
    ]

    print(f"Compiling {input_file} to {output_so}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Compilation failed:")
        print(result.stderr)
        return False

    print(f"✓ Built {output_so}")

    # Fix install name on macOS to use absolute path
    # This allows the .so to be loaded from anywhere, not just relative to current dir
    import platform
    if platform.system() == 'Darwin':
        so_abs = os.path.abspath(output_so)
        install_cmd = ['install_name_tool', '-id', so_abs, output_so]
        subprocess.run(install_cmd, capture_output=True)

    # Write symbol table if requested
    if output_symbols:
        with open(output_symbols, 'w') as f:
            json.dump(symbols, f, indent=2)
        print(f"✓ Symbols written to {output_symbols}")

    # Cleanup
    if os.path.exists(temp_c):
        os.remove(temp_c)

    return True


def main():
    parser = argparse.ArgumentParser(description='Build Mojo modules to shared libraries')
    parser.add_argument('input', help='Input .mojo file')
    parser.add_argument('--emit', default='shared-lib', help='Emit type')
    parser.add_argument('-o', '--output', help='Output file')
    parser.add_argument('--symbols', help='Symbol table output file')

    args = parser.parse_args()

    if not args.output:
        base = os.path.splitext(args.input)[0]
        args.output = f"{base}.so"

    if args.emit == 'shared-lib':
        success = build_module(args.input, args.output, args.symbols)
        sys.exit(0 if success else 1)
    else:
        print(f"Error: emit type '{args.emit}' not supported")
        sys.exit(1)


if __name__ == '__main__':
    main()
