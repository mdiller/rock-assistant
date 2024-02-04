from collections import OrderedDict
import re
import os
import typing
from colorama import Fore


# TODO: use this
class CodeLanguage():
	def __init__(self, name: str, extension: str, comment_block_start: str, comment_block_end: str, inline_comment: str, codeblock_options: typing.List[str] = []):
		self.name = name
		self.extension = extension
		self.comment_block_start = comment_block_start
		self.comment_block_end = comment_block_end
		self.inline_comment = inline_comment
		self.codeblock_options = codeblock_options
		self.codeblock_options.append(self.name)
		self.codeblock_options.append(self.extension)
	
	@property
	def codeblock_pattern(self):
		return f"(?:{'|'.join(self.codeblock_options)})"
	
	@classmethod
	def get_by_extension(cls, filename: str):
		for lang in ALL_CODELANGS:
			if filename.endswith(f".{lang.extension}"):
				return lang
		return None
	
	@classmethod
	def is_code_file(cls, filename: str):
		return CodeLanguage.get_by_extension(filename) is not None

	@classmethod
	def all():
		return ALL_CODELANGS

ALL_CODELANGS = [
	CodeLanguage("python", "py", "'''''", "'''''", "#"),
	CodeLanguage("javascript", "js", "/*", "*/", "//"),
	CodeLanguage("typescript", "ts", "/*", "*/", "//", [ "js", "javascript" ]),
	CodeLanguage("typescript", "tsx", "/*", "*/", "//", [ "js", "javascript" ]),
	CodeLanguage("AutoHotkey", "ahk", "/*", "*/", ";"),
]

# represents a snippet of code, usually extracted from a chatgpt response
class CodeSnippet():
	def __init__(self, code: str, lang_str: str = ""):
		self.code = code
		self.lang_str = lang_str
		self.fix_indentation()
	
	@classmethod
	def parse(cls, text: str, lang: CodeLanguage = None):
		codepattern = "[a-z]*"
		if lang:
			codepattern = lang.codeblock_pattern
		pattern = f"```({codepattern})\n((?:(?!```).)+)\n```"
		# match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
		matches = list(re.finditer(pattern, text, re.DOTALL))
		if len(matches) == 0:
			return None
		lang_str = matches[-1].group(1)
		code = matches[-1].group(2)
		return CodeSnippet(code, lang_str)

	def fix_indentation(self):
		self.code = re.sub(r'^( {4})+', lambda match: '\t' * (len(match.group(0)) // 4), self.code, flags=re.MULTILINE)
	
	def __repr__(self):
		return f"```{self.lang_str}\n{self.code}\n```"

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

METADATA_TEMPLATE = """
PROMPT:
{prompt}
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
	language: CodeLanguage

	def __init__(self, path):
		self.content = None
		self.metadata_text = None
		self.metadata = None
		self.path = path
		self.language = CodeLanguage.get_by_extension(self.path)
		self.read()
	
	def read(self):
		with open(self.path, "r", encoding="utf8") as f:
			text = f.read()

		START = re.escape(self.language.comment_block_start)
		END = re.escape(self.language.comment_block_end)

		metadata_regex = re.compile(f"^{START}\n([\s\S]*?)\n{END}\n", re.MULTILINE | re.DOTALL)
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
		if self.metadata:
			text += f"{self.language.comment_block_start}\n{self.metadata}\n{self.language.comment_block_end}\n"
		text += self.content
		return text

	def write(self):
		text = self._get_full_content()
		with open(self.path, "w+", encoding="utf8") as f:
			f.write(text)

