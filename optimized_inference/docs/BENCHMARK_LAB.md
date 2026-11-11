# Reproducible CPU benchmark laboratory

The repository-root `justfile` is the mandatory performance-study entry point.
It uses the Python standard library, systemd/cgroup v2, GCC, `perf`, and `just`.
The control backend is validated on the local AMD CPPC machine. It discovers
topology instead of assuming a CPU count or hardcoding L3 siblings. Unsupported
hardware or unverifiable frequency feedback is an error, not a weaker silent
fallback. Commands below run from the repository root.

The available acceptance hardware is fixed to the local PC and remote i7-7700T;
see [HARDWARE_SCOPE.md](HARDWARE_SCOPE.md). Another VNNI machine is not required
or blocking. Apply only usable facilities on each target and preserve explicit
diagnostic attribution where strict isolation is unsupported.

## Hardware profiling coverage contract

Every performance study must discover the target's actual CPU/core classes,
CPUID/XSTATE, kernel/microcode, perf version and PMU sysfs `caps`, `format` and
event aliases. Inventory is read-only evidence, not proof that an event opens,
counts the intended operation, or can be attributed to this process. Probe
access and validate event semantics before freezing the study plan. Use the
processor's correct event definitions; do not copy raw codes across models.

Apply the following ladder to baseline and candidate in separate warmed,
balanced profiling passes. Maximize applicable diagnostic coverage within a
small preregistered budget, not simultaneous counters or sample count. Record
each layer as collected, not applicable (with the bottleneck rationale), or
unavailable (with the concrete capability/access/integration failure).

| Layer | Coverage and purpose |
|---|---|
| Core and clocks | Cycles, instructions, IPC, reference/measured frequency, branches/misses; power/energy when supported and attributable |
| Hot symbols and assembly | Bounded cycles sampling, annotated disassembly, loads/stores, spills, instruction mix and code size; profiles explain, never supply bare timing |
| Frontend and control flow | Instruction-cache/TLB events and supported frontend metrics; LBR branch stacks when usable; distinguish branch overhead from long-latency work |
| Data access | L1/L2/L3 and data-TLB events with verified meanings; AMD IBS Fetch/Op or the target's equivalent precise sampling facilities |
| Latency/source attribution | Supported IBS load-latency and L3-miss filters; memory source/latency and relevant DTLB information, with actual sample counts and losses |
| Shared hierarchy | L3/data-fabric/memory-controller bandwidth/cache events when contention or memory pressure is relevant; synchronize windows and retain background activity |

On the audited HX 470 the kernel exposes IBS Op `ldlat`, `l3missonly`,
`cnt_ctl` and software-filter configuration, plus IBS Fetch and L3/DF/UMC PMUs.
Its core PMU reports 16 branch entries but generic `max_precise=0`: do not
equate `cycles:p` with IBS or infer working branch-stack capture from CPUID.
IBS kernel/user filtering, task/CPU attachment, skid, sampling period and
permissions must be verified for the actual driver. Other hosts may provide
different facilities (for example PEBS); do not hardcode AMD as a requirement.

Keep event groups small enough for available counters and scheduling constraints;
split into passes instead of accepting unsupported/multiplexed groups. Retain
enabled/running time, sample loss, call counts, hashes and normalization.
Report shared uncore activity as shared evidence, not process-exclusive work.
Compare sampling overhead separately; do not attach every sampler concurrently.
Record unsupported energy/frequency sources rather than fabricate estimates.
RDT/cache allocation and other global settings require controller support and
restoration; discovery does not authorize untracked policy changes.

**Implementation status:** `tools/bench_lab/pmu.py`, integrated through
`study.py`, implements explicit bounded stat and sampling collectors, PMU
inventory, LBR, IBS memory-source/weight reporting, shared-PMU attachment and
package-energy diagnostics. The legacy fixed-group collector remains available
for reproducing older manifests. New studies must declare `profile_collectors`
explicitly; platform event availability is verified during execution, not inferred
from the presence of this implementation.

## Explicit advanced collectors

### Repeating a study when background load is suspected

Use a new output directory, seed and frozen plan; retain previous raw data and
verdicts separately. Verify exact model/DSP/timer binaries, including the timer
actually resolved by the DSP shared library. Do not use source equivalence as a
substitute for binary identity. Keep the original power/idle, warmup, counts,
acceptance margins and endpoint family for a replication.

The optional manifest boolean `record_process_environment:true` records a
hash-bound `samples/NNNN.f64.environment.json` before and after each worker.
Receipts include read-only telemetry endpoints and per-CPU `/proc/stat` deltas.
The after receipt is written even on workload failure. No sampler runs during
timed callbacks. CPU utilization covers worker launch, warmup and teardown as
well as the measured series; GPU/temperature endpoints are not interval peaks.
This option defaults false to preserve historical measurement paths.

