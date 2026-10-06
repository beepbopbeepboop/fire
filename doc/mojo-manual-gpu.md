# Mojo Manual — GPU Programming

Source: https://docs.modular.com/mojo/manual/gpu/architecture/
        https://docs.modular.com/mojo/manual/gpu/fundamentals/
        https://docs.modular.com/mojo/manual/gpu/block-and-warp/
        https://docs.modular.com/mojo/manual/layout/layouts/
        https://docs.modular.com/mojo/manual/layout/tensors/

---

## GPU Architecture Overview

Source: https://docs.modular.com/mojo/manual/gpu/architecture/

GPUs contain thousands of smaller, simpler cores for parallel processing, vs CPUs with fewer powerful cores for sequential work.

### Streaming Multiprocessor (SM)

The fundamental GPU building block:
- **CUDA Cores**: basic integer and floating-point arithmetic
- **Tensor Cores**: matrix operations
- **Special Function Units**: complex math functions
- **Register Files**: ultra-fast per-thread storage
- **Shared Memory/L1 Cache**: low-latency programmable memory for thread collaboration
- **Load/Store Units**: data movement between memory spaces

### GPU Execution Model

Hierarchy: **Grid** → **Thread Blocks** → **Warps** (32–64 threads) → **Individual Threads**

Each thread in a warp executes the same instruction on different data — **SIMT** (single instruction, multiple threads). Optimal performance when all threads in a warp follow the same execution path (avoid warp divergence).

---

## GPU Programming Fundamentals

Source: https://docs.modular.com/mojo/manual/gpu/fundamentals/

### Detecting a GPU

```mojo
from std.sys import has_accelerator

def main():
    comptime if has_accelerator():
        print("GPU detected")
    else:
        print("No GPU detected")
```

Other detection functions: `has_amd_gpu_accelerator()`, `has_apple_gpu_accelerator()`, `has_nvidia_gpu_accelerator()`

### Programming Model

1. Initialize data in host (CPU) memory
2. Allocate device (GPU) memory, transfer data from host to device
3. Execute kernel function on GPU
4. Transfer results back from device to host

Typically asynchronous — CPU can do other work while GPU processes. Use `synchronize()` to wait for GPU completion.

### Complete Example: Scalar Addition

```mojo
from std.math import iota
from std.sys import exit, has_accelerator
from std.gpu.host import DeviceContext
from std.gpu import block_dim, block_idx, thread_idx

comptime num_elements = 20

def scalar_add(
    vector: UnsafePointer[Float32, MutAnyOrigin],
    size: Int,
    scalar: Float32,
):
    idx = block_idx.x * block_dim.x + thread_idx.x
    if idx < size:
        vector[idx] += scalar

def main() raises:
    comptime if not has_accelerator():
        print("No GPUs detected")
        exit(0)
    else:
        ctx = DeviceContext()

        host_buffer = ctx.enqueue_create_host_buffer[DType.float32](num_elements)
        ctx.synchronize()

        iota(host_buffer.as_span())
        print("Original:", host_buffer)

        device_buffer = ctx.enqueue_create_buffer[DType.float32](num_elements)
        ctx.enqueue_copy(src_buf=host_buffer, dst_buf=device_buffer)

        scalar_add_kernel = ctx.compile_function[scalar_add, scalar_add]()
        ctx.enqueue_function(
            scalar_add_kernel,
            device_buffer,
            num_elements,
            Float32(20.0),
            grid_dim=1,
            block_dim=num_elements,
        )

        ctx.enqueue_copy(src_buf=device_buffer, dst_buf=host_buffer)
        ctx.synchronize()
        print("Modified:", host_buffer)
```

### `DeviceContext`

Represents a logical GPU device instance.

```mojo
ctx = DeviceContext()            # default GPU (device 0)
ctx = DeviceContext(device_id=1) # specific GPU
ctx = DeviceContext(api="cuda")  # specific vendor API
n = DeviceContext.number_of_devices()
```

