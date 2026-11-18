# R340 — Direct resident intra-projection weights on model 2

All three profiles replace each shim-to-memory fanout with direct
DMA from four memory tiles to ten compute tile receivers. The 40
unsigned byte initializers hold 405,504 exact BF16 coefficient and
FP32 bias bytes. Each source chains both blocks for its active lane.
The original core processing order and kernel calls remain. The
receive buffer uses an empty/full lock pair and an explicit alias for
the matrix span. The grouped input staging FIFOs disappear.
[AMD memory and DMA programming](https://docs.amd.com/r/2025.2-English/ug1079-ai-engine-kernel-coding/Memory-and-DMA-Programming)

The common placement proves nonoverlapping bank intervals for each
image. Independent readback verifies every immutable packet through
MLIR, CDO, PDI and xclbin, all circuit switchbox routes, core lock
pairs and the actual two-element TXN buffer-descriptor chains. The
compiled model still has 32 cores with program memory at most 14,416 B.
The K128 layout occupies up to 65,536 B of compute-tile L1.

Each active dual DPRNN call removes sixteen shim DDR descriptors
requesting 405,504 B. The ten direct tasks per lane issue 20 chained
memory-tile tasks within the same DPRNN command. The two GRU calls,
all remaining host DDR windows, allocation and hot API transfers
keep their existing numerical and size contracts. The requested
startup instruction upload and staging are each 1,776 B larger.
The existing seven-BO native contract temporarily keeps the now
unused intra slot to preserve snapshot layout and isolate this change.

Thirty bare native checks, six snapshot-library checks and eleven
protected startup traces run without a device open. Two early SDK
attempts failed before linking due to shadowed index helper and an
unsupported Buffer slice. Their artifacts are retained. The accepted
build uses an explicit MLIR view of the original matrix span and
keeps the bias span byte-exact.

All nine live owners match R339 across 960 PCM hops, 960 CPU/DSP
snapshots and 684 raw and compact NN snapshot pairs, including open,
every diagnostic frame, reset and replay. All 2,880 commands reconcile.
Both CPU masks and device power restore, all 24 CPUs return, and no
contexts remain. Serial and parallel analyses agree. This is a
functional and requested-byte proof. Paired timing is separate.
