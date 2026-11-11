# DPDFNet engineering instructions

Reply to the user in Russian. Keep technical documentation in English.
The optimized Linux x86-64 runtime is in `optimized_inference/`.

## Hardware acceptance scope

- The complete available hardware inventory is this local PC and the remote
  Intel Core i7-7700T. Do not plan, request or wait for any additional processor.
- Test usable AVX2/VNNI paths and relevant core classes on the local PC; use the
  i7-7700T for its available AVX2 path. A second VNNI host/microarchitecture is
  not required and must never block acceptance, PR readiness or completion.
- Backlog item V04 is closed as not required by explicit user decision, not
  passed by an unperformed test. Earlier unavailable-hardware notes are historical.
- Keep capability/OS-state/fallback, numerical, performance and restoration
  gates on these machines. Report results for their tested scope without
  claiming measurements on other CPUs. See `optimized_inference/docs/HARDWARE_SCOPE.md`.

## Numerical changes

- Preserve exact quantization, FP operation order, model weights and ABI.
  Do not introduce approximate reciprocals, fast-math or implicit FMA.
- Keep an independent pre-change oracle when refactoring numerical helpers.
- Check both models and AVX2/VNNI, guarded memory, rounding modes, FTZ/DAZ,
  sanitizer contracts, ISA restrictions and stream/state/reset equivalence.
- Intrinsic-level equivalence is insufficient: changed compiler operand choices
  can change NaN payloads. Check final generated code with the independent
  oracle before timing; preserve failed cases rather than relaxing contracts.
- Keep experimental candidates separate from accepted runtime defaults.
- Do not ship rejected/unqualified optimization implementations behind OFF
  switches merely to retain research. Keep frozen source/binaries/results in
  ignored research archives; remove their runtime branches, public build options
  and experiment-only tests from the selected implementation. Promote only
  selected qualified paths enabled for their eligible models/CPUs, retaining
  necessary capability/layout fallbacks and normal developer QA controls.

## CPU capabilities and kernel selection

- For every optimization, inspect the actual kernel, dimensions, packing and
  bottleneck; consider every relevant available ISA facility, including EVEX
  128/256, masks, high registers and permutations, not just wider arithmetic.
  Follow `optimized_inference/docs/CPU_OPTIMIZATION_PLAN.md`. Instructions are
  candidates, not goals: retain only exact, measured, maintainable improvements.
- Treat features as independent requirements, not vendor names or a single
  AVX-512 level. Each implementation must declare its complete minimum CPU,
  OS XSTATE, build/toolchain and data-layout requirements. AVX-VNNI and
  AVX512-VNNI are separate capabilities; check each optional subset actually
  used, including AMD-specific CPUID locations where applicable.
- Detect safely in baseline code, check OSXSAVE before XGETBV, and require
  usable AVX/AVX-512 state. Respect all CPUs a worker may run on; a pinned
  detection on one core is insufficient for a migratable context. Document
  affinity/capability lifetime and reject or safely handle invalidation.
- Separate legal execution from performance policy. Select immutable private
  operation pointers at creation outside hot loops, independently for compatible
  kernel families. Preserve packing/pair/CM eligibility and a safe fallback
  for every unsupported feature combination. Do not require unrelated features
  or add combinatorial variants without a distinct measured purpose.
- Keep optional ISA in separately targeted translation units/functions and
  assembly. No global -march=native, accidental constructor/probe instructions,
  or cross-target LTO/PGO leakage. Audit final machine code against each
  implementation's declared requirements, including helpers and tails.
- Test the capability/selection matrix, missing individual prerequisites,
  OS-disabled state, incompatible packing and masking/bounds. Forced test
  selection may disable capabilities, never invent unsupported hardware.
  New faster defaults need numerical and end-to-end performance evidence;
  preserve previous user rejections and publication/deployment holds.

## Performance measurements

- Mandatory entry point: read `optimized_inference/docs/BENCHMARK_LAB.md`, run
  `just bench-test`, and use `just bench-session MANIFEST OUTPUT` for performance
  studies. For manual sessions use `just bench-prepare`, `just bench-ready`,
  `just bench-aa`, then `just bench-compare`, and always `just bench-restore`.
  Do not replace this with ad-hoc taskset/IRQ/power scripts. Unsupported
  hardware must fail clearly; extend and test the controller before proceeding.
