#ifndef DPDFNET_XDNA2_SPECTRAL_H
#define DPDFNET_XDNA2_SPECTRAL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { DPDFNET_XDNA2_SPECTRAL_WORDS = 962 };

uint32_t dpdfnet_xdna2_spectral_abi(void);
int dpdfnet_xdna2_spectral_validate(const char *manifest);
void *dpdfnet_xdna2_spectral_open(const char *manifest);
// One 48 kHz DPDFNet hop. DC through Nyquist, interleaved real/imaginary FP32.
// The caller owns both arrays. The selected engine owns recurrent state.
int dpdfnet_xdna2_spectral_step(void *session, const float *in, float *out);
int dpdfnet_xdna2_spectral_reset(void *session);
// Open, inference, reset and close run on the same thread and process.
// An uncertain device submission holds the worker until external termination.
void dpdfnet_xdna2_spectral_close(void *session);

#ifdef __cplusplus
}
#endif
#endif
