#define _GNU_SOURCE
#include "audio_clock.h"
#include <time.h>
#include <errno.h>
#include <stddef.h>
#include <unistd.h>
#include <sys/wait.h>
#include <cpuid.h>
#include <sched.h>
#include <sys/prctl.h>
/* Permission belongs to this thread, process and single-CPU affinity contract.
   Never fork or silently prepare optional instructions inside a timed window. */
static _Thread_local pid_t prepared_pid;
static _Thread_local int prepared_cpu = -1;
static int pinned_cpu(void) {
    cpu_set_t mask;
    if (sched_getaffinity(0,sizeof(mask),&mask) || CPU_COUNT(&mask)!=1) return -1;
    int cpu=sched_getcpu();
    return cpu>=0 && cpu<CPU_SETSIZE && CPU_ISSET(cpu,&mask) ? cpu : -1;
}
static int counter_prepared(void) {
    return prepared_pid==getpid() && prepared_cpu>=0 && pinned_cpu()==prepared_cpu;
}
static uint64_t ns(clockid_t clock) {
    struct timespec t;
    if (clock_gettime(clock, &t)) return 0;
    return (uint64_t)t.tv_sec*1000000000u+(uint64_t)t.tv_nsec;
}
static uint64_t counter(unsigned selector) {
    unsigned lo,hi;
    __asm__ volatile("lfence\n\trdpru\n\tlfence":"=a"(lo),"=d"(hi):"c"(selector):"memory");
    return ((uint64_t)hi<<32)|lo;
}
int audio_counter_probe(void) {
    int cpu=pinned_cpu();
    if (cpu<0) return 0;
    if (counter_prepared()) return 1;
    prepared_pid=0;prepared_cpu=-1;
    unsigned a,b,c,d;
    if (__get_cpuid_max(0x80000000u,NULL)<0x80000008u) return 0;
    __cpuid(0x80000008u,a,b,c,d);
    if (!(b&(1u<<4))) return 0;
    /* CPUID alone cannot prove user-mode permission. The child executes no
       application/runtime code, and cannot affect the parent on SIGILL. */
    pid_t pid=fork();
    if (pid<0) return 0;
    if (!pid) {
        if(prctl(PR_SET_DUMPABLE,0,0,0,0))_exit(77);
        volatile uint64_t x=counter(0)^counter(1);(void)x;_exit(0);
    }
    int status;
    while (waitpid(pid,&status,0)<0) if (errno!=EINTR) return 0;
    if (!WIFEXITED(status)||WEXITSTATUS(status)!=0||pinned_cpu()!=cpu) return 0;
    prepared_pid=getpid();prepared_cpu=cpu;
    return 1;
}
static int sleep_until(uint64_t deadline) {
    struct timespec t={(time_t)(deadline/1000000000u),(long)(deadline%1000000000u)};
    int e;
    do {e=clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,NULL);} while(e==EINTR);
    return e;
}
int audio_measure(audio_callback callback,void *context,uint64_t warmup,
                  uint64_t calls,uint64_t period,int paced_warmup,int counters,
                  audio_observation *out) {
    if (!callback || (calls && !out) || (!calls && !warmup) || calls>65536 || warmup>4096 ||
        period<1000000 || period>100000000 || (paced_warmup!=0&&paced_warmup!=1) ||
        (counters!=0&&counters!=1)) return EINVAL;
    if(counters&&!counter_prepared())return ENOTSUP;
    /* Fault in every output record and clock/sleep code before warmup. */
    for(uint64_t i=0;i<calls;i++)out[i]=(audio_observation){0};
    (void)ns(CLOCK_MONOTONIC_RAW);(void)ns(CLOCK_MONOTONIC);
    uint64_t deadline=ns(CLOCK_MONOTONIC);
    if(!deadline)return EIO;
    int e=sleep_until(deadline);if(e)return e;
    for(uint64_t i=0;i<warmup+calls;i++) {
        if(i<warmup && !paced_warmup) {
            if(callback(context,i))return ECANCELED;
            continue;
        }
        if(i==warmup)deadline=ns(CLOCK_MONOTONIC)+period;
        e=sleep_until(deadline);if(e)return e;
        uint64_t start=ns(CLOCK_MONOTONIC);
        uint64_t m0=0,a0=0;
        if(counters){m0=counter(0);a0=counter(1);}
        uint64_t begin=ns(CLOCK_MONOTONIC_RAW);
        if(callback(context,i))return ECANCELED;
        uint64_t end=ns(CLOCK_MONOTONIC_RAW);
        uint64_t a1=0,m1=0;
        if(counters){a1=counter(1);m1=counter(0);}
        uint64_t finish=ns(CLOCK_MONOTONIC);
        if(!begin||end<begin||finish<start)return EIO;
        if(i>=warmup)out[i-warmup]=(audio_observation){deadline,start,finish,end-begin,a1-a0,m1-m0};
        deadline+=period;
        if(finish>deadline)deadline=finish;
    }
    return 0;
}
