import os
import shutil
import platform

def find_gcc():
    """Find gcc binary: prefer gcc-15 in PATH, fallback to MacPorts gcc-mp-15, then gcc."""
    if shutil.which('gcc-15'):
        return 'gcc-15'
    if platform.system() == 'Darwin':
        gcc_mp15 = '/opt/local/bin/gcc-mp-15'
        if os.path.exists(gcc_mp15):
            return gcc_mp15
    return 'gcc'

def find_gxx():
    """Find g++ binary: prefer g++-15 in PATH, fallback to MacPorts g++-mp-15, then g++.

    Mirrors find_gcc()'s exact fallback chain. Used as the final LINK driver
    (not for ordinary .c compiles, which stay on gcc) whenever a build
    includes at least one C++-derived object file — e.g. the coroutine-based
    generator codegen path (see BACKLOG-CODEGEN.md / the generator-support
    milestones), which emits real C++20 `co_yield` code compiled by g++ and
    linked into an otherwise all-C -fgimple program."""
    if shutil.which('g++-15'):
        return 'g++-15'
    if platform.system() == 'Darwin':
        gxx_mp15 = '/opt/local/bin/g++-mp-15'
        if os.path.exists(gxx_mp15):
            return gxx_mp15
    return 'g++'

# Delegate to module_loader for stdlib path
from module_loader import STDLIB_PATH
__all__ = ['find_gcc', 'find_gxx', 'STDLIB_PATH']