- Reserve the complete discovered L3 domain from ordinary background work,
  with housekeeping on another domain. Use the verified `steady` non-boost
  frequency/idle policy as the laboratory baseline. Explicitly preregister
  `boost` when testing dynamic frequency and original idle states; its readiness
  checks frequency bounds, not stability. Readiness requires hardware-counter
  calibration, not just governor/min/max readback. Record requested/measured
  frequency and never pool or transfer gains across power profiles.
  Wait for exact requested frequency-limit readback before freezing the policy;
  asynchronous intermediate driver values must not become the contract.
- Require an unchanged-binary A/A report before comparing candidates. Declare
  a versioned workload-specific acceptance policy before new observations;
  use the v2 contract in `BENCHMARK_LAB.md` for new short reconsideration studies.
  A/A precision is diagnostic, not a universal 0.5% veto. A resolved practical
  A/A order bias invalidates the cell; a wide interval proves neither bias nor
  its absence. The candidate interval must independently resolve its claim.
  Preserve old v1 verdicts and all failed/slow samples; no optional extensions.
- Use the common library-loading measurement worker. Its CPU-time system
  calls are outside measured series; batch observations are amortized means,
  not individual-call latency. Keep per-call continuous/paced diagnostics
  separate. Compile everything before preparation, freeze hashes and do not
  rebuild or tune code/settings during the measured series.
- Finish builds and correctness tests before timing. Reserve one physical
  core together with its SMT sibling using an isolated CPU partition; run
  on one logical CPU and keep its sibling idle/offline. Affinity alone does
  not exclude other work. Verify actual topology and CPU ownership first.
- Save original settings, arm an independent restoration watchdog and use
  try/finally restoration. Verify CPU online state, IRQ/workqueue masks,
  power policy, services and cgroups after completion or failure.
- Steer movable IRQs/workqueues away and record remaining kernel activity.
  Do not promise zero interruptions or exclusive shared-cache/package use.
- Run benchmarks without privileges after setting up isolation. Separate
  unprofiled latency from perf counters/sampling; normalize warmed counter
  windows per call and check event support and multiplexing.
- For every performance study, inventory CPUID/XSTATE, CPU classes, kernel,
  microcode, perf version and PMU sysfs caps/format/event aliases. Maximize
  useful hardware evidence using the supported profiling ladder in
  `optimized_inference/docs/BENCHMARK_LAB.md`: core counters and symbol/assembly
  samples; frontend/branch/LBR; data-cache/TLB and IBS fetch/op with supported
  load-latency/L3-miss filters; L3/DF/UMC bandwidth and energy/frequency when
  relevant. Use equivalent Intel/other facilities when available. Document
  applicability and a concrete reason for each skipped/unavailable layer.
- CPUID bits, sysfs nodes and a generic event name do not prove usable
  measurements. Probe actual event access/semantics on each target/core class;
  use model-correct encodings, small schedulable groups and bounded separate
  passes. Check enabled/running time, sample loss, attribution and overhead.
  Shared uncore measurements are not process-exclusive. Do not infer IBS
  support from cycles:p or bypass laboratory restoration to enable a feature.
- New profiling studies must use explicit `profile_collectors` in the common
  laboratory. Empty filtered recordings are not proof of zero misses; IBS
  nonzero sample weights are not the latency distribution of all loads. Include
  kernel counters when a change adds syscalls, and verify the actual call count
  with a supported tracepoint when available.
- Use all relevant supported layers in a bounded preregistered before/after
  plan, with maximum diagnostic coverage rather than maximum simultaneous
  counters or unbounded runs. Extend and test the common laboratory first if
  a required layer lacks integration. Mark unsupported events explicitly;
  never silently substitute metrics or present planned collection as completed.
- Fix input hashes, warmup, cadence, process counts, balanced/randomized
  order, A/A controls and acceptance criteria before collecting results.
  For cadence/batch sweeps, declare explicit condition IDs, per-condition sample
  units and counts, and one multiplicity family covering all compared profiles.
  Use a small fixed discovery study and independent confirmation. Respect
  requests for short studies; report limited precision instead of extending
  the sample until a desirable result appears.
- Preregister process layout (`fixed` or `randomized`), verify effective ASLR
  policy and address distributions, and retain the cohorts separately. Use
  equal-length real library paths for fixed-layout comparisons. For full-audio
  claims, test the decoded-PCM FFT/inference/IFFT callback and verify its spectra,
  state and synthesized PCM before timing; spectral API timing alone is narrower.
- For new full-audio studies use the versioned audio path and `just
  bench-audio-test LIBRARY`, then `just bench-audio-pilot CONFIG OUTPUT`.
  Prefer the actual pinned native DSP adapter for native-application claims;
  buffered NumPy certifies that adapter only. Preserve the legacy worker as an
  independent numerical/method reference; never relabel old results.
