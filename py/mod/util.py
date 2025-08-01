def print_dict(d, indent=0):
	for key, value in d.items():
		if isinstance(value, dict):
			print("{}{}:".format(" " * indent, key))
			print_dict(value, indent + 2)
		else:
			print("{}{}: {}".format(" " * indent, key, value))


def makeEmitterChangeKey(op, parName):
	return f"{op.path}.{parName}"


def makeServiceId():
	projectfile = project.name
	sections = projectfile.split(".")
	
	serviceId = sections[0]

	return serviceId