"""Example: Using imports from modules.

This example demonstrates:
1. Importing functions from helper modules
2. Using imported functions in main program
3. Matrix multiply operator (via __matmul__ method calls)

To compile:
  python mojo_compiler.py < example_imports.mojo > /tmp/example.c
  gcc-mp-15 -fgimple -I runtime -o /tmp/example /tmp/example.c
"""

from test_helper import double, add

def main() -> Int:
    var x: Int = 10
    var y: Int = 20

    var doubled_x: Int = double(x)
    var sum_result: Int = add(doubled_x, y)

    return sum_result
