import datetime
import asyncio
import pyaudio
from pydub import AudioSegment, playback

from utils.settings import settings
import utils.utils as utils

MICROPHONE_TIMEOUT_SECONDS = 120.0

# This represents stuff connected to the local machine like playing/recording audio and clipboard grabbing etc

class LocalMachine():
	mic_lock: asyncio.Lock = asyncio.Lock()
	play_lock: asyncio.Lock = asyncio.Lock()
	audio: pyaudio.PyAudio = None

	def init_audio(self):
		if self.audio is not None:
			self.audio.terminate()
		self.audio = pyaudio.PyAudio()
		

	async def _play_wav(self, decoded_song, lock_set=False):
		if lock_set:
			await utils.run_async(lambda: playback.play(decoded_song))
			self.play_lock.release()
		else:
			async with self.play_lock:
				await utils.run_async(lambda: playback.play(decoded_song))

	async def play_wav(self, filename, wait=True):
		song = AudioSegment.from_wav(filename)
		if wait:
			await self._play_wav(song)
		else:
			await self.play_lock.acquire()
			asyncio.ensure_future(self._play_wav(song, True))

	# end the microphone recording
	async def record_microphone_stop(self):
		if self.mic_lock.locked():
			self.mic_lock.release()

	# start recording and wait until the recording has finished
	async def record_microphone(self):
		if self.mic_lock.locked():
			self.mic_lock.release()
		await self.mic_lock.acquire()
		self.init_audio()
		print("listening...")


		device_id_map = {}
		# check devices connected
		info = self.audio.get_host_api_info_by_index(0)
		numdevices = info.get('deviceCount')
		for i in range(0, numdevices):
			if (self.audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
				# print(i, " - ", audio.get_device_info_by_host_api_device_index(0, i).get('name'))
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
						print(f"listening via: '{name}'")
						break
		
		audio_queue = asyncio.Queue()
		def stream_callback(input_data, frame_count, time_info, status_flags):
			audio_queue.put_nowait(input_data)

			return (input_data, pyaudio.paContinue)

		recording_channels = 1
		recording_rate = 16000
		stream = self.audio.open(
			format = pyaudio.paInt16,
			channels = recording_channels,
			rate = recording_rate,
			input = True,
			frames_per_buffer = 8000,
			input_device_index=audio_device_index,
			stream_callback = stream_callback
		)

		stream_starttime = datetime.datetime.now()
		stream.start_stream()

		try:
			await asyncio.wait_for(self.mic_lock.acquire(), timeout = MICROPHONE_TIMEOUT_SECONDS)
			self.mic_lock.release()
		except asyncio.exceptions.TimeoutError:
			print("ignoring: recording too long")
			stream.stop_stream()
			stream.close()
			return None
		
		await asyncio.sleep(0.2) # finish recording for couple hundred miliseconds

		stream.stop_stream()
		stream.close()
		
		elapsed_time = datetime.datetime.now() - stream_starttime
		if elapsed_time < datetime.timedelta(seconds=1):
			print("ignoring: wasnt recording long enough")
			return None

		# Create an AudioSegment to store the audio data
		audio_data = AudioSegment.silent(duration=0)

		# Keep retrieving audio data from the queue until it is empty
		while not audio_queue.empty():
			audio_data += AudioSegment(audio_queue.get_nowait(), sample_width=2, channels=recording_channels, frame_rate=recording_rate)

		return audio_data