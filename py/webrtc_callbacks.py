from exec import Stream
from uuid import uuid4
from handle_webrtc import handle_on_answer, handle_on_ice_candidate, cleanup_connection
# me - this DAT.
# webrtcDAT - the connected WebRTC DAT
# connectionId - uuid of the connection associated with the callback


# Triggered after webrtcDAT.createOffer
# This callback should set the local description then pass it on to the remote peer via the signalling server
def onOffer(webrtcDAT, connectionId, localSdp):
	# webrtcDAT.setLocalDescription(connectionId, 'offer', localSdp, stereo=False)
	# Send localSdp to signalling server
	return

# Triggered after webrtcDAT.createAnswer
# This callback should set the local description then pass it on to the remote peer via the signalling server.
def onAnswer(webrtcDAT, connectionId, localSdp):
	webrtcDAT.setLocalDescription(connectionId, 'answer', localSdp, stereo=False)
	me.ext.RshipExt.HandleWebRTCAnswer(connectionId, localSdp)
	return

# Trigged when changes to the connection require negotiation via the signalling server
# Eg. webrtcDAT.addTrack, webrtcDAT.removeTrack 
def onNegotiationNeeded(webrtcDAT, connectionId):
	return

# Triggered when a local ICE candidate is gathered
# Local ICE candidates should be sent to remote peer via the signalling server
def onIceCandidate(webrtcDAT, connectionId, candidate, lineIndex, sdpMid):
	me.ext.RshipExt.HandleWebRTCIceCandidate(connectionId, candidate, sdpMid, lineIndex)
	# handle_on_ice_candidate(connectionId, candidate, sdpMid, lineIndex)
	return

def onIceCandidateError(webrtcDAT, connectionId, errorText):
	return

# Triggered on remote track added
def onTrack(webrtcDAT, connectionId, trackId, type):
	return

# Triggered on remote track removed
def onRemoveTrack(webrtcDAT, connectionId, trackId, type):
	return

# Triggered when data channel is created remotely
def onDataChannel(webrtcDAT, connectionId, channelName):
	return

# Triggered when data channel is opened
def onDataChannelOpen(webrtcDAT, connectionId, channelName):
	return

# Triggered when data channel is closed
def onDataChannelClose(webrtcDAT, connectionId, channelName):
	return

# Triggered on receive data through data channel
def onData(webrtcDAT, connectionId, channelName, data):
	return

def onConnectionStateChange(webrtcDAT, connectionId, newState):

	print(f"Connection {connectionId} state changed to {newState}")
	if newState == 'closed':

		cleanup_connection(connectionId)
		print(f"Connection {connectionId} cleaned up.")

def onSignalingStateChange(webrtcDAT, connectionId, newState):
	return

def onIceConnectionStateChange(webrtcDAT, connectionId, newState):
	return

def onIceGatheringStateChange(webrtcDAT, connectionId, newState):
	return
	