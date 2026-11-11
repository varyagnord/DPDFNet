# CPU-aware optimization and dispatch plan

Hardware acceptance uses only the local PC and remote i7-7700T. No additional
VNNI host or microarchitecture is required; V04 is closed as not required.
See [HARDWARE_SCOPE.md](HARDWARE_SCOPE.md). Runtime recommendations and measured
qualification outcomes are unchanged by this scope decision.

Final selection: unqualified runtime implementations are removed rather than
kept behind OFF switches. The selected quantizer is the legacy exact path;
CM stays enabled for both models and eligible model8 VNNI batch/pair fusion
stays enabled. Refined/VNNI quantize4 implementation/options are deleted;
EVEX and other rejected prototypes remain private. See the
[lean selection record](../validation/runtime_selection_20261111.json).

Latest follow-up: the2026-11-11
[exact-binary native repeat](../validation/audio_repeat_20261111.json) retains
per-process load receipts and resolves model2 mean slowdown on both core classes;
model8 audio benefit remains unconfirmed. EVEX stays private/excluded from the
future runtime PR. Reduced mean dispersion does not prove the old load caused
its earlier noise. No registered samples were excluded or cohorts pooled.

Earlier follow-up: the2026-11-11
[native DSP/noise confirmation](../validation/audio_noise_20261111.json) resolves
EVEX per-process-p99 noninferiority on both models/core classes, but all mean
guards remain inconclusive. Model2 compact p99 has a small resolved cost;
tracepoints confirm one per-hop CPU-domain affinity syscall in both candidate
models. Inspect whether unaffected model2 can avoid optional-wide guard work
while preserving its actual capability/lifetime contract before any future
implementation. This is a future design question, not an accepted source change.
Current runtime/defaults and the publication hold are unchanged. Historical
counter-enabled audio pilot diagnostics have a warmed permission-probe fork;
the new thread/process/CPU-bound preparation and16-pass regression supersede
that diagnostic methodology, without rewriting old primary verdicts.

Status: implementation and controlled qualification, 2026-11-10. The source
findings below describe the accepted runtime at the start of this study. New
kernels and domain-aware dispatch are isolated private candidates until the
registered confirmation gates pass; this document does not change defaults.
The existing model-8 fusion selection and publication hold remain authoritative;
rejected standalone K64 and dedicated VNNI padding are not reopened.

## Current implementation: findings from source

