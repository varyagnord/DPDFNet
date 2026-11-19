# EasyEffects integration candidate

The existing Deep Noise Remover effect selects DPDFNet through HushMic.
This candidate adds a per-user machine preference to the existing effect.
The preference lives in the HushMic XDNA2 host service and is outside
EasyEffects presets. Profile, runtime and model identities are separate
from that preference.

The optional LADSPA extension requires compatible HushMic and EasyEffects
builds. The standard descriptor remains `dpdfnet_mono` with the original
ports. Only EasyEffects' mono path requests acceleration. HushMic still
owns the STFT, attenuation limiter, overlap-add, mute and latency alignment.
The provider replaces only spectral model inference. A spectral frame
contains 481 complex FP32 bins interleaved from DC through Nyquist.

D-Bus carries local policy and opens a stream. The service returns a
connected Unix packet socket using a D-Bus file descriptor. Inference
uses bounded packets with a sequence number and reset generation. At
most one NPU owner is admitted. The worker is a child process with
parent-death containment, bounded audio deadlines and independent cleanup.
On failure the HushMic worker drops the stream, initializes its CPU model state,
and continues its existing audio timeline. The PipeWire callback keeps
using HushMic's existing rings.

The development Flatpak uses the `.Devel` ID, one additional D-Bus
permission, sandbox-built HushMic and CPU model files. The NPU images and
XRT stay on the host. Test package preparation takes explicit local
source and asset directories. Distribution packages still require a
portable provider catalog and asset redistribution review.

## Local qualification

Build the two spectral modules from this worktree using the pinned
offline Python and `research/xdna2_preview/spectral/build_local.py`
under `optimized_inference/`. Pass the verified WAV preview lab root
and a new output directory. This build deliberately produces unqualified
profiles. Model 2 uses BFP16 K128 on R339 and model 8 uses BF16 on R328.

Build the HushMic adapter with `cargo build --locked --release -p
dpdfnet-ladspa --features xdna2`. Build the host service with `cargo build
--locked --release -p dpdfnet-xdna2 --features host`. The integration harness
uses a private PipeWire graph and private D-Bus session. It enables the
development provider only in that session. The initial provider manifest
has both live and automatic qualification disabled.

Use `just ee-npu-doctor` with the prepared offline interpreter, catalog
and optional `--ladspa` or `--flatpak` argument to inspect prerequisites.
Use `just ee-npu-smoke` with the same interpreter and the paths printed by
`easyeffects_smoke.py --help` to exercise playback, mono NPU admission,
stereo CPU fallback and cleanup. The smoke uses a private null sink.
It does not grant accelerator access to the Flatpak sandbox.

For the Flatpak candidate, use `prepare_flatpak.py` with the patched
EasyEffects and HushMic sources, the Flathub recipe and prepared CPU assets.
Run `cargo vendor --locked --versioned-dirs --manifest-path
hushmic/Cargo.toml STAGE/cargo-vendor`, then build the generated manifest
with `flatpak-builder` using the matching KDE SDK and Rust SDK extension.

## Promotion gates

Before a distribution package can mark a profile live-qualified, verify
both app formats through the playback and capture graph, the full
attenuation and mode range, impulse latency, sustained mixed desktop
load, suspend/reset and injected service failure. Record timing,
driver commands and dropouts independently. Automatic mode also needs
at least a 5% reduction in aggregate EasyEffects and worker CPU use
against the optimized CPU build on the same host. Keep both qualifications
false until their evidence exists.

