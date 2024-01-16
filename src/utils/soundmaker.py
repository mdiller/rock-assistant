'''''
PROMPT:

[- Used So Far: 1.5398¢ | 7675 tokens -]
'''''
import typing
import numpy as np
from scipy.io.wavfile import write
from pydub import AudioSegment, playback
import librosa

WAV_FILE_NAME = "_temp.wav"
SAMPLE_RATE = 44100

# EASE_PLINK = lambda t, duration: np.exp(-4 * np.log(10) * t / duration)
EASE_EXP_IN = lambda t, duration: 1 - np.exp(-10 * t / duration)
EASE_EXP_OUT = lambda t, duration: 1 - np.exp(-10 * (duration - t) / duration)
EASE_PLINK_OLD = lambda t, duration: np.exp(-5 * t / duration)
EASE_PLINKFAST = lambda t, duration: np.exp(-10 * t / duration)
EASE_LINEAR = lambda t, duration: .5 * t / duration

def EASE_EXP_IN_OUT(t, duration):
	result = EASE_EXP_IN(t, duration)
	result *= EASE_EXP_OUT(t, duration)
	return result

def EASE_PLINK(t, duration):
	result = np.exp(-5 * t / duration)
	fader = 1 - np.exp(-10 * (duration - t) / duration)
	fader -= np.min(fader)
	fader /= np.max(fader)
	result *= fader
	return result

def EASE_ELASTIC(t, duration):
	amplitude = 1
	period = 0.3
	p = period / (2 * np.pi) * np.arcsin(1 / amplitude)
	result = amplitude * np.power(2, -10 * t / duration) * np.sin(((t / duration) - p) * (2 * np.pi) / period) + 1
	result /= np.max(result)
	result *= EASE_EXP_OUT(t, duration)
	return result

class WavBuilder():
	def __init__(self):
		self.waveform = np.array([])
		self.current_phase = 0

	def get_t(self, duration):
		return np.linspace(0, duration, int(duration * SAMPLE_RATE), False)
	
	def add_data(self, data):
		pass

	def add_slide(self, note1: str, note2: str, duration: float, ease_func = None):
		frequency_start = librosa.note_to_hz(note1)
		frequency_end = librosa.note_to_hz(note2)
		t = self.get_t(duration)
		frequency = np.linspace(frequency_start, frequency_end, len(t))

		# Calculate phase increment per sample
		phase_increment = 2 * np.pi * frequency / SAMPLE_RATE

		# Generate the waveform with phase continuity
		note = np.zeros_like(t)
		for i in range(len(t)):
			self.current_phase += phase_increment[i]
			note[i] = np.sin(self.current_phase)

			# Keep the phase in the range [-pi, pi] or [0, 2*pi] to avoid numerical issues
			if self.current_phase > 2 * np.pi:
				self.current_phase -= 2 * np.pi

		if ease_func:
			note *= ease_func(t, duration)
		self.waveform = np.concatenate((self.waveform, note))
	
	def add_note(self, note: str, duration: float, ease_func = None):
		frequency = librosa.note_to_hz(note)
		t = self.get_t(duration)
		
		phase_increment = 2 * np.pi * frequency / SAMPLE_RATE
		
		# Generate the waveform with phase continuity
		note = np.zeros_like(t)
		for i in range(len(t)):
			self.current_phase += phase_increment
			note[i] = np.sin(self.current_phase)

			# Keep the phase in the range [-pi, pi] or [0, 2*pi] to avoid numerical issues
			if self.current_phase > 2 * np.pi:
				self.current_phase -= 2 * np.pi

		# note = np.sin(2 * np.pi * frequency * self.get_t_sin(duration))
		if ease_func:
			note *= ease_func(t, duration)
		
		self.waveform = np.concatenate((self.waveform, note))
	
	def add_chord(self, notes: typing.List[str], duration: float, ease_func = None):
		t = self.get_t(duration)
		result = np.zeros(int(duration * SAMPLE_RATE))
		for note in notes:
			frequency = librosa.note_to_hz(note)
			note = np.sin(2 * np.pi * frequency * t)
			result += note
		result /= len(notes)
		if ease_func:
			result *= ease_func(t, duration)
		self.waveform = np.concatenate((self.waveform, result))
		
	def add_silence(self, duration: float):
		note = np.zeros(int(duration * SAMPLE_RATE))
		self.waveform = np.concatenate((self.waveform, note))

	def slide_notes(self, notes: typing.List[str], duration, slide_duration):
		last_note = None
		for note in notes:
			note_dur = duration
			if last_note is not None:
				note_dur -= slide_duration
				self.add_slide(last_note, note, slide_duration)
			self.add_note(note, note_dur)
			last_note = note
		
		# if ease_func:
		# 	t = self.get_t(total_duration)
		# 	result *= ease_func(t, duration)
		# self.waveform = np.concatenate((self.waveform, result))

	def apply_ease(self, ease_func):
		duration = self.waveform.shape[0] / SAMPLE_RATE
		t = np.linspace(0, duration, self.waveform.shape[0], False)
		if ease_func:
			self.waveform *= ease_func(t, duration)

	def save_and_play(self, filename):
		# Normalize waveform to 16-bit range
		waveform = self.waveform
		waveform *= 32767 / np.max(np.abs(waveform))
		waveform = waveform.astype(np.int16)

		# Trim trailing 0's
		non_zero_indices = np.nonzero(waveform)[0]
		first_non_zero = non_zero_indices.min()
		last_non_zero = non_zero_indices.max() + 1
		waveform = waveform[first_non_zero:last_non_zero]

		write(filename, SAMPLE_RATE, waveform)
		audio = AudioSegment.from_wav(filename)
		playback.play(audio)
		self.waveform = np.array([])

