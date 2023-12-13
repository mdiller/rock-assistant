import asyncio
from concurrent.futures import ThreadPoolExecutor

# better executor caller

# better printer?

# better async task runner
async def run_async(func: callable) -> asyncio.Task:
	loop = asyncio.get_event_loop()
	return await loop.run_in_executor(ThreadPoolExecutor(), func)