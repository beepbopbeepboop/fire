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
