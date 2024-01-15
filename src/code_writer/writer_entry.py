'''''
prompt: print "hello there" at the bottom of this script
[- Used So Far: 0.0¢ | 0 tokens -]
'''''
# Removed unnecessary imports
from colorama import Fore
from code_writer.CodeFile import CodeFile
import conversator as conv
import re

def print_color(text, color):
	print(f"{color}{text}{Fore.WHITE}")

def printerr(text):
	print_color(text, Fore.RED)

code_file = CodeFile("C:\dev\projects\chatgpt_rock_runner\src\code_writer\example.py")
# code_file = CodeFile(__file__)

print("hi")

code_file.metadata.print_args()
print_color("CODE:", Fore.CYAN)
print_color(code_file.content, Fore.BLACK)

code_file.write()

print_color("Running...", Fore.CYAN)
SYSTEM_PROMPT = """
You are a code assistant designed to help me with my code. I will send you entire python text files, and you will return the edited python text file in "```py" code blocks, after making the changes to accomplish what the prompt is requesting.
"""

async def run_thing(openai_client):
	prompt = code_file.metadata.get("prompt").strip()
	if prompt == "":
		print("No prompt! Nothing to do!")
	else:
		conversator = conv.Conversator(openai_client)
		conversator.input_system(SYSTEM_PROMPT.strip())
		conversator.input_user(f"I have the following python code:\n```py\n{code_file.content}\n```\nPROMPT: {prompt}")
		print("] Querying...")
		response = await conversator.get_response()
		token_count = conversator.get_token_count()
		print(f"] Token Count {token_count}")
		match = re.search("```py\n(.*)\n```", response, re.MULTILINE | re.DOTALL)
		if not match:
			printerr("Couldn't match regex for code")
			print_color("Response:", Fore.CYAN)
			print_color(response, Fore.BLACK)
			printerr("Exiting...")
		else:
			print("] Writing new code!")
			new_code = match.group(1)
			code_file.content = new_code
			code_file.metadata.set("tokens", code_file.metadata.get("tokens") + token_count.input_count + token_count.output_count)
			code_file.metadata.set("price", code_file.metadata.get("price") + float(token_count.get_total_price().cent_amount))
			code_file.write()
