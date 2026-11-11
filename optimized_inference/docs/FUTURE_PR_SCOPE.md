# Prepared future PR scope (2026-11-11)

Status: commits and push to the separate review branch
`perf/model8-vnni-fusion-20261111` are authorized on2026-11-11. Creating or
updating a pull request and deploying remain deferred. PR23 was verified open
and unmerged at head `6a07895`; its head branch must remain unchanged by this
push. The upstream target `optimized-inference` is still at `98df765`.

This proposal describes the incremental changes after `6a07895`. Its ancestry
contains the previously submitted PR22/PR23 work; those commits are not new
changes in this proposal. After that work is merged, refresh upstream, rebase
and revalidate before publishing the subsequent PR. No PR is created here.

Hardware acceptance is limited to the local PC and remote i7-7700T under the
[fixed hardware policy](HARDWARE_SCOPE.md). A second VNNI processor is not
required and is not a readiness blocker. This does not change the runtime
selection or turn failed/inconclusive performance outcomes into passes.

## Selected runtime change

Reuse the existing exact fused four-row VEX-VNNI assembly for eligible model 8
batch and paired K64 projections. Compile it in the model 8 namespace and select
it with one private backend definition, `DPDF_MODEL8_VNNI_FUSION`. No public
experiment switch, new ISA requirement, weight change or installed ABI change.
Model2 and unsupported/ineligible AVX2 fallbacks retain their existing paths.

The user previously selected this small conditional gain after reviewing the
completed factorial/confirmation study. Qualified model 8 gains were about
0.8–1.2% in six measured conditions. This is not universal superiority; the old
global statistical criterion did not pass and is not relabeled. The new future
PR qualification rebuilds the selected default and obtains the same measured
DSO SHA256:
`fcc69ff8cb3e3a818daa2114f72eb1291f7ab324aa132a4c8c2cd76a6026c7b7`.

The CM and existing quantize4 defaults already proposed in PR23 are preserved,
not presented as another new runtime change. Refined and VNNI four-row
quantization experiments are removed, including their implementations, build
options and experiment-only tests; they are not shipped as disabled features.

## Correctness and tooling changes

- Extend fused contracts to independent FTZ/DAZ combinations and cover model 8
  VNNI directly. Extend the guarded quantization oracle to check scalar K64
  numerics without enabling the rejected K64 dispatch specialization.
- Recognize legitimate assembler padding prefixes in ISA parsing while still
  rejecting forbidden EVEX, with parser regression tests.
- Wait for actual requested frequency-limit readback before freezing laboratory
  readiness; retain actionable mismatch/failure/rollback diagnostics.
- Add manifest-defined core/cache/TLB/stall/LBR/IBS/shared-PMU/energy profiling,
  warmed-window synchronization, counter/sampling validation and explicit
  unavailable/empty statuses. Keep profiled time separate from speed inference.
- Add opt-in versioned workload acceptance: throughput superiority, separate
  audio mean/process-p99 noninferiority, practical A/A drift diagnostics, and
  preflight endpoint-family checks. Preserve legacy reports and their verdicts.
- Include behavior tests, reproducible just entry points, architecture/build/
  measurement/default documentation and portable numerical/performance records.
  Raw/private recordings, local build trees and rejected kernel source stay out.

## Excluded runtime candidates

| Candidate | Completed evidence | Disposition |
|---|---|---|
| Extra scalar K64 selection | Fresh screen -0.019%; below useful size | Keep removed |
| Extra dedicated VNNI padding | Fresh screen +0.043%; below useful size | Keep removed |
| EVEX256 wider register blocking/domain prototype | Continuous gains remain scoped; quiet native repeat resolves model2 mean slowdown on both cores, model8 benefit unconfirmed | Private research only; no new runtime branch/API/Threads dependency |
| Refined + VNNI quantize4 | New independent Boost continuous model 8 +0.749% fast / +0.765% compact; all four audio guards inconclusive | Implementation/options/experiment-only tests removed; frozen research only |
| Gate tiling/staging | Regression, code/spill growth or qNaN payload mismatch | Keep rejected |

Do not add percentages from Q4 and EVEX: their composition was not tested.
Inconclusive audio does not prove either harmlessness or a resolved slowdown.
Scoped continuous acceleration does not satisfy the declared complete default
scope. No new public experimental runtime flags are proposed.

## Fresh validation of the selected defaults

| Configuration | Result |
|---|---|
| Native fresh PGO | 47 CTests pass; DSO byte-identical to selected measured fusion |
| ASan/UBSan | 47 CTests pass |
| AVX2-only | 37 CTests pass |
| Plain static | 46 CTests pass |
| Installed shared/static CMake consumers | Both models create/init/process with in-place buffers pass |

