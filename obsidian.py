import os
import re
import datetime
import yaml

# Set this before running any obsidian stuff
ROOT_DIR = None

def file(path):
	return ObsidianFile(path)

def fix_path(path):
	if path is None:
		raise Exception("null path passed to fix_path")
	link_pattern = re.compile("^\[\[([^|]*)|.*\]\]$")
	match = link_pattern.search(path)
	if match:
		path = match.group(1)
	if ROOT_DIR and (not ROOT_DIR in path) or not os.path.exists(path):
		path = os.path.join(ROOT_DIR, path)
	if not os.path.exists(path):
		print(f"ERROR OBS FILE NOT FOUND: {path}")
		return None
	return path

class ObsidianFile():
	name: str
	path: str
	metadata_text: str
	metadata: dict
	_ass_output: str
	ass_output_timestamp: str
	content: str

	def __init__(self, path):
		path = fix_path(path)
		self.content = None
		self.metadata_text = None
		self.metadata = None
		self.ass_output = None
		self.ass_output_previous = None
		self.ass_output_timestamp = None
		self.path = path
		self.name = os.path.splitext(os.path.basename(path))[0]
		self.read()
	
	@property
	def ass_output(self):
		return self._ass_output
	
	@ass_output.setter
	def ass_output(self, text):
		self._ass_output = text
		timestamp = datetime.datetime.now().strftime("%I:%M%p %b %d, %Y")
		if timestamp.startswith("0"):
			timestamp = timestamp[1:]
		timestamp = re.sub("(AM|PM)", lambda m: m.group(1).lower(), timestamp)
		self.ass_output_timestamp = timestamp
	
	def read(self):
		with open(self.path, "r", encoding="utf8") as f:
			text = f.read()

		metadata_regex = re.compile("^---\n([\s\S]*?)\n---\n", re.MULTILINE | re.DOTALL)
		match = metadata_regex.search(text)
		if match:
			self.metadata_text = match.group(1)
			try:
				self.metadata = yaml.safe_load(self.metadata_text) # to write: yaml.safe_dump(a, sort_keys=False)
			except Exception:
				print(f"ERROR reading metadata of: {self.path}")
				self.metadata = {}
			text = re.sub(metadata_regex, "", text)
		else:
			self.metadata = None
		
		ass_output_regex = re.compile("\n---\n> __ROCK ASSISTANT \(([^)\n]+)\):__\n\n([\s\S]*)$", re.MULTILINE | re.DOTALL)
		match = ass_output_regex.search(text)
		if match:
			self._ass_output = match.group(2)
			self.ass_output_timestamp = match.group(1)
			text = re.sub(ass_output_regex, "", text)
		
		self.content = text
	
	def reload(self):
		self.read()
	
	def _get_full_content(self):
		text = ""
		if self.metadata_text is not None:
			text += f"---\n{self.metadata_text}\n---\n"
		text += self.content

		if self.ass_output is not None:
			if self.content[-1] != "\n":
				text += "\n"
			
			text += f"\n---\n> __ROCK ASSISTANT ({self.ass_output_timestamp}):__\n\n{self.ass_output}"
		return text

	def write(self):
		text = self._get_full_content()
		with open(self.path, "w+", encoding="utf8") as f:
			f.write(text)

	def add_note(self, text):
		current_time = datetime.datetime.now().strftime("%I:%M %p")
		if current_time.startswith("0"):
			current_time = current_time[1:]
		if not re.search("\n\s*\n$", self.content):
			self.content += "\n"
		self.content += f"\n<span class=\"dillerm-timestamp\">🕥 {current_time}</span>\n{text}\n"
		self.write()

	# adds todo to the first list of todos in the note
	def add_todo_item(self, item):
		pattern = r"(?<=\n)([\t ]*- \[(x|\s)\]([ ]+)([^\n]*)\n)(?![\t ]*- \[)"
		match = re.search(pattern, self.content)
		if not match:
			raise Exception("Couldn't find a todo in this file")
		# item = re.escape(item)
		item = f"- [ ] {item}\n"
		if len(match.group(4)) > 2:
			item = f"\\1{item}"
		self.content = re.sub(pattern, item, self.content, 1)
		self.write()
	
	def print(self, text):
		self.content += f"\n{text}"
		self.write()


class AssistantConfig(ObsidianFile):
	@property
	def tts_voice(self):
		return self.metadata.get("tts_voice", None)
	
	@property
	def conversation_log(self):
		return self.metadata.get("conversation_log", None)
	
	@property
	def run_input(self):
		return self.metadata.get("run", {}).get("input", None)
		
	@property
	def run_system_prompt(self):
		return self.metadata.get("run", {}).get("system_prompt", None)

	@property
	def run_system_prompt_enabled(self):
		return self.metadata.get("run", {}).get("system_prompt_enabled", None)
		
	@property
	def chat_system_prompt(self):
		return self.metadata.get("chat", {}).get("system_prompt", None)
	
	@property
	def functions_dir(self):
		return self.metadata.get("functions_dir", None)