Supported APIs: `"cuda"` (NVIDIA), `"hip"` (AMD), `"metal"` (Apple)

### Asynchronous Operations

All `enqueue_*` methods are asynchronous. Operations in a stream execute in order.

```mojo
ctx.synchronize()  # block until all queued operations complete
```

### Multidimensional Grids

Thread organization: grid of blocks, each block of threads. Up to 3 dimensions.

```mojo
ctx.enqueue_function[kernel, kernel](
    grid_dim=(2, 2, 1),   # 2x2x1 blocks per grid
    block_dim=(4, 4, 2),  # 4x4x2 threads per block
)
```

`grid_dim` and `block_dim` accept `Dim`, `Tuple`, or `Int` (for x-only).

### Thread Index Variables (inside kernel)

| Variable | Description |
|----------|-------------|
| `grid_dim` | Dimensions of the grid (x, y, z) |
| `block_dim` | Dimensions of the thread block (x, y, z) |
| `block_idx` | Index of block within grid (x, y, z) |
| `thread_idx` | Index of thread within block (x, y, z) |
| `global_idx` | Global thread offset (x, y, z) |

```mojo
from std.gpu import block_dim, block_idx, global_idx, thread_idx

def print_threads():
    print(block_idx.x, block_idx.y, thread_idx.x, thread_idx.y, sep="\t")
```

### Writing Kernel Functions

- Must be non-raising
- Arguments must conform to `DevicePassable` trait
- No return values — write results to a passed memory buffer

Bounds check to avoid out-of-bounds memory:
```mojo
def process_vector(vector: UnsafePointer[Float32, MutAnyOrigin], size: Int):
    if global_idx.x < size:
        vector[global_idx.x] += 1.0
```

### `DevicePassable` Types

| Host type | Device type | Description |
|-----------|-------------|-------------|
| `Int` | `Int` | Signed integer |
| `SIMD[dtype, width]` | `SIMD[dtype, width]` | SIMD vector |
| `DeviceBuffer[dtype]` | `UnsafePointer[SIMD[dtype, 1]]` | Memory buffer |
| `TileTensor` | `TileTensor` | Multi-dimensional data |

### `DeviceBuffer` and `HostBuffer`

```mojo
device_buffer = ctx.enqueue_create_buffer[DType.float32](1024)
host_buffer = ctx.enqueue_create_host_buffer[DType.float32](1024)
ctx.synchronize()

# Write to host buffer
for i in range(1024):
    host_buffer[i] = Float32(i * i)

# Copy between buffers
ctx.enqueue_copy(src_buf=host_buffer, dst_buf=device_buffer)
ctx.enqueue_copy(src_buf=device_buffer, dst_buf=host_buffer)

# Convenience aliases
host_buffer.enqueue_copy_to(dst=device_buffer)
```

**Map to host** (for testing/prototyping):
```mojo
with input_device.map_to_host() as input_host:
    for i in range(length):
        input_host[i] = Float32(i)
# modifications auto-copied back on exit
```

Both types follow Mojo's ownership/lifecycle — memory freed automatically.

### Compiling and Enqueuing Kernels

```mojo
# Compile once, reuse
kernel = ctx.compile_function[my_kernel, my_kernel]()
ctx.enqueue_function(kernel, arg1, arg2, grid_dim=4, block_dim=256)

# Compile + enqueue in one step (for single-use)
ctx.enqueue_function[my_kernel, my_kernel](
    arg1, arg2, grid_dim=4, block_dim=256
)
```

**Note**: `compile_function_unchecked` / `enqueue_function_unchecked` are deprecated. Use `compile_function_experimental` / `enqueue_function_experimental` for new type-checked single-parameter API.

---

## Block and Warp Synchronization

Source: https://docs.modular.com/mojo/manual/gpu/block-and-warp/

### Block-Level Synchronization

**`barrier()`** — synchronization point for all threads in a block:
1. Execution barrier: all threads pause until every thread reaches the point
2. Memory fence: writes to shared memory become visible after the barrier

