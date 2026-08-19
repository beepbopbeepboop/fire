from glob import glob
from os import getcwd

fn main():
    var cwd = getcwd()
    var files = glob(cwd + "/*.mojo")
    print(len(files))