Declare quiet-preflight and background flag thresholds before candidate data;
do not discard flagged/slow observations or extend a study until it passes.
Separate reserved-worker activity from housekeeping CPUs when assessing
background load. A quiet repeat does not retroactively establish the previous
cohort's load or a causal explanation for changed variance. Do not stop user
applications automatically or pool old/new cohorts for a favorable interval.

### Audio noise diagnostics and teardown

`just bench-audio-noise CONFIG NEW_OUTPUT` runs a fixed baseline-only diagnostic
plan on one or two explicitly named CPUs. Config fields are `library`, `inputs`
(two decoded float32 PCM files), `native_plugin`, `native_provenance`, `onnx_dir`,
`cpus`, and `seed`. Build/validate the pinned native adapter first. The recipe
runs model8, 128 paced warmup hops and 128 measured hops at10ms, with four
separate passes per CPU/policy: idle+scheduler+hardIRQ trace; softIRQ trace;
task cycles/instructions/reference cycles; fork/clone/clone3 tracepoint counts.
The last pass must observe zero warmed child-creation syscalls. Each uses the same prepare/readiness,
watchdog, unprivileged worker and finally-restore lifecycle. It crosses original
idle Boost and shallow-idle steady in a fixed order; this is diagnosis, not a
randomized causal comparison or candidate acceptance. Existing pilot data stay
immutable. Every config/source/plugin/model input is hash-bound.
The recipe prints and saves `REPORT.md` and `summary.json`; use `just
bench-audio-noise-report OUTPUT` to audit/re-render without new collection.

Counter permission preparation runs before warmup on exactly one allowed CPU.
Its successful token is thread/process/CPU-bound; child processes, unprepared
threads or widened affinity fail safely. `audio_measure(counters=1)` never forks
or prepares optional instructions. The one child permission probe disables core
dumping and executes before paced warmup. Callback counters still perturb the
workload and remain diagnostic only. The earlier audio-v2 counter-enabled pilot
and initial noise-diagnostic cohort redundantly forked inside the warmed window;
retain them with that contamination note and use the fresh counter-fix cohort
for warmed PMU inference. Their counter-disabled primary A/A/A/B paths are
unaffected. Do not replace old primary observations or extend their budgets.