**Typical pattern**:
```mojo
# Load data into shared memory
# ...
barrier()  # ensure all data loaded
# Compute using shared memory
# ...
barrier()  # before loading new data (prevent overwrites)
```

**Critical**: All threads in a block MUST reach `barrier()`. Never place inside a conditional where some threads might skip — this causes deadlock.

### Block-Level Collective Operations

```mojo
from std.gpu.primitives.block import sum, max, min, broadcast, prefix_sum

result = sum(val)              # sum across all block threads
result = max(val)              # max across all threads
result = min(val)              # min across all threads
broadcast(val, src_thread=0)   # distribute from thread 0 to all
prefix_sum[exclusive=False](val)  # cumulative sum
```

These handle synchronization internally.

### Warp-Level Synchronization

**`syncwarp()`** — fine-grained sync within a single warp:
- NVIDIA (Volta+): actual hardware instruction
- AMD: no-op (wavefronts execute in lock-step)
- Apple: execution-only synchronization

Shuffle operations provide implicit synchronization — `syncwarp()` is unnecessary before them.

### Warp Shuffle Operations

Exchange registers between threads in a warp:

```mojo
shuffle_up(value, offset)    # receive from lower lane (lane - offset)
shuffle_down(value, offset)  # receive from higher lane (lane + offset)
shuffle_xor(value, offset)   # exchange via XOR of lane IDs
shuffle_idx(value, lane)     # receive from specified lane
broadcast(value)             # distribute lane 0's value to all
```

All support optional masks for thread participation.

### Warp Reduction Operations

```mojo
from std.gpu.primitives.warp import max, min, sum, prefix_sum

result = max(value)            # max across warp, broadcast to all lanes
result = min(value)            # min across warp, broadcast to all lanes
result = sum(value)            # sum across warp, broadcast to all lanes
prefix_sum[exclusive=False](value)  # scan
```

Faster than block-level reductions (operate on simultaneously-executing threads).

### Avoiding Race Conditions and Deadlocks

**Race condition**: multiple threads write to same memory without ordering. Use `Atomic` operations or `barrier()`.

**Deadlock pattern** (WRONG):
```mojo
if condition:
    barrier()  # some threads skip — DEADLOCK
```

### Choosing Synchronization Level

**Use warp primitives for**: high-frequency operations, data exchange between neighbors, small reductions, latency-critical code.

**Use block primitives for**: multi-warp shared memory coordination, multi-phase algorithms, aggregating from multiple warps.

### Portable Code

- Use `gpu.WARP_SIZE` constant instead of hardcoding 32
- Use `comptime if` for architecture-specific optimizations
- Test with varied thread block configurations

### Advanced: NVIDIA-Specific

- Semaphores for inter-block synchronization
- Named barriers (IDs 0–16)
- Memory barriers for async operations
- Thread fences for memory ordering

### Advanced: AMD-Specific

- Schedule barriers for instruction reordering
- Wait count operations for CDNA GPUs

---

## Layouts

Source: https://docs.modular.com/mojo/manual/layout/layouts/

### Overview

The `layout` package provides APIs for working with dense multidimensional arrays.

**Main types**:
- **`Layout`**: maps logical coordinates to linear index values (shape + stride tuples)
- **`LayoutTensor`**: flexible tensor type combining a Layout with a data pointer
- **`IntTuple`**: hierarchical tuple for defining and indexing layouts

### What's a Layout?

A layout maps logical coordinates to a single linear index. Comprises two tuples:
- **shape**: describes the logical coordinate space
- **stride**: determines linear index mapping

Notation: `(4:1)` means shape=4, stride=1 (contiguous vector of length 4).

**Concepts**:
- **Mode**: shape:stride pair. Rank-1 = vector; rank-2 = matrix.
- **Size**: product of all shape modes (number of elements addressed)
- **Rank**: number of modes
- **Cosize**: size of codomain; smallest contiguous array containing all elements

