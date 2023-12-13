import os
import re
import datetime
import uuid
import asyncio
import typing
from io import BytesIO
import orjson

from utils.settings import settings

# currently set to 1 week timeout for cache files
CACHE_FILE_TIMEOUT_MS = 1000 * 60 * 60 * 24 * 7

def get_timestamp(date=None):
	if date is None:
		date = datetime.datetime.now()
	return int(datetime.datetime.timestamp(date) * 1000)

class CacheItem(dict):
	filename: str
	timestamp: int
	permanent: bool
	def __init__(self, json_data={}): # only to be used internally
		for key in json_data:
			self[key] = json_data[key]
		
	@classmethod
	def create(cls, filename, permanent=False):
		item = CacheItem()
		item["permanent"] = permanent
		item["filename"] = filename
		item.update_timestamp()
		return item
	
	@property
	def permanent(self):
		return self.get("permanent")
		
	@property
	def filename(self):
		return self["filename"]

	@property
	def timestamp(self):
		return self["timestamp"]

	def update_timestamp(self):
		self["timestamp"] = get_timestamp()
	
	def is_expired(self, timestamp_threshold):
		return (not self.permanent) and (self.timestamp < timestamp_threshold)


class Cache:
	cache_data: typing.Dict[str, CacheItem]
	def __init__(self):
		self.lock = asyncio.Lock()
		self.cache_dir = settings.resource("cache/")
		if not os.path.exists(self.cache_dir):
			os.makedirs(self.cache_dir)
		self.cache_data = {}
		self.cache_index_filename = self.cache_dir + "_cache_index.json"
		if os.path.exists(self.cache_index_filename):
			with open(self.cache_index_filename, "rb") as f:
				json_dict = orjson.loads(f.read())
				for uri, item in json_dict.items():
					self.cache_data[uri] = CacheItem(item)
	
	def _save_to_disk(self):
		with open(self.cache_index_filename, "wb+") as f:
			f.write(orjson.dumps(self.cache_data))
	
	@property
	def size(self):
		return len(self.cache_data)

	async def exists(self, uri):
		async with self.lock:
			item = self.cache_data.get(uri)
			return not (item is None)

	# Returns the filename of the cached url if it exists, otherwise None
	async def get_filename(self, uri):
		async with self.lock:
			item = self.cache_data.get(uri)
			if item is None:
				return None
			item.update_timestamp()
			filename = self.cache_dir + item.filename
		if not os.path.isfile(filename):
			return None
		return filename

	# Returns the file if it exists, otherwise None
	# async def get(self, uri, return_type):
	# 	filename = await self.get_filename(uri)
	# 	if not filename:
	# 		return None
	# 	if return_type == "json":
	# 		return read_json(filename)
	# 	elif return_type == "text":
	# 		with open(filename, "r") as f:
	# 			return f.read()
	# 	elif return_type == "bytes":
	# 		with open(filename, "rb") as f:
	# 			return BytesIO(f.read())
	# 	elif return_type == "filename":
	# 		return filename
	# 	else:
	# 		raise ValueError(f"Invalid return type '{return_type}'")

	#creates a new entry in the cache and returns the filename of the new entry
	async def new(self, uri, extension=None, permanent=False):
		async with self.lock:
			item = self.cache_data.get(uri)
			if item is not None:
				filename = self.cache_dir + item.filename
				if os.path.isfile(filename):
					return filename
			filename = str(uuid.uuid4())
			if extension:
				filename = f"{filename}.{extension}"
			self.cache_data[uri] = CacheItem.create(filename, permanent=permanent)
			self._save_to_disk()
		return self.cache_dir + filename


	async def save(self, uri, return_type, response, permanent=False):
		extension = None
		if return_type == "json":
			extension = "json"
		elif return_type == "text":
			extension = "txt"
		elif return_type in ["filename", "bytes"]:
			match = re.search(r"\.([a-z0-9]{1,6})$", uri.lower())
			if match:
				extension = match.group(1)
		else:
			raise ValueError(f"Invalid return type '{return_type}'")

		filename = await self.new(uri, extension, permanent=permanent)
		with open(filename, "wb+") as f:
			f.write(await response.read())


	async def remove(self, uri):
		async with self.lock:
			item = self.cache_data.get(uri)
			if item is not None:
				filename = self.cache_dir + item.filename
				if os.path.isfile(filename):
					os.remove(filename)
				del self.cache_data[uri]

cache = Cache()