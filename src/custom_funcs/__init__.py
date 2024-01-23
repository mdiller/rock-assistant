'''''
PROMPT:

[- Used So Far: 0.0972¢ | 635 tokens -]
'''''
import pkgutil
import importlib
import inspect
import os
import sys

# List to hold all custom functions
CUSTOM_FUNCS = []

# Get the current directory
current_dir = os.path.dirname(__file__)

# Iterate over all modules in the current directory
for (_, module_name, _) in pkgutil.iter_modules([current_dir]):

    full_module_name = f"{__name__}.{module_name}"

    # Check if the module has already been imported
    if full_module_name in sys.modules:
        # Reload the module
        module = importlib.reload(sys.modules[full_module_name])
    else:
        # Import the module
        module = importlib.import_module(full_module_name)

    # Iterate over all members of the module
    for member_name, member_object in inspect.getmembers(module):
        # Check if the member is a function
        if inspect.isfunction(member_object) and member_object not in CUSTOM_FUNCS:
            # Add the function to the CUSTOM_FUNCS list
            CUSTOM_FUNCS.append(member_object)

# Optionally, export all functions for easier import (e.g., from yourpackage import *)
__all__ = [func for func in CUSTOM_FUNCS]