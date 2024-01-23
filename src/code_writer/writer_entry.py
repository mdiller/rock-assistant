'''''
PROMPT:

[- Used So Far: 0.0824¢ | 630 tokens -]
'''''
# Removed unnecessary imports
from colorama import Fore
from code_writer.CodeFile import CodeFile, CodeLanguage, CodeMetadata
from context import Context, StepFinalState
import chat.conversator as conv
import re

DEFAULT_FILE = __file__
# code_file = CodeFile("C:\dev\projects\chatgpt_rock_runner\src\code_writer\example.py")
# code_file = CodeFile("C:/dev/projects/chatgpt_rock_runner/src/utils/soundmaker.py")

def fix_indentation(text):
	return re.sub(r'^( {4})+', lambda match: '\t' * (len(match.group(0)) // 4), text, flags=re.MULTILINE)

def parse_system_prompt(prompt: str, lang: CodeLanguage):
	prompt = prompt.strip()
	prompt = prompt.replace("{lang_name}", lang.name)
	prompt = prompt.replace("{lang_codeblock}", lang.extension)
	return prompt

SYSTEM_PROMPT_INLINE = """
You are a code assistant designed to help me with my code. I will send you a prompt, and you will return to me a code snippet that will accomplish the task. The code should be written in {lang_name}.

Your response should be a short description followed by a single "```{lang_codeblock}" code block, and should contain only the code. Don't include any lines that say "...your code here" etc.

Understand that the code you are returning will be included as a code snippet in my script, and does not have to run by itself, so you don't need to initialize all the variables if I imply there are some existing ones.

Indentation should be 4 spaces
"""
SYSTEM_PROMPT = """
You are a code assistant designed to help me with my code. I will send you entire {lang_name} text files, and you will return the edited {lang_name} text file in a single "```{lang_codeblock}" code block, after making the changes to accomplish what the prompt is requesting.
"""
async def run_thing(ctx: Context, file: str = DEFAULT_FILE) -> StepFinalState:
	code_file = CodeFile(file)
	ctx.log(f"] Running CodeWriter on: {file}")

	if code_file.metadata:
		code_file.metadata.print_args()
	ctx.log("CODE:", Fore.CYAN)
	lines = code_file.content.split("\n")
	max_lines = 25
	show_ends = 5
	if len(lines) > max_lines:
		for i in range(show_ends):
			ctx.log(lines[i], Fore.BLACK)
		ctx.log(f"... ({len(lines) - (2 * show_ends)} more lines) ...", Fore.BLACK)
	else:
		ctx.log(code_file.content, Fore.BLACK)

	ctx.log("Running...", Fore.CYAN)

	prompt = ""
	if code_file.metadata:
		prompt = code_file.metadata.get("prompt").strip()
	
	prompt_pattern = f"\n([^\S\r\n]*){code_file.language.inline_comment} PROMPT: (.+)(?:\n|$)"
	
	prompt_pattern = re.compile(prompt_pattern)

	if prompt != "":
		conversator = ctx.get_conversator()
		conversator.input_system(parse_system_prompt(SYSTEM_PROMPT, code_file.language))
		conversator.input_user(f"I have the following {code_file.language.name} code:\n```{code_file.language.extension}\n{code_file.content}\n```\nPROMPT: {prompt}")
		ctx.log("] Querying...")
		response = await conversator.get_response()
		token_count = conversator.get_token_count()
		ctx.log(f"] Token Count {token_count}")
		match = re.search(f"```{code_file.language.codeblock_pattern}\n(.*)\n```", response, re.MULTILINE | re.DOTALL)
		if not match:
			ctx.log("Couldn't match regex for code", Fore.RED)
			ctx.log("Response:", Fore.CYAN)
			ctx.log(response, Fore.BLACK)
			return StepFinalState.NOTHING_DONE
		else:
			ctx.log("] Writing new code!")
			new_code = match.group(1)
			code_file.content = new_code
			code_file.metadata.set("tokens", code_file.metadata.get("tokens") + token_count.input_count + token_count.output_count)
			code_file.metadata.set("price", code_file.metadata.get("price") + float(token_count.get_total_price().cent_amount))
			ctx.log("] Removing prompt that caused this")
			code_file.metadata.set("prompt", "")
			code_file.write()
	elif re.search(prompt_pattern, code_file.content):
		match = re.search(prompt_pattern, code_file.content)
		whitespace = match.group(1)
		prompt = match.group(2)
		conversator = ctx.get_conversator()
		conversator.input_system(parse_system_prompt(SYSTEM_PROMPT_INLINE, code_file.language))
		conversator.input_user(prompt)
		
		ctx.log("] Querying...")
		response = await conversator.get_response()
		token_count = conversator.get_token_count()

		match = re.search(f"```{code_file.language.codeblock_pattern}\n(.*)\n```", response, re.MULTILINE | re.DOTALL)
		if not match:
			ctx.log("Couldn't match regex for code", Fore.RED)
			ctx.log("Response:", Fore.CYAN)
			ctx.log(response, Fore.BLACK)
			return StepFinalState.CHAT_ERROR
		else:
			ctx.log("] Writing new code!")
			new_code = match.group(1)
			new_code = fix_indentation(new_code)
			new_code = "\n".join(map(lambda line: f"{whitespace}{line}", new_code.split("\n")))
			new_code = f"\n{new_code}\n"
			NEWCODEPLACEHOLDER = "{NEWCODEPLACEHOLDER}"
			code_file.content = re.sub(prompt_pattern, NEWCODEPLACEHOLDER, code_file.content)
			code_file.content = code_file.content.replace(NEWCODEPLACEHOLDER, new_code)
			if code_file.metadata:
				code_file.metadata.set("tokens", code_file.metadata.get("tokens") + token_count.input_count + token_count.output_count)
				code_file.metadata.set("price", code_file.metadata.get("price") + float(token_count.get_total_price().cent_amount))
			code_file.write()
	else:
		code_file.metadata = CodeMetadata("")
		code_file.write()
		ctx.log("No prompt! Nothing to do!")
		return StepFinalState.NOTHING_DONE
	return StepFinalState.SUCCESS
