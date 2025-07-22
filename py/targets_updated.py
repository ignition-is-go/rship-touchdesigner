# # me - this DAT.
# # changeOp - the operator that has changed
# # 
# # Make sure the corresponding toggle is enabled in the OP Execute DAT.

# from exec import Stream, WebRTCConnection, GetWebRTCConnections
# from registry import client

# import uuid
# from touch import makeOpTarget, refresh
# from handle_webrtc import assertStream


# def onPreCook(changeOp):
# 	return

# def onPostCook(changeOp):

# 	print("updating targets")
# 	ops = [op(changeOp[i, 0].val) for i in range (0, changeOp.numRows)]
	
# 	targetIds = [o.fetch('rs_target_id', str(uuid.uuid4()), storeDefault=True) for o in ops]
	
# 	for i, o in enumerate(ops):
# 		id = targetIds[i]
# 		print(f"target id: {id} at {o.path}")
# 		first = targetIds.index(id)
# 		if first != i:
# 			#it's a duplicate
# 			o.store('rs_target_id', str(uuid.uuid4()))
# 		makeOpTarget(o)
# 		assertStream(id, o)

# 	# refresh()

# 	op('machine_id').par.request.pulse()
	
# 	return

# def onDestroy():
# 	return

# def onFlagChange(changeOp, flag):
# 	return

# def onWireChange(changeOp):
# 	return

# def onNameChange(changeOp):
# 	return

# def onPathChange(changeOp):
# 	return

# def onUIChange(changeOp):
# 	return

# def onNumChildrenChange(changeOp):
# 	return

# def onChildRename(changeOp):
# 	print("rename", changeOp)
# 	return

# def onCurrentChildChange(changeOp):
# 	return

# def onExtensionChange(changeOp, extension):
# 	return
	
