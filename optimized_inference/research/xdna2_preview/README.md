# Selected XDNA2 research source

This directory records the exact source of the local WAV preview images and
native owners. The [source index](source_hashes.json) hashes the files against
the corresponding sources in the qualified build workspace. The
[WAV preview guide](../../docs/XDNA2_PREVIEW.md) describes the user entry point.
The device objects, private audio, SDK, runtime dependencies and the complete
qualification ledger live in the local research workspace. The artifact
catalog pins the DSOs and manifest roots used by the preview.

## Results retained across the project

- The end-to-end PCM path uses XDNA2 for recurrent and projection work and
  uses CPU DSP and CPU ONNX operators for the remaining work. Both model sizes
  have device-command and recurrent-state evidence. The exact reference track
  remains frozen independently.
- R280 checked the BF16 two-command path against the original CPU oracle on
  nine held cases and seven stress cases per model, including a 120-second
  stream. It checked the complete PCM and sampled feedback states.
- R331 ran the five BFP16 and XINT8 profiles on 124,360 frames across 80
  owners, with 373,080 completed commands and exact same-precision PCM.
  Device-resident GRU coefficients removed 2,058,240 requested coefficient
  bytes from DDR per frame. R332 exercised the three submission boundaries
  on each of those five paths and verified fresh-context recovery.
- R339 reduced the model-2 layout to seven data buffers requesting 857,856
  bytes. R340 retained the same host layout and fed the intra-projection
  workers from four memory tiles. It removes 405,504 further requested
  coefficient bytes per DPRNN frame. The device matrix checks every PCM hop
  and complete state endpoints across nine owners and 2,880 commands.
- The model-8 R328 BF16 owner uses six data buffers and two commands per
  frame. In the R329 matched Boost test the resident arm averaged 6.7443 ms
  continuously and 6.7625 ms at 10 ms cadence. The corresponding sample SDs
  were 0.0314 ms and 0.0668 ms. The comparison with the streamed owner did
  not resolve a combined acceptance improvement.

The R341 paired run resolves a practical R340 latency gain in zero of six
cells and combined noninferiority in zero of six. All 96 owners reconcile
145,728 commands and produce exact PCM and final state. Both arms record
zero 10 ms deadline misses in the measured windows. The preview therefore
selects R339 for every model-2 profile. R340's verified DMA work stays in
the research archive.

The final CPU build passes 48 CTest entries and keeps its seven-symbol
ABI without vendor libraries. All six selected native release DSOs
rebuild byte-identically. Across both model sizes the local CLI verifies
8,602 NPU command completions in six WAV runs. Both CPU command options
give identical PCM. The installed EasyEffects Flatpak has the LADSPA
adapter and no accessible accelerator device in the sandbox.

[R329 model-8 timing](R329_RESULTS.md) · [R339 layout](R339_RESULTS.md) ·
[R340 direct DMA proof](R340_RESULTS.md) · [R341 paired timing](R341_RESULTS.md) ·
[Final validation record](release_validation.json)
