from base64 import b64encode
import copy
from datetime import datetime
import getopt
import io
from io import BytesIO
import logging
import os
import subprocess
import sys

# standard numeric/scientific libraries
import numpy as np
import pandas as pd
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 

#internal libraries which may or may not get used

import commpy_filters

import fdls
from lddutils import *

logging.getLogger(__name__).setLevel(logging.DEBUG)

def calclinelen(SP, mult, mhz):
    if type(mhz) == str:
        mhz = SP[mhz]
        
    return int(np.round(SP['line_period'] * mhz * mult)) 

# These are invariant parameters for PAL and NTSC
SysParams_NTSC = {
    'fsc_mhz': (315.0 / 88.0),
    'pilot_mhz': (315.0 / 88.0),
    'frame_lines': 525,
    'field_lines': (263, 262),

    'ire0': 8100000,
    'hz_ire': 1700000 / 140.0,
    
    'vsync_ire': -40,

    # most NTSC disks have analog audio, except CD-V and a few Panasonic demos
    'analog_audio': True,
    # From the spec - audio frequencies are multiples of the (color) line rate
    'audio_lfreq': (1000000*315/88/227.5) * 146.25,
    'audio_rfreq': (1000000*315/88/227.5) * 178.75,

    'colorBurstUS': (5.3, 7.8),
    'activeVideoUS': (9.45, 63.555-1.5),

    # In NTSC framing, the distances between the first/last eq pulses and the 
    # corresponding next lines are different.
    'firstField1H': (True, False),

    'numPulses': 6,
    'hsyncPulseUS': 4.7,
    'eqPulseUS': 2.3,
    'vsyncPulseUS': 27.1,
}

# In color NTSC, the line period was changed from 63.5 to 227.5 color cycles,
# which works out to 63.555(with a bar on top) usec
SysParams_NTSC['line_period'] = 1/(SysParams_NTSC['fsc_mhz']/227.5)
SysParams_NTSC['activeVideoUS'] = (9.45, SysParams_NTSC['line_period'] - 1.5)

SysParams_NTSC['FPS'] = 1000000/ (525 * SysParams_NTSC['line_period'])

SysParams_NTSC['outlinelen'] = calclinelen(SysParams_NTSC, 4, 'fsc_mhz')
SysParams_NTSC['outfreq'] = 4 * SysParams_NTSC['fsc_mhz']

SysParams_PAL = {
    'FPS': 25,
    
    # from wikipedia: 283.75 × 15625 Hz + 25 Hz = 4.43361875 MHz
    'fsc_mhz': ((1/64) * 283.75) + (25/1000000),
    'pilot_mhz': 3.75,
    'frame_lines': 625,
    'field_lines': (312, 313),
    'line_period': 64,

    'ire0': 7100000,
    'hz_ire': 800000 / 100.0,

    # only early PAL disks have analog audio
    'analog_audio': True,
    # From the spec - audio frequencies are multiples of the (colour) line rate
    'audio_lfreq': (1000000/64) * 43.75,
    'audio_rfreq': (1000000/64) * 68.25,

    'colorBurstUS': (5.6, 7.85),
    'activeVideoUS': (10.5, 64-1.5),

    # In PAL, the first field's line sync<->first/last EQ pulse are both .5H
    'firstField1H': (False, False),

    'numPulses': 5,
    'hsyncPulseUS': 4.7,
    'eqPulseUS': 2.35,
    'vsyncPulseUS': 27.3,
}

SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')
SysParams_PAL['outfreq'] = 4 * SysParams_PAL['fsc_mhz']

SysParams_PAL['vsync_ire'] = -.3 * (100 / .7)

# RFParams are tunable

RFParams_NTSC = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 350000,
    'audio_notchorder': 2,

    'video_deemp': (120*.32, 320*.32),

    # This BPF is similar but not *quite* identical to what Pioneer did
    'video_bpf': [3400000, 13800000],
    'video_bpf_order': 4,

    # This can easily be pushed up to 4.5mhz or even a bit higher. 
    # A sharp 4.8-5.0 is probably the maximum before the audio carriers bleed into 0IRE.
    'video_lpf_freq': 4500000,   # in mhz
    'video_lpf_order': 6, # butterworth filter order

    # MTF filter
    'MTF_basemult': .4, # general ** level of the MTF filter for frame 0.
    'MTF_poledist': .9,
    'MTF_freq': 12.2, # in mhz
}

RFParams_PAL = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 200000,
    'audio_notchorder': 2,

    'video_deemp': (100*.30, 400*.30),

    # XXX: guessing here!
    'video_bpf': (2700000, 13500000),
    'video_bpf_order': 1,

    'video_lpf_freq': 4800000,
    'video_lpf_order': 7,

    # MTF filter
    'MTF_basemult': 1.0,  # general ** level of the MTF filter for frame 0.
    'MTF_poledist': .70,
    'MTF_freq': 10,
}