[HushMic audio worker](https://github.com/Fovty/HushMic/blob/main/crates/dpdfnet-ladspa/src/worker.rs)
[Flatpak permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html)

## Reproducing the local desktop test

The native test archive and Flatpak bundle are built separately from
the working installation. Use the following example from the primary
DPDFNet checkout after building the provider and both app candidates.

```sh
base="$PWD/.local/ee-npu-20261119"
preview="$PWD/.local/npu-20261112"
python="$PWD/.local/toolchains/offline-python"
cd .local/npu-worktrees/easyeffects

just ee-npu-smoke "$python" \
  --app "$base/native-candidate/usr/bin/easyeffects" \
  --service "$base/native-candidate/usr/bin/dpdfnet-xdna2-service" \
  --providers "$base/spectral/providers.json" \
  --ladspa "$base/native-candidate/usr/lib64/ladspa/libdpdfnet_ladspa.so" \
  --model "$base/native-candidate/usr/share/dpdfnet/models/dpdfnet8_48khz_hr.onnx" \
  --ort "$base/native-candidate/usr/lib64/dpdfnet/libonnxruntime.so" \
  --input "$preview/r341_preview_smoke_v1/input.wav" \
  --rate 48000 --quantum 480 --output "$base/example-native"
```

For Flatpak, use `--flatpak com.github.wwmm.easyeffects.Devel` in place of
`--app` and omit `--ladspa` and `--ort`. Set `FLATPAK_USER_DIR` to the
test installation before running the harness. The development manifest
permits just one new bus destination. The harness separately redirects
PipeWire to its own socket and keeps the normal desktop audio graph out
of the test.

The accepted research engines still limit a single accelerator session
to 1,048,576 hops (about 2 h 55 min). Uninterrupted use beyond that horizon
requires qualification of an extended or renewed session. The current
runtime falls back to the CPU if the provider ends or fails.

## Recorded same-host results

- The native and Devel Flatpak candidates both run model 2 and model 8
  in the private PipeWire playback and capture graphs. The playback
  matrix covers 44.1 and 48 kHz, and 512 and 480-sample quanta. Mono
  prints the same signal on both channels. Stereo opens no NPU context.
- The two 120-second model 8 playback captures each record 23,970
  completed device commands at the end of playback. Aligned comparison
  between packages after the first two seconds gives 0.03845% NRMSE
  over 5,661,600 samples. The initial transition differs. Its
  startup-inclusive NRMSE is 37.31%, so this comparison does not qualify
  startup transparency or quality against the CPU baseline.
- Stopping the service during model 2 playback frees the hardware
  context and leaves a live, audible recording through the CPU path on
  both builds. The host service activates on demand, persists the test
  preference, and exits when its D-Bus session closes.
- Earlier model 8 runs lost the NPU session under concurrent builds.
  Quiet reruns and the two-minute playback runs pass. Desktop-load
  noninferiority, startup/impulse latency and the aggregate CPU threshold
  remain promotion gates. The test catalog keeps automatic and live
  qualification disabled.

The private workspace contains the artifact checksums, individual run
receipts and raw capture comparisons in `INTEGRATION_RESULTS.json`.

## Local desktop deployment

The working native launcher uses the existing EasyEffects application ID,
PipeWire nodes, and the same configuration and preset directories. The
user-scoped D-Bus service resolves the two installed spectral libraries
and verifies their recorded digests. The provider manifests still bind
the qualified research files under the local NPU lab directory.

The existing device-specific launch setting
`EASYEFFECTS_DPDFNET_MONO_INPUT=1` supplies the default for input presets
created before the application stored `mono-processing`. A preset with
an explicit stereo or mono choice overrides the old default.

The deployed catalog retains the automatic CPU selection. The host
service permits manual NPU selection as a local opt-in. A rollback
archive contains the previous application and adapter, the original
settings and presets, and the launch configuration. The deployment
receipt verifies the active binary and adapter, the preserved file
contents, and the PipeWire source and sink.

Changing the device preference in the effect applies to existing
instances. The inference worker also observes changes while waiting
for audio, so selecting CPU releases any held NPU session. Check again
keeps a healthy or opening session for the same preference. If the
previous owner is still closing, a replacement request allows a short,
bounded retry. Until the first frame completes, the effect shows that
NPU is selected and waiting for audio. A failed preference write is
reported on the effect page.

## Verifying NPU execution

During active mono capture, take two snapshots with
`/opt/xilinx/xrt/bin/xrt-smi examine -r aie-partitions`. Find the
DPDFNet worker PID in both snapshots and check that its context's
`Completions` increases without an increase in `Err`. An open context
and allocated memory also appear while the worker is waiting for its
first frame. The change in completions measures command throughput.

AMDGPU TOP computes per-process NPU use from a busy-time counter in
`/proc/<worker-pid>/fdinfo/<accel-fd>`. The in-tree `amdxdna` driver
in Linux 7.3.3 and 7.3.4 reports memory usage but omits this counter.
Linux 7.4-rc3 emits `drm-engine-npu`. AMDGPU TOP v0.11.5 parses
`drm-engine-npu-amdxdna`; a newer driver and monitor must agree on the
counter key. See the [kernel implementation][xdna-fdinfo] and
[AMD's fdinfo compatibility discussion][xdna-fdinfo-compat].

For aggregate NPU utilization on the Gorgon Point host, open **GPU Metrics**
for the APU in AMDGPU TOP and look for the `IPU` row. The same firmware
telemetry is available in JSON independently of the per-process counters:

```sh
amdgpu_top --no-pc -J -n 1 | jq '.devices[] | .npu_metrics.npu_busy | select(. != null)'
```

After rebooting into Fedora kernel 7.3.4, the production DPDFNet worker
completed 408 device commands in about two seconds without an error.
Five AMDGPU TOP samples reported 64–65% on all eight entries in the
firmware activity array. The worker's `fdinfo` still contained only
memory statistics, so its process row displayed 0%.

If the XRT snapshot hangs, check the NPU PCI device's
`power/runtime_status` in sysfs and the kernel journal. On the Fedora
integration host, Linux 7.3.3 logged an Oops in
`xdna_mailbox_alloc_channel` during runtime resume. The same failure
returned on Linux 7.3.4 when monitoring resumed after an idle period.
The driver left the device in `resuming`. Subsequent device opens
entered uninterruptible kernel sleep. The host needs a fresh boot to
recover from this state.

Disabling microphone monitoring removes its PipeWire links. Another
active capture client can still keep the input pipeline busy. The
LADSPA worker now closes its NPU stream after two seconds without a
frame, before the tested driver's five-second autosuspend interval.
The next frame requests a fresh session on the connector thread.
The CPU continues processing during session startup.

The normal model 8 path checks completion after each XRT command.
Closing the stream at a command boundary lets the worker call
`dpdfnet_xdna2_spectral_close` and destroy its XRT resources. The
audio client has a 20 ms frame deadline and the broker has a 24 ms
frame deadline. On startup or frame timeout, the broker closes both
stream sockets. The supervision thread waits for worker exit and
retains its exclusive lease. A worker still inside XRT can finish
the call and close the session on its owning thread. If the driver
never returns, the broker can answer policy requests and refuse
another NPU owner while CPU inference continues.

The private-bus regression check drove the release LADSPA module
against a stub provider for both DPDFNet models. Three capture pauses
per model retired the previous worker and resumed with a fresh
session. A 180 ms frame triggered CPU fallback, kept the lease
exclusive through cleanup and closed the
session when the call returned. A 1.4 s startup timed out at about
900 ms and closed once startup finished. On the recovered desktop,
the updated broker ran model 8 and XRT recorded 208 additional
completed commands in a one-second interval without errors.

On the real device, the kernel logged `-EINTR` while creating the
mailbox workqueue's rescuer. The workqueue failure path in the driver
dereferences the channel's mailbox pointer before initialization.
This explains the null pointer Oops. The broker timeout is a plausible
source of the fatal signal. The kernel log does not identify the sender.
The [XRT run API][xrt-run-api] distinguishes a wait timeout from
completion or abort. The failing stack was in submission, so an abort
of a submitted command cannot be assumed to cover this case.

[xdna-fdinfo]: https://github.com/torvalds/linux/blob/v7.4-rc3/drivers/accel/amdxdna/amdxdna_pci_drv.c
[xdna-fdinfo-compat]: https://github.com/amd/xdna-driver/issues/1754
[xrt-run-api]: https://xilinx.github.io/XRT/master/html/xrt_native.main.html
