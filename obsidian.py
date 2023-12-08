import os
import re
import datetime
import yaml

def fix_path(path, root = None):
	link_pattern = re.compile("^\[\[([^|]*)|.*\]\]$")
	match = link_pattern.search(path)
	if match:
		path = match.group(1)
	if root and (not root in path) or not os.path.exists(path):
		path = os.path.join(root, path)
	if not os.path.exists(path):
		print(f"ERROR OBS FILE NOT FOUND: {path}")
		return None
	return path

class Obsidian():
	def __init__(self, root):
		self.root = root

	def open(self, path):
		path = fix_path(path, self.root)
		return ObsidianFile(path)


class ObsidianFile():
	path: str
	metadata_text: str
	metadata: dict
	content: str

	def __init__(self, path):
		path = fix_path(path)
		self.metadata_text = None
		self.metadata = None
		self.content = None
		self.path = path
		self.read()
	
	def read(self):
		with open(self.path, "r") as f:
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
		
		self.content = text
	
	def reload(self):
		self.read()
	
	def _get_full_content(self):
		text = ""
		if self.metadata_text:
			text += "---\n"
			text += self.metadata_text
			text += "\n---\n"
		text += self.content
		return text

	def write(self):
		text = self._get_full_content()
		with open(self.path, "w+", encoding="utf8") as f:
			f.write(text)

	def add_note(self, text):
		current_time = datetime.datetime.now().strftime("%I:%M %p")
		if not re.search("\n\s*\n$", self.content):
			self.content += "\n"
		self.content += f"\n<span class=\"dillerm-timestamp\">🕥 {current_time}</span>\n{text}\n"
		self.write()

	# def replace(self, pattern, replacement):
	# 	self.content = re.sub(pattern, replacement, self.content, re.MULTILINE | re.DOTALL)
	
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