| Location | Observed behavior | Design implication |
|---|---|---|
| `src/runtime.c`, `model_backend.c` | Two fixed graph backends; public creation requires the selected AVX2/FMA runtime | Preserve public ABI and baseline requirement; internal scalar oracles do not imply a public scalar runtime |
| `common/dpdf_dprnn.c:dpdf_has_avx2` | Compiler builtins check AVX2 and FMA, including OS AVX state | Centralize future capability semantics without making baseline detection execute optional ISA |
| `common/int8.c:dpdf_qcreate` | Selects AVX2 or VEX AVX-VNNI affine/pair once per matrix | Reuse creation-time dispatch; do not add per-dot CPUID |
| `common/int8.c:dpdf_qaffine_cm64` | Selects CM by affine function-pointer identity | Introduce an explicit compatible CM operation binding when adding an ISA family; adding a new affine alone would fall back or fail eligibility |
| `private/int8_matrix.h` | Matrix owns packed weights, scale/sum and affine/pair pointers | Store a compact immutable kernel/layout descriptor, not a process-global mutable current ISA |
| `common/int8.c:dpdf_qcreate` | Weights packed in four K bytes by eight output columns; 64-byte allocation alignment | EVEX256 can initially reuse this layout; 16-column ZMM tiles require an explicit packing design |
| `common/int8_kernels.inc:qdot64` | Eight accumulators; intentional noinline boundary prevents historical spills | Extra registers are an opportunity, but current CM loops were already spill-free in prior measured binaries |
| `qdot4pair_generic`, fused assembly | Four rows, two 8-column tiles and shared weights | Evaluate larger blocking against reuse, register pressure, load bandwidth and code size together |
| `common/int8_kernels.inc:CM_TRANSPOSE8` | Integer lanes are transposed after FP32 quantization using unpack/shuffle/permute operations | Consider narrowing before byte rearrangement and VBMI only after proving an exact mapping |
| `quantize_legacy.inc`, `quantize_refined.inc` | Exact division/rounding; lane-local saturating packs and dword permutation | Narrowing/masks may remove packing work independently of VNNI or quantize4 promotion |
| `common/avx2.c:dpdf_norm_residual_avx2` | Double-precision mean/variance, increasing-channel additions; eight rows in two YMM lane groups | Consider more independent rows/registers; do not replace ordered reductions with horizontal sums |
| `common/avx2.c:dpdf_gates_avx2` | Validated polynomial, explicit FMA/division; reset/update scratch arrays | Register-resident per-channel tiling may remove scratch traffic; preserve input/output alias contracts |
| `common/full_ops.c`, `dpdf_generated_gru256_exact_avx2` | Model 2 vectorizes surrounding arithmetic but retains scalar expf/tanhf; model 8 uses scalar helper | Model-8 exact surrounding arithmetic is a candidate only after hotspot evidence; wide SIMD does not vectorize scalar libm by itself |
| `generated_model.c` in both graphs | Many elementwise/copy passes; logf/sqrtf/expf remain | Inspect arena lifetimes and exact local fusion, not only GEMM; no approximate vector-libm substitution |
| `tools/generate_vnni.py` | Replaces AVX2 multiply/reduction sequences mechanically | Audit dead setup separately: five of six generated `.S` files write YMM8 once for an obsolete all-ones broadcast; the pair-affine file reuses YMM8 later, so blanket register deletion is unsafe |
| `CMakeLists.txt`, `tests/vnni_isa_contract.py` | Separate VNNI C unit; existing contracts forbid EVEX in AVX2/VEX paths | Add new object-specific positive/negative contracts, retain the existing prohibition for old paths |
| `tools/bench_lab/study.py:profiles` | Two fixed five-counter groups plus cycles sampling; requires >=99.9% running | The new explicit `pmu.py` collectors integrate IBS/LBR/shared PMUs with bounded manifest plans and verified attribution; retain legacy groups for old manifests |

Source-level loop/call counts are not dynamic execution counts or measured
hotspot shares. Prior model-8 profiles retained roughly 1.3% more instructions
with lower cycles after accepted fusion; instruction count alone is not a
selection criterion. The old data is descriptive, not a fresh profile of new
candidates or another microarchitecture.

## Independent legality and performance decisions

Define three distinct stages:

1. **Usable capabilities:** CPU-advertised feature bits, OS-enabled XSTATE,
   allowed CPU scope and successfully built implementation objects.
2. **Eligible implementations:** complete ISA closure plus matrix shape,
   layout, alignment/bounds, pair compatibility, aliasing and numerical contract.
3. **Performance policy:** select among eligible, validated implementations
   using measured kernel/graph evidence. Wider or newer does not mean faster.

Do not implement a linear `AVX2 < VNNI < AVX512 < VBMI2` ladder. A CPU can have
AVX512-VNNI without VEX AVX-VNNI; dot products can be available without VBMI.
Quantization, dot products, CM rearrangement and FP32 helpers can have different
useful feature sets. Conversely, do not generate the Cartesian product of all
features: add one candidate per distinct useful operation/layout combination.

### Candidate feature requirements

All entries inherit the runtime AVX2/FMA baseline and usable AVX state. This is
a design table, not a list of implementations already built or enabled.