### Making Layouts

```mojo
Layout.row_major(rows, cols)    # rightmost coordinate varies fastest
Layout.col_major(rows, cols)    # leftmost coordinate varies fastest
Layout(shape, strides)          # custom layout
tile_to_shape(tile, shape)      # tiled layout from tile + final shape
blocked_product(tile, tiler)    # replace each tiler element with a tile
make_ordered_layout(shape, order)  # layout from shape and iteration order
```

### Non-contiguous Layouts

`(4:2)` creates a sparse 1D array where elements are spaced 2 apart in memory.

---

## LayoutTensor

Source: https://docs.modular.com/mojo/manual/layout/tensors/

A `LayoutTensor` provides a view of multi-dimensional data in a linear array.

Properties:
- A **layout** defining element arrangement
- A **DType** specifying data type
- A **pointer** to the data

### Accessing Elements

```mojo
element = tensor2d[x, y]
tensor2d[x, y] = z

# SIMD vector of elements:
var elements = tensor.load[4](row, col)
elements = elements * 2
tensor.store(row, col, elements)
```

### Creating a LayoutTensor

**On the CPU** (stack allocation):
```mojo
comptime rows = 8
comptime columns = 16
comptime layout = Layout.row_major(rows, columns)
var storage = InlineArray[Float32, rows * columns](uninitialized=True)
var tensor = LayoutTensor[DType.float32, layout](storage).fill(0)
```

**Large tensors** (heap):
```mojo
comptime layout = Layout.row_major(1024, 1024)
var ptr = alloc[Float32](1024 * 1024)
var tensor = LayoutTensor[DType.float32, layout](ptr)
```

**On the GPU** (global memory via `DeviceBuffer`):
```mojo
var dev_buf = ctx.enqueue_create_buffer[dtype](size)
var tensor = LayoutTensor[dtype, input_layout](dev_buf)
```

**Shared/local memory** (via `stack_allocation`):
```mojo
comptime tile_layout = Layout.row_major(16, 16)
var shared_tile = LayoutTensor[
    dtype,
    tile_layout,
    MutAnyOrigin,
    address_space=AddressSpace.SHARED,
].stack_allocation()
```

### Tiling Tensors

```mojo
var tile = tensor.tile[tile_size, tile_size](row_idx, col_idx)

# TileType for declaring tile variables
var my_tile: tensor.TileType[tile_size, tile_size]
for i in range(rows):
    for j in range(columns):
        my_tile = tensor.tile[tile_size, tile_size](i, j)
```

### Tiled Iterators

**Tiling a memory buffer**:
```mojo
comptime tile_layout = Layout.row_major(4, 4)
var iter = LayoutTensorIter[DType.int16, tile_layout, MutAnyOrigin](
    storage.unsafe_ptr(), buf_size
)
for i in range(ceildiv(buf_size, comptime (tile_layout.size()))):
    var tile = iter[]
    iter += 1
```

**Tiling a LayoutTensor**:
```mojo
for i in range(num_row_tiles):
    var iter = tensor.tiled_iterator[tile_size, tile_size, axis=1](i, 0)
    for _ in range(num_col_tiles):
        var tile = iter[]
        iter += 1
```

### Vectorizing Tensors

```mojo
var vectorized_tensor = tensor.vectorize[1, 4]()
```

Creates a view where each element is a vector of values. Useful for thread coarsening and efficient memory copies.

### Partitioning Across Threads

```mojo
comptime thread_layout = Layout.row_major(WARP_SIZE // simd_size, simd_size)
var fragment = tile.vectorize[1, simd_size]().distribute[thread_layout](lane_id())
```

### Copying Tensors

```mojo
shared_fragment.copy_from(global_fragment)          # synchronous
shared_fragment.copy_from_async(global_fragment)    # async (global→shared)
```

After `copy_from_async`, call `async_copy_wait_all()` (NVIDIA) then `barrier()`.
