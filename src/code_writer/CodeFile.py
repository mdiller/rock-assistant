from collections import OrderedDict
import re
import os
from colorama import Fore


# A serializable piece of metadata that can be inserted into a template etc
class MetadataVar():
	def __init__(self, name, pattern, default_value = "", format_lambda = None):
		self.name = name
		self.pattern = pattern
		self.default_value = default_value
		self.format_lambda = format_lambda
		self.value = default_value
		if self.format_lambda is None:
			self.format_lambda = lambda x: str(x)
		
	def parse_set(self, text):
		print(f"SETTING: {self.name} - {text}")
		if text is None:
			self.value = self.default_value
		else:
			self.value = text

	def get_val(self):
		return self.format_lambda(self.value)
	
	def get_pattern(self):
		# return f"({self.pattern}|)"
		return f"(?P<{self.name}>{self.pattern}|)"

# TODO: next todo is to write a thing in CodeFile so that the arg definitions are included in the template, and we have arg types, and we generate a class from the template when it changes and automatically reload the module after


METADATA_START = "'''''"
METADATA_END = "'''''"
METADATA_TEMPLATE = """
prompt:{prompt}
[- Used So Far: {price}¢ | {tokens} tokens -]
"""
class CodeMetadata():
	def __init__(self, metadata_text: str):
		self.text = metadata_text
		self.args = [
			MetadataVar("prompt", " ?.*"),
			MetadataVar("price", "[0-9.]+", 0, format_lambda=lambda x: float(x)),
			MetadataVar("tokens", "[0-9]+", 0, format_lambda=lambda x: int(x)),
		]
		self.template = METADATA_TEMPLATE.strip()
		self.template_pattern = METADATA_TEMPLATE.strip()
		re_translator = str.maketrans({"]": "\]", "[": "\[", "|": "\|"})
		self.template_pattern = self.template_pattern.translate(re_translator)
		for arg in self.args:
			self.template_pattern = re.sub(f"{{{arg.name}}}", arg.get_pattern(), self.template_pattern)

		self.parse(metadata_text)
	
	def get(self, argname):
		for arg in self.args:
			if arg.name == argname:
				return arg.get_val()
		raise Exception(f"invalid arg name: {argname}")

	def set(self, argname, value):
		for arg in self.args:
			if arg.name == argname:
				arg.value = value
				return arg.get_val()
		raise Exception(f"invalid arg name: {argname}")
	
	def has_content(self):
		return True

	def parse(self, text: str):
		text = text.strip()
		match = re.match(self.template_pattern, text)
		if not match:
			print(f"Bad Metadata!!!:\n{text}")
		else:
			for arg in self.args:
				arg.parse_set(match.group(arg.name))
	
	def print_args(self):
		print(f"{Fore.CYAN}METADATA:{Fore.WHITE}")
		for arg in self.args:
			print(f"- {Fore.GREEN}{arg.name}:{Fore.WHITE} {arg.get_val()}")


	def __repr__(self):
		text = self.template
		for arg in self.args:
			text = re.sub(f"{{{arg.name}}}", str(arg.get_val()), text)
		return text

class CodeFile():
	path: str
	metadata_text: str
	metadata: CodeMetadata
	content: str

	def __init__(self, path):
		self.content = None
		self.metadata_text = None
		self.metadata = None
		self.path = path
		self.read()
	
	
	def read(self):
		with open(self.path, "r", encoding="utf8") as f:
			text = f.read()

		metadata_regex = re.compile(f"^{METADATA_START}\n([\s\S]*?)\n{METADATA_END}\n", re.MULTILINE | re.DOTALL)
		match = metadata_regex.search(text)
		if match:
			self.metadata_text = match.group(1)
			try:
				self.metadata = CodeMetadata(self.metadata_text)
				text = re.sub(metadata_regex, "", text)
			except Exception:
				print(f"ERROR reading metadata of: {self.path}")
				self.metadata = CodeMetadata()
		else:
			self.metadata = None
		
		self.content = text
	
	def reload(self):
		self.read()
	
	def _get_full_content(self):
		text = ""
		if self.metadata.has_content():
			text += f"{METADATA_START}\n{self.metadata}\n{METADATA_END}\n"
		text += self.content
		return text

	def write(self):
		text = self._get_full_content()
		with open(self.path, "w+", encoding="utf8") as f:
			f.write(text)

