"""Versioned, buffered reference adapter; the original pipeline stays unchanged."""
import numpy as np
from audio_pipeline import AudioPipeline
from dpdfnet import FP

class BufferedAudioPipeline(AudioPipeline):
    def __init__(self,model,audio):
        super().__init__(model,audio)
        self.windowed=np.empty(960,dtype=np.float32)
        self.spectrum=np.empty((481,2),dtype=np.float32)
        self.valid=np.empty((481,2),dtype=np.bool_)
        probe=np.fft.rfft(np.zeros(960,dtype=np.float32))
        self.fft=np.empty_like(probe)
        self.complex_product=np.empty(481,dtype=np.complex64)
        self.complex_sum=np.empty(481,dtype=np.complex64)
        self.inverse=np.empty_like(np.fft.irfft(probe,n=960))
        self.frame=np.empty(960,dtype=np.float32)
        self.head=self.overlap[:480];self.tail=self.overlap[480:]
        self.real=self.spectrum[:,0];self.imag=self.spectrum[:,1]
        self.out_real=model.output[:,0];self.out_imag=model.output[:,1]
        self._state=model.state;self._output=model.output;self._handle=model.handle
        self._pointers=[a.ctypes.data_as(FP) for a in [self.spectrum,model.state,model.output]]
        # Validate the required out= support before any privileged preparation.
        self.windowed.fill(0)
        np.fft.rfft(self.windowed,out=self.fft)
        self.complex_sum.fill(0)
        np.fft.irfft(self.complex_sum,n=960,out=self.inverse)

    def process(self,index):
        if not self.model.handle or self.model.handle!=self._handle or self.model.state is not self._state or self.model.output is not self._output:
            raise RuntimeError('Model bindings changed or closed')
        i=index%self.frames
        np.multiply(self.padded[i*480:i*480+960],self.window,out=self.windowed)
        np.fft.rfft(self.windowed,out=self.fft)
        self.real[:]=self.fft.real;self.imag[:]=self.fft.imag
        self.last_input=self.spectrum
        np.isfinite(self.spectrum,out=self.valid)
        if not self.valid.all():raise ValueError('Expected finite spectrum')
        a,s,y=self._pointers
        if self.model.lib.dpdfnet_process(self._handle,a,s,y,s):raise RuntimeError('Inference failed')
        # Retain multiplication then addition, including the original complex
        # operand order; direct real/imag assignment has different edge cases.
        np.multiply(self.out_imag,1j,out=self.complex_product)
        np.add(self.out_real,self.complex_product,out=self.complex_sum)
        np.fft.irfft(self.complex_sum,n=960,out=self.inverse)
        np.copyto(self.frame,self.inverse,casting='unsafe')
        np.multiply(self.frame,self.window,out=self.frame)
        self.head[:]=self.tail;self.tail.fill(0)
        np.add(self.overlap,self.frame,out=self.overlap)
        return self.head
