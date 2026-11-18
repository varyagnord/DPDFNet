# R341 — Matched unprofiled latency of direct intra-projection weights

R339 and R340 use the same three model-2 precision profiles and native
PCM callback with Boost and original idle on the isolated physical core.
The first 48 process owners are R339/R339 A/A controls. The next 48
balance the two binary orders and both held recordings within six
model-profile and cadence cells. The callback times exclude profiling.
Each process supplies 426 warm steady-window frames after its
warmup and transition period. All PCM and final CPU and NN state
endpoints match the archived same-profile witnesses.

Positive gains favor R340. Intervals are paired independent-owner
simultaneous intervals across 18 endpoints. The body SD is the median
within-owner sample SD. Deadline counts include transition frames.

| Profile / mode | R339 / R340 mean, ms | R339 / R340 body SD, ms | Mean gain [CI], % | R339 / R340 deadline misses | Accepted gain |
| --- | ---: | ---: | ---: | ---: | --- |
| m2-erb-xint8/continuous | 2.9245 / 2.9324 | 0.0235 / 0.0229 | -0.269 [-2.089, +1.519] | — | unresolved |
| m2-erb-xint8/paced10ms | 2.9903 / 3.3165 | 0.0508 / 0.2694 | -10.211 [-98.394, +38.777] | 0 / 0 | unresolved |
| m2-df-bfp16-k64/continuous | 2.9247 / 2.9359 | 0.0229 / 0.0268 | -0.382 [-1.533, +0.755] | — | unresolved |
| m2-df-bfp16-k64/paced10ms | 3.1109 / 3.1750 | 0.0381 / 0.1991 | -1.905 [-118.163, +52.400] | 0 / 0 | unresolved |
| m2-df-bfp16-k128/continuous | 2.9187 / 2.9283 | 0.0267 / 0.0188 | -0.329 [-1.516, +0.845] | — | unresolved |
| m2-df-bfp16-k128/paced10ms | 3.0408 / 3.5969 | 0.1358 / 0.4042 | -16.644 [-139.284, +43.139] | 0 / 0 | unresolved |

Useful gains pass in 0/6 cells. Combined noninferiority passes
in 0/6 cells. Practical A/A order drift resolves in 0/6 cells.
The full data include 96 release owners, 40,896
retained timing observations and 145,728 device commands.

The readback retains individual owners, hot CPU costs, original
schedule response tails, and variation. The restored lab verifies
exact kernel masks, accelerator default mode and zero remaining contexts.
This comparison covers the two NPU layouts at the registered Boost
policy. Desktop audio host integration and device energy require their
own evidence.
