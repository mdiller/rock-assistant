import asyncio
import conversator as conv
from pydub import AudioSegment
from pydub.playback import play
import pyaudio
import os
import asyncio
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor
import winsound
import re
import openai
import datetime
import elevenlabs
import json
from obsidian import Obsidian, ObsidianFile, AssistantConfig
from collections import OrderedDict

# used this service for finding a wake sound https://www.voicy.network/official-soundboards/sfx

conversator = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(SCRIPT_DIR, "sounds")

miniconfig = {}
with open(os.path.join(SCRIPT_DIR, "miniconfig.json"), "r") as f:
	miniconfig = json.loads(f.read())

openai_client = openai.OpenAI(api_key=miniconfig["openai"])
elevenlabs.set_api_key(miniconfig["elevenlabs"])

# the root location for obsidian
OBSIDIAN_ROOT = miniconfig["obsidian_root"]
OBSIDIAN_HELPER_PATH = os.path.join(OBSIDIAN_ROOT, miniconfig["obsidian_helper_path"])


obsidian = Obsidian(OBSIDIAN_ROOT)
config = AssistantConfig(os.path.join(OBSIDIAN_HELPER_PATH, "assistant_config.md"))


elevenlabs_voices = elevenlabs.voices()
elevenlabs_voice = elevenlabs_voices[0]

def get_sound_path(filename):
	return os.path.join(SOUNDS_DIR, filename)

# GENERATE VOICES
VOICE_SEPARATOR = ": "
OPENAI_VOICE_KEYWORD = "OpenAI"
ELEVENLABS_VOICE_KEYWORD = "ElevenLabs"
VOICES_LIST = []
openai_voices = [ "alloy", "echo", "fable", "onyx", "nova", "shimmer" ]
for voice in openai_voices:
	VOICES_LIST.append(f"{OPENAI_VOICE_KEYWORD}{VOICE_SEPARATOR}{voice}")
for voice in elevenlabs_voices:
	VOICES_LIST.append(f"{ELEVENLABS_VOICE_KEYWORD}{VOICE_SEPARATOR}{voice.name}")

# EDIT CONFIG WITH UPDATES TO VOICES
voice_config_options = ",\n".join(map(lambda v: f"\toption({v})", VOICES_LIST))
voice_list_pattern = re.compile("(?<=```meta-bind\nINPUT\[inlineSelect\(\n)[\s\S]*(?=\n\):tts_voice\]\n```)", re.MULTILINE | re.DOTALL)
config.content = re.sub(voice_list_pattern, voice_config_options, config.content)
config.write()

mic_lock: asyncio.Lock
mic_lock = asyncio.Lock()

async def mic_start(request):
	global conversator
	print("WEB> /mic_start")
	if mic_lock.locked():
		mic_lock.release()
	await mic_lock.acquire()
	conversator = None
	main_task = asyncio.create_task(main_chat())
	return web.Response(text="You called GET on /mic_start")

async def mic_start_continue(request):
	print("WEB> /mic_start_continue")
	if mic_lock.locked():
		mic_lock.release()
	await mic_lock.acquire()
	main_task = asyncio.create_task(main_chat())
	return web.Response(text="You called GET on /mic_start_continue")

async def mic_stop(request):
	print("WEB> /mic_stop")
	if mic_lock.locked():
		mic_lock.release()
	return web.Response(text="You called GET on /mic_stop")

async def run(request):
	print("WEB> /run")
	main_task = asyncio.create_task(main_run())
	return web.Response(text="You called GET on /run")

async def webserver():
	app = web.Application()

	# Add the GET route for /mic_start
	app.router.add_get("/mic_start", mic_start)
	app.router.add_get("/mic_stop", mic_stop)
	app.router.add_get("/mic_start_continue", mic_start_continue)
	app.router.add_get("/run", run)

	# Create the server and run it
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, "localhost", 8080)
	await site.start()

	print("Server started on http://localhost:8080")

	# Keep the application running
	while True:
		await asyncio.sleep(3600)  # Sleep to keep the application alive

