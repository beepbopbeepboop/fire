"""Test class definitions."""

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    
    def distance(self):
        return self.x * self.x + self.y * self.y

def create_point():
    p = Point(3, 4)
    return p
