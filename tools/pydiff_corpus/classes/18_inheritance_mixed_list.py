class Animal:
    def __init__(self, name):
        self.name = name

    def speak(self):
        return "..."

    def describe(self):
        return self.name + " says " + self.speak()


class Dog(Animal):
    def speak(self):
        return "woof"


class Cat(Animal):
    def speak(self):
        return "meow"


def main():
    zoo = [Animal("thing"), Dog("rex"), Cat("tom"), Dog("")]
    for a in zoo:
        print(a.describe())
    sounds = []
    for a in zoo:
        sounds.append(a.speak())
    print(sounds)
    print(len(zoo))
    print(zoo[1].speak())
    print(zoo[2].name)
    print(type(zoo[0]).__name__)
    print(type(zoo[3]).__name__)
    print(isinstance(zoo[1], Animal))
    print(isinstance(zoo[0], Dog))
    print(Dog("x").speak() == Cat("y").speak())
    print(Animal("q").speak())


main()