| Candidate | Additional architectural requirements | Notes |
|---|---|---|
| Existing AVX2 dot | None | Current W7/A8 saturating-pair proof retained |
| Existing VEX dot | AVX-VNNI | Does not require AVX-512 |
| EVEX256 integer dot | AVX512F + VL + VNNI, OS opmask/ZMM state | Must not require VEX AVX-VNNI; BW/DQ only if actual surrounding instructions need them |
| ZMM integer dot | AVX512F + VNNI, OS opmask/ZMM state | Additional helpers may add BW/VL/DQ; verify actual object, do not assume |
| EVEX256 FP32/high-register helper | AVX512F + VL, OS opmask/ZMM state | Some operations need further subsets; not every existing VEX instruction has an EVEX equivalent |
| Byte permute | AVX512VBMI + base prerequisites; VL for narrow forms | Optional packer/CM operation, not a prerequisite for every dot kernel |
| Byte/word compress/expand | AVX512VBMI2 + base prerequisites; VL for narrow forms | Useful only when masks/sparsity justify cost; validate any BW dependencies of helpers |
| Integer narrowing pack | Exact conversion-specific F/BW/VL requirements | Audit installed intrinsics and disassembly; same byte result need not require VBMI |
| Instruction prefetch | PREFETCHI in the appropriate vendor CPUID location | Only for a demonstrated instruction-fetch bottleneck |

Each implemented descriptor must contain an exact requirement bitset derived
from every emitted instruction, including compiler-generated prologues, tails,
loads/stores and callees. The table is not a substitute for that final audit.
Do not unnecessarily require all 13 AVX-512 groups on a narrower kernel.

### Safe capability snapshot

- Keep detection and public entry paths at the current safe baseline.
  Validate CPUID leaf/subleaf ranges; check OSXSAVE before executing XGETBV.
  AVX state needs XCR0 bits 1/2; AVX-512 also needs bits 5/6/7, even for
  EVEX256. Account for compiler/runtime detection guarantees explicitly.
- Vendor/model identifies feature encoding and performance hints, not a
  substitute for instruction checks. AMD PREFETCHI and short-REP hints illustrate
  why Intel-only extended-feature parsing is insufficient.
- Define the execution domain: ordinary migratable contexts require capabilities
  safe across all CPUs on which the worker can execute. Detection on one pinned
  CPU, the benchmark's private affinity or one hybrid-core class is insufficient.
  Do not change application affinity during model creation. Capture and validate
  the domain/lifetime; capability shrink or migration outside it requires an
  explicit safe lifecycle mechanism, never execution followed by SIGILL recovery.
  If the platform cannot establish a stable safe optional feature set, retain
  the baseline. CPU hotplug/affinity expansion is a documented lifecycle case.
- Cache discovery outside process callbacks using thread-safe immutable state
  with an explicit lifetime. Never let a testing mask grant hardware features;
  masks only remove capabilities. No audio-thread autotuning or PGO training.

### Operation bindings and packed layouts

Use private immutable descriptors (conceptually `kernel_id`, `requires`,
`layout_id`, affine, pair and CM bindings), constructed at creation. FP32 block
operation pointers already provide a similar boundary. Keep separate operation
selection only where data contracts permit it; do not insert function-pointer
calls per vector or alter the installed public ABI.

Initially keep eight-column packing for EVEX256. A ZMM design must either
demonstrably combine existing tiles efficiently or introduce a tagged 16-column
layout packed once at creation. Count memory/initialization cost; do not keep
all packed copies by default. N=8-multiple tails cannot read an unallocated
16-column tile. Scales, sums and biases must match the chosen column order.

Paired kernels require both layout descriptors and shape contracts to match.
Incompatible pairs must use verified separate affine fallbacks or a compatible
pair implementation. CM eligibility must use the selected explicit binding,
not assume affine pointer identity implies a specific ISA. All paths retain
existing row limits, overlap guards and correct fallback behavior.

Compile optional families in isolated objects/targeted functions with matching
namespace declarations. Keep baseline objects free of EVEX; restrict EVEX256
objects from accidental ZMM widening. `prefer-vector-width=256` is a preference,
not an opcode prohibition. Audit emitted code and cross-target calls after
release, PGO, sanitizer and any LTO build. No global `-march=native`.

## Prioritized experiments and exactness requirements

