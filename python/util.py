def print_dict(d, indent=0):
	for key, value in d.items():
		if isinstance(value, dict):
			print("{}{}:".format(" " * indent, key))
			print_dict(value, indent + 2)
		else:
			print("{}{}: {}".format(" " * indent, key, value))