def get_context():
	infos = OrderedDict()
	infos["today"] = datetime.datetime.now().strftime("%Y-%m-%d (%A)")

	results = []
	for key in infos:
		results.append(f"{key}: {infos[key]}")
	return "\n".join(results)

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 8000
audio_queue = asyncio.Queue()
def stream_callback(input_data, frame_count, time_info, status_flags):
	audio_queue.put_nowait(input_data)

	return (input_data, pyaudio.paContinue)


async def wait_lock():
	await mic_lock.acquire()


async def play_audio(filename):
	wav_path = get_sound_path(filename)
	# winsound.Beep(400, 100)
	winsound.PlaySound(wav_path, flags = winsound.SND_ASYNC)

async def whisper_transcribe(filename):
	audio_file = open(filename, "rb")
	loop = asyncio.get_event_loop()
	response = await loop.run_in_executor(ThreadPoolExecutor(), lambda: openai_client.audio.transcriptions.create(
		model="whisper-1",
		file=audio_file
	))
	return response.text


def openai_tts(text):
	response = openai_client.audio.speech.create(
		model="tts-1",
		voice="alloy",
		input=text
	)
	temp_file_mp3 = get_sound_path("_tts.mp3")
	temp_file_wav = get_sound_path("_tts.wav")
	response.stream_to_file(temp_file_mp3)
	sound = AudioSegment.from_mp3(temp_file_mp3)
	sound.export(temp_file_wav, format="wav")
	return temp_file_wav

def elevenlabs_tts(text):
	global elevenlabs_voice
	elevenlabs_voice_name = config.tts_voice.replace(f"{ELEVENLABS_VOICE_KEYWORD}{VOICE_SEPARATOR}", "")
	if elevenlabs_voice is None or elevenlabs_voice_name != elevenlabs_voice.name:
		for voice in elevenlabs_voices:
			if voice.name == elevenlabs_voice_name:
				elevenlabs_voice = voice
	audio = elevenlabs.generate(text=text, voice=elevenlabs_voice)
	# temp_file_wav = get_sound_path("_tts.wav")
	# elevenlabs.save(audio, temp_file_wav)
	# return temp_file_wav
	elevenlabs.play(audio)
	return None

async def text_to_speech(text):
	loop = asyncio.get_event_loop()
	if config.tts_voice.startswith(OPENAI_VOICE_KEYWORD):
		wav_file = await loop.run_in_executor(ThreadPoolExecutor(), lambda: openai_tts(text))
		await play_audio(wav_file)
	elif config.tts_voice.startswith(ELEVENLABS_VOICE_KEYWORD):
		await loop.run_in_executor(ThreadPoolExecutor(), lambda: elevenlabs_tts(text))
	else:
		raise Exception("Unsupported voice type")

# key has been pressed and we need to record input
async def transcribe_microphone():
	audio = pyaudio.PyAudio()
	stream = audio.open(
		format = FORMAT,
		channels = CHANNELS,
		rate = RATE,
		input = True,
		frames_per_buffer = CHUNK,
		stream_callback = stream_callback
	)

	stream_starttime = datetime.datetime.now()
	stream.start_stream()

	# Play the audio
	await play_audio("wake_sound.wav")

	try:
		await asyncio.wait_for(mic_lock.acquire(), timeout = 30.0)
		mic_lock.release()
	except asyncio.exceptions.TimeoutError:
		print("ignoring: recording too long")
		stream.stop_stream()
		stream.close()
		return None
	
	await asyncio.sleep(0.2) # record for couple hundred miliseconds

	stream.stop_stream()
	stream.close()


	elapsed_time = datetime.datetime.now() - stream_starttime
	if elapsed_time < datetime.timedelta(seconds=1):
		print("ignoring: wasnt recording long enough")
		return None
	# Play the audio
	# await play_audio("done_sound.wav")

	# Create an AudioSegment to store the audio data
	audio_data = AudioSegment.silent(duration=0)

	# Keep retrieving audio data from the queue until it is empty
	while not audio_queue.empty():
		audio_data += AudioSegment(audio_queue.get_nowait(), sample_width=2, channels=CHANNELS, frame_rate=RATE)

	# Save the audio data to a WAV file
	output_file = get_sound_path("_speech_input.wav")
	audio_data.export(output_file, format="wav")

	print("transcribing...")
	spoken_text = await whisper_transcribe(output_file)
	print("TRANSCRIPTION: " + spoken_text)

	spoken_text = spoken_text.strip()
	
	if spoken_text == "" or spoken_text == ".":
		print("ignoring: nothing was said")
		return None
	
	return spoken_text

