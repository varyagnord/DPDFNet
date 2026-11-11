#ifndef DPDF_AUDIO_CLOCK_H
#define DPDF_AUDIO_CLOCK_H
#include <stdint.h>
typedef int (*audio_callback)(void *, uint64_t);
typedef struct {
    uint64_t scheduled_ns, start_ns, finish_ns, body_ns;
    uint64_t aperf, mperf;
} audio_observation;
/* Baseline Linux timing helper; no model code or process-global tuning. */
int audio_measure(audio_callback, void *, uint64_t warmup, uint64_t calls,
                  uint64_t period_ns, int paced_warmup, int counters,
                  audio_observation *out);
/* Call before warmup on a thread pinned to exactly one CPU. Successful
   preparation is thread/process/CPU-bound; audio_measure never probes/forks. */
int audio_counter_probe(void);
#endif
