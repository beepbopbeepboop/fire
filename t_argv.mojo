import sys

def main():
    print(len(sys.argv))
    print(sys.argv[0])
    if len(sys.argv) > 1:
        print(sys.argv[1])
