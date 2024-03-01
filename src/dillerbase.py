'''''
PROMPT:

[- Used So Far: 0.09740000000000001¢ | 738 tokens -]
'''''
import datetime
import psycopg2
from psycopg2 import sql

from utils.settings import settings

# string like: "dbname='---' user='---' host='---' password='---' port='---'"
DB_CONNECTION_STRING = settings.dillerbase_connection_string

custom_column_docs = {
	"strava_rides.distance": "UNITS: miles",
	"strava_rides.moving_time": "UNITS: seconds",
	"strava_rides.total_elevation_gain": "UNITS: feet",
	"strava_rides.average_speed": "UNITS: miles per hour",
	"strava_rides.max_speed": "UNITS: miles per hour",
	"strava_rides.sport_type": "Biking is 'Ride', Skiing is 'AlpineSki'. Unless the user specifies skiing, filter for biking here."
}

def _get_create_table_script(table_name, cursor):
	# Fetch table details
	cursor.execute(
		"SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
		"FROM information_schema.columns "
		"WHERE table_name = %s", (table_name,)
	)
	columns = cursor.fetchall()

	# Fetch primary key
	cursor.execute(
		"SELECT a.attname "
		"FROM   pg_index i "
		"JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
		"WHERE  i.indrelid = %s::regclass AND i.indisprimary", (table_name,)
	)
	primary_key = [row[0] for row in cursor.fetchall()]

	# Fetch foreign keys
	cursor.execute(
		"SELECT tc.constraint_name, kcu.column_name, ccu.table_name AS foreign_table_name, ccu.column_name AS foreign_column_name "
		"FROM information_schema.table_constraints AS tc "
		"JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name "
		"JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name "
		"WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name=%s", (table_name,)
	)
	foreign_keys = cursor.fetchall()

	# Construct CREATE TABLE script
	script = f"CREATE TABLE {table_name} (\n"
	added_column_names = []
	sorted_columns = []

	filter_order = [
		lambda column_name: column_name in primary_key,
		lambda column_name: column_name == "timestamp" and column_name not in added_column_names,
		lambda column_name: column_name not in added_column_names
	]

	for filter in filter_order:
		for column in columns:
			column_name, data_type, char_max_length, is_nullable, column_default = column
			if filter(column_name):
				added_column_names.append(column_name)
				sorted_columns.append(column)

	column_lines = []
	for column in sorted_columns:
		column_name, data_type, char_max_length, is_nullable, column_default = column
		line = f"    {column_name} {data_type.upper()}"
		if char_max_length:
			line += f"({char_max_length})"
		if column_name in primary_key:
			line += " PRIMARY KEY"
		if not is_nullable:
			line += " NOT NULL"
		if column_default:
			line += f" DEFAULT {column_default}"
		for key in custom_column_docs:
			key_table, key_column = key.split(".")
			if key_table == table_name and key_column == column_name:
				line += " -- " + custom_column_docs[key]
		column_lines.append(line)
	for i, line in enumerate(column_lines):
		if i < (len(column_lines) - 1):
			if " --" in line:
				comment_index = line.index(" --")
				column_lines[i] = line[:comment_index] + "," + line[comment_index:]
			else:
				column_lines[i] += ","
	script += "\n".join(column_lines)
	for fk in foreign_keys:
		constraint_name, column_name, foreign_table_name, foreign_column_name = fk
		script += f",\n    FOREIGN KEY ({column_name}) REFERENCES {foreign_table_name}({foreign_column_name})"
	script += "\n);"
	return script

def stringify_value(value):
	if isinstance(value, datetime.datetime):
		# Convert the UTC datetime object to local time (US Oregon/LA time)
		local_timezone = datetime.timezone(datetime.timedelta(hours=-8)) # US Oregon/LA timezone (UTC-8)
		value_local = value.astimezone(local_timezone)
		
		# Format the local datetime object as "YYYY-MM-DD h:mm AM/PM"
		return value_local.strftime("%Y-%m-%d %I:%M %p")
	return str(value)

def create_markdown_table(results, has_header = False):
	# Calculate the maximum length for each column
	max_lengths = [max([len(stringify_value(row[i])) for row in results]) for i in range(len(results[0]))]

	# TODO: parse dates properly to put em in the right locality and format

	# Generate the markdown table
	table = ""
	if has_header:
		header = results[0]
		results = results[1:]
		table += "|"
		for i in range(len(header)):
			table += " {:{}s} |".format(header[i], max_lengths[i])
		table += "\n" + "|"
		table += " --- |" * len(header)
		table += "\n"
	for row in results:
		table += "|"
		for i in range(len(row)):
			cellval = stringify_value(row[i])
			table += " {:{}s} |".format(cellval, max_lengths[i])
		table += "\n"
	
	return table

class Dillerbase():
	def __init__(self):
		self.connection = psycopg2.connect(DB_CONNECTION_STRING)
		self.connection.set_session(readonly=True)
	
	def __enter__(self) -> 'Dillerbase':
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.connection.close()

	def get_db_table_schema(self):
		with self.connection.cursor() as cursor:
			# Fetch all table names
			cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
			tables = cursor.fetchall()
			
			table_scripts = []

			for table in tables:
				table_name = table[0]
				table_scripts.append(_get_create_table_script(table_name, cursor))
			return "\n\n".join(table_scripts)

	def query(self, query: str, include_headers = False):
		with self.connection.cursor() as cursor:
			# Fetch all table names
			try:
				cursor.execute(query)
				data = cursor.fetchall()
				if include_headers:
					headers = [desc[0] for desc in cursor.description]
					data.insert(0, headers)
				return data
			except Exception as e:
				self.connection.rollback()
				raise

	def query_as_table(self, query: str, lines_max = 5):
		results = self.query(query, True)
		if len(results) > lines_max:
			table = create_markdown_table(results[:lines_max], True)
			table += f"...{len(results) - lines_max} more rows not shown..."
			return table
		else:
			return create_markdown_table(results)


