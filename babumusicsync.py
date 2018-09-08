import sys
import time
from Queue import Queue
from ctypes import POINTER, c_ubyte, c_void_p, c_ulong, cast
from dotstar import Adafruit_DotStar
import numpy as np
import numpy.fft as fft
numPixels = 300 # Number of LEDs in strip

strip   = Adafruit_DotStar(numPixels)

strip.begin()           # Initialize pins for output
strip.setBrightness(240) # Limit brightness to ~1/4 duty cycle

# From https://github.com/Valodim/python-pulseaudio
from pulseaudio.lib_pulseaudio import *

# edit to match your sink
SINK_NAME = 'alsa_output.0.analog-stereo'
METER_RATE = 344
MAX_SAMPLE_VALUE = 127
DISPLAY_SCALE = 2
MAX_SPACES = MAX_SAMPLE_VALUE >> DISPLAY_SCALE
SAMPLES_PER_FFT = (METER_RATE * numPixels / 1000)

def rainbowCycle(wait):
        for j in range(0,256*5):
                for i in range(0,numPixels):
                        strip.setPixelColor(i, Wheel(((i * 256 / numPixels) + j) & 255))
                strip.show()
                time.sleep(wait)

def Wheel(WheelPos):
        WheelPos = 255 - WheelPos
        if WheelPos < 85:
                return strip.Color(255 - WheelPos * 3, 0, WheelPos * 3)
        elif WheelPos < 170:
                WheelPos -= 85;
                return strip.Color(0, WheelPos * 3, 255 - WheelPos * 3);
        WheelPos -= 170;
        return strip.Color(WheelPos * 3, 255 - WheelPos * 3, 0);

class PeakMonitor(object):

    def __init__(self, sink_name, rate):
        self.sink_name = sink_name
        self.rate = rate

        # Wrap callback methods in appropriate ctypefunc instances so
        # that the Pulseaudio C API can call them
        self._context_notify_cb = pa_context_notify_cb_t(self.context_notify_cb)
        self._sink_info_cb = pa_sink_info_cb_t(self.sink_info_cb)
        self._stream_read_cb = pa_stream_request_cb_t(self.stream_read_cb)

        # stream_read_cb() puts peak samples into this Queue instance
        self._samples = Queue()

        # Create the mainloop thread and set our context_notify_cb
        # method to be called when there's updates relating to the
        # connection to Pulseaudio
        _mainloop = pa_threaded_mainloop_new()
        _mainloop_api = pa_threaded_mainloop_get_api(_mainloop)
        context = pa_context_new(_mainloop_api, 'peak_demo')
        pa_context_set_state_callback(context, self._context_notify_cb, None)
        pa_context_connect(context, None, 0, None)
        pa_threaded_mainloop_start(_mainloop)

    def __iter__(self):
        while True:
            yield self._samples.get()

    def context_notify_cb(self, context, _):
        state = pa_context_get_state(context)

        if state == PA_CONTEXT_READY:
            print "Pulseaudio connection ready..."
            # Connected to Pulseaudio. Now request that sink_info_cb
            # be called with information about the available sinks.
            o = pa_context_get_sink_info_list(context, self._sink_info_cb, None)
            pa_operation_unref(o)

        elif state == PA_CONTEXT_FAILED :
            print "Connection failed"

        elif state == PA_CONTEXT_TERMINATED:
            print "Connection terminated"

    def sink_info_cb(self, context, sink_info_p, _, __):
        if not sink_info_p:
            return

        sink_info = sink_info_p.contents
        print '-'* 60
        print 'index:', sink_info.index
        print 'name:', sink_info.name
        print 'description:', sink_info.description

        if sink_info.name == self.sink_name:
            # Found the sink we want to monitor for peak levels.
            # Tell PA to call stream_read_cb with peak samples.
            print
            print 'setting up peak recording using', sink_info.monitor_source_name
            print
            samplespec = pa_sample_spec()
            samplespec.channels = 1
            samplespec.format = PA_SAMPLE_U8
            samplespec.rate = self.rate

            pa_stream = pa_stream_new(context, "peak detect demo", samplespec, None)
            pa_stream_set_read_callback(pa_stream,
                                        self._stream_read_cb,
                                        sink_info.index)
            pa_stream_connect_record(pa_stream,
                                     sink_info.monitor_source_name,
                                     None,
                                     PA_STREAM_PEAK_DETECT)

    def stream_read_cb(self, stream, length, index_incr):
        data = c_void_p()
        pa_stream_peek(stream, data, c_ulong(length))
        data = cast(data, POINTER(c_ubyte))
        for i in xrange(length):
            # When PA_SAMPLE_U8 is used, samples values range from 128
            # to 255 because the underlying audio data is signed but
            # it doesn't make sense to return signed peaks.
            self._samples.put(data[i] - 128)
        pa_stream_drop(stream)

    def get_samples_len(self):
        return self._samples.qsize()
    def get_samples(amount):
        samples = []
        for i in range(0, amount):
            samples.append(self._samples.get() >> DISPLAY_SCALE)
        return samples

def map(value, from_min, from_max, to_min, to_max):
	return ((to_max-to_min) * ((value-from_min)/(from_max-from_min)))+to_min
# Return a color that is either in red, orange, yellow, green, blue, or purple range
def fourier_pixel_color(intensity, max_intensity):
    color_value = int((intensity / max_intensity) * 1020)
    if color_value <= 204:
        return (255, 51 + color_value, 51)
    elif color_value <= 408:
        return (51 + (408 - color_value), 255, 51)
    elif color_value <= 612:
        return (51, 255, 51 + (color_value - 408))
    elif color_value <= 816:
        return (51, 816 - color_value + 51, 255)
    else:
        return (51 + color_value - 816, 255)
def main():
    j = 0
    monitor = PeakMonitor(SINK_NAME, METER_RATE)
    while True:
        if monitor.get_samples_len() >= SAMPLES_PER_FFT:
            samples = monitor.get_samples(SAMPLES_PER_FFT)
            fourier = abs(fft.fft(np.array(samples)))
            max_intensity = max(fourier)
            led_bin_size = (numPixels // len(fourier))
            bins = fft.fftfreq(SAMPLES_PER_FFT)
            for fourier_index in range(0, len(fourier)):
                color_tuple = fourier_pixel_color(fourier[fourier_index], max_intensity)
                for i in range(led_bin_size * fourier_index, led_bin_size * (fourier_index + 1)):
                    strip.setPixelColor(i, strip.Color(color_tuple))
            strip.show()
    '''
	for sample in monitor:

		if sample == 0:
			rainbowCycle(j, 0.01)
			j += 1
			if j >= 256*5:
				j = 0
		else:

		sample = ((float(sample))/120)*280
		for i in range(0,numPixels/2+1):
			if i < sample*1.5:
				strip.setPixelColor((i+(numPixels/2)), strip.Color(0,255,0));
         			strip.setPixelColor(((numPixels/2)-i), strip.Color(0,255,0));
			elif i < (sample+66):
				strip.setPixelColor((i+(numPixels/2)), strip.Color(255,0,0));
         			strip.setPixelColor(((numPixels/2)-i), strip.Color(255,0,0));
			else:
				strip.setPixelColor((i+(numPixels/2)), strip.Color(0,0,255));
         			strip.setPixelColor(((numPixels/2)-i), strip.Color(0,0,255));
		strip.show()
		print '%3d\r' % (sample),
        	sys.stdout.flush()
        '''
if __name__ == '__main__':
	main()
