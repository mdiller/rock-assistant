import asyncio
from concurrent.futures import ThreadPoolExecutor
from colorama import Fore

# better executor caller


def print_color(text, color):
	print(f"{color}{text}{Fore.WHITE}")

def printerr(text):
	print_color(text, Fore.RED)

# better async task runner
async def run_async(func: callable) -> asyncio.Task:
	loop = asyncio.get_event_loop()
	return await loop.run_in_executor(ThreadPoolExecutor(), func)