| Priority | Candidate | First question / acceptance constraint |
|---|---|---|
| P0 | Capability/selection contracts and profiling inventory | Can every missing prerequisite safely select an existing fallback? Can the laboratory collect applicable PMUs with explicit failures? |
| P1 | EVEX256 VNNI register blocking | Do extra registers reduce actual spills, setup or repeated loads? Compare existing packing first; current spill-free CM is not an assumed win |
| P1 | Direct narrowing and CM byte rearrangement | Can narrowing plus a proven byte mapping replace the current 8x8 dword transpose/pack chain without changing results? |
| P1 | Gate channel tiling | Can reset/update stay in registers and input loads remain alias-safe, preserving the exact existing polynomial and explicit FMA sites? |
| P2 | AVX512-VNNI 512-bit with matched packing | Does whole-graph throughput improve after packing/load/clock/code-size effects on both core classes? Compare against EVEX256, not only AVX2 |
| P2 | Ordered normalization and FP32 convolution | Can more independent rows/outputs use registers effectively while retaining channel order, double intermediates and original fused-vs-separate operations? |
| P2 | Generated elementwise/arena pass fusion | Can exact adjacent operations remove memory passes without destroying live aliases or overwriting later graph consumers? |
| P2 | Exact model-8 GRU surrounding arithmetic | Does profiling justify vector arithmetic around unchanged scalar libm? Model-2 implementation is a reference, not a transferable speed claim |
| P3 | Generated VNNI dead setup | Remove only proven dead initialization through the generator; retain ABI/CFI and used registers, requalify code-layout effects before acceptance |
| Conditional | Software/data/instruction prefetch | Only after IBS/cache/frontend evidence; preregister distance, keep pointer legality and avoid pollinguting hot caches |

The local HX 470 reports FP256 and FP512-to-FP256 downgrade; this is a policy
hint, not measured VNNI throughput. Test 256 and 512 independently. Other CPUs
may select a different validated width. Keep unknown microarchitectures on a
conservative measured fallback rather than inferring speed from feature count.

Quantization must preserve zero inclusion, min/max operand/tree behavior,
rounding, FTZ/DAZ, NaN/Inf behavior covered by current contracts, signed zero
and empty-row semantics. Keep exact division; masked inactive lanes must not
introduce FP exceptions absent from the reference. Do not use reciprocal or
reciprocal-square-root approximations. Direct unsigned narrowing requires
signed clamping to [0,254] first: negative/invalid INT32 results must not
become 254 through unsigned saturation. This needs guarded oracle tests.

Concrete packing starting point: AVX512F/VL `_mm256_cvtusepi32_epi8` after
signed int32 clamping, compared with existing packs/permutation. The installed
GCC 16 header places this in `avx512vlintrin.h`; it does not inherently require
VBMI. EVEX `_mm256_dpbusd_epi32` and `_mm256_permutexvar_epi8` have distinct
VNNI/VL and VBMI/VL requirements in their respective headers. Verify those
closures again against the eventual complete object, not just the intrinsic.

For CM, compare a narrow-byte permutation network with the present dword
transpose; avoid simply making an 8x8 transpose twice as wide. For convolutions,
test masked loads and permute/two-source-permute against current fringe/stride
handling; regular strides may favor contiguous loads over gather/scatter.
Preserve the current per-tap vector-FMA versus scalar-separate distinction:
widening the interior must not move a formerly separate tail into fused FMA.
Ternary logic (`VPTERNLOGD/Q`) may reduce mask/select integer sequences if an
actual sequence matches its truth table. Special range/reduction/scale FP
instructions are not substitutes unless NaN/signed-zero, exceptions and
rounding are proved identical. None justifies a standalone dispatch variant
without a measured useful kernel.

For INT8, retain A<=254, |W|<=63 and K<=512. The AVX2 pair bound is 32004;
the full absolute dot bound is 8193024, safely inside int32. Preserve zero-point
correction, conversion, scale and bias ordering, including existing explicit
FMA sites. Do not indiscriminately replace existing FMA or introduce new ones.

Parallelize independent outputs/rows, not FP reductions. Ordinary `_reduce`
intrinsics, reassociation and BF16/FP16 substitution are not exact shortcuts.
Masked tails must retain bounds and existing scalar-tail rounding semantics.
Inspect thread sharing and all supported input/output aliases before removing
scratch storage. Padded dimensions and 40/48-row blocks must remain valid.

## Features considered but not justified for current dense inference

