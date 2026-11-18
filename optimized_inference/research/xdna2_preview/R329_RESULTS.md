# R329 — Paired boost timing for fully resident GRU coefficients

The streamed R316 and fully resident six-BO R328 arms use the same BF16 arithmetic,
fixtures, PCM/frame layout and saved state. Both issue two commands per frame.
The resident arm requests 2,058,240 fewer GRU weight bytes from DDR per frame.
The test uses CPU 3 with boost and shallow idle and parks its SMT sibling.
Four A/A and four A/B pairs per model and cadence match the same PCM input.
Positive paired gains favor residency. Intervals adjust over the sixteen endpoints.

| Cell | Streamed / resident callback, mean ± SD ms | Body gain and CI | Caller CPU gain and CI |
| --- | ---: | ---: | ---: |
| m2/continuous | 2.9103 ± 0.0198 / 2.9000 ± 0.0205 | +0.355% [-0.518%, +1.221%] | +0.387% [-0.280%, +1.049%] |
| m2/paced10ms | 2.9496 ± 0.0514 / 2.9358 ± 0.0442 | +0.467% [-1.474%, +2.371%] | +0.301% [-2.970%, +3.468%] |
| m8/continuous | 6.7368 ± 0.0266 / 6.7443 ± 0.0314 | -0.111% [-0.489%, +0.265%] | +0.280% [-2.503%, +2.987%] |
| m8/paced10ms | 6.7646 ± 0.0390 / 6.7625 ± 0.0668 | +0.031% [-0.434%, +0.493%] | +0.418% [-1.156%, +1.967%] |

| Cell | p99 gain and CI | Maximum gain and CI | Paired body SD, ms |
| --- | ---: | ---: | ---: |
| m2/continuous | +0.399% [-1.932%, +2.676%] | -1.839% [-55.366%, +33.247%] | 0.00578 |
| m2/paced10ms | +0.433% [-3.721%, +4.420%] | +5.257% [-14.504%, +21.608%] | 0.01296 |
| m8/continuous | -0.684% [-4.444%, +2.941%] | -1.155% [-17.872%, +13.192%] | 0.00580 |
| m8/paced10ms | -0.897% [-8.269%, +5.973%] | -6.896% [-53.421%, +25.520%] | 0.00715 |

m2/paced10ms records 0 streamed and 0 resident deadline misses including transition.
m8/paced10ms records 0 streamed and 0 resident deadline misses including transition.

Combined caller CPU, mean, tails and deadline acceptance passes in 0 of four cells.
64,768 submitted and completed commands reconcile across 64 owners. There are 31,360
sustained callback observations including the A/A pairs. The six-BO resident arm performs no preload
command. Exact PCM, saved state, A/A and laboratory restoration pass. Serial and parallel readers agree.

Cold startup, non-boost operation, DMA or driver event attribution, and supported energy are
separate endpoints. The BF16 warmed results do not qualify another numerical profile.
