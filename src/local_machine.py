import datetime
import asyncio
import pyaudio
from pydub import AudioSegment, playback
from gui.gui import AssistantGui
import pyperclip

from utils.settings import settings
import utils.utils as utils
from pynput.keyboard import Key, Controller

MICROPHONE_TIMEOUT_SECONDS = 15 * 60.0

# This represents stuff connected to the local machine like playing/recording audio and clipboard grabbing etc

class LocalMachine():
	mic_lock: asyncio.Lock = asyncio.Lock()
	play_lock: asyncio.Lock = asyncio.Lock()
	audio: pyaudio.PyAudio = None

	def __init__(self):
		self.gui: AssistantGui = None
		self.frames_saved: int = 0

	def init_audio(self, logger):
		if self.audio is None:
			logger.log("initializing audio...")
			self.audio = pyaudio.PyAudio()
			logger.log("audio initialized!")
		# self.audio.terminate()

	async def _play_wav(self, filename, lock_set=False):
		decoded_song = await utils.run_async(lambda: AudioSegment.from_wav(filename))
		decoded_song -= 15 # turn volume down by 15 db
		if lock_set:
			await utils.run_async(lambda: playback.play(decoded_song))
			self.play_lock.release()
		else:
			async with self.play_lock:
				await utils.run_async(lambda: playback.play(decoded_song))

	async def play_wav(self, filename, wait=True):
		if wait:
			await self._play_wav(filename)
		else:
			await self.play_lock.acquire()
			asyncio.ensure_future(self._play_wav(filename, True))

	# end the microphone recording
	async def record_microphone_stop(self):
		if self.mic_lock.locked():
			self.mic_lock.release()
	
	def get_clipboard_text(self) -> str:
		return pyperclip.paste()
	
	def set_clipboard_text(self, text: str):
		return pyperclip.copy(text)
	
	# press paste and enter
	def paste_and_enter(self):
		keyboard = Controller()

		keyboard.press(Key.ctrl.value)
		keyboard.press("v")
		keyboard.release("v")
		keyboard.release(Key.ctrl.value)

		keyboard.press(Key.enter.value)
		keyboard.release(Key.enter.value)

	# start recording and wait until the recording has finished
	async def record_microphone(self, logger):
		record_method_entered = datetime.datetime.now()
		if self.mic_lock.locked():
			self.mic_lock.release()
		await self.mic_lock.acquire()
		self.init_audio(logger)

		logger.log("getting audio device data")
		device_id_map = {}
		# check devices connected
		info = self.audio.get_host_api_info_by_index(0)
		numdevices = info.get('deviceCount')
		for i in range(0, numdevices):
			if (self.audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
				# logger.log(i, " - ", audio.get_device_info_by_host_api_device_index(0, i).get('name'))
				device_id_map[self.audio.get_device_info_by_host_api_device_index(0, i).get('name')] = i
		
		microphone_priorities = [
			"HD Web Camera",
			"Headset Microphone (Arctis"
		]
		audio_device_index = None
		for devicenamepart in microphone_priorities:
			if audio_device_index is None:
				for name in device_id_map:
					if devicenamepart in name:
						audio_device_index = device_id_map[name]
						logger.log(f"listening via: '{name}'")
						break
		
		self.frames_saved = 0
		audio_queue = asyncio.Queue()
		def stream_callback(input_data, frame_count, time_info, status_flags):
			audio_queue.put_nowait(input_data)
			self.frames_saved += frame_count

			return (input_data, pyaudio.paContinue)

		recording_channels = 1
		recording_rate = 16000
		stream = self.audio.open(
			format = pyaudio.paInt16,
			channels = recording_channels,
			rate = recording_rate,
			input = True,
			frames_per_buffer = 4000,
			input_device_index=audio_device_index,
			stream_callback = stream_callback
		)
		# this initializating of the stream is what takes like 100 ms sometimes

		stream_starttime = datetime.datetime.now()
		stream.start_stream()
		
		logger.log("waiting...")

		try:
			await asyncio.wait_for(self.mic_lock.acquire(), timeout = MICROPHONE_TIMEOUT_SECONDS)
			self.mic_lock.release()

			# catch back up to real time before stopping
			seconds_requested = (datetime.datetime.now() - record_method_entered).total_seconds()
			seconds_recorded = self.frames_saved / recording_rate
			logger.log(f"waiting for {seconds_requested - seconds_recorded:.2f}s of audio to streaming in")
			while seconds_recorded < seconds_requested:
				await asyncio.sleep(0.1)
				seconds_recorded = self.frames_saved / recording_rate


		except asyncio.exceptions.TimeoutError:
			logger.log("ignoring: recording too long")
			stream.stop_stream()
			stream.close()
			return None
		
		# await asyncio.sleep(0.1) # finish recording for 100 ms incase we un-pressed to early

		stream.stop_stream()
		stream.close()

		logger.log(f"{self.frames_saved / recording_rate:.2f} seconds of audio recorded")
		
		elapsed_time = datetime.datetime.now() - stream_starttime
		if elapsed_time < datetime.timedelta(seconds=2):
			logger.log("ignoring: wasnt recording long enough")
			return None

		# Create an AudioSegment to store the audio data
		audio_data = AudioSegment.silent(duration=0)

		# Keep retrieving audio data from the queue until it is empty
		while not audio_queue.empty():
			audio_data += AudioSegment(audio_queue.get_nowait(), sample_width=2, channels=recording_channels, frame_rate=recording_rate)

		return audio_data