IFMA, AES/VAES, SHA, PCLMUL/GFNI, VPOPCNT/BITALG and VP2INTERSECT do not have
a demonstrated matching operation in the current graph. Conflict detection
does not accelerate regular dense accesses. Sparse compress/expand needs real
usable sparsity, not zeros inferred from an unrelated corpus. CLWB/CLFLUSH and
non-temporal/direct stores are not improvements for immediately reused state.
CLZERO/REP/glibc initialization paths need measured significance. Avoid manual
huge-page/cache-allocation changes without a memory bottleneck and restoration
support. GPU/NPU are separate backend/quality/latency proposals, not dispatch
branches for these CPU kernels. No unsupported feature is assumed available.
BMI/ADX and endian/bit-manipulation instructions are candidates for matching
packing/address logic only; no such bottleneck or general dense arithmetic
advantage is established. RDPRU/RDPID are diagnostic/system primitives, not
instructions to add to the inference loop. Retain existing exact library
memory operations until evidence supports replacing them.

## Validation and implementation sequence

1. Save the current accepted binary/hash, independent numerical oracles and
   private publication decision. Refresh per-host capability/PMU evidence.
2. Extend/test capability resolver, object ISA audits and the profiling layers
   needed by the chosen first experiment. Add no candidate default yet.
3. Build one independent candidate at a time. Test complete prerequisite removal,
   OS XSTATE disabled, unusual supported combinations (including AVX512-VNNI
   without AVX-VNNI), conservative unknown CPU policy, shape/layout incompatibility
   and fallback parity. Synthetic tests validate decisions, not hardware execution.
4. Run both-model release/sanitizer/guarded numerical contracts, all empty masks,
   rounding/FTZ/DAZ and full spectral/state/reset/PCM equivalence. Execute only
   genuinely supported ISA on hardware; tests cannot emulate absent hardware by
   setting feature bits. Keep the old AVX2/VEX negative ISA contracts.
5. Use the mandatory laboratory for a short preregistered discovery study,
   then independent confirmation. Both core classes, power profiles, continuous
   and paced/full-audio scopes remain separate. Use the supported profiling
   ladder in [BENCHMARK_LAB.md](BENCHMARK_LAB.md); retain skips/failures.
6. Report mean/sample SD, paired uncertainty, A/A precision, tails/deadlines,
   cycles/instructions/loads/branches and relevant sampling evidence. Measure
   full-graph effects incrementally against the accepted implementation, not
   against an obsolete baseline. Reject inconclusive additions from defaults.
7. Promote only qualified useful candidates; remove unsuccessful maintained
   branches/flags. Update architecture/build/backlog and memory/creation costs.
   Publication still waits for explicit release of the existing user hold.

## Primary references and local evidence

