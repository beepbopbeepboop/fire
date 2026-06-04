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

# Delegate to module_loader for stdlib path
from module_loader import STDLIB_PATH
__all__ = ['find_gcc', 'STDLIB_PATH']