async def main_chat():
	global conversator
	config.reload()
	
	prompt_text = await transcribe_microphone()

	if prompt_text is None:
		return

	if conversator is None:
		system_prompt_file = obsidian.open(config.chat_system_prompt)
		system_text = system_prompt_file.content
		system_text = system_text.strip()
		conversator = conv.Conversator(asyncio.get_event_loop(), openai_client)
		conversator.input_system(system_text)
	conversator.input_self(prompt_text)

	print("querying chatgpt...")
	response_text = await conversator.get_response()
	print(f"> {response_text}")

	print("tts...")
	await text_to_speech(response_text)
	print("tts done!")

async def main_run():
	global conversator
	config.reload()
	
	RESULT_SEPARATOR = "\n> CHATGPT RESPONSE:"
	result_pattern = re.compile(f"{RESULT_SEPARATOR}\n[\s\S]*$", re.MULTILINE | re.DOTALL)
	
	prompt_file = obsidian.open(config.run_input)

	prompt_text = prompt_file.content
	prompt_text = re.sub(result_pattern, "", prompt_text)
	prompt_text = prompt_text.strip()

	# QUERY CHATGPT
	conversator = conv.Conversator(asyncio.get_event_loop(), openai_client)

	if config.run_system_prompt_enabled:
		system_prompt_file = obsidian.open(config.run_system_prompt)
		system_text = system_prompt_file.content
		system_text = system_text.strip()
		system_text = system_text.replace("{CONTEXT}", get_context())
		conversator.input_system(system_text)

	functions = [
		{
			'name': 'record_note',
			'description': 'Saves the note to a text file',
			'parameters': {
				'type': 'object',
				'properties': {
					'text': {
						'type': 'string',
						'description': 'The content of the note to save'
					}
				}
			}
		},
		{
			'name': 'add_todo',
			'description': 'Adds a to-do item for the given day',
			'parameters': {
				'type': 'object',
				'properties': {
					'date': {
						'type': 'string',
						'description': 'The day the todo item should be done on. Format should be YYYY-MM-DD (ex: 2020-12-30)'
					},
					'todo_text': {
						'type': 'string',
						'description': 'The text of the todo'
					}
				}
			}
		}
	]

	conversator.input_user(prompt_text)
	print("querying chatgpt...")
	response = await conversator.get_response_raw(functions)

	message = response.choices[0].message

	while message.content is None and message.function_call:
		func_name = message.function_call.name
		args = json.loads(message.function_call.arguments)
		function_text = f"{func_name} {args}"
		print("> " + function_text)
		conversator.input_self(function_text)
		conversator.input_user("Done!")
		response = await conversator.get_response_raw(functions)
		message = response.choices[0].message
	
	response_text = message.content
	conversator.input_self(response_text)


	print(f"> {response_text}")

	# STORE RESULTS
	result = f"{RESULT_SEPARATOR}\n\n{response_text}"
	result_pattern = re.compile(f"{RESULT_SEPARATOR}\n[\s\S]*$", re.MULTILINE | re.DOTALL)
	if re.search(result_pattern, prompt_file.content):
		prompt_file.content = re.sub(result_pattern, result, prompt_file.content)
	else:
		prompt_file.content += "\n" + result
	prompt_file.write()

	# TTS RESULTS?
	# print("tts...")
	# await text_to_speech(response_text)
	# print("tts done!")

	# LOG CONVERSATION
	conversation_file = obsidian.open(config.conversation_log)
	conversation_file.content = ""
	for message in conversator.messages:
		conversation_file.content += f"\n> {message['role'].upper()}\n\n{message['content']}\n"
	conversation_file.write()



if __name__ == '__main__':
	asyncio.run(webserver())
