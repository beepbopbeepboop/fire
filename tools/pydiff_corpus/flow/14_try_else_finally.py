def attempt(text):
    try:
        n = int(text)
    except ValueError:
        print("  except for", repr(text))
        result = "bad"
    else:
        print("  else with", n)
        result = n * 2
    finally:
        print("  finally for", repr(text))
    return result


def main():
    print(attempt("5"))
    print(attempt("five"))
    print(attempt("-0"))
    print(attempt(""))
    print("done")


main()