The independent Q4 follow-up uses 256 fresh processes / 73,728 observations and
160 separate warmed profile jobs, randomized layout, both core classes in Boost,
eight A/A and eight A/B pairs per cell. All 32 reported intervals were checked
independently with SciPy. No sample extension or discarded slow observations.
Every session restored its saved environment; final readback verifies power,
CPU/IRQ policy, watchdog and temporary cgroup cleanup.

See [future PR qualification](../validation/future_pr_qualification_20261111.json),
[model8 fusion evidence](MODEL8_VNNI_EXPERIMENTS.md),
[short reconsideration](../validation/reconsideration_20261111.json) and
[benchmark laboratory](BENCHMARK_LAB.md). Private preparation artifacts are in
`.local/future-pr-20261111/`, including an English PR body, review patch and
file/hash manifest. No release/deployment or production plugin change occurred.


## Validated audio measurement tooling

The future tooling scope also includes versioned audio measurement with paced
warmup, reused buffers, C timestamp acquisition, hash-verified wakeup/body/response
records and an optional real HushMic DSP adapter. It is a test-only dependency,
not a new runtime engine or installed FFT/Rust requirement. Existing NumPy/legacy
workers remain reference versions. Native PGO 48 / ASan 48 / AVX2-only 37 / static 47
CTest gates pass after the test-only CMake integration.

A fixed 96-process A/A pilot and 40 separate PMU jobs show lower observed paired
variance in original-idle Boost (55.4% buffered, 70.5% native), with zero measured
minor faults. Results are local/descriptive: dynamic Boost still has substantial
noise and the shallow-idle combination was worse. No candidate acceleration or
new default follows. See
[audio method validation](../validation/audio_lab_v2_20261111.json).

The subsequent [native audio/noise audit](../validation/audio_noise_20261111.json)
adds bounded CPU-wide idle/scheduler/IRQ tracing, read-only telemetry, process-group
cleanup, a restoration audit and offline reports. Counter permission preparation
is thread/process/single-CPU-bound and runs before warmup. A redundant warmed
permission-probe fork was found and removed; historical counter-enabled pilot
diagnostics are retained with that contamination note. Counter-disabled primary
timings are unaffected. The fresh16-pass diagnostic regression verifies zero
warmed fork/clone/clone3 calls and retains3 minor faults total.

Independent native DSP confirmation retains160 processes/81,920 callbacks,
four A/A and16 A/B pairs per model/core cell, plus24 separate warmed PMU jobs.
All four5%-margin per-process-p99 guards pass; all four2%-margin mean guards
remain inconclusive. Compact model2 p99 slows1.438% [0.528,2.357]%, within the
registered tail margin; this is not a claim of zero cost. No EVEX/Q4 default is
promoted or new public experiment flag proposed.58 lab contracts,10 audio
contracts and the current49/49/38/48 CTest matrix pass. No publication occurred.

The subsequent [exact-binary load-controlled repeat](../validation/audio_repeat_20261111.json)
retains another160 processes/81,920 callbacks and24 PMU jobs separately. Mean
dispersion improves, but model2 slows2.404% fast /1.529% compact with corrected
intervals excluding zero; model8 still lacks a resolved mean benefit. All mean
NI guards fail; fast p99 guards pass and compact p99 guards are inconclusive.
Per-process boundary receipts and prospective load flags retain every observation.
61 lab contracts,10 audio contracts and49 native CTests pass. This strengthens
the decision to exclude the private EVEX runtime prototype from the proposed PR;
prior cohorts/verdicts and selected fusion/CM/quantization defaults are unchanged.

## Final lean runtime selection

The user rejected retaining unqualified implementations behind OFF switches.
The refined quantizer source, both experimental build options, conditional
selection branches and experiment-only test targets are now removed. Retired
settings fail configuration explicitly, including stale cached OFF values.
The selected implementation retains CM for both models on AVX2/VNNI, legacy
AVX2 four-row quantization and model8 VNNI batch/pair fusion enabled for eligible
shapes/CPUs. Model2 already had its fused path; no new fusion change is needed.
EVEX, gate tiling, dedicated K64 and extra branch-padding prototypes stay out.

A fresh source-matching PGO build produces the exact same selected DSO SHA256
`fcc69ff8cb3e3a818daa2114f72eb1291f7ab324aa132a4c8c2cd76a6026c7b7`.
Current CTest counts47/47/37/46 reflect removed experiment-only tests; selected
path contracts remain. Both installed shared/static consumers pass for both
models. Historical source/results remain archived. See the
[selection record](../validation/runtime_selection_20261111.json).
