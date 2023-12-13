import datetime
import asyncio
import pyaudio
from pydub import AudioSegment, playback

from utils.settings import settings
import utils.utils as utils

MICROPHONE_TIMEOUT_SECONDS = 30.0

# This represents stuff connected to the local machine like playing/recording audio and clipboard grabbing etc

class LocalMachine():
	mic_lock: asyncio.Lock = asyncio.Lock()
	play_lock: asyncio.Lock = asyncio.Lock()

	async def _play_wav(self, decoded_song):
		async with self.play_lock:
			await utils.run_async(lambda: playback.play(decoded_song))

	async def play_wav(self, filename, wait=True):
		song = AudioSegment.from_wav(filename)
		task = self._play_wav(song)
		if wait:
			await task
		else:
			asyncio.ensure_future(task)

	# end the microphone recording
	async def record_microphone_stop(self):
		if self.mic_lock.locked():
			self.mic_lock.release()

	# start recording and wait until the recording has finished
	async def record_microphone(self):
		if self.mic_lock.locked():
			self.mic_lock.release()
		await self.mic_lock.acquire()
		print("listening...")
		audio = pyaudio.PyAudio()
		
		audio_queue = asyncio.Queue()
		def stream_callback(input_data, frame_count, time_info, status_flags):
			audio_queue.put_nowait(input_data)

			return (input_data, pyaudio.paContinue)

		recording_channels = 1
		recording_rate = 16000
		stream = audio.open(
			format = pyaudio.paInt16,
			channels = recording_channels,
			rate = recording_rate,
			input = True,
			frames_per_buffer = 8000,
			stream_callback = stream_callback
		)

		stream_starttime = datetime.datetime.now()
		stream.start_stream()

		# play wake sound
		await self.play_wav(settings.resource("sounds/wake_sound.wav"), wait=False)

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