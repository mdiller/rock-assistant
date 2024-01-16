import re
import asyncio
import elevenlabs
from obsidian import AssistantConfig
from openai import OpenAI
from pydub import AudioSegment

from utils.settings import settings
from utils.cache import cache
import utils.utils as utils

tts_file_lock = asyncio.Lock()
TTS_TEMP_MP3 = settings.resource("sounds/_tts.mp3")
VOICE_SEPARATOR = ": "
OPENAI_VOICE_KEYWORD = "OpenAI"
ELEVENLABS_VOICE_KEYWORD = "ElevenLabs"

class AudioApi():
	def __init__(self, openai_client: OpenAI, config: AssistantConfig):
		self.elevenlabs_voices = elevenlabs.voices() # TODO: make so this doesnt break when we've got no internet?
		self.elevenlabs_voice = self.elevenlabs_voices[0]
		self.openai_voices = [ "alloy", "echo", "fable", "onyx", "nova", "shimmer" ]
		self.openai_client = openai_client
		self.config = config

		# GENERATE VOICES
		VOICES_LIST = []
		for voice in self.openai_voices:
			VOICES_LIST.append(f"{OPENAI_VOICE_KEYWORD}{VOICE_SEPARATOR}{voice}")
		for voice in self.elevenlabs_voices:
			VOICES_LIST.append(f"{ELEVENLABS_VOICE_KEYWORD}{VOICE_SEPARATOR}{voice.name}")

		# EDIT CONFIG WITH UPDATES TO VOICES
		voice_config_options = ",\n".join(map(lambda v: f"\toption({v})", VOICES_LIST))
		voice_list_pattern = re.compile("(?<=```meta-bind\nINPUT\[inlineSelect\(\n)[\s\S]*(?=\n\):tts_voice\]\n```)", re.MULTILINE | re.DOTALL)
		config.content = re.sub(voice_list_pattern, voice_config_options, config.content)
		config.write()


	async def transcribe(self, filename):
		audio_file = open(filename, "rb")
		response = await utils.run_async(lambda: self.openai_client.audio.transcriptions.create(
			model="whisper-1",
			file=audio_file,
			language="en" # english
		))
		return response.text

	def openai_tts(self, text):
		openai_voice_name = self.config.tts_voice.replace(f"{OPENAI_VOICE_KEYWORD}{VOICE_SEPARATOR}", "")
		response = self.openai_client.audio.speech.create(
			model="tts-1",
			voice=openai_voice_name,
			input=text
		)
		response.stream_to_file(TTS_TEMP_MP3)
		return TTS_TEMP_MP3

	def elevenlabs_tts(self, text):
		elevenlabs_voice_name = self.config.tts_voice.replace(f"{ELEVENLABS_VOICE_KEYWORD}{VOICE_SEPARATOR}", "")
		if self.elevenlabs_voice is None or elevenlabs_voice_name != self.elevenlabs_voice.name:
			for voice in self.elevenlabs_voices:
				if voice.name == elevenlabs_voice_name:
					self.elevenlabs_voice = voice
		audio = elevenlabs.generate(text=text, voice=self.elevenlabs_voice)
		elevenlabs.save(audio, TTS_TEMP_MP3)
		return TTS_TEMP_MP3

	async def generate_tts(self, text):
		if text == True:
			return settings.resource("sounds/success.wav")
		uri = f"tts:{self.config.tts_voice}:{text}"
		filename = await cache.get_filename(uri)
		if not filename:
			print("tts...")
			filename = await cache.new(uri, "wav")
			loop = asyncio.get_event_loop()
			async with tts_file_lock:
				if self.config.tts_voice.startswith(OPENAI_VOICE_KEYWORD):
					mp3_file = await utils.run_async(lambda: self.openai_tts(text))
				elif self.config.tts_voice.startswith(ELEVENLABS_VOICE_KEYWORD):
					mp3_file = await utils.run_async(lambda: self.elevenlabs_tts(text))
				else:
					raise Exception("Unsupported voice type")
			
			sound = AudioSegment.from_mp3(mp3_file)
			sound.export(filename, format="wav")
		else:
			print("tts(cached)")
		return filename