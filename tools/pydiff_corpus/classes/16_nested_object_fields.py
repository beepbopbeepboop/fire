class Engine:
    def __init__(self, power: int):
        self.power = power


class Car:
    def __init__(self, model: str, engine: Engine):
        self.model = model
        self.engine = engine


class Garage:
    def __init__(self, car: Car):
        self.car = car


def main():
    g = Garage(Car("zoom", Engine(150)))
    print(g.car.model)
    print(g.car.engine.power)
    g.car.engine.power = g.car.engine.power + 25
    print(g.car.engine.power)
    print(g.car.engine.power > 100)
    e = Engine(0)
    g.car.engine = e
    print(g.car.engine.power)
    print(g.car.engine is e)
    g2 = Garage(Car("", Engine(-1)))
    print(g2.car.model == "")
    print(g2.car.engine.power)
    print(g.car is g2.car)
    print(g.car.engine.power + g2.car.engine.power)
    shared = Engine(7)
    x = Car("a", shared)
    y = Car("b", shared)
    shared.power = 8
    print(x.engine.power)
    print(y.engine.power)


main()
