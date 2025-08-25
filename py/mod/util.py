def print_dict(d, indent=0):
	for key, value in d.items():
		if isinstance(value, dict):
			print("{}{}:".format(" " * indent, key))
			print_dict(value, indent + 2)
		else:
			print("{}{}: {}".format(" " * indent, key, value))


def makeEmitterChangeKey(op, parName):
	return f"{op.path}.{parName}"





RS_TARGET_INFO_PAGE = "Rship Target Config"
RS_BUNDLE_COMPLETE_PAR = "Rshipparsupdated"
RS_TARGET_ID_PAR = "Rshiptargetid"
RS_TARGET_ID_STORAGE_KEY = 'rs_target_id'

