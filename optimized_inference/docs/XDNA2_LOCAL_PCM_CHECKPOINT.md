# Full PCM on a user-scoped XDNA2 host

This checkpoint selects the model-2 R851 image and the model-8 R877 image.
They run the full mono PCM processing graph on the NPU under explicit
Prefer NPU, including analysis and synthesis, recurrent inference,
attenuation, and overlap-add. The LADSPA adapter still owns streaming,
rate conversion, transition handling and CPU recovery. Its public ports are
the same ones that EasyEffects already uses.

## Install from a qualified catalog

The staging command takes a previously qualified two-model PCM catalog,
a host broker executable, and optionally the active version-1 spectral catalog.
Use a fresh destination. The staging process copies and verifies the provider
manifests, libraries, models and referenced assets. The resulting versioned
directory contains both full PCM profiles, a service executable and a digest
inventory. Existing spectral entries keep their previous identities.

```sh
python3 -B optimized_inference/research/xdna2_preview/spectral/stage_local_pcm.py \
  --qualified-catalog /path/to/verified/providers-qualified.json \
  --existing-catalog /path/to/current/providers.json \
  --service /path/to/dpdfnet-xdna2-service \
  --output ~/.local/share/dpdfnet-xdna2/pcm-checkpoint
```

Build the HushMic bridge and LADSPA adapter from the
[release source patch](../research/xdna2_preview/spectral/hushmic-full-pcm.patch).
Apply it with `git am` on HushMic commit `7937286`. The resulting source
tree matches the two integration commits through `55e7876`. Run
`cargo build --locked --release -p dpdfnet-ladspa --features xdna2 -p
dpdfnet-xdna2 --features host`. Run the corresponding package tests and
check LADSPA, model and provider identities on the intended host.
The existing EasyEffects device selector can use the adapter without a port
or preset migration.

Use the existing service and bus names. In the user service, point
`ExecStart` and `HUSHMIC_XDNA2_PROVIDERS` at the verified versioned directory.
Create a private `RuntimeDirectory=dpdfnet-xdna2` with mode `0700` and set
`HUSHMIC_XDNA2_PCM_RECEIPTS=%t/dpdfnet-xdna2`. Enable
`HUSHMIC_XDNA2_DEVELOPMENT=1` for this local opt-in. Set
`HUSHMIC_XDNA2_FULL_PCM=1` in the native EasyEffects launch environment.
The service's existing persisted device preference controls selection.
Keep the XRT and NPU driver installation supplied by the host.

Back up the active adapter, launcher, service overrides and the configuration
and preset directories before briefly closing the app. Switch the adapter and
service, then restart the original launcher with its existing DSP tier and
input-channel defaults. To roll back, restore the adapter and launcher, remove
the PCM service override, reload the user systemd units and start the previous
service and app. If the app changed settings during a failed switch, restore
the saved settings while it is closed.

## Verify the installed integration

Run isolated native PipeWire and D-Bus cases with both model files, the exact
installed EasyEffects binary, and the staged broker and LADSPA adapter.
Exercise mono microphone processing and monitor toggles at 44.1 kHz/512,
then playback and mono/stereo transitions at 48 kHz/480. Force a broker exit
in the isolated graph and check the PCM recorder continues through CPU
recovery. Verify real XRT command progress, the matching model digest, finite
audio, expected gain transitions and context teardown.

On the host desktop, check the active effect and the previous preset identity.
Connect a temporary capture client to the existing EasyEffects source and
discard its audio. Check that a child of the user broker was launched using
`--pcm-worker`, XRT completions advance and the error count stays zero.
Disconnect the client and verify the context retires. Reconnect and require
a fresh working owner. Compare the preset and settings digests with the
pre-deployment backup.

The XDNA2 Gorgon Point checkpoint passes the native playback and capture
matrix on both models. It sustains roughly 100 commands per second in
the physical model-8 capture and releases the device about two seconds
after the last frame. The desktop's configured idle interval can keep
the graph processing briefly after the test client disconnects. The
same service activates on D-Bus and opens a fresh PCM worker for the
resumed stream. Exact source and artifact identities are in the
[local qualification record](../research/xdna2_preview/local_pcm_release.json).

## Maintainer handoff

R907/R912 expose an earlier first ERB40 quartet. The profile shows time
moves into later reverse-credit waits, with the first 16–19 wait reaching
about 13k cycles. The original model-8 release profile remains R877 unless
a candidate establishes practical full-frame benefit in the paced A/B test.
R913 saves 2,048 bytes and about 255 cycles on the initial right encoder DMA.
Keep that experiment for cumulative transport changes.

1. Profile reverse availability from the rightmost encoder group through
   the later reverse stripes. Measure queue waits and DMA callbacks
   separately. Use the smallest change that can advance a complete stripe
   without adding a staging copy. Recheck both serialized states and
   isolate the final frame-time test from the instrumented build.
2. Move the qualified model build recipes and their dependency identities
   into a clean build environment. Compare the rebuilt images, selector
   sequences and CPU baseline at the same precision and sample rates.
3. Qualify session renewal for long-running applications and dynamic
   admission during concurrent desktop load. Measure aggregate CPU cost and
   device activity before qualifying automatic selection.
4. Propose the optional provider boundary and a short reproducible
   benchmark to the DPDFNet maintainers. Keep the EasyEffects controls
   and HushMic bridge in their own repositories.

Before external distribution, assemble buildable graph sources and recipes,
identify all generated binaries and firmware interfaces, and document
redistribution rights for each SDK/runtime and model asset. Include the
upstream Apache-2.0 notices and preserve the licenses of the HushMic and
EasyEffects sources. The EasyEffects code is distributed under its applicable
GPL terms. Use the optional backend and independent host package as the
public boundary for an upstream DPDFNet proposal.
