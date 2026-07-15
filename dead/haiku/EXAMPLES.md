# Formal English Examples

This document contains Formal English code examples that demonstrate the transpiler's capabilities.

## Basic Math Operations

Example: Simple arithmetic function

```formal-english
Import math

Define function calculate(a of type float, b of type float) returning float:
    Declare variable sum with value a plus b
    Declare variable product with value a times b
    Declare variable result with value sum plus product
    Return result

Declare variable answer with value call calculate with 3.5, 2.5
Print "Result:" and answer
```

## Working with Collections

Example: List processing

```formal-english
Declare variable numbers with value [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

Define function sum_list(items of type list of integer) returning integer:
    Declare variable total of type integer with value 0
    For each item in items:
        Increase total by item
    Return total

Declare variable result with value call sum_list with numbers
Print "Sum:" and result
```

## String Manipulation

Example: String operations

```formal-english
Define function get_length(text of type string) returning integer:
    Return call text.__len__

Declare variable original with value "hello world"
Declare variable length with value call get_length with original
Print "Text:" and original
Print "Length:" and length
```

## Data Structures

Example: Using structs and methods

```formal-english
Define struct Rectangle:
    Field width of type float
    Field height of type float

    Define method area(self) returning float:
        Return self's width times self's height

    Define method perimeter(self) returning float:
        Return 2.0 times (self's width plus self's height)

Declare variable rect of type Rectangle with value Rectangle()
Set rect's width to 5.0
Set rect's height to 3.0
Print "Area:" and call rect.area
Print "Perimeter:" and call rect.perimeter
```

## Control Flow

Example: Complex conditionals

```formal-english
Define function classify_number(x of type integer) returning string:
    If x is greater than 100:
        Return "large"
    Otherwise if x is greater than 10:
        Return "medium"
    Otherwise if x is greater than 0:
        Return "small"
    Otherwise:
        Return "non-positive"

Declare variable values with value [150, 50, 5, -10]
For each val in values:
    Print "Value:" and val and "Class:" and call classify_number with val
```

## Error Handling

Example: Exception handling

```formal-english
Define function safe_divide(a of type float, b of type float) returning float:
    Try:
        If b equals 0.0:
            Raise ValueError("Division by zero")
        Return a divided by b
    Except ValueError as e:
        Print "Error:" and e
        Return 0.0
    Finally:
        Print "Division operation completed"

Declare variable result1 with value call safe_divide with 10.0, 2.0
Declare variable result2 with value call safe_divide with 10.0, 0.0
```

## Functional Patterns

Example: Higher-order operations

```formal-english
Define function apply_operation(a of type integer, b of type integer, op of type string) returning integer:
    If op equals "add":
        Return a plus b
    Otherwise if op equals "multiply":
        Return a times b
    Otherwise if op equals "subtract":
        Return a minus b
    Otherwise:
        Return 0

Declare variable operations with value ["add", "multiply", "subtract"]
For each operation in operations:
    Declare variable res with value call apply_operation with 5, 3, operation
    Print operation and "result:" and res
```

## Advanced Comprehensions

Example: List comprehensions with filtering

```formal-english
Declare variable numbers with value [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
Declare variable filtered with value [x for x in numbers if x is greater than 5]
Declare variable squared with value [x times x for x in filtered]
Print "Filtered and squared:" and squared

Declare variable mapping with value {"a": 1, "b": 2, "c": 3}
Declare variable keys with value ["a", "b", "c"]
For each key in keys:
    Print "Key:" and key
```
