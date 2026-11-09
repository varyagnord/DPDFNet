# Red experiment snapshot

Captured on 2026-11-10 from the `vector` worktree.
Base commit: `afa8292f3b8083c3daadd06dbcfe4ff877dd3172`.

This branch preserves an independent CPU inference/benchmark experiment.
It is an archival development branch, not a selected release or a claim of
performance improvement.

## Validation

- Rebuilt the existing Release configuration with CMake.
- CTest: 100% tests passed out of 27.
- Skipped hardware-specific tests: model2_fused_contract_vnni, model2_pair_contract_vnni, model2_wide_contract_vnni, model2_pair_fused_contract_vnni, model8_fused_contract_vnni, model8_pair_contract_vnni.
- Parsed changed Python sources and reviewed source files for credential patterns.
- Benchmark data, model weights and generated build outputs are not added.
