# CODEGEN: user __eq__/__len__/__contains__/__getitem__ are not used by ==/len/in/[]; subclass with super().__init__ crashes

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

`a == b` on two objects of a class with `__eq__`, `len(a)`, `x in a`, `a[0]` do not call the user methods. A hierarchy where one subclass calls `super().__init__(name)` and another does not crashes at the first call (segfault). Find how the compare/len/in/index lowering treats a struct operand and dispatch to the dunder method when the class defines it.

## Repro `class_dunder.py`

```python
class P:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
    def __len__(self):
        return self.x
    def __contains__(self, v):
        return v == self.x or v == self.y
    def __getitem__(self, i):
        return self.x if i == 0 else self.y
    def __str__(self):
        return "P(" + str(self.x) + ", " + str(self.y) + ")"

def main():
    a = P(1, 2)
    b = P(1, 2)
    print(a == b)
    print(a is b)
    print(len(a))
    print(2 in a)
    print(5 in a)
    print(a[0], a[1])
    print(a)
    print(str(a))
    print(isinstance(a, P))
main()
```

Differences:

```
line 4: CPython 'True'   compiled 'False'
```

## Repro `inherit.py`

```python
class Animal:
    def __init__(self, name):
        self.name = name
    def speak(self):
        return self.name + " says ..."

class Dog(Animal):
    def speak(self):
        return self.name + " says woof"

class Cat(Animal):
    def __init__(self, name, lives):
        super().__init__(name)
        self.lives = lives
    def speak(self):
        return self.name + " says meow"

def main():
    zoo = [Animal("thing"), Dog("rex"), Cat("tom", 9)]
    for a in zoo:
        print(a.speak())
    print(isinstance(zoo[1], Animal))
    print(isinstance(zoo[1], Cat))
    print(zoo[2].lives)
main()
```

Differences:

```
line 1: CPython 'thing says ...'   compiled ''
line 2: CPython 'rex says woof'   compiled '<no line>'
line 3: CPython 'tom says meow'   compiled '<no line>'
line 4: CPython 'True'   compiled '<no line>'
line 5: CPython 'False'   compiled '<no line>'
line 6: CPython '9'   compiled '<no line>'
line 7: CPython ''   compiled '<no line>'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
