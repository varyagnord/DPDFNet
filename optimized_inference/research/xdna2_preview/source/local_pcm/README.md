# Selected XDNA2 component sources

These Apache-2.0 source inputs accompany the local R851/R877 checkpoint.
The model weights, model family and original DPDFNet implementation are
by the DPDFNet authors at Ceva. The changes here cover XDNA2 inference,
placement and the desktop integration.

- `paired_hidden.cc` is the packed BF16 paired-gate kernel from the
  compiled model-2 source. It keeps four projection bands in accumulators
  and adds bias before the two role-specific stores.
- `packed_snapshot.h` converts that device-side coefficient layout back
  to the original diagnostic byte order directly from mapped buffers.
- `grid_exp.inc` is the model-8 exponential implementation. The selected
  graph instantiates it with `GRID_BITS=5` and `GRID_FAST=1` in the guarded
  activation path and uses duplicated vector lookup tables.

The [R1044 model-8 source delta](model8-r1044.patch) applies to
the materialized R1007 graph source directory. Apply it there
with `git apply --check` and `git apply`. It advances the high
DF48 quartet and both reverse intra-GRU coefficient groups.
The three resulting graph source files match the qualified
R1044 inputs byte for byte. The promotion record pins both
versions of each source file.

The component identities and complete qualified provider identities
are recorded in the local PCM checkpoint. Rebuilding the full device
images also requires graph generation, immutable inputs, the matching
MLIR-AIE compiler and the program/placement and audio qualification
steps. See the [checkpoint](../../../../docs/XDNA2_LOCAL_PCM_CHECKPOINT.md).