wav_builder = WavBuilder()
tempo = 0.2

# wav_builder.add_slide("C4", "E4", tempo, EASE_EXP_IN)
# wav_builder.add_note("C5", tempo * 2, EASE_PLINK)
# wav_builder.add_chord(["C5", "E4", "G4"], tempo * 2, EASE_PLINK)

# wav_builder.add_slide("D4", "E4", tempo, EASE_EXP_IN)
# wav_builder.add_note("E4", tempo)
# wav_builder.add_slide("E4", "D4", tempo, EASE_EXP_OUT)

# wav_builder.slide_notes(["C4", "E4", "G4", "C5"], tempo, tempo / 8)
# wav_builder.apply_ease(EASE_EXP_IN_OUT)


# wav_builder.slide_notes(["C4", "Eb4", "F4", "Gb4", "G4", "Bb4", "C5", "Bb4", "G4", "Gb4", "F4", "Eb4", "C4"], tempo, tempo / 8)
# wav_builder.apply_ease(EASE_EXP_IN_OUT)


# wav_builder.slide_notes(["C4", "C5", "C4"], tempo, tempo / 8)
# wav_builder.add_note("C4", tempo * 2)
# wav_builder.slide_notes(["C4", "C5", "C4"], tempo, tempo / 8)
# wav_builder.apply_ease(EASE_EXP_IN_OUT)

# wav_builder.add_slide("C4", "F4", tempo * .3, EASE_EXP_IN)
# wav_builder.add_note("F4", tempo * .7, EASE_EXP_OUT)
# wav_builder.add_note("C5", tempo * 2, EASE_PLINK)

# notes = [ "F4", "C5", "F5" ]
# notes = [ "F3", "C4", "C5" ]
# notes = [ "G4", "C5", "G5" ]

# wav_builder.add_slide(notes[0], notes[1], tempo * .3, EASE_EXP_IN)
# wav_builder.add_note(notes[1], tempo * .7, EASE_EXP_OUT)
# wav_builder.add_note(notes[2], tempo * 2, EASE_PLINK)



# GOOD WAKE
wav_builder.add_slide("G3", "C4", tempo, EASE_EXP_IN)
wav_builder.add_note("G4", tempo * 2, EASE_PLINK)
wav_builder.save_and_play("resource/sounds/wake.wav")

