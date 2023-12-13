import os
import json
from collections import OrderedDict

# The root directory of the repo
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

def write_json(filename, data):
	text = json.dumps(data, indent="\t")
	with open(filename, "w+") as f:
		f.write(text) # Do it like this so it doesnt break mid-file

def read_json(filename):
	with open(filename, encoding="utf-8") as f:
		return json.load(f, object_pairs_hook=OrderedDict)

class Settings:
	def __init__(self):
		self.path = "settings.json"
		if os.path.exists(self.path):
			self.json_data = read_json(self.path)
		else:
			raise Exception("Missing settings.json file")

	def save_settings(self):
		write_json(self.path, self.json_data)

	@property
	def openai_key(self):
		return self.json_data["openai_key"]
	
	@property
	def elevenlabs_key(self):
		return self.json_data["elevenlabs_key"]

	@property
	def obsidian_root(self):
		return self.json_data["obsidian_root"]

	@property
	def obsidian_config_path(self):
		return self.json_data["obsidian_config_path"]

	@property
	def homeassistant_key(self):
		return self.json_data["homeassistant_key"]
	
	@property
	def homeassistant_url(self):
		return self.json_data["homeassistant_url"]
	
	
	@property
	def resourcedir(self):
		return os.path.join(ROOT_DIR, "resource/")

	def resource(self, dir):
		return os.path.join(self.resourcedir, dir)

settings = Settings()
