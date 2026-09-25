def bitops(n):
    return (n & 0xff) + (n | 0xf0) + (n ^ 0x55)