# GOOD UNWAKE
wav_builder.add_slide("G4", "E4", tempo, EASE_EXP_IN)
wav_builder.add_note("C4", tempo * 2, EASE_PLINK)
wav_builder.save_and_play("resource/sounds/unwake.wav")

# SUCCESS
wav_builder.add_note("C5", tempo * 2, EASE_PLINK)
wav_builder.save_and_play("resource/sounds/success.wav")

# IGNORE
wav_builder.add_note("C4", tempo * 2, EASE_PLINK)
wav_builder.save_and_play("resource/sounds/ignore.wav")

# ERROR
wav_builder.add_slide("A4", "D5", tempo, EASE_EXP_IN)
wav_builder.add_note("A4", tempo * 2, EASE_PLINK)
wav_builder.save_and_play("resource/sounds/error.wav")

# TASK_START
wav_builder.add_note("G4", tempo * 2, EASE_PLINK)
wav_builder.save_and_play("resource/sounds/task_start.wav")



# wav_builder.add_note("D5", tempo * 2, EASE_PLINK)
# wav_builder.add_note("A4", tempo * 2, EASE_PLINK)

# # wav_builder.add_note(notes[0], tempo / 2, EASE_PLINK)
# wav_builder.add_note(notes[0], tempo, EASE_LINEAR)
# wav_builder.add_note(notes[1], tempo * 2, EASE_PLINK)


# wav_builder.add_slide("C4", "E4", tempo, EASE_EXP_IN)
# wav_builder.add_note("C4", tempo, EASE_EXP_IN)
# wav_builder.add_slide("C5", "E5", tempo * 2, EASE_PLINK)
# wav_builder.add_note("C5", tempo * 2, EASE_PLINK)

# wav_builder.add_note("D4", tempo)
# wav_builder.add_slide("D4", "E4", tempo, EASE_EXP_IN)
# wav_builder.add_note("E4", tempo)
# wav_builder.add_note("G5", tempo * 2, EASE_PLINK)
# wav_builder.add_note("C5", tempo * 1.5, EASE_PLINK)
# wav_builder.add_slide("E4", "C5", tempo / 4)  
# wav_builder.add_note("E5", tempo * 1.5, EASE_PLINK)

# wav_builder.add_slide("C4", "E4", tempo, EASE_EXP_IN)
# wav_builder.add_note("C5", tempo * 2, EASE_PLINK)
# wav_builder.add_silence(tempo * 4)
# # wav_builder.add_slide("C5", "E4", tempo, EASE_EXP_IN)
# wav_builder.add_note("G4", tempo * 2, EASE_PLINK)

# wav_builder.add_silence(tempo * 4)
# wav_builder.add_note("F4", tempo, EASE_EXP_IN)
# wav_builder.add_note("C5", tempo * 2, EASE_PLINK)
# wav_builder.add_silence(tempo * 4)
# wav_builder.add_note("C5", tempo, EASE_EXP_IN)
# wav_builder.add_note("F4", tempo * 2, EASE_PLINK)



# wav_builder.save_and_play(WAV_FILE_NAME)


# STUFF FOR VISUALIZING EASE FUNCTIONS

# import numpy as np
# import matplotlib.pyplot as plt

# # Parameters
# duration = 5  # duration in seconds
# SAMPLE_RATE = 100  # sample rate per second

# # Generating the time array
# t = np.linspace(0, duration, int(duration * SAMPLE_RATE), False)

# # Plotting
# plt.figure(figsize=(12, 6))

# plt.subplot(1, 2, 1)
# plt.plot(t, EASE_PLINK(t, duration))
# plt.title("EASE_PLINK")
# plt.xlabel("Time (seconds)")
# plt.ylabel("Value")
# plt.ylim(0, 1)

# plt.subplot(1, 2, 2)
# plt.plot(t, EASE_PLINK3(t, duration))
# plt.title("EASE_PLINK3")
# plt.xlabel("Time (seconds)")
# plt.ylabel("Value")
# plt.ylim(0, 1)

# plt.tight_layout()
# plt.show()
