# Model-8 grouped VNNI experiments

## Scope

This study evaluates the remaining grouped model-8 VNNI work after the selected
CM implementation. Quantize4 refinement and VNNI four-row quantization remain
separate, default-OFF experiments. Exact division, reduction order, weight
packing, recurrent state, model files and the public ABI are preserved.

## Outcome (2026-11-10)

Discovery selected batch + pair fusion (mask 3). Independent confirmation
qualified 6 of 12 native model-8 cells; the registered global promotion rule
did not pass. This is the recorded statistical outcome, not a claim of universal
superiority. After reviewing it, the user explicitly accepted batch + pair
fusion as the model-8 VNNI default, accepting the remaining performance
uncertainty. The standalone grouped K64 and extra padding candidates were
rejected and removed from the working code. All four temporary experiment
switches were removed; accepted fusion uses one private backend definition.
The existing CM and quantize4 selection is unchanged.

Publication is deferred by explicit user instruction: do not push or create/
update a PR now. Revisit the accepted change after the already submitted work
has been accepted and merged. The current published branch is not updated by
this local decision. Rebase and revalidate against the eventual merge base
before preparing the later PR.

A fresh default native-PGO build after cleanup passes 45 CTests and is byte
identical to the measured mask-3 finalist (SHA-256
fcc69ff8cb3e3a818daa2114f72eb1291f7ab324aa132a4c8c2cd76a6026c7b7).
No performance observations or original acceptance gates were changed.

| Core / policy | Workload | Time reduction | Family-adjusted interval |
| --- | --- | ---: | ---: |
| Fast / steady | Continuous | +0.921% | [0.771, 1.070]% |
| Fast / steady | Paced 10 ms | +0.899% | [0.756, 1.041]% |
| Fast / steady | Full host audio | +0.801% | [0.582, 1.020]% |
| Compact / steady | Continuous | +1.176% | [0.946, 1.405]% |
| Compact / steady | Paced 10 ms | +1.212% | [0.859, 1.564]% |
| Fast / Boost | Continuous | +0.849% | [0.420, 1.276]% |

Other native cells do not qualify. Model-2 controls fail the strict A/A
precision limit; this is inconclusive, not a numerical regression. Both
model-8 masked-AVX2 guards pass practical 0.5% noninferiority. K64 and extra
padding alone did not meet discovery's useful-effect threshold. These are
completed experiments, not omitted implementations.

Separate model-8 PMU recordings show cycles/call lower by about 0.92–0.96%,
instructions higher by 1.323%, branches lower by 3.939%, and branch misses
lower by about 21%. This describes a different instruction mix and schedule;
it does not establish a unique causal explanation for the gain.

The full study retains 3,280 unprofiled processes, 861,056 individually timed
calls and 1,640 paired blocks. All raw hashes, means, sample SDs, layouts and
primary intervals were revalidated. Maximum observed time was 2.218730 ms,
with no 10-ms misses, late completions or major faults. Separate primary and
frontend groups plus sampling comprise 40 profile jobs; counters were 100%
scheduled. Numerical and application coverage below passed, including eight
actual private PipeWire replay/capture graphs with native process-call
receipts and 48 mono/stereo adapter cases. The live plugin was not replaced.

See [portable condition/SD/profile evidence](../validation/model8_vnni_experiments_20261110.json)
and [all paired process blocks](../validation/model8_vnni_blocks_20261110.json).
Secondary chronological/HAC/bootstrap/randomization diagnostics do not change
the primary gates or repair failed A/A controls.

## Historical discovery factors (removed build switches)

The study used the following temporary default-OFF switches. They are listed
as historical provenance for the frozen factorial evidence and are absent
from the current build. Each combination had fresh native PGO; AVX2 training
was not reused as evidence of native VNNI training.

| Bit | CMake option | Effect |
| --- | --- | --- |
| 0 | `DPDF_EXPERIMENT_MODEL8_VNNI_BATCH_FUSION` | Reuse namespaced VNNI four-row fused assembly in eligible batch projections. |
| 1 | `DPDF_EXPERIMENT_MODEL8_VNNI_PAIR_FUSION` | Independently select that assembly in eligible paired projections. |
| 2 | `DPDF_EXPERIMENT_MODEL8_VNNI_K64` | Select existing exact scalar-row `quantize64` in grouped K64 paths. |
| 3 | `DPDF_EXPERIMENT_MODEL8_VNNI_BRANCH_ALIGNMENT` | Retain model-8 dedicated VNNI 32-byte branch padding. |

