# Reproducible local CPU laboratory. All mutations are reversible and journaled.
set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments

# Compile the common measurement/probe executable before isolating CPUs.
bench-tools:
    mkdir -p .local/bench-lab
    /usr/bin/gcc -O3 -Wall -Wextra -Werror -ffp-contract=off -mavx2 -mfma -Ioptimized_inference/include optimized_inference/tools/bench_lab/worker.c -ldl -lm -o .local/bench-lab/worker.tmp
    mv .local/bench-lab/worker.tmp .local/bench-lab/worker

# Reserve the discovered L3 domain and verify actual non-boost frequency.
bench-prepare cpu="3" frequency_khz="auto" ttl_seconds="1800" power_profile="steady" idle_policy="auto": bench-tools
    sudo -n python3 optimized_inference/tools/bench_lab/controller.py prepare --cpu "$1" --frequency-khz "$2" --ttl "$3" --power-profile "$4" --idle-policy "$5" --probe "$(pwd)/.local/bench-lab/worker" | tee .local/bench-lab/prepare.json

# Refresh readiness, including three hardware-counter frequency probes.
bench-ready:
    sudo -n python3 optimized_inference/tools/bench_lab/controller.py ready | tee .local/bench-lab/ready.json

# Inspect current preparation/restoration state without another workload.
bench-status:
    sudo -n python3 optimized_inference/tools/bench_lab/controller.py status

# Run an absolute executable as the ordinary user on the reserved worker CPU.
bench-exec +command:
    sudo -n python3 optimized_inference/tools/bench_lab/controller.py exec -- "$@"

# Restore and independently read back every saved setting. Safe to repeat.
bench-restore:
    sudo -n python3 optimized_inference/tools/bench_lab/controller.py restore | tee .local/bench-lab/restore.json

# Read-only independent teardown audit, accounting for later irqbalance updates.
bench-audit:
    sudo -n python3 optimized_inference/tools/bench_lab/controller.py audit

# Behavioral tests do not modify the machine or require root.
bench-test:
    python3 optimized_inference/tests/bench_lab_test.py
    python3 optimized_inference/tests/pmu_test.py
    python3 optimized_inference/tests/telemetry_test.py
    python3 optimized_inference/tests/acceptance_test.py

# Fixed-size A/A control; refuses to reuse an existing output directory.
bench-aa manifest output:
    python3 optimized_inference/tools/bench_lab/study.py aa "$1" "$2"

# Comparison requires the unchanged-binary A/A report.
bench-compare manifest output aa_report:
    python3 optimized_inference/tools/bench_lab/study.py compare "$1" "$2" --aa "$3"

# Separate hardware counters and sampling; never used as latency results.
bench-profile manifest output:
    python3 optimized_inference/tools/bench_lab/study.py profile "$1" "$2"

# Isolated profile-only lifecycle; output durations are never speed evidence.
bench-profile-session manifest output: bench-tools
    python3 optimized_inference/tools/bench_lab/study.py profile-session "$1" "$2"

# Recommended complete workflow: prepare, A/A, compare, profiles, finally restore.
bench-session manifest output: bench-tools
    python3 optimized_inference/tools/bench_lab/study.py session "$1" "$2"

# Continue after a fully collected A/A phase; never repeat collected samples.
bench-resume manifest output: bench-tools
    python3 optimized_inference/tools/bench_lab/study.py resume "$1" "$2"

# Build the versioned C audio timer before any isolation or timing session.
bench-audio-tools:
    mkdir -p .local/bench-lab
    /usr/bin/gcc -std=c11 -O2 -Wall -Wextra -Werror -fPIC -shared optimized_inference/tools/bench_lab/audio_clock.c -o .local/bench-lab/libaudio_clock.so.tmp
    mv .local/bench-lab/libaudio_clock.so.tmp .local/bench-lab/libaudio_clock.so

# Optional offline real-DSP adapter; pins the external HushMic source provenance.
bench-audio-native hushmic_root output: bench-audio-tools
    python3 optimized_inference/tools/bench_lab/build_audio_native.py --hushmic-root "$1" --output "$2" --clock-dir "$(pwd)/.local/bench-lab"

# Baseline-only A/A lifecycle, with full readiness/watchdog/finally restoration.
bench-aa-session manifest output: bench-tools
    python3 optimized_inference/tools/bench_lab/study.py aa-session "$1" "$2"

# Numerical and timing-helper contracts for the versioned audio measurement path.
bench-audio-test library="optimized_inference/build/libdpdfnet.so": bench-audio-tools
    test -f "$1"
    DPDF_AUDIO_REQUIRE_NUMERICS=1 DPDF_AUDIO_TEST_LIBRARY="$1" /usr/bin/python3 optimized_inference/tests/audio_lab_test.py

# Cross frequency/idle policies using one frozen binary; report A/A precision.
bench-audio-pilot config output: bench-tools bench-audio-tools
    /usr/bin/python3 optimized_inference/tools/bench_lab/audio_pilot.py "$1" "$2"
    /usr/bin/python3 optimized_inference/tools/bench_lab/audio_report.py "$2"

# Render a completed pilot; no isolation, tuning or extra measurements.
bench-audio-report output:
    /usr/bin/python3 optimized_inference/tools/bench_lab/audio_report.py "$1"

# Baseline-only idle/scheduler/IRQ traces plus read-only package diagnostics.
bench-audio-noise config output: bench-tools bench-audio-tools
    /usr/bin/python3 optimized_inference/tools/bench_lab/audio_noise.py "$1" "$2"

# Re-render a completed diagnostic cohort without new measurements or tuning.
bench-audio-noise-report output:
    /usr/bin/python3 optimized_inference/tools/bench_lab/audio_noise_report.py "$1"
