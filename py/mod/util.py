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


def ensureUniqueTargetIds(owners, previousTargets):
	"""Keep registered identities when copied COMPs inherit the same storage UUID."""
	from uuid import uuid4
	previous = {key: getattr(target, 'ownerComp', None) for key, target in previousTargets.items()}
	ordered = sorted(owners, key=lambda owner: (
		previous.get(owner.storage.get(RS_TARGET_ID_STORAGE_KEY)) != owner,
		owner.id,
	))
	reserved = {owner.storage.get(RS_TARGET_ID_STORAGE_KEY) for owner in owners}
	seen = set()
	changes = []
	for owner in ordered:
		uid = owner.storage.get(RS_TARGET_ID_STORAGE_KEY)
		if not uid:
			continue
		if uid in seen:
			newId = str(uuid4())
			while newId in reserved:
				newId = str(uuid4())
			owner.storage[RS_TARGET_ID_STORAGE_KEY] = newId
			reserved.add(newId)
			changes.append((owner, uid, newId))
		else:
			seen.add(uid)
	return changes