The reused assembly fuses integer projection with FP32 scale/bias application;
it does not approximate division or change quantization. Batch and pair guards
are separate so a combined improvement is not attributed to either component
without a direct contrast. Model-2 executable object sections are identical
across the factorial builds. Fresh model-8 PGO can change common hot/cold C
sections as well as the directly edited path; inspect every `.text*` section,
not only `.text`, before describing the code-generation scope.

## Validation design

The fixed discovery matrix contains all 16 combinations, model 8 on the fast
core in steady mode, continuous 512-call and paced 10-ms 48-call conditions,
four A/A pairs and eight comparison pairs, family size 30. Its result selects
one frozen finalist; screening estimates are not acceptance evidence.

Independent confirmation uses both models, fast/compact cores, steady/Boost,
continuous spectral, paced spectral and full FFT/inference/IFFT callbacks.
It uses two held-out inputs, 16 A/A pairs and 16 comparison pairs per cell.
Four same-artifact masked-AVX2 guard cells join the 24 native cells in one
family of 28. Useful gain is 0.3%, the A/A envelope limit is 0.5%, and the
separately registered noninferiority margin is 0.5%. Promotion requires all
12 model-8 native superiority gates, all model-2 native noninferiority gates
and all four AVX2 fallback noninferiority gates. Failed A/A controls remain
inconclusive, with no optional sample extension or post-outcome gate changes.

Historical and ISA measurements are a separate family of 24 contrasts:
`afa8292` to `41d0aa8`, `afa8292` to the selected current implementation, and
same-artifact AVX2 to native VNNI, both models and power profiles, continuous
512-call and paced 10-ms 64-call workloads, eight A/A/comparison pairs each.
These whole-runtime contrasts do not identify individual historical G/V/S/J
contributions. Overlapping percentages must never be added.

Every phase uses the [mandatory laboratory](BENCHMARK_LAB.md): reserved L3,
parked SMT sibling, independent watchdog, hardware frequency calibration,
ordinary-user workers, fixed process layout, paired fresh processes, separate
counter/sampling jobs and verified restoration. Report call SD separately
from process-mean SD. Fixed layout and isolated Boost do not represent every
production layout or normal desktop power policy.

## Numerical and integration coverage

All factorial builds receive fresh native PGO and CTest. Independent full-stream
checks cover both models, 65 regenerated public/stress fixtures, every output
spectrum and recurrent state, reset and four alias modes. Selected endpoints
also receive complete PCM checks, static/sanitizer/AVX2-only configurations,
ISA restrictions, CPU masks and installed shared/static consumers.

The direct quantization oracle exercises generic, scalar K64 and four-row
quantizers over 73,728 combinations of guarded placement, all 16 empty-row
masks, four rounding modes, independent FTZ/DAZ states and input patterns.
Fused contracts likewise cover all four FTZ/DAZ combinations. The ISA checker
recognizes optional assembler padding prefixes before VEX while continuing to
reject EVEX, with six parser regressions.

Local integration uses complete private microphone recordings and public
HushMic fixtures. Private audio stays outside Git. The installed EasyEffects
HushMic plugin embeds an older native ABI; dropping in `libdpdfnet.so` does
not upgrade it. An uninstalled test-only ABI bridge connects the real HushMic
STFT/model/iSTFT code and rebuilt LADSPA plugin to pinned ready libraries.
Native-engine/no-fallback receipts, complete PCM/reset equality and the actual
compiled EasyEffects adapter are checked with private settings/audio server,
44.1/48-kHz audio and 128/480/1024-frame mono/stereo callbacks. These checks
do not certify a physical microphone loopback or deploy a replacement plugin.

The regenerated 65-case corpus is distinct from the historical reference
corpus; public fixtures cannot silently replace missing original inputs.
Hardware acceptance is explicitly limited to the local PC and remote i7-7700T:
another VNNI machine is not required or blocking. See
[HARDWARE_SCOPE.md](HARDWARE_SCOPE.md); earlier extra-hardware coverage notes
are historical, not pending acceptance gates.


## Authorized reconsideration (2026-11-11)

The user authorized new, prospectively revised performance criteria and a
short fresh screen. Direct accepted-fusion → fusion+K64 / fusion+padding
comparisons again show no useful screening gain. Their runtime code/flags stay
removed. This new authorization does not rewrite the historical rejection or
release the publication hold. See the
[short-study record](../validation/reconsideration_20261111.json) and
[workload-specific policy](BENCHMARK_LAB.md#workload-specific-acceptance-v2-2026-11-11).