- [GCC x86 function attributes](https://gcc.gnu.org/onlinedocs/gcc/x86-Attributes.html)
  documents per-function targeting and vector-width preference, not a promise
  of a particular fastest width.
- [AMD IBS analysis guide](https://docs.amd.com/r/en-US/68658-uProf-getting-started-guide/Analyzing-Performance-Using-IBS-Data)
  describes fetch/execution and load-latency diagnostics.
- [AMD Zen 5 optimization guide](https://docs.amd.com/v/u/en-US/58455_1.00).
- Private local audit: `.local/cpu-audit-20261110/REPORT.md`, raw per-CPU CPUID,
  executed-instruction checks and `profiling-capabilities.json`. The latter
  records sysfs advertisement only, not successful event-open/sampling probes.
- Prior selected-fusion evidence: `.local/model8-vnni-20261110/RESULTS.md`,
  separate hardware profiles. This plan does not retroactively extend their scope.

## Completed first implementation batch (2026-11-10)

The common laboratory now implements and tests explicit advanced PMU plans,
including actual LBR, IBS Fetch/Op and load filters, shared L3/DF/UMC/energy,
kernel costs and an available syscall tracepoint. All four primary CPU/power
scopes completed their fixed profiling budget with verified restoration.
See [the portable record](../validation/cpu_optimization_20261110.json).

| Candidate | Implemented/tested result | Selection |
|---|---|---|
| Single-pass AVX2 gates | Exact, but large diagnostic whole-graph regression | Rejected |
| Single-pass EVEX256 gates | Extra registers removed a spill; no qualified incremental benefit | Rejected |
| Fully staged eight-row gates | Static code expansion and spills | Rejected before timing |
| Bounded staged EVEX gates | Independent qNaN payload oracle failed | Rejected before timing |
| EVEX256 K64, four rows, two 16-column projections | Exact guarded FP/integer/ISA checks; independent model8 continuous gains on both core classes | Private candidate; registered global qualification failed |
| Domain-aware capability/qops architecture | Independent feature combinations, OS XSTATE and fallback/domain tests pass | Private candidate coupled to qualification; no current ABI/default change |

The wider integer candidate retains the old FP epilogue, uses high YMM
registers without ZMM arithmetic, and requires F+VL+VNNI independently of
AVX-VNNI. Only model8 selected the new computational kernel; model2 guarded
dispatch/checking overhead. Unknown profiles retained the old kernels.
All registered confirmation contrasts, mean/sample SD, corrected intervals,
A/A precision and noninferiority results are retained. A/A failures in paced,
audio and model2 guard cells prevent promotion; positive diagnostic estimates
are not acceptance. No sample extensions or new maintained experiment flags.

Direct narrowing/CM byte permutations, matched ZMM packing, ordered FP helpers,
graph fusion and exact GRU surroundings remain future independent experiments;
they are not implemented, rejected or certified faster by this batch. The local
full report is `.local/cpu-optimization-20261110/RESULTS.md`. Publication remains
held, and the accepted runtime defaults are unchanged.


## Authorized short reconsideration (2026-11-11)

The user explicitly reopened previously rejected performance candidates and
requested prospective workload-specific criteria with a smaller study. Numerical
failures and large-regression gate variants were excluded. Historical decisions
remain immutable records; the new policy is described in BENCHMARK_LAB.md.

Four exact candidates were screened directly against accepted fusion: K64,
extra branch padding, EVEX256, and freshly rebuilt incremental refined/VNNI Q4.
K64/padding remain below useful size; no source or experiment switch is restored.
Q4 is promising in steady screening (+0.930%) but is not independently qualified
by this one-finalist budget. EVEX256 won screening, then independently qualified
randomized-layout Boost continuous model8 on fast (+1.628%) and compact (+1.128%)
cores, with model2 continuous noninferiority guards passing. The complete audio
scope still fails its mean/tail precision requirements; defaults remain unchanged.
Do not combine Q4/EVEX gains or claim their untested composition is beneficial.

The [portable record](../validation/reconsideration_20261111.json) retains all
320 processes, 106,496 observations, 48 independently checked intervals and
160 separate PMU jobs. Full report: `.local/reconsideration-20261111/RESULTS.md`.
The user publication hold remains in force. Existing broader future ISA research
is not implemented or certified by this bounded reconsideration.


## Future PR scope resolved (2026-11-11)

The previously pending independent Q4 follow-up is complete. It qualifies scoped
continuous Boost model8 benefit on both core classes, but not the full audio
scope. Q4 defaults remain OFF; no public option or runtime branch is added.
The EVEX audio cohort was not extended or recollected. K64/padding and failed
gates remain excluded. The [prepared scope](FUTURE_PR_SCOPE.md) includes accepted
model8 VNNI fusion, strict contracts/ISA parsing, reusable profiling/acceptance
and portable evidence. All requested local preparation is complete; publication
continues to wait for the existing PR merge and release of the user hold.


## Audio methodology implementation (2026-11-11)

The [versioned audio pilot](../validation/audio_lab_v2_20261111.json) implements
cadence warmup, buffered/native adapters, C timing, independent frequency/idle
selection, sidecar validation and reusable just entries. Buffered FFT/state/PCM
matches all 130 model/fixture cases; native DSP/reference/reset and FP-mode
contracts pass. One-host original-idle Boost observed lower paired SD, but
absolute noise remains material and shallow idle is not universally better.
No optimization default or old verdict changes. A future candidate study needs
its own budget/scope; this baseline-only pilot is not a candidate confirmation.