class RFDecode:
    def __init__(self, inputfreq = 40, system = 'NTSC', blocklen_ = 16384, decode_digital_audio = False, decode_analog_audio = True, have_analog_audio = True, mtf_mult = 1.0, mtf_offset = 0):
        self.blocklen = blocklen_
        self.blockcut = 1024 # ???
        self.system = system
        
        freq = inputfreq
        self.freq = freq
        self.freq_half = freq / 2
        self.freq_hz = self.freq * 1000000
        self.freq_hz_half = self.freq * 1000000 / 2
        
        self.mtf_mult = mtf_mult
        self.mtf_offset = mtf_offset
        
        if system == 'NTSC':
            self.SysParams = copy.deepcopy(SysParams_NTSC)
            self.DecoderParams = copy.deepcopy(RFParams_NTSC)
        elif system == 'PAL':
            self.SysParams = copy.deepcopy(SysParams_PAL)
            self.DecoderParams = copy.deepcopy(RFParams_PAL)

        linelen = self.freq_hz/(1000000.0/self.SysParams['line_period'])
        self.linelen = int(np.round(linelen))
            
        self.decode_digital_audio = decode_digital_audio
        self.decode_analog_audio = decode_analog_audio

        self.computefilters()    

    def computefilters(self):
        self.computevideofilters()

        if self.decode_analog_audio: 
            self.computeaudiofilters()

        if self.decode_digital_audio:
            self.computeefmfilter()

        self.computedelays()
        self.blockcut_end = self.Filters['F05_offset']

    def computeefmfilter(self):
        ''' same for both PAL and NTSC LD's '''

        # from Simon's dev work.  I haven't replicated this yet.
        efmFilter_b = [0.002811997668622127, 0.004557434177095733, 0.005518081763120638, 0.006175434988371297,
                0.007079542302379131, 0.007762746564588261, 0.007195457153986951, 0.004856513521712550,
                830.5207151564147810E-6, -0.004778562707971237, -0.011982337787676704, -0.020620652183251653,
            -0.030313333572191556, -0.040603187005666612, -0.050923073987327538, -0.060516949563439962,
            -0.068546464145567254, -0.074232214244951744, -0.076886606768788085, -0.075966051373979687,
            -0.071190271468117655, -0.062596043962852732, -0.050510748183213161, -0.035543389044287388,
            -0.018571164687106789, -653.7572477720859750E-6, 0.017076103040008714, 0.033491741568629191,
                0.047560393829158804, 0.058451726209266315, 0.065610957042443047, 0.068787227432726056,
                0.068052927749701272, 0.063800948413328271, 0.056691533146975850, 0.047573385532196255,
                0.037405276759632830, 0.027164400458192961, 0.017743654186943611, 0.009870181642090168,
                0.004052704260208225, 544.6177383273721940E-6, -667.1955887800581880E-6, 165.1444186576358670E-6,
                0.002601820774369020, 0.006075778653150664, 0.009965935705131752, 0.013676514558850801,
                0.016702483466449127, 0.018675612904669636, 0.019395327506222131, 0.018837755091170524,
                0.017137913326564228, 0.014554762572554125, 0.011427836596406824, 0.008126164613403961,
                0.004996232601002520, 0.002320620946358973, 290.5097959689243230E-6, -0.001009070788039298,
                -0.001598148724027520, -0.001584492210927387, -0.001136622115179061, -452.5692444180374420E-6,
                273.0780338995041350E-6, 878.5749907962782570E-6, 0.001255201534195653, 0.001356950513019374,
                0.001200086984625413, 852.4978004878322510E-6, 415.1503402529320400E-6]

        # the above data is reversed
        efmFilter_b.reverse()
        self.Filters['Fefm'] = filtfft((efmFilter_b, [1.0]), self.blocklen)

        # ISI filter
        # similar to original: Fisi = commpy_filters.rcosfilter(81, .75, 1/4400000, 40000000)
        # enhanced version:
        #Fisi = commpy_filters.rcosfilter(221, 0.08, 1/4321800, 40000000)
        Fisi = commpy_filters.rcosfilter(221, 0.5, 1/4321800, 40000000)
        self.Filters['Fefm'] *= filtfft((Fisi[1], [1.0]), self.blocklen)

    def computevideofilters(self):
        self.Filters = {}
        
        # Use some shorthand to compact the code.
        SF = self.Filters
        SP = self.SysParams
        DP = self.DecoderParams
        
        # compute the pole locations symmetric to freq_half (i.e. 12.2 and 27.8)
        MTF_polef_lo = DP['MTF_freq']/self.freq_half
        MTF_polef_hi = (self.freq_half + (self.freq_half - DP['MTF_freq']))/self.freq_half

        MTF = sps.zpk2tf([], [polar2z(DP['MTF_poledist'],np.pi*MTF_polef_lo), polar2z(DP['MTF_poledist'],np.pi*MTF_polef_hi)], 1)
        SF['MTF'] = filtfft(MTF, self.blocklen)

        SF['hilbert'] = np.fft.fft(hilbert_filter, self.blocklen)
        
        filt_rfvideo = sps.butter(DP['video_bpf_order'], [DP['video_bpf'][0]/self.freq_hz_half, DP['video_bpf'][1]/self.freq_hz_half], btype='bandpass')
        SF['RFVideo'] = filtfft(filt_rfvideo, self.blocklen)

        if SP['analog_audio']: 
            cut_left = sps.butter(DP['audio_notchorder'], [(SP['audio_lfreq'] - DP['audio_notchwidth'])/self.freq_hz_half, (SP['audio_lfreq'] + DP['audio_notchwidth'])/self.freq_hz_half], btype='bandstop')
            SF['Fcutl'] = filtfft(cut_left, self.blocklen)
            cut_right = sps.butter(DP['audio_notchorder'], [(SP['audio_rfreq'] - DP['audio_notchwidth'])/self.freq_hz_half, (SP['audio_rfreq'] + DP['audio_notchwidth'])/self.freq_hz_half], btype='bandstop')
            SF['Fcutr'] = filtfft(cut_right, self.blocklen)
        
            SF['RFVideo'] *= (SF['Fcutl'] * SF['Fcutr'])
            
        SF['RFVideo'] *= SF['hilbert']
        
        video_lpf = sps.butter(DP['video_lpf_order'], DP['video_lpf_freq']/self.freq_hz_half, 'low')
        SF['Fvideo_lpf'] = filtfft(video_lpf, self.blocklen)

        # The deemphasis filter.  This math is probably still quite wrong, but with the right values it works
        deemp0, deemp1 = DP['video_deemp']
        [tf_b, tf_a] = sps.zpk2tf(-deemp1*(10**-10), -deemp0*(10**-10), deemp0 / deemp1)
        SF['Fdeemp'] = filtfft(sps.bilinear(tf_b, tf_a, 1.0/self.freq_hz_half), self.blocklen)

        # The direct opposite of the above, used in test signal generation
        [tf_b, tf_a] = sps.zpk2tf(-deemp0*(10**-10), -deemp1*(10**-10), deemp1 / deemp0)
        SF['Femp'] = filtfft(sps.bilinear(tf_b, tf_a, 1.0/self.freq_hz_half), self.blocklen)
        
        # Post processing:  lowpass filter + deemp
        SF['FVideo'] = SF['Fvideo_lpf'] * SF['Fdeemp'] 
    
        # additional filters:  0.5mhz and color burst
        # Using an FIR filter here to get a known delay
        F0_5 = sps.firwin(65, [0.5/self.freq_half], pass_zero=True)
        SF['F05_offset'] = 32
        SF['F05'] = filtfft((F0_5, [1.0]), self.blocklen)
        SF['FVideo05'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['F05']

        SF['Fburst'] = filtfft(sps.butter(1, [(SP['fsc_mhz']-.1)/self.freq_half, (SP['fsc_mhz']+.1)/self.freq_half], btype='bandpass'), self.blocklen) 
        SF['FVideoBurst'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['Fburst']

        if self.system == 'PAL':
            SF['Fpilot'] = filtfft(sps.butter(1, [3.7/self.freq_half, 3.8/self.freq_half], btype='bandpass'), self.blocklen) 
            SF['FVideoPilot'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['Fpilot']
        
        # emperical work determined that a single-pole low frequency filter effectively 
        # detects the end of a (regular) sync pulse when binary level detection is used. TODO: test with PAL
        f = sps.butter(1, 0.05/self.freq_half, btype='low')
        SF['FPsync'] = filtfft(f, self.blocklen)

    # frequency domain slicers.  first and second stages use different ones...
    def audio_fdslice(self, freqdomain):
        return np.concatenate([freqdomain[self.Filters['audio_fdslice_lo']], freqdomain[self.Filters['audio_fdslice_hi']]])

    def audio_fdslice2(self, freqdomain):
        return np.concatenate([freqdomain[self.Filters['audio_fdslice2_lo']], freqdomain[self.Filters['audio_fdslice2_hi']]])
    
    def computeaudiofilters(self):
        SF = self.Filters
        SP = self.SysParams

        # first stage audio filters
        if self.freq >= 32:
            audio_fdiv1 = 32 # this is good for 40mhz - 16 should be ideal for 28mhz
        else:
            audio_fdiv1 = 16
            
        afft_halfwidth = self.blocklen // (audio_fdiv1 * 2)
        arf_freq = self.freq_hz / (audio_fdiv1 / 2)
        SF['freq_arf'] = arf_freq
        SF['audio_fdiv1'] = audio_fdiv1

        SP['audio_cfreq'] = (SP['audio_rfreq'] + SP['audio_lfreq']) // 2
        afft_center = int((SP['audio_cfreq'] / self.freq_hz) * (self.blocklen))

        # beginning and end symmetrical frequency domain slices.  combine to make a cut-down sampling
        afft_start = int(afft_center-afft_halfwidth)
        afft_end = int(afft_center+afft_halfwidth)

        # slice areas for reduced FFT audio demodulation filters
        SF['audio_fdslice_lo'] = slice(afft_start, afft_end)
        SF['audio_fdslice_hi'] = slice(self.blocklen-afft_end, self.blocklen-afft_start)

        # compute the base frequency of the cut audio range
        SF['audio_lowfreq'] = SP['audio_cfreq']-(self.freq_hz/(2*SF['audio_fdiv1']))

        apass = 150000 # audio RF bandpass.  150khz is the maximum transient.
        afilt_len = 800 # good for 150khz apass

        afilt_left = filtfft([sps.firwin(afilt_len, [(SP['audio_lfreq']-apass)/self.freq_hz_half, (SP['audio_lfreq']+apass)/self.freq_hz_half], pass_zero=False), 1.0], self.blocklen)
        SF['audio_lfilt'] = self.audio_fdslice(afilt_left * SF['hilbert']) 
        afilt_right = filtfft([sps.firwin(afilt_len, [(SP['audio_rfreq']-apass)/self.freq_hz_half, (SP['audio_rfreq']+apass)/self.freq_hz_half], pass_zero=False), 1.0], self.blocklen)
        SF['audio_rfilt'] = self.audio_fdslice(afilt_right * SF['hilbert'])

        # second stage audio filters (decimates further, and applies audio LPF)
        audio_fdiv2 = 4
        SF['audio_fdiv2'] = audio_fdiv2
        SF['audio_fdiv'] = audio_fdiv1 * audio_fdiv2
        SF['freq_aud2'] = SF['freq_arf'] / audio_fdiv2

        # slice areas for reduced FFT audio filters
        SF['audio_fdslice2_lo'] = slice(0, self.blocklen//(audio_fdiv2*2))
        SF['audio_fdslice2_hi'] = slice(self.blocklen-self.blocklen//(audio_fdiv2*2), self.blocklen)

        SF['audio_lpf2'] = filtfft([sps.firwin(65, [21000/(SF['freq_aud2']/2)]), [1.0]], self.blocklen // (SF['audio_fdiv2'] * 1))

        # convert 75usec into the exact -3dB frequency
        d75freq = 1000000/(2*pi*75)

        # I was overthinking deemphasis for a while.  For audio it turns out a straight
        # 1-pole butterworth does a good job.
        adeemp_b, adeemp_a = sps.butter(1, [d75freq/(SF['freq_aud2']/2)], btype='lowpass')
        SF['audio_deemp2'] = filtfft([adeemp_b, adeemp_a],  self.blocklen // SF['audio_fdiv2'])
        
    def iretohz(self, ire):
        return self.SysParams['ire0'] + (self.SysParams['hz_ire'] * ire)

    def hztoire(self, hz):
        return (hz - self.SysParams['ire0']) / self.SysParams['hz_ire']
    
    def demodblock(self, data, mtf_level = 0):
        rv_efm = None

        mtf_level *= self.mtf_mult
        mtf_level *= self.DecoderParams['MTF_basemult']
        mtf_level += self.mtf_offset
            
        indata_fft = np.fft.fft(data[:self.blocklen])
        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        if mtf_level != 0:
            indata_fft_filt *= self.Filters['MTF'] ** mtf_level

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real
        
        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        out_videoburst = np.fft.ifft(demod_fft * self.Filters['FVideoBurst']).real
        
        # NTSC: filtering for vsync pulses from -55 to -25ire seems to work well even on rotted disks
        output_sync = inrange(out_video05, self.iretohz(-55), self.iretohz(-25))
        # Perform FFT convolution of above filter
        output_syncf = np.fft.ifft(np.fft.fft(output_sync) * self.Filters['FPsync']).real

        if self.system == 'PAL':
            out_videopilot = np.fft.ifft(demod_fft * self.Filters['FVideoPilot']).real
            rv_video = np.rec.array([out_video, demod, out_video05, output_syncf, out_videoburst, out_videopilot], names=['demod', 'demod_raw', 'demod_05', 'demod_sync', 'demod_burst', 'demod_pilot'])
        else:
            rv_video = np.rec.array([out_video, demod, out_video05, output_syncf, out_videoburst], names=['demod', 'demod_raw', 'demod_05', 'demod_sync', 'demod_burst'])

        if self.decode_digital_audio == True:
            rv_efm = np.fft.ifft(indata_fft * self.Filters['Fefm'])

        if self.decode_analog_audio == False:
            return rv_video, None, rv_efm

        # Audio phase 1
        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_lfilt'])
        audio_left = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_rfilt'])
        audio_right = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        rv_audio = np.rec.array([audio_left, audio_right], names=['audio_left', 'audio_right'])

        return rv_video, rv_audio, rv_efm
    
    # Second phase audio filtering.  This works on a whole field's samples, since 
    # the frequency is reduced by 16/32x.

    def runfilter_audio_phase2(self, frame_audio, start):
        left = frame_audio['audio_left'][start:start+self.blocklen].copy() 
        left_fft = np.fft.fft(left)
        #logging.info(self.audio_fdslice2(left_fft).shape)
        audio_out_fft = self.audio_fdslice2(left_fft) * self.Filters['audio_lpf2']
        left_out = np.fft.ifft(audio_out_fft).real / self.Filters['audio_fdiv2']

        right = frame_audio['audio_right'][start:start+self.blocklen].copy() 
        right_fft = np.fft.fft(right)
        audio_out_fft = self.audio_fdslice2(right_fft) * self.Filters['audio_lpf2'] #* adeemp
        right_out = np.fft.ifft(audio_out_fft).real / self.Filters['audio_fdiv2']

        return np.rec.array([left_out, right_out], names=['audio_left', 'audio_right'])

    def audio_phase2(self, field_audio):
        # this creates an output array with left/right channels.
        output_audio2 = np.zeros(len(field_audio['audio_left']) // self.Filters['audio_fdiv2'], dtype=field_audio.dtype)

        # copy the first block in it's entirety, to keep audio and video samples aligned
        tmp = self.runfilter_audio_phase2(field_audio, 0)
        output_audio2[:tmp.shape[0]] = tmp

        end = field_audio.shape[0] #// filterset['audio_fdiv2']

        askip = 64 # length of filters that needs to be chopped out of the ifft
        sjump = self.blocklen - (askip * self.Filters['audio_fdiv2'])

        ostart = tmp.shape[0]
        for sample in range(sjump, field_audio.shape[0] - sjump, sjump):
            tmp = self.runfilter_audio_phase2(field_audio, sample)
            oend = ostart + tmp.shape[0] - askip
            output_audio2[ostart:oend] = tmp[askip:]
            ostart += tmp.shape[0] - askip

        tmp = self.runfilter_audio_phase2(field_audio, end - self.blocklen - 1)
        output_audio2[output_audio2.shape[0] - (tmp.shape[0] - askip):] = tmp[askip:]

        return output_audio2    

    def demod(self, indata, start, length, mtf_level = 0, doaudio = True):
        end = int(start + length) + 1
        start = int(start - self.blockcut) if (start > self.blockcut) else 0

        # set a placeholder
        output = None
        output_audio = None
        output_efm = None
        output_audio1 = None

        blocklen_overlap = self.blocklen - self.blockcut - self.blockcut_end
        for i in range(start, end, blocklen_overlap):
            # XXX: process last block with 0 padding
            if (i + blocklen_overlap) > end:
                break

            tmp_video, tmp_audio, tmp_efm = self.demodblock(indata[i:i+self.blocklen], mtf_level = mtf_level)

            # if the output hasn't been created yet, do it now using the 
            # data types returned by dodemod (should be faster than multiple
            # allocations...)
            if output is None:
                output = np.zeros(end - start + 1, dtype=tmp_video.dtype)

            if i - start + (self.blocklen - self.blockcut) > len(output):
                copylen = len(output) - (i - start)
            else:
                copylen = self.blocklen - self.blockcut - self.blockcut_end

            output_slice = slice(i - start, i - start + copylen)
            tmp_slice = slice(self.blockcut, self.blockcut + copylen)

            output[output_slice] = tmp_video[tmp_slice]

            if tmp_efm is not None:
                if output_efm is None:
                    output_efm = np.zeros(end - start + 1, dtype=np.int16)

                output_efm[output_slice] = tmp_efm[tmp_slice].real

            # repeat the above - but for audio
            if doaudio == True and tmp_audio is not None:
                audio_downscale = tmp_video.shape[0] // tmp_audio.shape[0]

                if output_audio1 is None:
                    output_audio1 = np.zeros(((end - start) // audio_downscale) + 1, dtype=tmp_audio.dtype)

                output_aslice = slice((i - start) // audio_downscale, (i - start + copylen) // audio_downscale)
                tmp_aslice = slice(self.blockcut // audio_downscale, (self.blockcut + copylen) // audio_downscale)

                output_audio1[output_aslice] = tmp_audio[tmp_aslice]

        if doaudio == True and output_audio1 is not None:
            output_audio = self.audio_phase2(output_audio1)

        return output, output_audio, output_efm

    def computedelays(self, mtf_level = 0):
        ''' Generate a fake signal and compute filter delays '''

        rf = self

        filterset = rf.Filters
        fakeoutput = np.zeros(rf.blocklen, dtype=np.double)

        # set base level to black
        fakeoutput[:] = rf.iretohz(0)

        synclen_full = int(4.7 * rf.freq)
        
        # sync 1 (used for gap determination)
        fakeoutput[1500:1500+synclen_full] = rf.iretohz(rf.SysParams['vsync_ire'])
        # sync 2 (used for pilot/rot level setting)
        fakeoutput[2000:2000+synclen_full] = rf.iretohz(rf.SysParams['vsync_ire'])

        porch_end = 2000+synclen_full + int(0.6 * rf.freq)
        burst_end = porch_end + int(1.2 * rf.freq)

        rate = np.full(burst_end-porch_end, rf.SysParams['fsc_mhz'], dtype=np.double)
        fakeoutput[porch_end:burst_end] += (genwave(rate, rf.freq / 2) * rf.SysParams['hz_ire'] * 20)
        
        # white
        fakeoutput[3000:3500] = rf.iretohz(100)

        # white + burst
        fakeoutput[4500:5000] = rf.iretohz(100)

        rate = np.full(5500-4200, rf.SysParams['fsc_mhz'], dtype=np.double)
        fakeoutput[4200:5500] += (genwave(rate, rf.freq / 2) * rf.SysParams['hz_ire'] * 20)
        
        rate = np.full(synclen_full, rf.SysParams['fsc_mhz'], dtype=np.double)
        fakeoutput[2000:2000+synclen_full] = rf.iretohz(rf.SysParams['vsync_ire']) + (genwave(rate, rf.freq / 2) * rf.SysParams['hz_ire'] * rf.SysParams['vsync_ire'])

        # add filters to generate a fake signal

        # NOTE: group pre-delay is not implemented, so the decoded signal
        # has issues settling down.  Emphasis is correct AFAIK

        tmp = np.fft.fft(fakeoutput)
        tmp2 = tmp * (filterset['Fvideo_lpf'] ** 1)
        tmp3 = tmp2 * (filterset['Femp'] ** 1)

        #fakeoutput_lpf = np.fft.ifft(tmp2).real
        fakeoutput_emp = np.fft.ifft(tmp3).real

        fakesignal = genwave(fakeoutput_emp, rf.freq_hz / 2)

        fakedecode = rf.demodblock(fakesignal, mtf_level=mtf_level)

        # XXX: sync detector does NOT reflect actual sync detection, just regular filtering @ sync level
        # (but only regular filtering is needed for DOD)
        dgap_sync = calczc(fakedecode[0]['demod'], 1500, rf.iretohz(rf.SysParams['vsync_ire'] / 2), _count=512) - 1500
        dgap_white = calczc(fakedecode[0]['demod'], 3000, rf.iretohz(50), _count=512) - 3000

        rf.delays = {}
        # factor in the 1k or so block cut as well, since we never *just* do demodblock
        rf.delays['video_sync'] = dgap_sync - self.blockcut
        rf.delays['video_white'] = dgap_white - self.blockcut
        
        fdec_raw = fakedecode[0]['demod_raw']
        
        rf.limits = {}
        rf.limits['sync'] = (np.min(fdec_raw[1400:2800]), np.max(fdec_raw[1400:2800]))
        rf.limits['viewable'] = (np.min(fdec_raw[2900:6000]), np.max(fdec_raw[2900:6000]))

        return fakedecode, dgap_sync, dgap_white

# right now defualt is 16/48, so not optimal :)
def downscale_audio(audio, lineinfo, rf, linecount, timeoffset = 0, freq = 48000.0, scale=64):
    #frametime = 1 / (rf.SysParams['FPS'] * 2)
    frametime = linecount / (1000000 / rf.SysParams['line_period'])
    #logging.info(frametime)
    soundgap = 1 / freq

    # include one extra 'tick' to interpolate the last one and use as a return value
    # for the next frame
    arange = np.arange(timeoffset, frametime + (soundgap / 2), soundgap, dtype=np.double)
    locs = np.zeros(len(arange), dtype=np.float)
    swow = np.zeros(len(arange), dtype=np.float)
    
    for i, t in enumerate(arange):
        linenum = (((t * 1000000) / rf.SysParams['line_period']) + 1)
        
        lineloc_cur = lineinfo[np.int(linenum)]
        try:
            lineloc_next = lineinfo[np.int(linenum) + 1]
        except:
            lineloc_next = lineloc_cur + rf.linelen

        sampleloc = lineloc_cur
        sampleloc += (lineloc_next - lineloc_cur) * (linenum - np.floor(linenum))

        swow[i] = ((lineloc_next - lineloc_cur) / rf.linelen)
        locs[i] = sampleloc / scale

    output = np.zeros((2 * (len(arange) - 1)), dtype=np.int32)
    output16 = np.zeros((2 * (len(arange) - 1)), dtype=np.int16)

    for i in range(len(arange) - 1):    
        output_left = np.mean(audio['audio_left'][np.int(locs[i]):np.int(locs[i+1])])
        output_right = np.mean(audio['audio_right'][np.int(locs[i]):np.int(locs[i+1])])

        output_left *= swow[i]
        output_right *= swow[i]
        
        output_left -= rf.SysParams['audio_lfreq']
        output_right -= rf.SysParams['audio_rfreq']
        
        # XXX: replace nan's here?

        output[(i * 2) + 0] = int(np.round(output_left * 32767 / 150000))
        output[(i * 2) + 1] = int(np.round(output_right * 32767 / 150000))
        
    np.clip(output, -32766, 32766, out=output16)
            
    return output16, arange[-1] - frametime

# The Field class contains common features used by NTSC and PAL
class Field:
    def get_linefreq(self, l = None):
        if l is None or l == 0:
            return self.rf.freq
        else:
            return self.rf.freq * (((self.linelocs[l+1] - self.linelocs[l-1]) / 2) / self.rf.linelen)

    def usectoinpx(self, x, line = None):
        return x * self.get_linefreq(line)
    
    def inpxtousec(self, x, line = None):
        return x / self.get_linefreq(line)

    def lineslice(self, l, begin = None, length = None, linelocs = None):
        ''' return a slice corresponding with pre-TBC line l, begin+length are uSecs '''
        
        # for PAL, each field has a different offset so normalize that
        l_adj = l + self.lineoffset

        _begin = linelocs[l_adj] if linelocs is not None else self.linelocs[l_adj]
        _begin += self.usectoinpx(begin, l_adj) if begin is not None else 0

        _length = self.usectoinpx(length, l_adj) if length is not None else 1

        return slice(int(np.round(_begin)), int(np.round(_begin + _length)))

    def usectooutpx(self, x):
        return x * self.rf.SysParams['outfreq']

    def outpxtousec(self, x):
        return x / self.rf.SysParams['outfreq']

    def lineslice_tbc(self, l, begin = None, length = None, linelocs = None, keepphase = False):
        ''' return a slice corresponding with pre-TBC line l '''
        
        _begin = self.rf.SysParams['outlinelen'] * (l - 1)

        begin_offset = self.usectooutpx(begin) if begin is not None else 0
        if keepphase:
            begin_offset = (begin_offset // 4) * 4

        _begin += begin_offset 
        _length = self.usectooutpx(length) if length is not None else self.rf.SysParams['outlinelen']

        return slice(int(np.round(_begin)), int(np.round(_begin + _length)))

    def find_vsync(self, pulses, start = 0):
        ''' find the beginning and end of the core VSYNC period from a pulse set, starting with index # start
        
            returns (first pulse # of vsync, first pulse # *after* vsync)
        '''
        vset = []
        prev = None

        for i, p in enumerate(pulses[start:]):
            usec = self.inpxtousec(p[1])

            # a VSYNC pulse should be *much* longer than 9.6 usec,
            # so even if there's corruption this should find things...
            
            #logging.info(i, p, p[0], usec)
            
            if usec > self.rf.SysParams['hsyncPulseUS'] * 2:
                vset.append((i + start, *p))
            elif len(vset) and (p[0] - vset[0][1]) > (self.inlinelen * 5):
                break
                
        if len(vset) > 2:
            return vset[0][0], vset[-1][0]+1
        else:
            return None
        
    def compute_distance(self, pulses, p1, p2, ll = 0, round=True):
        linelen = self.inlinelen if ll == 0 else ll
        #logging.info(p1, p2, len(pulses))
        dist = (pulses[p2][0]-pulses[p1][0]) / linelen
        
        return np.round(dist*2)/2 if round else dist

    def refinepulses(self, pulses):
        ''' returns validated pulses with type and distance checks '''
        
        # compute the allowable times for each pulse type
        hsync_min = self.usectoinpx(self.rf.SysParams['hsyncPulseUS'] - .7)
        hsync_max = self.usectoinpx(self.rf.SysParams['hsyncPulseUS'] + .5)

        eq_min = self.usectoinpx(self.rf.SysParams['eqPulseUS'] - .7)
        eq_max = self.usectoinpx(self.rf.SysParams['eqPulseUS'] + .5)

        vsync_min = self.usectoinpx(self.rf.SysParams['vsyncPulseUS'] - .7)
        vsync_max = self.usectoinpx(self.rf.SysParams['vsyncPulseUS'] + .5)

        # Pulse validator routine.  Removes sync pulses of invalid lengths, does not 
        # fill missing ones.

        # states for first field of validpulses (second field is pulse #)
        HSYNC, EQPL1, VSYNC, EQPL2 = range(4)

        vints = []  # vertical intervals (first EQ->start of next field)
        vsyncs = [] # VSYNC area (first broad pulse->first EQ after broad pulses)

        inorder = False
        validpulses = []

        earliest_eq = 0

        # state order: HSYNC -> EQPUL1 -> VSYNC -> EQPUL2 -> HSYNC

        for i, p in enumerate(pulses):

            spulse = None

            state = validpulses[-1][0] if len(validpulses) > 0 else -1

            if state == -1:
                # First valid pulse must be a regular HSYNC
                if inrange(p.len, hsync_min, hsync_max):
                    spulse = (HSYNC, p)
            elif state == HSYNC:
                # HSYNC can transition to EQPUL/pre-vsync at the end of a field
                if inrange(p.len, hsync_min, hsync_max):
                    spulse = (HSYNC, p)
                elif p.start > earliest_eq and inrange(p.len, eq_min, eq_max):
                    eq_start = len(validpulses)-1
                    spulse = (EQPL1, p)
            elif state == EQPL1:
                if inrange(p.len, eq_min, eq_max):
                    spulse = (EQPL1, p)
                elif inrange(p.len, vsync_min, vsync_max):
                    # len(validpulses)-1 before appending adds index to first VSYNC pulse
                    vsync_start = len(validpulses)-1
                    spulse = (VSYNC, p)
            elif state == VSYNC:
                if inrange(p.len, eq_min, eq_max):
                    # len(validpulses)-1 before appending adds index to first EQ pulse
                    vsyncs.append((vsync_start, len(validpulses)-1))
                    spulse = (EQPL2, p)
                elif inrange(p.len, vsync_min, vsync_max):
                    spulse = (VSYNC, p)
            elif state == EQPL2:
                if inrange(p.len, eq_min, eq_max):
                    spulse = (EQPL2, p)
                elif inrange(p.len, hsync_min, hsync_max):
                    vints.append((eq_start, len(validpulses)-1))
                    spulse = (HSYNC, p)
                    earliest_eq = p.start + (self.inlinelen * (np.min(self.rf.SysParams['field_lines']) - 10))

            # Quality check
            if spulse is not None and len(validpulses) >= 1:
                prevpulse = validpulses[-1]
                if prevpulse[0] > 0 and spulse[0] > 0:
                    exprange = (.4, .6)
                elif prevpulse[0] == 0 and spulse[0] == 0:
                    exprange = (.9, 1.1)
                else: # transition to/from regular hsyncs can be .5 or 1H
                    exprange = (.4, 1.1)

                linelen = (spulse[1].start - prevpulse[1].start) / self.inlinelen
                inorder = inrange(linelen, *exprange)

            if spulse is not None:
                validpulses.append((*spulse, inorder))


        # It's possible to have completed vsync cycles without the end of the whole
        # vert interval cycle.  Not recommended.
        if len(vsyncs) > len(vints):
            vints.append((eq_start, None))            

        return validpulses, vints

    def getblankrange(self, vpulses, start = 0):
        vp_type = np.array([p[0] for p in vpulses])
        
        try:
            firstblank = np.where(vp_type[start:] > 0)[0][0] + start
            lastblank = np.where(vp_type[firstblank:] == 0)[0][0] + firstblank - 1
        except:
            # there isn't a valid range to find
            return None, None
        
        return firstblank, lastblank

    def getBlankLength(self, isFirstField):
        core = (self.rf.SysParams['numPulses'] * 3 * .5)
        
        if self.rf.system == 'NTSC':
            return core + 1
        else:
            return core + .5 + (0 if isFirstField else 1)
        
        return core

    def processVBlank(self, validpulses, start):
        vp_type = np.array([p[0] for p in validpulses])
        firstblank, lastblank = self.getblankrange(validpulses, start)

        HSYNC, EQPL1, VSYNC, EQPL2 = range(4)
        
        goodones = [vp[2] == True for vp in self.validpulses[firstblank:firstblank+24]]

        # determine which of the HSYNC<->EQ pulse transitions are valid, by determining if
        # there are no excessive line gaps and the full set of pulses
        
        # XXX : can clean this up
        matches = [vp[0] == EQPL1 for vp in self.validpulses[firstblank:firstblank+24]]
        if (np.sum(np.logical_and(matches, goodones)) == self.rf.SysParams['numPulses'] 
                and np.sum(matches) == self.rf.SysParams['numPulses'] 
                and validpulses[firstblank - 1][2]
                and validpulses[firstblank][2]):
            line0p = firstblank - 1
        else:
            line0p = None

        matches = [vp[0] == EQPL2 for vp in self.validpulses[firstblank:firstblank+24]]
        if (np.sum(np.logical_and(matches, goodones)) == self.rf.SysParams['numPulses'] 
                and np.sum(matches) == self.rf.SysParams['numPulses'] 
                and validpulses[lastblank][2]
                and validpulses[lastblank + 1][2]):
            lineXp = lastblank + 1
        else:
            lineXp = None

        line0loc = None
        isFirstField = None

        if line0p is not None:
            gap = validpulses[line0p + 1][1].start - validpulses[line0p][1].start

            gap1H = inrange(gap / self.inlinelen, .9, 1.1)
            isFirstField = (gap1H == self.rf.SysParams['firstField1H'][0])

            line0loc = validpulses[line0p][1].start
            #logging.info(line0loc, gap, isFirstField, validpulses[line0p])

        if line0loc is None and lineXp is not None:
            gap = validpulses[lineXp][1].start - validpulses[lineXp - 1][1].start

            gap1H = inrange(gap / self.inlinelen, .9, 1.1)
            isFirstField = (gap1H == self.rf.SysParams['firstField1H'][1])

            locallinelen = self.computeLineLen(validpulses, 'begin' if start < 50 else 'end')
            
            lineXloc = validpulses[lineXp][1].start
            line0loc = lineXloc - np.round(self.getBlankLength(isFirstField) * locallinelen)

            #logging.info(line0loc, gap, isFirstField, validpulses[lineXp])

        return line0loc, isFirstField

    def computeLineLen(self, validpulses, where = 'all'):
        linelens = []
        
        blank1 = self.getblankrange(validpulses)
        blank2 = self.getblankrange(validpulses, blank1[1] + 1)
        
        # This uses +/- 2 since the previous line is used as well
        if where == 'begin':
            scanrange = (blank1[1] + 2, blank1[1] + 20)
        elif where == 'end':
            scanrange = (blank2[0] - 20, blank2[0] - 2)
        else: # where == 'all':
            scanrange = (blank1[1] + 2, blank2[0] - 2)
            
        for i in range(*scanrange):
            linelen = validpulses[i][1].start - validpulses[i - 1][1].start
            
            if inrange(linelen, self.inlinelen * .95, self.inlinelen * 1.05):
                linelens.append(linelen)

        return np.mean(linelens) if len(linelens) else self.inlinelen

    # pull the above together into a routine that (should) find line 0, the last line of
    # the previous field.

    # Basically as long as *one* of the four hsync<->eq pulse transitions work this should
    # get a reasonably accurate location

    def getLine0(self, validpulses):

        line0loc, isFirstField = self.processVBlank(validpulses, 0)
        
        # If there isn't a valid transition in the first field's hsync, try the next
        if line0loc is None:
            line0loc_next, isNotFirstField = self.processVBlank(validpulses, 100)

            if line0loc_next is None:
                try:
                    if self.prevfield is not None:
                        logging.warning("Severe VSYNC-area corruption detected.")
                        return self.prevfield.linelocs[self.prevfield.outlinecount - 1] - self.prevfield.nextfieldoffset, not self.prevfield.isFirstField
                except:
                    # If the previous field is corrupt, something may fail up there
                    pass

                logging.error("Extreme VSYNC-area corruption detected, dropping field")
                return None, None

            isFirstField = not isNotFirstField

            meanlinelen = self.computeLineLen(validpulses, 'all')
            fieldlen = (meanlinelen * self.rf.SysParams['field_lines'][0 if isFirstField else 1])
            line0loc = int(np.round(line0loc_next - fieldlen))
            
        return line0loc, isFirstField        

    def compute_linelocs(self):
        # pulse_hz range:  vsync_ire - 10, maximum is the 50% crossing point to sync
        pulse_hz_min = self.rf.iretohz(self.rf.SysParams['vsync_ire'] - 10)
        pulse_hz_max = self.rf.iretohz(self.rf.SysParams['vsync_ire'] / 2)

        pulses = findpulses(self.data[0]['demod_05'], pulse_hz_min, pulse_hz_max)

        if len(pulses) == 0:
            logging.info("Unable to find any sync pulses")
            return None, None, self.rf.freq_hz

        validpulses, vints = self.refinepulses(pulses)
        self.validpulses = validpulses

        blank1 = self.getblankrange(validpulses)
        if blank1[1] is None:
            return None, None, self.inlinelen * 200

        blank2 = self.getblankrange(validpulses, blank1[1] + 1)
        if blank2[1] == None:
            if blank1[0] > 6:
                return None, None, validpulses[blank1[0] - 6][1].start
            else:
                return None, None, self.inlinelen * 200

        line0loc, self.isFirstField = self.getLine0(validpulses)
        linelocs_dict = {}

        if line0loc is None:
            logging.error("Unable to determine start of field - dropping field")
            return None, None, self.inlinelen * 200

        meanlinelen = self.computeLineLen(validpulses, 'all')
        for p in validpulses:
            lineloc = (p[1].start - line0loc) / meanlinelen
            hlineloc = int(np.round(lineloc * 2) )
            
            if not (hlineloc % 2):
                #logging.info(p, hlineloc, hlineloc / 2)
                linelocs_dict[hlineloc // 2] = p[1].start

        rv_err = np.full(self.outlinecount + 6, False)

        # Convert dictionary into list, then fill in gaps
        linelocs = [linelocs_dict[l] if l in linelocs_dict else -1 for l in range(0, self.outlinecount + 6)]
        linelocs_filled = linelocs.copy()

        if linelocs_filled[0] < 0:
            next_valid = None
            for i in range(0, self.outlinecount + 1):
                if linelocs[i] > 0:
                    next_valid = i
                    break

            if next_valid is None:
                return None, None, validpulses[blank1[0]][1].start + (self.inlinelen * self.outlinecount - 7)

            linelocs_filled[0] = linelocs_filled[next_valid] - (next_valid * meanlinelen)
            
            if linelocs_filled[0] < self.inlinelen:
                #logging.info(linelocs_filled[0])
                return None, None, validpulses[blank1[0]][1].start + (self.inlinelen * self.outlinecount - 7)

        for l in range(1, self.outlinecount + 6):
            if linelocs_filled[l] < 0:
                rv_err[l] = True

                prev_valid = None
                next_valid = None

                for i in range(l, 1, -1):
                    if linelocs[i] > 0:
                        prev_valid = i
                        break
                for i in range(l, self.outlinecount + 1):
                    if linelocs[i] > 0:
                        next_valid = i
                        break

                if prev_valid is None:
                    avglen = self.inlinelen
                    linelocs_filled[l] = linelocs[next_valid] - (avglen * (next_valid - l))
                elif next_valid is not None:
                    avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (next_valid - prev_valid)
                    linelocs_filled[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))
                else:
                    avglen = self.inlinelen 
                    linelocs_filled[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))

        # *finally* done :)

        rv_ll = [linelocs_filled[l] for l in range(0, self.outlinecount + 6)]

        self.vsync1loc = validpulses[blank1[0]][1].start
        self.vsync2loc = validpulses[blank2[0]][1].start

        self.pulses = pulses

        return rv_ll, rv_err, validpulses[blank2[0] - 6][1].start

    def refine_linelocs_hsync(self):
        linelocs2 = self.linelocs1.copy()

        for i in range(len(self.linelocs1)):
            # skip VSYNC lines, since they handle the pulses differently 
            if inrange(i, 3, 6) or (self.rf.system == 'PAL' and inrange(i, 1, 2)):
                self.linebad[i] = True
                continue
                        
            # Find beginning of hsync (linelocs1 is generally in the middle)
            ll1 = self.linelocs1[i] - self.usectoinpx(5.5)
            #logging.info(i, ll1)
            zc = calczc(self.data[0]['demod_05'], ll1, self.rf.iretohz(self.rf.SysParams['vsync_ire'] / 2), reverse=False, _count=400)

            if zc is not None and not self.linebad[i]:
                linelocs2[i] = zc 

                # The hsync area, burst, and porches should not leave -50 to 30 IRE (on PAL or NTSC)
                hsync_area = self.data[0]['demod_05'][int(zc-(self.rf.freq*1.25)):int(zc+(self.rf.freq*8))]
                if np.min(hsync_area) < self.rf.iretohz(-55) or np.max(hsync_area) > self.rf.iretohz(30):
                    self.linebad[i] = True
                else:
                    porch_level = np.median(self.data[0]['demod_05'][int(zc+(self.rf.freq*8)):int(zc+(self.rf.freq*9))])
                    sync_level = np.median(self.data[0]['demod_05'][int(zc+(self.rf.freq*1)):int(zc+(self.rf.freq*2.5))])

                    zc2 = calczc(self.data[0]['demod_05'], ll1, (porch_level + sync_level) / 2, reverse=False, _count=400)

                    # any wild variation here indicates a failure
                    if zc2 is not None and np.abs(zc2 - zc) < (self.rf.freq / 2):
                        linelocs2[i] = zc2
                    else:
                        self.linebad[i] = True
            else:
                self.linebad[i] = True

            if (i >= 2) and self.linebad[i]:
                gap = linelocs2[i - 1] - linelocs2[i - 2]
                linelocs2[i] = linelocs2[i - 1] + gap

        return linelocs2

    def compute_deriv_error(self, linelocs, baserr):
        ''' compute errors based off the second derivative - if it exceeds 1 something's wrong '''

        derr1 = np.full(len(linelocs), False)
        derr1[1:-1] = np.abs(np.diff(np.diff(linelocs))) > 4
        
        derr2 = np.full(len(linelocs), False)
        derr2[2:] = np.abs(np.diff(np.diff(linelocs))) > 4

        derr = np.logical_or(derr1, derr2)
        
        return np.logical_or(baserr, derr)

    def fix_badlines(self, linelocs_in, linelocs_backup_in = None):
        self.linebad = self.compute_deriv_error(linelocs_in, self.linebad)
        linelocs = np.array(linelocs_in.copy())

        if linelocs_backup_in is not None:
            linelocs_backup = np.array(linelocs_backup_in.copy())
            badlines = np.isnan(linelocs)
            linelocs[badlines] = linelocs_backup[badlines]

        for l in np.where(self.linebad)[0]:
            prevgood = l - 1
            nextgood = l + 1

            while prevgood >= 0 and self.linebad[prevgood]:
                prevgood -= 1

            while nextgood < len(linelocs) and self.linebad[nextgood]:
                nextgood += 1

            if prevgood >= 0 and nextgood < len(linelocs):
                gap = (linelocs[nextgood] - linelocs[prevgood]) / (nextgood - prevgood)
                linelocs[l] = (gap * (l - prevgood)) + linelocs[prevgood]
                
        return linelocs

    def computewow(self, lineinfo):
        wow = np.ones(len(lineinfo))

        for l in range(0, len(wow)-1):
            wow[l] = (lineinfo[l + 1] - lineinfo[l]) / self.inlinelen

        return wow

        # early work on issue 37, hits a FutureWarning in scipy

        # apply a simple 5-tap filter to the wowfactor
        #filt = (0.1, 0.2, 0.4, 0.2, 0.1)
        # do not use the first or last lines, which are often inaccurate...
        #wf_filter = sps.lfilter(filt, (1.0), wow[1:-1])

        # copy the valid new wowfactors (drop the first few lines since they were 0...)
        #wf2 = copy.copy(wow)
        #wf2[4:-3] = wf_filter[5:]

    def downscale(self, lineinfo = None, linesout = None, outwidth = None, wow=True, channel='demod', audio = False):
        if lineinfo is None:
            lineinfo = self.linelocs
        if outwidth is None:
            outwidth = self.outlinelen
        if linesout is None:
            # for video always output 263/313 lines
            linesout = self.outlinecount

        dsout = np.zeros((linesout * outwidth), dtype=np.double)    
        # self.lineoffset is an adjustment for 0-based lines *before* downscaling so add 1 here
        lineoffset = self.lineoffset + 1

        if wow:
            self.wowfactor = self.computewow(lineinfo)

        for l in range(lineoffset, linesout + lineoffset):
            #logging.info(l, lineinfo[l], lineinfo[l+1])
            if lineinfo[l + 1] > lineinfo[l]:
                scaled = scale(self.data[0][channel], lineinfo[l], lineinfo[l + 1], outwidth)

                if wow:
                    #linewow = (lineinfo[l + 1] - lineinfo[l]) / self.inlinelen
                    scaled *= self.wowfactor[l] # linewow

                dsout[(l - lineoffset) * outwidth:(l + 1 - lineoffset)*outwidth] = scaled
            else:
                logging.warning("WARNING: TBC failure at line" + l)
                dsout[(l - lineoffset) * outwidth:(l + 1 - lineoffset)*outwidth] = self.rf.SysParams['ire0']

        if audio and self.rf.decode_analog_audio:
            self.dsaudio, self.audio_next_offset = downscale_audio(self.data[1], lineinfo, self.rf, self.linecount, self.audio_offset)
            
        if self.rf.decode_digital_audio:
            self.efmout = self.data[2][self.vsync1loc:self.vsync2loc]
        else:
            self.efmout = None

        return dsout, self.dsaudio, self.efmout
    
    def decodephillipscode(self, linenum):
        linestart = self.linelocs[linenum]
        data = self.data[0]['demod']
        curzc = calczc(data, int(linestart + self.usectoinpx(2)), self.rf.iretohz(50), _count=int(self.usectoinpx(12)))

        zc = []
        while curzc is not None:
            zc.append((curzc, data[int(curzc - self.usectoinpx(0.5))] < self.rf.iretohz(50)))
            curzc = calczc(data, curzc+self.usectoinpx(1.9), self.rf.iretohz(50), _count=int(self.usectoinpx(0.2)))

        usecgap = self.inpxtousec(np.diff([z[0] for z in zc]))
        valid = len(zc) == 24 and np.min(usecgap) > 1.85 and np.max(usecgap) < 2.15

        if valid:
            bitset = [z[1] for z in zc]
            linecode = 0

            for b in range(0, 24, 4):
                linecode *= 0x10
                linecode += (np.packbits(bitset[b:b+4]) >> 4)[0]

            return linecode
        
        return None

    def __init__(self, rf, rawdata, rawdecode, audio_offset = 0, keepraw = True, prevfield = None):
        if rawdecode is None:
            return None

        self.prevfield = prevfield

        self.rawdata = rawdata
        self.data = rawdecode
        self.rf = rf
        
        self.inlinelen = self.rf.linelen
        self.outlinelen = self.rf.SysParams['outlinelen']

        self.lineoffset = 0
        
        self.valid = False
        self.sync_confidence = 75
        
        self.dspicture = None
        self.dsaudio = None
        self.audio_offset = audio_offset
        self.audio_next_offset = audio_offset

        # On NTSC linecount rounds up to 263, and PAL 313
        self.outlinecount = (self.rf.SysParams['frame_lines'] // 2) + 1
        # this is eventually set to 262/263 and 312/313 for audio timing
        self.linecount = None
        
        self.linelocs1, self.linebad, self.nextfieldoffset = self.compute_linelocs()
        if self.linelocs1 is None:
            if self.nextfieldoffset is None:
                self.nextfieldoffset = self.rf.linelen * 200

            return

        self.linebad = self.compute_deriv_error(self.linelocs1, self.linebad)

        self.linelocs2 = self.refine_linelocs_hsync()
        self.linebad = self.compute_deriv_error(self.linelocs2, self.linebad)

        self.linelocs = self.linelocs2

        self.wowfactor = np.ones_like(self.linelocs)

        # VBI info
        self.valid = True

        self.prevfield = None

        return

    def dropout_detect_demod(self):
        # current field
        f = self

        # Do raw demod detection here.  (This covers only extreme cases right now)
        dod_margin_low = 2500000 if self.rf.system == 'PAL' else 1500000
        dod_margin_high = 12000000 if self.rf.system == 'PAL' else 1500000
        
        iserr1 = inrange(f.data[0]['demod_raw'], f.rf.limits['viewable'][0] - dod_margin_low, f.rf.limits['viewable'][1] +  dod_margin_high) == False

        # build sets of min/max valid levels 

        # the base values are good for viewable-area signal
        if self.rf.system == 'PAL':
            valid_min = np.full_like(f.data[0]['demod'], f.rf.iretohz(-50))
            valid_max = np.full_like(f.data[0]['demod'], f.rf.iretohz(150))
        else:
            valid_min = np.full_like(f.data[0]['demod'], f.rf.iretohz(-50))
            valid_max = np.full_like(f.data[0]['demod'], f.rf.iretohz(140))

        # the minimum valid value during VSYNC is lower for PAL because of the pilot signal
        minsync = -100 if self.rf.system == 'PAL' else -50

        # these lines should cover both PAL and NTSC

        for i in range(0, len(f.linelocs)):
            l = f.linelocs[i]
            # Could compute the estimated length of setup, but we can cut this a bit early...
            valid_min[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 8))] = f.rf.iretohz(minsync)
            valid_max[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 8))] = f.rf.iretohz(40)

            if self.rf.system == 'PAL':
                # basically exclude the pilot signal altogether
                # This is needed even though HSYNC is excluded later, since failures are expanded
                valid_min[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 4.7))] = f.rf.iretohz(-100)
                valid_max[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 4.7))] = f.rf.iretohz(120)

        # effectively disable during VSYNC
        for i in range(1, 7 + self.lineoffset):
            valid_min[int(f.linelocs[i]):int(f.linelocs[i+1])] = f.rf.iretohz(-150)
            valid_max[int(f.linelocs[i]):int(f.linelocs[i+1])] = f.rf.iretohz(150)

        iserr2 = f.data[0]['demod'] < valid_min
        iserr2 |= f.data[0]['demod'] > valid_max

        iserr = iserr1 | iserr2
        
        return iserr

    def build_errlist(self, errmap):
        errlist = []

        firsterr = errmap[np.nonzero(errmap >= self.linelocs[self.lineoffset])[0][0]]
        curerr = (firsterr, firsterr)

        for e in errmap:
            if e > curerr[0] and e <= (curerr[1] + 20):
                epad = curerr[0] + ((e - curerr[0]) * 2)
                curerr = (curerr[0], epad)
            elif e > firsterr:
                errlist.append(curerr)
                curerr = (e, e)
                
        return errlist

    def dropout_errlist_to_tbc(self, errlist):
        dropouts = []

        if len(errlist) == 0:
            return dropouts

        # Now convert the above errlist into TBC locations
        errlistc = errlist.copy()
        curerr = errlistc.pop(0)

        lineoffset = -self.lineoffset

        for l in range(lineoffset, self.linecount - 1):
            while curerr is not None and inrange(curerr[0], self.linelocs[l], self.linelocs[l + 1]):
                start_rf_linepos = curerr[0] - self.linelocs[l]
                start_linepos = start_rf_linepos / (self.linelocs[l + 1] - self.linelocs[l])
                start_linepos = int(start_linepos * self.outlinelen)

                end_rf_linepos = curerr[1] - self.linelocs[l]
                end_linepos = end_rf_linepos / (self.linelocs[l + 1] - self.linelocs[l])
                end_linepos = int(np.round(end_linepos * self.outlinelen))

                if end_linepos > self.outlinelen:
                    # need to output two dropouts
                    dropouts.append((l + 1 + lineoffset, start_linepos, self.outlinelen))
                    dropouts.append((l + 1 + lineoffset + (end_linepos // self.outlinelen), 0, np.remainder(end_linepos, self.outlinelen)))
                else:
                    dropouts.append((l + 1 + lineoffset, start_linepos, end_linepos))

                if len(errlistc):
                    curerr = errlistc.pop(0)
                else:
                    curerr = None

        return dropouts

    def dropout_detect(self):
        ''' returns dropouts in three arrays, to line up with the JSON output '''

        iserr = self.dropout_detect_demod()
        errmap = np.nonzero(iserr)[0]
        errlist = self.build_errlist(errmap)

        rvs = self.dropout_errlist_to_tbc(errlist)    
        endhsync = int(4.7 * self.rf.SysParams['outfreq'])

        rv_lines = []
        rv_starts = []
        rv_ends = []

        for r in rvs:
            # exclude HSYNC from output
            if r[2] < endhsync:
                continue
            
            rv_lines.append(r[0] - 1)
            rv_starts.append(int(r[1]) if r[1] > endhsync else endhsync)
            rv_ends.append(int(r[2]))

        return rv_lines, rv_starts, rv_ends

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldPAL(Field):
    def refine_linelocs_pilot(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        pilots = []
        alloffsets = []
        offsets = {}

        # first pass: get median of all pilot positive zero crossings
        for l in range(len(linelocs)):
            pilot = self.data[0]['demod'][int(linelocs[l]):int(linelocs[l]+self.usectoinpx(4.7))].copy()
            pilot -= self.data[0]['demod_05'][int(linelocs[l]):int(linelocs[l]+self.usectoinpx(4.7))]
            pilot = np.flip(pilot)

            pilots.append(pilot)
            offsets[l] = []

            adjfreq = self.rf.freq
            if l > 1:
                adjfreq /= (linelocs[l] - linelocs[l - 1]) / self.rf.linelen

            i = 0

            while i < len(pilot):
                if inrange(pilot[i], -300000, -100000):
                    zc = calczc(pilot, i, 0)

                    if zc is not None:
                        zcp = zc / (adjfreq / 3.75)
                        offsets[l].append(zcp - np.floor(zcp))
                        i = np.int(zc + 1)

                i += 1

            if len(offsets) >= 3:
                offsets[l] = offsets[l][1:-1]
                if i >= 11:
                    alloffsets += offsets[l]
            else:
                offsets[l] = []

        medianoffset = np.median(alloffsets)
        if inrange(medianoffset, 0.25, 0.75):
            tgt = .5
        else:
            tgt = 0

        for l in range(len(linelocs)):
            if offsets[l] != []:
                adjustment = tgt - np.median(offsets[l])
                linelocs[l] += adjustment * (self.rf.freq / 3.75) * .25

        return linelocs  

    def calc_burstmedian(self):
        burstlevel = np.zeros(314)

        for l in range(3, 313):
            burstarea = self.data[0]['demod'][self.lineslice(l, 6, 3)]
            burstlevel[l] = rms(burstarea) * np.sqrt(2)

        return np.median(burstlevel / self.rf.SysParams['hz_ire'])

    def hz_to_output(self, input):
        reduced = (input - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
        reduced -= self.rf.SysParams['vsync_ire']
        
        return np.uint16(np.clip((reduced * self.out_scale) + 256, 0, 65535) + 0.5)

    def output_to_ire(self, output):
        return ((output- 256.0) / self.out_scale) + self.rf.SysParams['vsync_ire']

    def downscale(self, final = False, *args, **kwargs):
        # For PAL, each field starts with the line containing the first full VSYNC pulse
        dsout, dsaudio, dsefm = super(FieldPAL, self).downscale(audio = final, *args, **kwargs)
        
        if final:
            self.dspicture = self.hz_to_output(dsout)
            return self.dspicture, dsaudio, dsefm
                    
        return dsout, dsaudio, dsefm
    
    def __init__(self, *args, **kwargs):
        super(FieldPAL, self).__init__(*args, **kwargs)
        
        if not self.valid:
            return

        self.linelocs = self.refine_linelocs_pilot()
        self.linelocs = self.fix_badlines(self.linelocs)

        self.burstmedian = self.calc_burstmedian()

        self.linecount = 312 if self.isFirstField else 313
        self.lineoffset = 2 if self.isFirstField else 3

        self.linecode = [self.decodephillipscode(l + self.lineoffset) for l in [16, 17, 18]]

        self.out_scale = np.double(0xd300 - 0x0100) / (100 - self.rf.SysParams['vsync_ire'])

        self.downscale(wow = True, final=True)

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldNTSC(Field):

    def get_burstlevel(self, l, linelocs = None):
        burstarea = self.data[0]['demod'][self.lineslice(l, 5.5, 2.4, linelocs)].copy()

        return rms(burstarea) * np.sqrt(2)

    def compute_line_bursts(self, linelocs, line):
        '''
        Compute the zero crossing for the given line using calczc
        '''
        # calczc works from integers, so get the start and remainder
        s = int(linelocs[line])
        s_rem = linelocs[line] - s

        # compute adjusted frequency from neighboring line lengths
        if line > 0:
            lfreq = self.rf.freq * (((self.linelocs2[line+1] - self.linelocs2[line-1]) / 2) / self.rf.linelen)
        elif line == 0:
            lfreq = self.rf.freq * (((self.linelocs2[line+1] - self.linelocs2[line-0]) / 1) / self.rf.linelen)
        elif line >= 262:
            lfreq = self.rf.freq * (((self.linelocs2[line+0] - self.linelocs2[line-1]) / 1) / self.rf.linelen)

        # compute approximate burst beginning/end
        bstime = 17 * (1 / self.rf.SysParams['fsc_mhz']) # approx start of burst in usecs

        bstart = int(bstime * lfreq)
        bend = int(8.8 * lfreq)

        zc_bursts = {False: [], True: []}

        # copy and get the mean of the burst area to factor out wow/flutter
        burstarea = self.data[0]['demod_burst'][s+bstart:s+bend].copy()
        if len(burstarea) == 0:
            #logging.info( line, s + bstart, s + bend, linelocs[line])
            return zc_bursts
        burstarea -= np.mean(burstarea)

        i = 0
        while i < (len(burstarea) - 1):
            if np.abs(burstarea[i]) > (8 * self.rf.SysParams['hz_ire']):
                zc = calczc(burstarea, i, 0)
                if zc is not None:
                    zc_burst = ((bstart+zc-s_rem) / lfreq) / (1 / self.rf.SysParams['fsc_mhz'])
                    zc_bursts[burstarea[i] < 0].append(np.round(zc_burst) - zc_burst)
                    i = int(zc) + 1

            i += 1

        return zc_bursts

    def compute_burst_offsets(self, linelocs):
        linelocs_adj = linelocs

        burstlevel = np.zeros_like(linelocs_adj, dtype=np.float32)

        zc_bursts = {}
        # Counter for which lines have + polarity.  TRACKS 1-BASED LINE #'s
        bursts = {'odd': [], 'even': []}

        for l in range(0, 266):
            zc_bursts[l] = self.compute_line_bursts(linelocs, l)
            burstlevel[l] = self.get_burstlevel(l, linelocs)

            if (len(zc_bursts[l][True]) == 0) or (len(zc_bursts[l][False]) == 0):
                continue

            if not (l % 2):
                bursts['even'].append(zc_bursts[l][True])
                bursts['odd'].append(zc_bursts[l][False])
            else:
                bursts['even'].append(zc_bursts[l][False])
                bursts['odd'].append(zc_bursts[l][True])

        bursts_arr = {}
        bursts_arr[True] = np.concatenate(bursts['even'])
        bursts_arr[False] = np.concatenate(bursts['odd'])

        amed = {}
        amed[True] = np.abs(np.median(bursts_arr[True]))
        amed[False] = np.abs(np.median(bursts_arr[False]))
        field14 = amed[True] < amed[False]

        # if the medians are too close, recompute them with a 90 degree offset
        if (np.abs(amed[True] - amed[False]) < .1):
            amed = {}
            amed[True] = np.abs(np.median(bursts_arr[True] + .25))
            amed[False] = np.abs(np.median(bursts_arr[False] + .25))
            field14 = amed[True] > amed[False]

        self.amed = amed
        self.zc_bursts = zc_bursts

        return zc_bursts, field14, burstlevel

    def refine_linelocs_burst(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2

        linelocs_adj = linelocs.copy()
        burstlevel = np.zeros_like(linelocs_adj, dtype=np.float32)

        zc_bursts, field14, burstlevel = self.compute_burst_offsets(linelocs_adj)

        adjs = {}

        for l in range(1, 9):
            self.linebad[l] = True

        # compute the adjustments for each line but *do not* apply, so
        # outliers can be bypassed
        for l in range(0, 266):
            if self.linebad[l]:
                continue

            edge = not ((field14 and (l % 2)) or (not field14 and not (l % 2)))

            if not (np.isnan(linelocs_adj[l]) or len(zc_bursts[l][edge]) == 0 or self.linebad[l]):
                if l > 0:
                    lfreq = self.rf.freq * (((self.linelocs2[l+1] - self.linelocs2[l-1]) / 2) / self.rf.linelen)
                elif l == 0:
                    lfreq = self.rf.freq * (((self.linelocs2[l+1] - self.linelocs2[l-0]) / 1) / self.rf.linelen)
                elif l >= 262:
                    lfreq = self.rf.freq * (((self.linelocs2[l+0] - self.linelocs2[l-1]) / 1) / self.rf.linelen)

                adjs[l] = -(np.median(zc_bursts[l][edge]) * lfreq * (1 / self.rf.SysParams['fsc_mhz']))

        try:
            adjs_median = np.median([adjs[a] for a in adjs])
            
            for l in range(0, 266):
                if l in adjs and inrange(adjs[l] - adjs_median, -2, 2):
                    linelocs_adj[l] += adjs[l]
                else:
                    linelocs_adj[l] += adjs_median
                    self.linebad[l] = True

            self.field14 = field14

            if self.isFirstField:
                self.fieldPhaseID = 1 if self.field14 else 3
            else:
                self.fieldPhaseID = 4 if self.field14 else 2
        except:
            self.fieldPhaseID=1
            return linelocs_adj, burstlevel#, adjs

        return linelocs_adj, burstlevel#, adjs
    
    def hz_to_output(self, input):
        reduced = (input - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
        reduced -= self.rf.SysParams['vsync_ire']

        return np.uint16(np.clip((reduced * self.out_scale) + 1024, 0, 65535) + 0.5)

    def output_to_ire(self, output):
        return ((output - 1024) / self.out_scale) + self.rf.SysParams['vsync_ire']

    def downscale(self, lineoffset = 0, final = False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldNTSC, self).downscale(audio = final, *args, **kwargs)
        
        if final:
            lines16 = self.hz_to_output(dsout)

            self.dspicture = lines16
            return lines16, dsaudio, dsefm
                    
        return dsout, dsaudio, dsefm
    
    def calc_burstmedian(self):
        burstlevel = [self.get_burstlevel(l) for l in range(11, 264)]

        return np.median(burstlevel) / self.rf.SysParams['hz_ire']

    def apply_offsets(self, linelocs, phaseoffset, picoffset = 0):
        #logging.info(phaseoffset, (phaseoffset * (self.rf.freq / (4 * 315 / 88))))
        return np.array(linelocs) + picoffset + (phaseoffset * (self.rf.freq / (4 * 315 / 88)))

    def __init__(self, *args, **kwargs):
        self.burstlevel = None
        self.burst90 = False

        super(FieldNTSC, self).__init__(*args, **kwargs)
        
        self.out_scale = np.double(0xc800 - 0x0400) / (100 - self.rf.SysParams['vsync_ire'])
        
        if not self.valid:
            return

        self.linecode = [self.decodephillipscode(l + self.lineoffset) for l in [16, 17, 18]]

        self.linelocs3, self.burstlevel = self.refine_linelocs_burst(self.linelocs2)
        self.linelocs3 = self.fix_badlines(self.linelocs3, self.linelocs2)

        self.burstmedian = self.calc_burstmedian()

        # Now adjust 33 degrees to get the downscaled image onto I/Q color axis
        # self.linelocs = np.array(self.linelocs3) + ((33/360.0) * (63.555555/227.5) * self.rf.freq)
        # Now adjust 33 degrees (-90 - 33) for color decoding
        shift33 = 84 * (np.pi / 180)
        self.linelocs = self.apply_offsets(self.linelocs3, -shift33 - 0)        
        
        self.linecount = 263 if self.isFirstField else 262

        self.downscale(wow = True, final=True)

class CombNTSC:
    ''' *partial* NTSC comb filter class - only enough to do VITS calculations ATM '''
    
    def __init__(self, field):
        self.field = field
        self.cbuffer = self.buildCBuffer()

    def getlinephase(self, line):
        ''' determine if a line has positive color burst phase '''
        fieldID = self.field.fieldPhaseID
        
        fieldPositivePhase = (fieldID == 1) | (fieldID == 4)
        
        return fieldPositivePhase if ((line % 2) == 0) else not fieldPositivePhase

    def buildCBuffer(self, subset = None):
        ''' 
        prev_field: Compute values for previous field
        subset: a slice computed by lineslice_tbc (default: whole field) 
        
        NOTE:  first and last two returned values will be zero, so slice accordingly
        '''
        
        data = self.field.dspicture
        
        if subset:
            data = data[subset]
            
        # this is a translation of this code from tools/ld-comb-ntsc/comb.cxx:
        #
        # for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
        #  qreal tc1 = (((line[h + 2] + line[h - 2]) / 2) - line[h]);
                        
        fldata = data.astype(np.float32)
        cbuffer = np.zeros_like(fldata)
        
        cbuffer[2:-2] = (fldata[:-4] + fldata[4:]) / 2
        cbuffer[2:-2] -= fldata[2:-2]
        
        return cbuffer

    def splitIQ(self, cbuffer, line = 0):
        ''' 
        NOTE:  currently? only works on one line
        
        This returns normalized I and Q arrays, each one half the length of cbuffer 
        '''
        linephase = self.getlinephase(line)
        
        sq = cbuffer[::2].copy()
        si = cbuffer[1::2].copy()

        if not linephase:
            si[0::2] = -si[0::2]
            sq[1::2] = -sq[1::2]
        else:
            si[1::2] = -si[1::2]
            sq[0::2] = -sq[0::2]
    
        return si, sq
    
    def calcLine19Info(self, comb_field2 = None):
        ''' returns color burst phase (ideally 147 degrees) and (unfiltered!) SNR '''
        
        # Don't need the whole line here, but start at 0 to definitely have an even #
        l19_slice = self.field.lineslice_tbc(19, 0, 40)
        l19_slice_i70 = self.field.lineslice_tbc(19, 14, 18)

        # fail out if there is obviously bad data
        if not ((np.max(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])) < 100) and
                (np.min(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])) > 40)):
            #logging.info("WARNING: line 19 data incorrect")
            #logging.info(np.max(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])), np.min(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])))
            return None, None, None

        cbuffer = self.cbuffer[l19_slice]
        if comb_field2 is not None:
            # fail out if there is obviously bad data
            if not ((np.max(self.field.output_to_ire(comb_field2.field.dspicture[l19_slice_i70])) < 100) and
                    (np.min(self.field.output_to_ire(comb_field2.field.dspicture[l19_slice_i70])) > 40)):
                return None, None, None

            cbuffer -= comb_field2.cbuffer[l19_slice]
            cbuffer /= 2
            
        si, sq = self.splitIQ(cbuffer, 19)

        sl = slice(110,230)
        cdata = np.sqrt((si[sl] ** 2.0) + (sq[sl] ** 2.0))

        phase = np.arctan2(np.mean(si[sl]),np.mean(sq[sl]))*180/np.pi
        if phase < 0:
            phase += 360

        # compute SNR
        signal = np.mean(cdata)
        noise = np.std(cdata)

        snr = 20 * np.log10(signal / noise)
        
        return signal / (2 * self.field.out_scale), phase, snr

class LDdecode:
    
    def __init__(self, fname_in, fname_out, freader, analog_audio = True, digital_audio = False, system = 'NTSC', doDOD = True):
        self.infile = open(fname_in, 'rb')
        self.freader = freader

        self.fields_written = 0

        self.blackIRE = 0

        self.analog_audio = analog_audio
        self.digital_audio = digital_audio

        self.outfile_json = None

        if fname_out is not None:        
            self.outfile_video = open(fname_out + '.tbc', 'wb')
            #self.outfile_json = open(fname_out + '.json', 'wb')
            self.outfile_audio = open(fname_out + '.pcm', 'wb') if analog_audio else None
            #self.outfile_efm = open(fname_out + '.efm', 'wb') if digital_audio else None
        else:
            self.outfile_video = None
            self.outfile_audio = None
            self.outfile_efm = None

        if fname_out is not None and digital_audio:
            # create pipeline : EFM output -> dddconv .lds -> ld-ldstoefm

            #self.subproc_dddconv = subprocess.Popen(['dddconv', '-p'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            self.subproc_ldstoefm = subprocess.Popen(['ld-ldstoefm', '-n', '-e', '/dev/stdin', fname_out + '.efm'], stdin=subprocess.PIPE)
            
            # feed EFM stream into dddconv
            self.outfile_efm = self.subproc_ldstoefm.stdin

        self.fname_out = fname_out

        self.firstfield = None # In frame output mode, the first field goes here
        self.fieldloc = 0

        self.system = system
        if system == 'PAL':
            self.rf = RFDecode(system = 'PAL', decode_analog_audio=analog_audio, decode_digital_audio=digital_audio)
            self.FieldClass = FieldPAL
            self.readlen = self.rf.linelen * 400
            self.clvfps = 25
        else: # NTSC
            self.rf = RFDecode(system = 'NTSC', decode_analog_audio=analog_audio, decode_digital_audio=digital_audio)
            self.FieldClass = FieldNTSC
            self.readlen = ((self.rf.linelen * 350) // 16384) * 16384
            self.clvfps = 30

        self.output_lines = (self.rf.SysParams['frame_lines'] // 2) + 1
        
        self.bytes_per_frame = int(self.rf.freq_hz / self.rf.SysParams['FPS'])
        self.bytes_per_field = int(self.rf.freq_hz / (self.rf.SysParams['FPS'] * 2)) + 1
        self.outwidth = self.rf.SysParams['outlinelen']

        self.fdoffset = 0
        self.audio_offset = 0
        self.mtf_level = 1

        self.prevfield = None
        self.curfield = None

        self.doDOD = doDOD

        self.fieldinfo = []

        self.leadOut = False
        self.isCLV = False
        self.frameNumber = None

        self.autoMTF = True

        self.bw_ratios = []
        
    def close(self):
        ''' deletes all open files, so it's possible to pickle an LDDecode object '''

        # use setattr to force file closure
        for outfiles in ['infile', 'outfile_video', 'outfile_audio', 'outfile_json', 'outfile_efm']:
            setattr(self, outfiles, None)

    def roughseek(self, fieldnr):
        self.prevPhaseID = None
        self.fdoffset = fieldnr * self.bytes_per_field

    def checkMTF_calc(self, field):
        if not self.isCLV and self.frameNumber is not None:
            newmtf = 1 - (self.frameNumber / 10000) if self.frameNumber < 10000 else 0
            oldmtf = self.mtf_level
            self.mtf_level = newmtf

            if np.abs(newmtf - oldmtf) > .1: # redo field if too much adjustment
                #logging.info(newmtf, oldmtf, field.cavFrame)
                return False
            
        return True

    def checkMTF(self, field, pfield = None):
        if not self.autoMTF:
            return self.checkMTF_calc(field)

        oldmtf = self.mtf_level

        if (len(self.bw_ratios) == 0):
            return True

        # scale for NTSC - 1.1 to 1.55
        self.mtf_level = (np.mean(self.bw_ratios) - 1.08) / .38
        if self.mtf_level < 0:
            self.mtf_level = 0
        if self.mtf_level > 1:
            self.mtf_level = 1

        return np.abs(self.mtf_level - oldmtf) < .05

    def decodefield(self):
        ''' returns field object if valid, and the offset to the next decode '''
        self.readloc = self.fdoffset - self.rf.blockcut
        if self.readloc < 0:
            self.readloc = 0
            
        self.indata = self.freader(self.infile, self.readloc, self.readlen)

        if self.indata is None:
            logging.info("End of file")
            return None, None
        
        self.rawdecode = self.rf.demod(self.indata, self.rf.blockcut, self.readlen, self.mtf_level)
        if self.rawdecode is None:
            logging.info("Failed to demodulate data")
            return None, None
        
        f = self.FieldClass(self.rf, self.indata, self.rawdecode, audio_offset = self.audio_offset, prevfield = self.curfield)
        
        self.curfield = f

        if not f.valid:
            #logging.info("Bad data - jumping one second")
            return f, f.nextfieldoffset
        else:
            self.audio_offset = f.audio_next_offset
            #logging.info(f.isFirstField, f.cavFrame)
            
        return f, f.nextfieldoffset
        
    def readfield(self):
        # pretty much a retry-ing wrapper around decodefield with MTF checking
        self.prevfield = self.curfield
        #self.curfield = None
        done = False
        MTFadjusted = False
        
        while done == False:
            self.fieldloc = self.fdoffset
            f, offset = self.decodefield()

            if f is None:
                # EOF, probably
                return None

            self.curfield = f
            self.fdoffset += offset
            
            if f is not None and f.valid:
                metrics = self.computeMetrics(f, None)
                if 'blackToWhiteRFRatio' in metrics and MTFadjusted == False:
                    keep = 900 if self.isCLV else 30
                    self.bw_ratios.append(metrics['blackToWhiteRFRatio'])
                    self.bw_ratios = self.bw_ratios[-keep:]

                    #logging.info(metrics['blackToWhiteRFRatio'], np.mean(self.bw_ratios))

                if self.checkMTF(f, self.prevfield) or MTFadjusted:
                    done = True
                else:
                    # redo field
                    MTFadjusted = True
                    self.fdoffset -= offset

        if f is not None and self.fname_out is not None:
            picture, audio, efm = f.downscale(linesout = self.output_lines, final=True)
            
            fi = self.buildmetadata(f)
            fi['audioSamples'] = 0 if audio is None else int(len(audio) / 2)
            self.fieldinfo.append(fi)

            self.outfile_video.write(picture)
            self.fields_written += 1

            if audio is not None and self.outfile_audio is not None:
                self.outfile_audio.write(audio)

            if self.digital_audio == True:
                self.outfile_efm.write(efm)
            
        return f

    def decodeFrameNumber(self, f1, f2):
        ''' decode frame #/information from Philips code data on both fields '''

        # CLV
        self.isCLV = False
        self.earlyCLV = False
        self.clvMinutes = None
        self.clvSeconds = None
        self.clvFrameNum = None

        leadoutCount = 0

        for l in f1.linecode + f2.linecode:
            if l is None:
                continue
            
            if l == 0x80eeee: # lead-out reached
                leadoutCount += 1
            elif (l & 0xf0dd00) == 0xf0dd00: # CLV minutes/hours
                self.clvMinutes = (l & 0xf) + (((l >> 4) & 0xf) * 10) + (((l >> 16) & 0xf) * 60)
                self.isCLV = True
                #logging.info('CLV', mins)
            elif (l & 0xf00000) == 0xf00000: # CAV frame
                fnum = 0
                for y in range(16, -1, -4):
                    fnum *= 10
                    fnum += l >> y & 0x0f
                    
                    fnum = fnum if fnum < 80000 else fnum - 80000

                return fnum
            elif (l & 0x80f000) == 0x80e000: # CLV picture #
                self.clvSeconds = (((l >> 16) & 0xf) - 10) * 10
                self.clvSeconds += ((l >> 8) & 0xf)

                self.clvFrameNum = ((l >> 4) & 0xf) * 10
                self.clvFrameNum += (l & 0xf)

                self.isCLV = True

            if self.clvMinutes is not None:
                if self.clvSeconds is not None: # newer CLV
                    return (((self.clvMinutes * 60) + self.clvSeconds) * self.clvfps) + self.clvFrameNum
                else:
                    self.earlyCLV = True
                    return (self.clvMinutes * 60)

        if leadoutCount >= 3:
            self.leadOut = True

        return None #seeking won't work w/minutes only

    def calcsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])
        
        signal = np.mean(data)
        noise = np.std(data)

        return 20 * np.log10(signal / noise)

    def calcpsnr(self, f, snrslice):
        # if dspicture isn't converted to float, this underflows at -40IRE
        data = f.output_to_ire(f.dspicture[snrslice].astype(float))
        
        noise = np.std(data)

        return 20 * np.log10(100 / noise)

    def computeMetricsPAL(self, metrics, f, fp = None):
        
        if f.isFirstField:
            # compute IRE50 from field1 l13
            # Unforunately this is too short to get a 50IRE RF level
            wl_slice = f.lineslice_tbc(13, 4.7+15.5, 3)
            metrics['greyPSNR'] = self.calcpsnr(f, wl_slice)
            metrics['greyIRE'] = np.mean(f.output_to_ire(f.dspicture[wl_slice]))
        else:
            # There's a nice long burst at 50IRE block on field2 l13
            b50slice = f.lineslice_tbc(13, 36, 20)
            metrics['palVITSBurst50Level'] = rms(f.dspicture[b50slice]) / f.out_scale

        return metrics    

    def computeMetricsNTSC(self, metrics, f, fp = None):
        # check for a white flag - only on earlier discs, and only on first "frame" fields
        wf_slice = f.lineslice_tbc(11, 15, 40)
        if inrange(np.mean(f.output_to_ire(f.dspicture[wf_slice])), 92, 108):
            metrics['ntscWhiteFlagSNR'] = self.calcpsnr(f, wf_slice)

        # use line 19 to determine 0 and 70 IRE burst levels for MTF compensation later
        c = CombNTSC(f)

        level, phase, snr = c.calcLine19Info()
        if level is not None:
            #metrics['ntscLine19ColorLevel'] = level
            metrics['ntscLine19ColorPhase'] = phase
            metrics['ntscLine19ColorRawSNR'] = snr

        ire50_slice = f.lineslice_tbc(19, 36, 10)
        metrics['greyPSNR'] = self.calcpsnr(f, ire50_slice)
        metrics['greyIRE'] = np.mean(f.output_to_ire(f.dspicture[ire50_slice]))

        ire50_rawslice = f.lineslice(19, 36, 10)
        rawdata = f.rawdata[ire50_rawslice.start - int(self.rf.delays['video_white']):ire50_rawslice.stop - int(self.rf.delays['video_white'])]
        metrics['greyRFLevel'] = np.std(rawdata)
        
        if not f.isFirstField and fp is not None:
            cp = CombNTSC(fp)
            
            level3d, phase3d, snr3d = c.calcLine19Info(cp)
            #logging.info(level3d)
            if level3d is not None:
                metrics['ntscLine19Burst70IRE'] = level3d
                #metrics['ntscLine19Color3DPhase'] = phase3d
                metrics['ntscLine19Color3DRawSNR'] = snr3d

                sl_cburst = f.lineslice_tbc(19, 4.7+.8, 2.4)
                diff = (f.dspicture[sl_cburst].astype(float) - fp.dspicture[sl_cburst].astype(float))/2

                metrics['ntscLine19Burst0IRE'] = np.sqrt(2)*rms(diff)/f.out_scale

        return metrics    

    def computeMetrics(self, f, fp = None):
        if not self.curfield:
            raise ValueError("No decoded field to work with")

        system = f.rf.system
            
        metrics = {}

        if system == 'NTSC':
            self.computeMetricsNTSC(metrics, f, fp)
            whitelocs = [(20, 14, 12), (20, 52, 8), (13, 13, 15)]#, (20, 13, 2)]
        else:
            self.computeMetricsPAL(metrics, f, fp)
            whitelocs = [(19, 12, 8)]
        
        for l in whitelocs:
            wl_slice = f.lineslice_tbc(*l)
            #logging.info(l, np.mean(f.output_to_ire(f.dspicture[wl_slice])))
            if inrange(np.mean(f.output_to_ire(f.dspicture[wl_slice])), 90, 110):
                metrics['whiteSNR'] = self.calcpsnr(f, wl_slice)
                metrics['whiteIRE'] = np.mean(f.output_to_ire(f.dspicture[wl_slice]))

                rawslice = f.lineslice(*l)
                rawdata = f.rawdata[rawslice.start - int(self.rf.delays['video_white']):rawslice.stop - int(self.rf.delays['video_white'])]
                metrics['whiteRFLevel'] = np.std(rawdata)

                break
        
        # compute black line SNR.  For PAL line 22 is guaranteed to be blanked for a pure disk (P)SNR
        blackline = 14 if system == 'NTSC' else 22
        bl_slicetbc = f.lineslice_tbc(blackline, 12, 50)

        # these metrics handle various easily detectable differences between fields
        bl_slice = f.lineslice(blackline, 12, 50)

        delay = int(f.rf.delays['video_sync'])
        bl_sliceraw = slice(bl_slice.start - delay, bl_slice.stop - delay)
        metrics['blackLineRFLevel'] = np.std(f.rawdata[bl_sliceraw])

        metrics['blackLinePreTBCIRE'] = f.rf.hztoire(np.mean(f.data[0]['demod'][bl_slice]))
        metrics['blackLinePostTBCIRE'] = f.output_to_ire(np.mean(f.dspicture[bl_slicetbc]))

        metrics['blackLinePSNR'] = self.calcpsnr(f, bl_slicetbc)

        #sl_slice = f.lineslice(4, 35, 20)
        #sl_slicetbc = f.lineslice_tbc(4, 35, 20)
        #sl_sliceraw = slice(sl_slice.start - delay, sl_slice.stop - delay)

        # metrics['syncLevelPSNR'] = self.calcpsnr(f, sl_slicetbc)

        # metrics['syncRFLevel'] = np.std(f.rawdata[sl_sliceraw])

        # There is *always* enough data to determine the RF level differences from sync to black/0IRE
        # (but it isn't as consistent?)
        # metrics['syncToBlackRFRatio'] = metrics['syncRFLevel'] / metrics['blackLineRFLevel']

        if 'whiteRFLevel' in metrics:
            #metrics['syncToWhiteRFRatio'] = metrics['syncRFLevel'] / metrics['whiteRFLevel']
            metrics['blackToWhiteRFRatio'] = metrics['blackLineRFLevel'] / metrics['whiteRFLevel']

        metrics_rounded = {}

        for k in metrics.keys():
            digits = 1
            if 'Ratio' in k:
                digits = 4
            elif 'Burst' in k:
                digits = 3
            rounded = roundfloat(metrics[k], places=digits)
            if np.isfinite(rounded):
                metrics_rounded[k] = rounded

        return metrics_rounded

    def buildmetadata(self, f):
        prevfi = self.fieldinfo[-1] if len(self.fieldinfo) else None

        fi = {'isFirstField': True if f.isFirstField else False, 
              'syncConf': f.sync_confidence, 
              'seqNo': len(self.fieldinfo) + 1, 
              #'audioSamples': 0 if audio is None else int(len(audio) / 2),
              'diskLoc': np.round((self.fieldloc / self.bytes_per_field) * 10) / 10,
              'medianBurstIRE': roundfloat(f.burstmedian)}

        if self.doDOD:
            dropout_lines, dropout_starts, dropout_ends = f.dropout_detect()
            fi['dropOuts'] = {'fieldLine': dropout_lines, 'startx': dropout_starts, 'endx': dropout_ends}

        # This is a bitmap, not a counter
        decodeFaults = 0

        if f.rf.system == 'NTSC':
            fi['fieldPhaseID'] = f.fieldPhaseID

            if prevfi:
                if not ((fi['fieldPhaseID'] == 1 and prevfi['fieldPhaseID'] == 4) or
                        (fi['fieldPhaseID'] == prevfi['fieldPhaseID'] + 1)):
                    logging.warning('NTSC field phaseID sequence mismatch')
                    decodeFaults |= 2

        if prevfi is not None and prevfi['isFirstField'] == fi['isFirstField']:
            #logging.info('WARNING!  isFirstField stuck between fields')
            if inrange(fi['diskLoc'] - prevfi['diskLoc'], .95, 1.05):
                decodeFaults |= 1
                fi['isFirstField'] = not prevfi['isFirstField']
                fi['syncConf'] = 10
            else:
                logging.error('Skipping field')
                decodeFaults |= 4
                fi['syncConf'] = 0

        fi['decodeFaults'] = decodeFaults
        fi['vitsMetrics'] = self.computeMetrics(self.curfield, self.prevfield)

        self.frameNumber = None
        if f.isFirstField:
            self.firstfield = f
        else:
            # use a stored first field, in case we start with a second field
            if self.firstfield is not None:
                # process VBI frame info data
                self.frameNumber = self.decodeFrameNumber(self.firstfield, f)

                rawloc = np.floor((self.readloc / self.bytes_per_field) / 2)

                try:
                    if self.isCLV and self.earlyCLV: # early CLV
                        print("file frame %d early-CLV minute %d" % (rawloc, self.clvMinutes), file=sys.stderr)
                    elif self.isCLV and self.frameNumber is not None:
                        print("file frame %d CLV timecode %d:%.2d.%.2d frame %d" % (rawloc, self.clvMinutes, self.clvSeconds, self.clvFrameNum, self.frameNumber), file=sys.stderr)
                    elif self.frameNumber:
                        print("file frame %d CAV frame %d" % (rawloc, self.frameNumber), file=sys.stderr)
                    elif self.leadOut:
                        print("file frame %d lead out" % (rawloc), file=sys.stderr)
                    else:
                        print("file frame %d unknown" % (rawloc), file=sys.stderr)

                    if self.frameNumber is not None:
                        fi['frameNumber'] = int(self.frameNumber)

                    if self.isCLV and self.clvMinutes is not None:
                        fi['clvMinutes'] = int(self.clvMinutes)
                        if self.earlyCLV == False:
                            fi['clvSeconds'] = int(self.clvSeconds)
                            fi['clvFrameNr'] = int(self.clvFrameNum)
                except:
                    logging.warning("file frame %d : VBI decoding error" % (rawloc))

        return fi

    # seek support function
    def seek_getframenr(self, start):
        self.roughseek(start)

        for fields in range(10):
            self.fieldloc = self.fdoffset
            f, offset = self.decodefield()

            self.prevfield = self.curfield
            self.curfield = f
            self.fdoffset += offset

            if self.prevfield is not None and f is not None and f.valid:
                fnum = self.decodeFrameNumber(self.prevfield, self.curfield)

                if self.earlyCLV:
                    logging.error("Cannot seek in early CLV disks w/o timecode")
                    return None
                elif fnum is not None:
                    rawloc = np.floor((self.readloc / self.bytes_per_field) / 2)
                    logging.info('seeking: file loc {0} frame # {1}'.format(rawloc, fnum))
                    return fnum
        
        return False
        
    def seek(self, start, target):
        cur = start * 2
        
        logging.info("Beginning seek")

        if not sys.warnoptions:
            import warnings
            warnings.simplefilter("ignore")

        for retries in range(3):
            fnr = self.seek_getframenr(cur)
            cur = int((self.fieldloc / self.bytes_per_field))
            if fnr is None:
                return None
            else:
                if fnr == target:
                    logging.info("Finished seek")
                    print("Finished seeking, starting at frame", fnr, file=sys.stderr)
                    self.roughseek(cur)
                    return cur
                else:
                    cur += ((target - fnr) * 2) - 1

        print("Finished seeking, starting at frame", fnr, file=sys.stderr)

        return cur - 0

    def build_json(self, f):
        ''' build up the JSON structure for file output. '''
        jout = {}
        jout['pcmAudioParameters'] = {'bits':16, 'isLittleEndian': True, 'isSigned': True, 'sampleRate': 48000}

        vp = {}

        vp['numberOfSequentialFields'] = len(self.fieldinfo)
        
        vp['isSourcePal'] = True if f.rf.system == 'PAL' else False

        vp['fsc'] = int(f.rf.SysParams['fsc_mhz'] * 1000000)
        vp['fieldWidth'] = f.rf.SysParams['outlinelen']
        vp['sampleRate'] = vp['fsc'] * 4
        spu = vp['sampleRate'] / 1000000

        vp['black16bIre'] = np.float(f.hz_to_output(f.rf.iretohz(self.blackIRE)))
        vp['white16bIre'] = np.float(f.hz_to_output(f.rf.iretohz(100)))

        vp['fieldHeight'] = f.outlinecount

        badj = -1.4 # current burst adjustment as of 2/27/19, update when #158 is fixed!
        vp['colourBurstStart'] = np.round((f.rf.SysParams['colorBurstUS'][0] * spu) + badj)
        vp['colourBurstEnd'] = np.round((f.rf.SysParams['colorBurstUS'][1] * spu) + badj)
        vp['activeVideoStart'] = np.round((f.rf.SysParams['activeVideoUS'][0] * spu) + badj)
        vp['activeVideoEnd'] = np.round((f.rf.SysParams['activeVideoUS'][1] * spu) + badj)

        jout['videoParameters'] = vp
        
        jout['fields'] = self.fieldinfo.copy()

        return jout
