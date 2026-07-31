# CODEGEN_generator_function: Lib/subprocess.py

## Status
**STILL FAILING** (2026-07-30) — generator .cpp: /tmp/db.cpp:145:26: error: cast from 'Popen*' to 'int' loses. The generated generator C++ body does not compile standalone (gcc -fgimple on the .ci alone is not the real gate; mojo.py/test_gimple compile the companion .cpp).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/subprocess.py
