def xorshift64star(state: Int) -> Int:
    var x = state
    x = x ^ (x >> 12)
    x = x ^ (x << 25)
    x = x ^ (x >> 27)
    return x * 0x2545F4914F6CDD1D & 0xFFFFFFFFFFFFFFFF

def mix_hash(hash: Int, value: Int) -> Int:
    return xorshift64star(hash) ^ value

def main() raises:
    var hash: Int = 1
    var pass_count: Int = 0
    var fail_count: Int = 0
    
    # Basic arithmetic
    var r1: Int = 42
    hash = mix_hash(hash, r1)
    if r1 == 42: pass_count += 1
    else: fail_count += 1
    
    var r2: Int = 15 + 27
    hash = mix_hash(hash, r2)
    if r2 == 42: pass_count += 1
    else: fail_count += 1
    
    var r3: Int = 100 - 58
    hash = mix_hash(hash, r3)
    if r3 == 42: pass_count += 1
    else: fail_count += 1
    
    var r4: Int = 6 * 7
    hash = mix_hash(hash, r4)
    if r4 == 42: pass_count += 1
    else: fail_count += 1
    
    var r5: Int = 84 / 2
    hash = mix_hash(hash, r5)
    if r5 == 42: pass_count += 1
    else: fail_count += 1
    
    var r6: Int = 84 // 2
    hash = mix_hash(hash, r6)
    if r6 == 42: pass_count += 1
    else: fail_count += 1
    
    var r7: Int = 86 % 44
    hash = mix_hash(hash, r7)
    if r7 == 42: pass_count += 1
    else: fail_count += 1
    
    var r8: Int = 42 ** 1
    hash = mix_hash(hash, r8)
    if r8 == 42: pass_count += 1
    else: fail_count += 1
    
    var r9: Int = 42 & 42
    hash = mix_hash(hash, r9)
    if r9 == 42: pass_count += 1
    else: fail_count += 1
    
    var r10: Int = 42 | 0
    hash = mix_hash(hash, r10)
    if r10 == 42: pass_count += 1
    else: fail_count += 1
    
    var r11: Int = 42 ^ 0
    hash = mix_hash(hash, r11)
    if r11 == 42: pass_count += 1
    else: fail_count += 1
    
    var r12: Int = 10 << 2
    hash = mix_hash(hash, r12)
    if r12 == 40: pass_count += 1
    else: fail_count += 1
    
    var r13: Int = 168 >> 2
    hash = mix_hash(hash, r13)
    if r13 == 42: pass_count += 1
    else: fail_count += 1
    
    var r14: Int = -(-42)
    hash = mix_hash(hash, r14)
    if r14 == 42: pass_count += 1
    else: fail_count += 1
    
    # Comparisons
    var c1: Bool = 42 == 42
    hash = mix_hash(hash, 1)
    if c1: pass_count += 1
    else: fail_count += 1
    
    var c2: Bool = 42 != 43
    hash = mix_hash(hash, 1)
    if c2: pass_count += 1
    else: fail_count += 1
    
    var c3: Bool = 41 < 42
    hash = mix_hash(hash, 1)
    if c3: pass_count += 1
    else: fail_count += 1
    
    var c4: Bool = 43 > 42
    hash = mix_hash(hash, 1)
    if c4: pass_count += 1
    else: fail_count += 1
    
    var c5: Bool = 42 <= 42
    hash = mix_hash(hash, 1)
    if c5: pass_count += 1
    else: fail_count += 1
    
    var c6: Bool = 42 >= 42
    hash = mix_hash(hash, 1)
    if c6: pass_count += 1
    else: fail_count += 1
    
    # Boolean operations
    var b1: Bool = True
    hash = mix_hash(hash, 1)
    if b1: pass_count += 1
    else: fail_count += 1
    
    var b2: Bool = False
    hash = mix_hash(hash, 0)
    if not b2: pass_count += 1
    else: fail_count += 1
    
    # Collections
    var list1 = [1, 2, 3]
    hash = mix_hash(hash, 3)
    pass_count += 1
    
    var dict1 = {"a": 1, "b": 2}
    hash = mix_hash(hash, 2)
    pass_count += 1
    
    var tup1 = (1, 2, 3)
    hash = mix_hash(hash, 3)
    pass_count += 1
    
    var set1 = {1, 2, 3}
    hash = mix_hash(hash, 3)
    pass_count += 1
    
    # Function definition
    def add(a: Int, b: Int) -> Int:
        return a + b
    var f1: Int = add(20, 22)
    hash = mix_hash(hash, f1)
    if f1 == 42: pass_count += 1
    else: fail_count += 1
    
    # If statement
    var cond: Bool = True
    var if_result: Int = 0
    if cond: if_result = 1
    hash = mix_hash(hash, if_result)
    if if_result == 1: pass_count += 1
    else: fail_count += 1
    
    # While loop (simple)
    var sum_val: Int = 0
    var i: Int = 1
    while i <= 10:
        sum_val = sum_val + i
        i = i + 1
    hash = mix_hash(hash, sum_val)
    if sum_val == 55: pass_count += 1
    else: fail_count += 1
    
    # For loop
    var total: Int = 0
    for item in [1, 2, 3]:
        total = total + item
    hash = mix_hash(hash, total)
    if total == 6: pass_count += 1
    else: fail_count += 1
    
    # String
    var s1: String = "hello"
    hash = mix_hash(hash, 0)
    pass_count += 1
    
    # List indexing
    var list2: List[Int] = [10, 20, 30]
    hash = mix_hash(hash, list2[1])
    if list2[1] == 20: pass_count += 1
    else: fail_count += 1
    
    # Dict access
    var dict2: Dict[String, Int] = {"x": 100}
    hash = mix_hash(hash, dict2["x"])
    if dict2["x"] == 100: pass_count += 1
    else: fail_count += 1
    
    # Assignment
    var a1: Int = 10
    a1 = a1 + 32
    hash = mix_hash(hash, a1)
    if a1 == 42: pass_count += 1
    else: fail_count += 1
    
    # Finally
    print("Test Results:")
    print("Pass:", pass_count, "Fail:", fail_count, "Hash:", hash)
    if fail_count == 0:
        print("SUCCESS: All tests passed")
    else:
        print("FAILURE: Tests failed")
