# DPDFNet XDNA2 preview

This branch adds a standalone, opt-in WAV path for the verified Linux
Ryzen XDNA2 host. It uses the same WAV entry point as the CPU example.
The CPU library remains the default. The NPU runtime is a separate
process that loads the matching XRT image, profile, ORT and DSP bindings.
This preview uses the original absolute research bindings on the qualified
host. Keep its local build tree and pinned runtime dependencies available.

## Run locally

From the primary DPDFNet checkout, use finite mono 48 kHz WAV input.

```sh
preview=.local/npu-worktrees/preview
lab="$PWD/.local/npu-20261112"
python=.local/toolchains/offline-python

"$python" "$preview/optimized_inference/examples/enhance_wav.py" \
  input.wav xdna2.wav --model 2 --backend xdna2 --xdna-root "$lab"

"$python" "$preview/optimized_inference/examples/enhance_wav.py" \
  input.wav cpu.wav --model 2 --library "$preview/build-preview/libdpdfnet.so"
```

Model 2 exposes `df-bfp16-k128`, `df-bfp16-k64` and `erb-xint8`. Model 8
exposes `bf16`, `bfp16` and `xint8`. Use `--profile` to pin a numerical
profile. Model 2 defaults to `df-bfp16-k128` on R339 within the explicit
XDNA2 mode. Model 8 defaults to `bf16` on R328.
Profiles can yield different PCM and recurrent states. Each selected
artifact has its own numerical qualification. Output keeps the input
sample count and uses the registered 2,400-sample causal alignment.

The WAV example requires NumPy and SoundFile. The worker relies on the
qualified host XRT and driver, `/dev/accel`, its system Python, the pinned
runtime libraries and the hash-bound model and native bindings. It uses
an idle accelerator, admits one owned context, runs frames in order,
accounts for actual command completions, and verifies context release.
An explicit XDNA2 request reports failure if any gate fails. The worker
accepts audio from the local file workflow and the preview emits only
the resulting WAV and a concise command receipt.

## Execution scope and integration

Both models run end-to-end from PCM with actual neural work on XDNA2.
The accelerator covers blocks of the recurrent and projection graph.
Host DSP and remaining ONNX graph operators still run on the CPU.
The untouched models, seven exported CPU symbols, and ordinary CPU
package remain independently usable.

The installed EasyEffects DPDFNet effect uses HushMic's LADSPA adapter.
The installed Flatpak's shell cannot access the host accelerator device.
The WAV preview is available outside the sandbox. For a desktop rollout, use
an optional provider behind HushMic's existing host contract. With the
Flatpak client, a user-scoped worker is the first integration to qualify.
It must preserve the LADSPA descriptor, audio ports and latency semantics
and meet measured callback deadlines including IPC and copies.
[EasyEffects plugin documentation](https://github.com/wwmm/easyeffects/blob/master/src/contents/docs/plugins/deepfilternet.md)
[Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html)

Expose `cpu`, `xdna2` and eventually `auto` at stream creation. An
explicit `xdna2` request should report unavailable or incompatible
components. `auto` should choose CPU when a runtime/profile lacks
qualification for that host or the accelerator is unavailable.
Keep numerical profile selection independent of device selection.

The [source index](../research/xdna2_preview/source_hashes.json) identifies
the tested engine sources. The [artifact catalog](../examples/xdna2_preview.json)
binds the corresponding local native builds. Release qualification and
the evidence for this branch are recorded alongside the source index.
