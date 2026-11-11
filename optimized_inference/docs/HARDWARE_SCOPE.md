# Hardware acceptance scope

The user fixed the complete hardware inventory on2026-11-11:

| Machine | Required applicable coverage |
|---|---|
| Current local PC | Both models, usable AVX2 and VNNI paths, relevant fast/compact core classes and declared power/workload conditions |
| Remote Intel Core i7-7700T | Both models on the available AVX2 path; portability/numerical/ABI checks and explicitly supported diagnostics |

No additional processor will be available. A second VNNI machine, different
microarchitecture or broader CPU sample is not an acceptance, completion,
release-readiness or PR-readiness requirement. Do not create hardware-access
tasks or wait for another machine. Private backlog V04 is closed as not required
by the user's scope decision; no unperformed test is marked passed.

Previous mentions of unavailable additional hardware describe historical
coverage only and do not create pending work. This policy supersedes them.
Existing exact-artifact evidence can be reused with verified provenance; the
scope change itself requires no new timing or changes to runtime defaults.

Capability detection, OS XSTATE checks, legal instruction use and safe fallbacks
remain required. This is a validation inventory, not a vendor/model whitelist
to hardcode into runtime dispatch. Never invent VNNI support on the i7-7700T.
When a target lacks the laboratory's required isolation/topology, label its
timings as diagnostics rather than strict isolated performance evidence; that
does not create a requirement for replacement hardware.

The deployment matrix is unchanged: selected CM for both models on AVX2/VNNI,
existing AVX2 four-row quantization, existing model2 fusion and the accepted
eligible model8 VNNI batch/pair fusion. Refined quantization, EVEX and other
rejected prototypes stay excluded because of their measured qualification
outcomes, independently of the removed hardware requirement.

Physical-device/service-load rollout checks, unavailable historical inputs and
the publication hold are separate matters. This hardware decision does not
silently mark them tested or authorize deployment/publication.
