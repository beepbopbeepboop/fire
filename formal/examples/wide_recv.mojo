struct Point:
    var x: Int
    var y: Int

    fn set_x(self, v: Int):
        self.x = v

    fn get_x(self) -> Int:
        return self.x

    fn get_y(self) -> Int:
        return self.y

def main(n) -> Int:
    var p = Point()
    p.set_x(3)
    p.set_x(4)
    return p.get_x() + p.get_y()
