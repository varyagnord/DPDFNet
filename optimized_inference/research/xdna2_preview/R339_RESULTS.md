# R339 — Seven physical data buffers for the resident model-2 images

Model 2 removes the now unused normalization coefficient argument from
the compiled XRT kernel and omits its physical buffer in all three
owners. The selected three-command profiles keep five XRT data arguments
per submission and seven distinct physical buffers per owner. The
immutable original initializer supplies the legacy field in both raw
and compact diagnostic snapshots.

The compiled PDI and initialization CDO are byte-identical to R338.
All 18 instruction streams preserve order, lengths and the same
physical buffer offsets. The output argument moves from index 5 to
index 4. This crosses the firmware's five-argument translation boundary,
so the compiler subtracts the former 0x80000000 address adjustment in
the affected patches. The static checker accounts for both changes and
independently checks the exact output offsets. All other command words,
resources and core logic match.
[AMD MLIR-AIE many-buffer test](https://github.com/Xilinx/mlir-aie/blob/main/test/npu-xrt/many_buffers/aie.mlir)

The 30 bare native cold controls, six diagnostic-library cold controls
and eleven protected cold entries issue zero accelerator commands.
An initial cold build rejected the new registry because the facade still
checked the old registry kind. The source, cold logs and traces are
retained separately. The accepted facade, loader and registry agree on
the new identifier.

On the physical device, the nine owners match R338 across 960 PCM hops,
960 full CPU/DSP snapshots, 684 paired raw and compact NN snapshots and
2,880 completed commands, including open, reset and replay. Serial and
parallel offline verifiers agree. The system restores both kernel CPU
masks, all 24 logical CPUs and accelerator power. No contexts remain.

Requested physical data capacity falls from 862,208 to 857,856 bytes
per owner. Initial host staging and XRT upload each request 4,352 fewer
bytes. A full native diagnostic snapshot requests 4,352 fewer bytes in
two fewer synchronization calls. Reconstructed snapshot bytes, frame
request/reply and reset ledgers remain exact. The cohort contributes
zero primary performance samples. Latency and energy require matched
unprofiled cohorts.
[XRT buffer API](https://xilinx.github.io/XRT/master/html/xrt_native_apis.html)