- Preallocate audio/timing working buffers, prefault the measured path and warm
  at the actual callback cadence. Retain minor faults and warmup policy. Record
  scheduled/start/finish timestamps and hash-verified body/wakeup/response data;
  never subtract timestamps from different clock domains. Keep diagnostic
  counters/tracing separate from primary elapsed-time measurements.
- Declare idle and frequency policies independently. A shallow-idle setting is
  not automatically more precise; all tuning must use the common controller,
  readiness and restoration. Original-idle Boost remains necessary for claims
  about that deployment policy. Do not frequency-normalize away real effects.
- When residual audio noise matters, use `just bench-audio-noise CONFIG OUTPUT`
  for bounded baseline-only CPU-wide idle/scheduler/IRQ traces, task clocks and
  read-only package telemetry. Keep these intrusive diagnostics separate from
  unprofiled A/A and A/B; primary studies receive boundary snapshots only.
  Correlate MONOTONIC timestamps, retain trace loss/empty records and distinguish
  requested idle states from actual residency. Cross-CPU wakeups may be absent.
  Record temperature, AC/platform policy, CPU/GPU background load and available
  power/throttle sensors; absent sensors never prove absence of throttling.
  Do not launch competing timerlat threads on the measured core by default.
  Always reap perf's process group, stop/join telemetry and remove FIFOs before
  controller restoration. Run `just bench-audit` after restoration; verify
  teardown after success, failure and interruption. Device-IRQ tracepoints do
  not cover every local APIC timer/NMI/firmware interruption.
  Prepare optional counter permissions before warmup, bind the token to the
  thread/process/single CPU and verify zero warmed fork/clone/clone3 calls.
  Never probe/fork lazily inside the measured counter window. Retain contaminated
  diagnostic cohorts with explicit limitations; primary timing remains separate.
  Choose a new candidate budget from baseline-only evidence before observing B;
  preserve ordinary Boost and controlled frequency as separate estimands.
- A short-window p99 can be a maximum or second-largest observation. Report its
  rank/support and do not certify population tails or WCET from a short pilot.
  Use baseline-only pilot variance to fix a future candidate budget; four-pair
  method improvements are local descriptive evidence, not universal guarantees.
- Separate throughput superiority from audio safety. For throughput require
  a useful point gain and a positive corrected lower bound, not a lower bound
  exceeding the entire A/A noise envelope. For audio require preregistered
  mean and per-process p99 noninferiority, plus observed deadline/fault guards;
  do not require every audio cell to prove acceleration. Tail summaries are
  not population-p99 or WCET bounds. Keep numerical/ISA/memory gates unchanged.
- Use short fixed screening first, then fresh independent confirmation of one
  selected candidate. Compare against the current accepted runtime; historical
  rejection may be reopened only by explicit user authorization. Reuse pinned
  correctness and recent same-binary PMU evidence with verified provenance,
  rather than repeating an entire factorial study. Confirm narrower scopes
  explicitly; do not silently shrink the family after inspecting results.
- Preregister a practical noninferiority margin separately from useful gain.
  Noninferiority is not proof of zero slowdown or superiority. Hosts without a
  separate housekeeping L3 can receive numerical checks, not claims of strict
  isolated performance under this laboratory contract.
- Retain raw observations, slow calls, binary/PGO hashes and failed attempts.
  For a load-suspected repeat, preserve the previous cohort, freeze a fresh
  budget/seed and exact binary identities, register a quiet preflight and use
  `record_process_environment:true` for hash-bound per-process boundary receipts.
  Classify background-load flags with prospectively declared thresholds, retain
  flagged observations and report whole-process CPU averages separately from
  callback-only timing. GPU/temperature endpoints do not certify absence of
  short peaks. Do not stop user applications or pool cohorts to rescue a claim.
  Preserve controller failure reasons and rollback verdicts in session logs.
  A preparation-only retry must retain its failed audit and must not overwrite
  a begun timing journal or change the registered plan.
  Report mean and sample SD for calls and for process means separately,
  paired process/block confidence intervals, tails and deadline misses.
  Serially dependent calls are not independent statistical replicates.
- Compare incremental changes with the current selected implementation.
  Never add overlapping gains or infer full-graph speed from a microbenchmark.
  Assess continuous and paced workloads separately; record tested CPU scope.
- Document methods, numerical results, uncertainty and default/experimental
  selection. Update affected architecture/build docs and the private backlog.

## Completion

Run appropriate checks and `git diff --check`. Do not push or deploy unless
requested. Include `Documentation:` with updated/not-needed entries in the
final response, alongside checks, measured effects and remaining limitations.
