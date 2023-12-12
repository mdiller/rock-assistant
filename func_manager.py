
from obsidian import ObsidianFile, AssistantConfig
import obsidian
from collections import OrderedDict
import typing
import os
import re
import datetime
import inspect

class AssFunctionArg():
	name: str
	description: str
	type: str
	def __init__(self, name, description):
		self.name = name
		self.description = description
		self.type = None
	
	@classmethod
	def try_convert_type(cls, argtype):
		if argtype == str:
			return "string"
		else:
			return None

class AssFunction():
	file: ObsidianFile
	exec: typing.Callable
	args: typing.List[AssFunctionArg]
	def __init__(self, file: ObsidianFile):
		self.file = file
		self.args = []
		self.exec = None
	
	def to_json(self):
		result = OrderedDict([
			("name", self.name),
			("description", self.description)
		])
		args = OrderedDict()
		for arg in self.args:
			args[arg.name] = OrderedDict([
				("type", arg.type),
				("description", arg.description)
			])
		result["parameters"] = OrderedDict([
			("type", "object"),
			("properties", args)
		])
		return result
	
	# returns False if this function is invalid / improper syntax
	def try_load(self):
		problems = []
		props = [ "name", "description", "args" ]
		for prop in props:
			if prop in self.file.metadata:
				value = self.file.metadata[prop]
				if value is None or value == "":
					problems.append(f"Property '{prop}' requires actual value")
			else:
				problems.append(f"Missing property '{prop}'")
		
		# load args from metadata
		for arg_name in self.file.metadata["args"]:
			self.args.append(AssFunctionArg(arg_name, self.file.metadata["args"][arg_name]))
		
		# load code
		code_match = re.search("```python\n([\s\S]+?)\n```", self.file.content, re.MULTILINE | re.DOTALL)
		if code_match:
			code_text = code_match.group(1)
			ns = {}
			exec(code_text, globals(), ns)
			ns_values = list(ns.values())
			if len(ns_values) < 1 or not callable(ns_values[-1]):
				problems.append("Code block is missing a function")
			else:
				self.exec = ns_values[-1]
				signature = inspect.signature(self.exec)
				args = list(signature.parameters.keys())
				if args[0] != "ctx":
					problems.append("Missing ctx arg")
				else:
					args = args[1:]
					# TODO: implement better error checking here
					# if len(args) > len(self.args):
					# 	arg_list = ", ".join(list(filter(lambda arg: arg in map(lambda a: a.name, self.args), args)))
					# 	problems.append(f"Undocumented func args: {arg_list}")
					# 	 # TODO: in future, add docs for params that dont have doc, and then make it empty so user has to fill
					# if len(args) < len(self.args):
					# 	arg_list = ", ".join(list(filter(lambda arg: arg.name in args, self.args)))
					# 	problems.append(f"Args missing from code: {arg_list}")
					
					if len(args) != len(self.args):
						problems.append(f"Args count mismatch between code and docs")
					else:
						for i in range(len(self.args)):
							param = signature.parameters[args[i]]
							argtype = self.args[i].try_convert_type(param.annotation)
							if argtype:
								self.args[i].type = argtype
							else:
								problems.append(f"Invalid param type on func arg: '{args[i]}'")
					
		else:
			problems.append("Missing a code block")

		if len(problems) == 0:
			if self.file.ass_output:
				self.file.ass_output = None
				self.file.write()
			return True
		else:
			error_str = f"ERROR LOADING {self.file.name}"
			for problem in problems:
				error_str += f"\n - {problem}"
			error_str = f"```\n{error_str}\n```"
			print(error_str)
			
			self.file.ass_output = error_str
			self.file.write()
	
	@property
	def name(self):
		return self.file.metadata["name"]
		
	@property
	def description(self):
		return self.file.metadata["description"]


# loads and manages the assistant functions
class AssFunctionsManager():
	funcs_dir: str
	functions: typing.List[AssFunction]
	def __init__(self, funcs_dir: str):
		self.funcs_dir = obsidian.fix_path(funcs_dir)
		self.reload()
	
	# re-loads the functions
	def reload(self):
		self.functions = []
		files = os.listdir(self.funcs_dir)
		files = [f for f in files if os.path.isfile(os.path.join(self.funcs_dir, f))]
		for file in files:
			file = ObsidianFile(os.path.join(self.funcs_dir, file))
			func = AssFunction(file)
			if func.try_load():
				self.functions.append(func)



# def write_thought(ctx: Context, text: str):
# 	now = datetime.datetime.now()
# 	today_note_path = "daily_notes/" + now.strftime("%b-%Y\\%d-%b %A.md")
# 	today_note = obsidian.file(today_note_path)
# 	today_note.add_note(text)