The new `kind:"trace", scope:"cpu"` collector records every event from an
explicit whitelist on the reserved worker CPU (`perf record -a -C CPU -c1
--clockid mono`). Allowed tracepoints cover `power:cpu_idle`, scheduler wakeup
and switch, hardIRQ/softIRQ entry/exit. At most six events, a30s paced measured
window, 200,000 parsed records, and60s process timeout are allowed. The normal
FIFO brackets the warmed window. Save raw perf.data and nanosecond trace
payloads; reject losses, unexpected events/CPUs, malformed or unordered data.
No global ftrace tracer, mount or competing real-time test thread is enabled.
An idle exit state of -1/4294967295 is decoded per the
[kernel power trace documentation](https://kernel.org/doc/html/v5.7/trace/events-power.html).
The trace reports kernel-requested states, not measured hardware residency.
Cross-CPU wakers may be absent from this CPU-local recording. IRQ/body overlap
and nearest completed idle spans are descriptive, not causal attribution.

`telemetry.py` samples read-only, whitelisted hwmon temperature/power/fan data,
AC/battery status, platform policy, cpufreq hints, optional powercap energy and
throttle counters, DRM busy percentage and per-CPU `/proc/stat` deltas. Raw units
and labels are preserved; temperature has driver-specific exceptions documented
by the [kernel hwmon interface](https://kernel.org/doc/html/v6.6/hwmon/sysfs-interface.html).
Missing/unreadable sources are explicit. A policy frequency is not a callback
clock; shared power/temperature cannot prove task-exclusive frequency causes.
Diagnostics sample at5Hz for at most60s on housekeeping CPUs. Ordinary primary
studies take before/after boundary snapshots only, without a sampler or perf in
the timed windows. Do not divide raw latency by diagnostic frequency.

On timeout/interruption, perf's separate privileged process group receives TERM,
then KILL only if needed, and is reaped. The sampler is stopped/joined and writes
its completion receipt even on worker failure; FIFO paths are removed in finally.
The enclosing controller then restores CPU/power/IRQ/cgroup/service state.
Check immediate exact restoration separately from later dynamic irqbalance
updates. Run `just bench-audit` after restoration for a read-only check of the
saved static policy, online CPUs, cgroup/holder/watchdog removal and irqbalance
state. Later IRQ changes are reported only when irqbalance is active, CPUs are
online and the current mask differs from the lab mask; other mismatches fail.
This is distinct from `bench-restore`'s immediate exact readback.
No module unloading is required: neither helper starts a persistent
service nor loads a kernel module. Shared libraries unload when workers exit.

The device-IRQ tracepoints do not cover every local APIC timer, NMI or firmware
interruption. The local2026-11-11 baseline diagnosis found RCU/SCHED softIRQs
inside callbacks despite zero observed device IRQs/switch-outs in the separate
hardIRQ pass. Trace absence is not proof of zero interruptions. Reboot-time
full-dynticks/RCU offload would be a distinct machine policy and future study;
do not silently change boot options, unload production audio components, or
stop ordinary user services to make this study pass.

Add `profile_collectors`, `profile_conditions`, `profile_calls`,
`profile_repetitions` and `profile_arms` to the normal study manifest. For example
(the IBS event is AMD-driver-specific and must be probed on the target):

```json
{
  "profile_conditions": ["continuous"],
  "profile_calls": {"continuous": 256},
  "profile_repetitions": 2,
  "profile_arms": ["baseline", "candidate"],
  "profile_collectors": [
    {"id":"core", "kind":"stat", "required":true,
     "events":["cycles:u","instructions:u","branches:u","branch-misses:u"],
     "reason":"Core and branch efficiency"},
    {"id":"lbr", "kind":"record", "events":["cycles:u"],
     "frequency":997, "branches":"any,u", "reason":"Branch stacks"},
    {"id":"ibs-op", "kind":"record",
     "events":["ibs_op/cnt_ctl=1,swfilt=1/u"], "period":100000,
     "memory":true, "reason":"Sampled user load sources and weights"},
    {"id":"l3", "kind":"stat", "scope":"shared-pmu", "pmu":"amd_l3",
     "events":["l3_lookup_state.all_coherent_accesses_to_l3"],
     "reason":"Shared cache activity; not exclusive task attribution"}
  ]
}
```

Use `just bench-profile-session MANIFEST OUTPUT` for a profiling-only session
with the same prepare/readiness/watchdog/finally-restore lifecycle. It performs
no A/A or A/B timing study and cannot justify a speed claim. Normal
`bench-session` runs unprofiled A/A and A/B first, then separate profiles.
`bench-profile` remains the manual command inside an already prepared session.

Limits are explicit: 1–32 uniquely named collectors, 1–6 events per stat group,
one event source per sampling pass, 1–3 stat repetitions, at most 512 profile
jobs per session. Sampling uses either 19–2000 Hz or a fixed period of
10,000–10,000,000 events. Profile call counts are 16–65,536, compatible with
the registered batch size. Preregister these budgets; do not add passes after
inspecting the result. Sampling sources run separately. Shared-PMU collectors
use a supported online representative CPU from the PMU's actual cpumask and
retain shared attribution. Do not convert DRAM beats or CAS commands to bytes
without the target's documented event semantics.

The workload is unprivileged; only perf and the existing controller setup need
privileges. FIFO enable/disable brackets the warmed worker window. Save the
perf executable/version, input/tool hashes, raw stat JSON, perf recordings,
symbol reports, branch-stack samples, memory reports and loss diagnostics.
Stat counters require finite nonnegative values, positive event runtime and
at least 99.9% running time. Multiplexing, lost samples, malformed receipts,
workload failures and changed hashes fail the study. Optional unavailable
PMUs retain a concrete perf error; `required:true` turns unavailability into
a hard failure. No collector mounts tracefs or changes perf permissions.

A valid recording with no filtered samples is `empty`, not evidence that no
cache misses or long-latency loads occurred. LBR must contain actual branch
stacks. IBS reports observed load sources and the mean/sample SD of **nonzero
reported sample weights** separately, retaining periods and unparsed counts.
Zero reported weight is not zero load latency, and filtered sampling does not
estimate the mean latency of all loads. Counter mean/sample SD is per warmed
call, within each collector/model/arm/condition; two repetitions are descriptive
and do not supply a speed confidence interval. Profiled durations are excluded
from all latency inference. Keep user and kernel counters separate when a
candidate adds a system call; an optional syscall tracepoint can verify its
count when the running kernel exposes it.

See [CPU_OPTIMIZATION_PLAN.md](CPU_OPTIMIZATION_PLAN.md) for dispatch contracts,
source findings and the bounded experiment sequence.

## Recommended complete session

Finish runtime builds and numerical checks first. Construct a JSON manifest
using the example below and absolute artifact paths. Choose fixed counts,
randomization seed, precision limit and acceptance criteria before collection.

```sh
just bench-test
just bench-session /absolute/path/manifest.json .local/my-study
```

The session compiles the common measurement worker before preparing isolation,
then runs prepare, A/A, comparison, continuous-call diagnostics and separate
hardware profiles. It always restores the environment in a `finally` block,
including on failure or SIGINT/SIGTERM. The output directory must not already
exist; completed studies must not be overwritten or extended opportunistically.
An independent monotonic systemd timer restores settings if the controller is
killed. SIGKILL/power loss cannot be handled by a process `finally`; `/run` state
and the independent timer cover the live-machine case until its recorded TTL.

Reports include `prepare.json`, `aa/result.json`, `compare/result.json`, raw
binary64 observations, plans/hashes, separate perf data, `RESULTS.md`, and
`restore.json`. A failure retains partial evidence and produces an error;
it never prints a successful readiness/restoration verdict without readback.
Controller failure JSON, including the reason and rollback verdict, is retained
in the session error log even when preparation fails before session ownership.
Do not treat a preparation-only retry as a new statistical sample; retain its
failed attempt and never overwrite or recollect a begun timing journal.

## Manual session

```sh
just bench-prepare                  # CPU 3; nominal non-boost frequency; 1800 s TTL
just bench-ready                    # structural checks + three frequency probes
just bench-aa manifest.json .local/control
just bench-compare manifest.json .local/comparison .local/control/result.json
just bench-profile manifest.json .local/hardware
just bench-restore
just bench-status
```

`bench-prepare` accepts CPU, frequency in kHz (or `auto`), and TTL in seconds:
`just bench-prepare 3 auto 1800`. A second active session is refused. The TTL
is 60–7200 seconds and is not silently renewed. `bench-restore` is idempotent;
it terminates remaining workers in this laboratory's cgroup. `bench-exec`
executes an absolute executable as the original ordinary user with zero
capabilities and no-new-privileges. It does not grant privileges to a benchmark.
For arbitrary manual commands the caller must still restore afterward; use the
managed session for automatic cleanup. `bench-status` is read-only; `bench-ready`
also refreshes actual-frequency calibration and restores on calibration failure.

The optional fourth preparation argument selects `steady` (default) or `boost`:
`just bench-prepare 3 auto 1800 boost`. Manifests use `"power_profile": "boost"`.
Both reserve the same L3 domain and park the worker's SMT sibling. `steady`
disables Boost, fixes nominal-frequency bounds and restricts deep worker idle.
`boost` enables Boost, uses dynamic min/max bounds with governor/EPP performance,
and retains original idle settings. This is an isolated Boost experiment, not
the complete normal-desktop/real-audio environment. Boost calibration records
mean/SD and checks permitted bounds with 3% counter tolerance; it explicitly
does not claim constant frequency. Never apply the steady-profile 1%/0.3%
stability gate to variable-frequency Boost or relabel its range check as one.

Preparation compiles the worker first. Do not invoke `bench-tools` during an
active study: changing the probe binary invalidates the saved hash. Runtime
libraries must likewise remain unchanged. Profile recordings and counter jobs
are never mixed into latency estimates.

## Environment contract

- Discover the worker's physical SMT siblings and unified L3 domain.
  Reserve the complete online L3 domain with a cgroup v2 isolated partition;
  admit only the worker CPU into its child cgroup. Keep ordinary system/user
  work on the remaining housekeeping CPUs and verify every live thread's
  effective affinity. Zombies are not runnable and are excluded.
- Stop irqbalance temporarily, steer writable IRQ affinities, default IRQ mask,
  unbound workqueues, movable kernel workers and watchdog placement away from
  the reserved domain. Retain unmovable IRQ/kernel diagnostics. Firmware,
  per-CPU work, shared RAM and package effects cannot be eliminated this way.
- Save every cpufreq policy before disabling Boost, not only the worker policy:
  the boost control can change other policies' limits. Set worker governor/EPP
  to performance and request equal min/max at a non-boost nominal frequency.
  Park the worker's online SMT sibling. Disable idle states with declared exit
  latency above 1 µs on the worker only; leave the rest of the machine's idle
  policy intact. This is a controlled laboratory environment, not a deployment
  recommendation or evidence for normal power-policy performance.
- Frequency-limit writes require three consecutive exact requested min/max
  readbacks, 10 ms apart, within a two-second bound, before freezing policy.
  This handles asynchronous amd-pstate QoS publication without accepting an
  intermediate limit or relaxing later structural/calibration checks. Failure
  retains requested/observed limits and restores settings. It is a preparation
  check, never an extension or repetition of collected timing observations.
- Verify actual frequency using CPPC delivered/reference counters under three
  600 ms AVX2 load probes. The backend requires positive nominal frequency and
  equal nominal/reference performance units. Default readiness tolerances are
  mean within 1% of target and sample SD <=0.3% of measured mean. Retain every
  probe; actual hardware frequency may differ slightly from the request.
- Readiness additionally verifies policy settings, online CPUs, the independent
  restore timer and absence of ordinary background threads in the reserved L3
  domain. Snapshot worker IRQ/softirq counters before/after timing. No claim of
  an interrupt-free CPU or physically exclusive cache/package is made.

## Transaction and privilege boundaries

Root controls only configuration and perf access. State is root-owned under
`/run/dpdfnet-bench-lab` with mode 0700 and a process lock. Rollback data are
saved and fsynced before writes. An immutable copy of the rollback controller
is installed there before the independent restoration timer is armed. The
timer is scoped to its session ID, so a delayed old timer cannot restore a new
session. Managed cleanup also checks the ID.
The controller and measurement-worker hashes are frozen for the active session;
readiness/launch refuses edits. The validated backend requires the local TSC
clocksource. If the workspace is unavailable, the saved rollback can be invoked
with `sudo python3 /run/dpdfnet-bench-lab/rollback.py restore`.

CPU hotplug, every original frequency policy, Boost, IRQ/workqueue/watchdog and
idle settings are restored with readback; moved live kernel tasks are matched
by PID plus start time to avoid PID-reuse errors. Cgroups and temporary units
are removed and irqbalance returned to its original state. The original root
controller set and CPU online mask are verified. Existing configuration for the
owned systemd unit names is refused rather than overwritten. Restoration errors
remain explicit and retryable; a second successful restore performs no writes.

## Measurement contract

One executable loads each selected library with `dlopen`; no separate benchmark
build/code layout is introduced for the two treatments. Readable ELF pages,
buffers and timing samples are prefaulted before 128 warmup calls. Worker timer
slack is set to 1 ns for the process lifetime. Runtime/model code is unchanged.

- `batch`: CLOCK_MONOTONIC_RAW brackets 16 inferences by default, with no clock
  calls between them. Each retained value is amortized time per inference in
  that group. Its SD/tails are group-mean statistics, not individual-call SD or
  a bound on any one call's latency.
- `continuous`: the same clock brackets each inference, providing separate
  per-call diagnostics. No CPU-time syscall surrounds individual calls.
- `paced`: individual calls at a 10 ms absolute-monotonic cadence; actual calls
  are timed with MONOTONIC_RAW. Warmup is continuous, so this differs from the
  earlier benchmark's paced warmup. Record late completion before cadence reset.

Thread CPU time is read only before/after the measured window (plus one
untimed warmup read); process resource accounting is outside it. Tracepoint
validation on the local machine found exactly three clock_gettime syscalls per
process in both batch and per-call modes, independent of the number of calls.
CLOCK_MONOTONIC/RAW use the local stable-TSC vDSO path. The worker also reports
UID, no-new-privileges, CPU, hardware frequency feedback, faults, context switches
and a final output/full-state checksum. The checksum supplements, not replaces,
the independent every-frame numerical regression tests.

Fresh-process paired blocks are the inference units. Orders are balanced within
each of two inputs; use block counts divisible by four. A/A compares the same
library/binary with itself for every planned ISA/model/cadence. Comparison
requires a matching A/A report with unchanged binary/input hashes. Both phases
retain all observations; a failed A/A precision gate is not repaired by extending
the series. Such comparisons remain diagnostic even if their point estimates
are favorable. Adjust Student-t log-ratio intervals for all planned contrasts.
Report call/group SD separately from process-mean SD, tails and deadline misses.

## Manifest example

```json
{
  "schema_version": 1,
  "cpu": 3,
  "frequency_khz": "auto",
  "ttl_seconds": 1800,
  "worker": "/absolute/repository/.local/bench-lab/worker",
  "inputs": ["/absolute/original.f32", "/absolute/gain.f32"],
  "variants": {
    "native": {
      "baseline": "/absolute/native-baseline/libdpdfnet.so",
      "candidate": "/absolute/native-candidate/libdpdfnet.so"
    },
    "avx2": {
      "baseline": "/absolute/avx2-baseline/libdpdfnet.so",
      "candidate": "/absolute/avx2-candidate/libdpdfnet.so"
    }
  },
  "models": [2, 8],
  "weights": {"2": "/absolute/model2/weights.f32", "8": "/absolute/model8/weights.f32"},
  "seed": 202611105017,
  "calls": {"batch": 512, "continuous": 256, "paced": 100},
  "batch_size": 16,
  "aa_blocks": 4,
  "compare_blocks": 8,
  "aa_noise_limit_percent": 0.5,
  "minimum_useful_gain_percent": 0.3
}
```

With two ISAs/two models this fixed plan uses 64 A/A processes, 128 comparison
processes, eight continuous diagnostic processes, and 40 separate hardware jobs.
The former two phases use eight family-adjusted contrasts each. There are two
counter repetitions per condition/group and one sampling recording per arm;
these profiles provide descriptive diagnostics, not an independent precise
speedup estimate. Do not pool this non-boost study with earlier Boost-enabled
measurements or transfer its gains directly to a real audio deployment.

## Cadence and batching sweeps

The optional `conditions` array replaces the default batch/paced pair. Each
condition has a unique `id`, `worker_mode`, `calls`, `batch_size` and, for paced
conditions, `period_ns`. For example:

```json
[
  {"id":"continuous","worker_mode":"continuous","calls":512,"batch_size":1},
  {"id":"batch16","worker_mode":"batch","calls":512,"batch_size":16},
  {"id":"batch64","worker_mode":"batch","calls":512,"batch_size":64},
  {"id":"paced5","worker_mode":"paced","calls":64,"batch_size":1,"period_ns":5000000},
  {"id":"paced10","worker_mode":"paced","calls":64,"batch_size":1,"period_ns":10000000},
  {"id":"paced20","worker_mode":"paced","calls":64,"batch_size":1,"period_ns":20000000}
]
```

The worker accepts `paced:PERIOD_NS` (1–100 ms); plain `paced` retains 10 ms.
Late completion is relative to the selected period, while `over_10ms` retains
its absolute 10 ms meaning. Model input still represents 10 ms spectral hops;
5/20 ms test cadence is a synthetic wakeup/workload experiment, not a changed
audio sample rate. Continuous and batch modes do not observe paced deadlines.

Use `family_comparisons` to cover the complete planned family across manifests,
never fewer than the contrasts in one manifest. For the six-condition example,
two ISAs/two models/two power profiles require family size 48. Declare separate
manifests and seeds for power profiles; execute them sequentially with complete
restoration between sessions. Shared session order/time-of-day effects prevent
causal attribution of cross-profile differences to one power/idle setting.

Optional `profile_conditions` selects condition IDs for hardware counters;
`profile_groups` selects primary/frontend groups, `profile_repetitions` fixes
their repeats, `profile_calls` fixes shorter profile-only counts, and
`profile_sample:false` omits separate sampling recordings. Profiled time is
always excluded from latency inference. `continuous_diagnostics:false` avoids
redundant diagnostics when continuous already is a primary condition.

## Recovery after aggregation failure

`just bench-resume MANIFEST EXISTING_OUTPUT` supports a fully collected A/A
phase when comparison has not started. It validates the original schedule,
binary/input hashes, every raw sample hash/count, mean and sample SD, then
reconstructs the derived A/A summary. It archives the original preparation and
restoration reports before starting a fresh equivalent environment for the
remaining comparison/profile phases. It never recollects A/A samples or accepts
an incomplete journal, changed manifest, changed binary, or begun comparison.
Record both preparation epochs and the reason for recovery. It is not a way
to extend a completed study after inspecting an unfavorable result.

## Process layout and complete audio callbacks

Preregister `"layout_profile": "fixed"` when measuring small code changes.
The controller applies Linux `ADDR_NO_RANDOMIZE` to each unprivileged worker
before exec, without changing the machine-wide ASLR setting. The worker reports
the effective personality, API address and state-buffer address. Use real
byte-identical library copies at equal-length absolute paths when necessary:
symlinks are resolved by the launcher and do not equalize argument lengths.
Check address distributions after collection. Fixed layout controls one nuisance
variable; it cannot establish performance under every possible layout. Keep
independent randomized-layout evidence separate and never pool these cohorts.
`"layout_profile": "randomized"` is the default and explicitly clears the flag.
The controller also fixes Python's hash seed and numerical-library thread counts.

A condition can override `worker` and its two `inputs`. The standard executable
`tools/bench_lab/audio_worker.py` accepts decoded mono float32 PCM and measures
the documented NumPy FFT -> ready-library inference -> IFFT/overlap-add callback.
Use individual paced conditions, not batch mode, for this worker. It uses the
same warmup, absolute cadence, per-process privilege/layout checks, CPPC feedback
and perf FIFO protocol as the C spectral worker. Add `audio_pipeline.py` and
`examples/dpdfnet.py` to manifest `extra_files`; pin NumPy's reported version.
This is a host-callback measurement, excluding device I/O, resampling, codecs,
audio-server scheduling and service concurrency. It is not a hardware-loopback
or production deployment test. Counter profiles must inherit the same worker
and input override; their durations remain excluded from latency inference.

Before timing, regenerate spectra from the decoded PCM and compare them with
the pinned spectral fixtures. Compare complete synthesized PCM, every spectral
output and recurrent state for all selected libraries and both models. A final
checksum in a timing process is an additional guard, not a substitute for these
checks. State explicitly when regenerated public/stress fixtures do not reproduce
an unavailable historical corpus.

## Practical noninferiority (legacy v1)

For legacy v1 fields, declare `noninferiority_margin_percent` before collection (default 0.5%).
`passes_noninferiority` requires a qualified matching A/A control and a
family-adjusted gain-interval lower bound above the negative margin. It means
losses at or beyond that practical margin are excluded by this experiment's
model; it does not prove zero slowdown or useful acceleration. Report it
separately from `passes_acceptance`, deadline/fault checks and numerical gates.
An unqualified A/A cell remains inconclusive even if its point estimate is
positive. Do not increase the sample after inspecting its result.

For multiple machines, require independent readiness and restoration on each.
A host with only one L3 domain cannot satisfy this backend's reserved-L3 plus
separate-housekeeping contract. Ready binaries may still receive low-priority
numerical portability checks there, with service health checked before/during/
afterward, but do not label those runs isolated performance measurements.


## Workload-specific acceptance v2 (2026-11-11)

The user authorized fresh, shorter reconsideration studies. Old v1 manifests,
results and verdicts remain unchanged; v2 must be explicit in a new manifest.
Correctness, ISA legality, guarded memory, CPU isolation, restoration, frozen
hashes, retained observations and publication holds are not relaxed.

Declare `acceptance_policy` with all fields, including an explicit endpoint
family and a role per condition. `model_roles` can override a model to `guard`:

```json
{
  "version": 2,
  "roles": {"continuous":"throughput", "audio10":"audio"},
  "model_roles": {"2":"guard"},
  "minimum_gain_percent": 0.3,
  "mean_loss_margin_percent": 2.0,
  "tail_loss_margin_percent": 5.0,
  "aa_drift_percent": 0.3,
  "family_comparisons": 14
}
```

These are engineering thresholds for the local short study, not universal
constants. A 2% callback-time allowance is tens of microseconds here, a small
fraction of the 10-ms deadline; the 5% tail allowance admits bounded occasional
cost without treating an observed deadline violation as acceptable. Neither
margin promises zero slowdown. Set stricter margins when the actual application
budget requires them, and never select a margin after seeing new measurements.

- **A/A:** retain its bias estimate, corrected interval and precision report.
  A wide interval is diagnostic and does not automatically veto A/B. Invalidate
  a cell if its A/A interval excludes zero and absolute point bias reaches the
  preregistered practical drift threshold. Passing this test is not equivalence
  or proof of no bias. A/B uncertainty still controls its own decision.
- **Throughput:** require point gain >=0.3% and corrected lower gain bound >0;
  no requirement that the lower bound exceed the A/A envelope. Both arms must
  satisfy observed deadline/fault guards. Do not call a noninferiority pass
  an acceleration.
- **Audio/guard:** require corrected mean gain lower bound >-2% and corrected
  per-process p99 gain lower bound >-5%, with no late completions, >=10-ms calls
  or major faults in either arm. A mean-only pass cannot hide an unbounded tail.
- **Estimands:** paired fresh-process log ratios of process means and process
  p99 values, exponentiated to geometric ratios. Call counts are not statistical
  replicates. A CI for the typical per-process p99 ratio is not a confidence
  bound for population p99, rare deadline probability or worst-case latency.
- **Multiplicity:** declare all primary mean and tail endpoints across the
  confirmation manifests. Diagnostic exploratory screens cannot certify a
  default; independently confirm the selected candidate using fresh processes
  and held-out inputs. Do not pool screening, old v1, fixed/randomized layouts,
  power profiles or core classes. Software emits `workload_acceptance` alongside
  unchanged legacy fields so they cannot be confused or retroactively relabeled.

The short 2026-11-11 design screens the previously removed K64 and padding,
the exact EVEX256 candidate and a fresh incremental quantize4 build against the
accepted fusion binary. Candidates with numerical failures or large diagnostic
regressions are not reopened. One finalist receives independent fast/compact
Boost confirmation with continuous and complete host-audio conditions, model2
as an overhead guard, fixed sample counts and a declared inconclusive outcome
when the budget cannot establish the claim. This is narrower than a full
steady/Boost/layout/cadence sweep. Publication remains held.

The paired interval construction follows the
[NIST paired-observation framework](https://itl.nist.gov/div898/handbook/prc/section3/prc312.htm),
applied to log ratios; normality and finite small-sample precision remain
assumptions/limitations, not guarantees supplied by isolation.


The completed short study is recorded in
[reconsideration_20261111.json](../validation/reconsideration_20261111.json).
It uses 64 screening and 256 confirmation processes, with 160 separate warmed
profile jobs. Screening defers causal profiling to the selected finalist;
verified old same-binary evidence is retained, and all targets receive fresh
read-only inventory/provenance checks. Confirmation repeats all 20 collector
families on both core classes with one descriptive pass per source.
The 14 primary endpoints are eight mean contrasts plus six audio/model2-guard
process-p99 contrasts. Two model8-throughput p99 intervals are diagnostic and
are not additional primary tail claims. Counter SD is not estimated from one
pass; latency call/process SD remains fully reported.

V2 confirms scoped continuous model8 gains on both core classes but does not
qualify the complete audio/default scope. Neither a screen pass nor a narrower
throughput pass automatically changes the runtime or publication decision.

## Versioned audio measurement (2026-11-11)

The old `audio_worker.py` / `AudioPipeline` remain unchanged reference adapters.
`audio_worker_v2.py` delegates cadence and all timestamp recording to the
baseline-only C `audio_clock` helper. Its buffered NumPy path reuses data buffers,
FFT outputs and ctypes pointers while retaining reference operation order and
finite-input checks. The optional Rust adapter uses the real HushMic DSP and a
reviewed test-only bridge to the requested public runtime. It is not installed
with libdpdfnet and adds no runtime FFT/Rust/Threads dependency.

```sh
just bench-audio-tools
just bench-audio-test /absolute/path/to/accepted/libdpdfnet.so
just bench-audio-native /absolute/path/to/reviewed/hushmic /new/adapter/output
just bench-audio-pilot /absolute/path/pilot-config.json .local/new-audio-pilot
just bench-audio-report .local/new-audio-pilot
```

The pilot config explicitly supplies `library`, two decoded `inputs`,
`native_plugin`, `native_provenance`, `onnx_dir`, `cpu`, `seed`,
`calls:128`, `warmup:128`, `blocks:4` and the bounded `profile_collectors` list.
The native builder requires the reviewed public-runtime test bridge and builds
offline; it records external source hashes and the resolved Cargo lockfile.
Preflight verifies adapter/clock provenance. Freeze the produced artifacts;
rebuilding the adapter or helper invalidates earlier hashes.

The pilot is baseline-only: one model8, one core, four paired processes per
adapter/policy, 96 fresh processes total. It crosses fixed/Boost frequency with
original/shallow idle, rather than confounding the two settings. All environment
mutations remain in the common controller journal and watchdog/finally lifecycle.
`idle_policy:auto` preserves the older steady/Boost behavior; new manifests can
explicitly use `original` or `shallow`. Readiness verifies actual idle readback.
`bench-aa-session` supplies the baseline-only lifecycle without a redundant
candidate phase. The pilot stops on failure and never extends its sample budget.

The C helper performs paced warmup and records MONOTONIC schedule/start/finish
plus a separate RAW callback duration, with the original reset-after-lateness
policy. Measurement starts one period after post-warmup setup; retain the first
sample rather than hiding this boundary. Sidecars are hash-checked against raw
samples and response/deadline summaries, including completed-A/A recovery.
All data buffers are allocated before collection; Python still has interpreter
object overhead, so this is not a claim of zero Python allocations.

Optional diagnostic passes verify user-mode RDPRU APERF/MPERF access in a child
before using it, retain raw per-callback counter deltas and include their overhead.
They do not turn CPU-wide counters into exclusive task counters or rescale primary
wall times. Main A/A measurements leave counter instrumentation off. Native DSP
and NumPy are different frontend scopes; compare each candidate to its own
numerically verified baseline, not their absolute times as a kernel speedup.

In the completed one-host pilot, original-idle Boost paired-log SD decreased by
55.4% for buffered NumPy and 70.5% for native DSP relative to the legacy adapter.
Both new paths had zero measured minor faults, versus roughly 454–456 faults over
eight legacy processes per policy. Fixed/shallow paired SD was 0.184% buffered,
0.225% native and 0.614% legacy. Dynamic/shallow was substantially noisier; it is
not a preferred general setting. Four-pair estimates do not prove a universal
variance reduction or adequate precision for sub-percent candidate claims.

All 130 full-corpus model/fixture PCM+FFT checks pass for buffered NumPy;
rounding/FTZ/DAZ and guarded-timer contracts pass. Native DSP matches the existing
real-DSP reference/reset for both models. The pilot retains 12 independently
verified intervals, 12,288 raw callback observations and 40 separate diagnostic
PMU jobs. It changes no model/runtime default or previous qualification verdict.

The exact restore receipt is verified immediately, before ordinary service
activity evolves the state. With restored irqbalance active, a later IRQ mask
may legitimately differ from that snapshot; log such drift explicitly and verify
static settings, service policy and absence of the laboratory mask/cgroup. Do not
fight the normal daemon or report permanent IRQ-mask equality.
