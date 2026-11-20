def banner() -> str:
    return """line one
line two"""


def main():
    text = """first
second
third"""
    print(text)
    print(len(text))
    print(text.count("\n"))
    print(text.split("\n")[1])
    print(banner())
    block = '''quote ' and " inside
  indented'''
    print(block)
    print(repr(block))
    lines = text.splitlines()
    print(lines[-1])
    folded = "abc" \
        "def"
    print(folded)
    print(repr("""a\nb"""))
    print(len(""))
    print(len(""" """))


main()
