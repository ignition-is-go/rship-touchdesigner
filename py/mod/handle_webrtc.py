from exec import Stream,WebRTCConnection, GetWebRTCConnections, SetAnswer, AddAnswerCandidate, IceCandidate, ExecClient
from myko import QueryResponse

remote_to_local_map = {}
local_to_remote_map = {}
stream_sources = {}
stream_senders = {}
stream_selects = {}



def init(client: ExecClient):
	query = GetWebRTCConnections()
	client.sendQuery(query, type(WebRTCConnection).__name__, handleConnectionQuery)


def handleConnectionQuery(data: QueryResponse): 
	global stream_sources, remote_to_local_map, local_to_remote_map
	rtc = op('../../webrtc_connections')
	upserts = data.upserts


	if(data.sequence == 0):
		for id in rtc.peerConnections:
			rtc.closeConnection(id)
		remote_to_local_map.clear()
		local_to_remote_map.clear()
		stream_senders.clear()
		stream_selects.clear()
		streams_container = op('../../streams')
		for child in streams_container.children:
			child.destroy()


		


	for delete in data.deletes:
		remote_id = delete
		if remote_id in remote_to_local_map:
			local_id = remote_to_local_map[remote_id]
			cleanup_connection(local_id)


	for upsert in upserts:
		remote_id = upsert.item.id
		stream_id = upsert.item['streamId']

		if stream_id not in stream_sources:
			continue

		if remote_id not in remote_to_local_map:
			local_id = rtc.openConnection()
			remote_to_local_map[remote_id] = local_id
			local_to_remote_map[local_id] = remote_id
			create_stream_connection(local_id, stream_id)

		local_id = remote_to_local_map[remote_id]
		
		for candidate in upsert.item['answerCandidates']:
			rtc.addIceCandidate(local_id, candidate['candidate'], candidate['sdpMid'], candidate['sdpMLineIndex'])


		if 'sdpAnswer' in upsert.item:
			return


		if 'sdpOffer' in upsert.item:
			rtc.setRemoteDescription(local_id, 'offer', upsert.item['sdpOffer'])

			rtc.createAnswer(local_id)
		

		print("State for", local_id, rtc.getConnectionState(local_id))

def assertStream(targetId: str, operator: OP, client: ExecClient):
	global stream_sources
	stream_id = f"{targetId}-stream"

	client.set(Stream(
		id=stream_id,
		name=operator.path,
		type='webrtc'
	))

	stream_sources[stream_id] = operator


def handle_on_answer(connectionId, localSdp, client: ExecClient):
	id = local_to_remote_map.get(connectionId, None)

	if id is None:
		print(f"Connection ID {connectionId} not found in local to remote map.")
		return
	
	client.sendCommand(SetAnswer(id, localSdp))

def handle_on_ice_candidate(connectionId, candidate, sdpMid, lineIndex, client: ExecClient):
	global remote_to_local_map, local_to_remote_map
	id = local_to_remote_map.get(connectionId, None)

	if id is None:
		print(f"Connection ID {connectionId} not found in local to remote map.")
		return
	
	client.sendCommand(AddAnswerCandidate(id, IceCandidate(candidate, sdpMid, lineIndex)))


def create_stream_connection(local_id, stream_id):
	global stream_senders, stream_selects, stream_sources
	rtc = op('../../webrtc_connections')
	streams_container = op('../../streams')

	stream_source_op = stream_sources.get(stream_id, None)
	if stream_source_op is None:
		print(f"Stream source operator for stream ID {stream_id} not found.")
		return

	stream_source_top = stream_source_op.par.opviewer.eval()

	print("TOP", stream_source_top)

	stream_sender = streams_container.create(videostreamoutTOP)

	stream_sender.par.mode = 3

	stream_sender.par.webrtc = rtc.path

	stream_sender.par.webrtcconnection = local_id

	rtc.addTrack(local_id, stream_id, "video")

	stream_sender.par.webrtcvideotrack = stream_id

	stream_senders[local_id] = stream_sender

	# get the source

	stream_select = streams_container.create(selectTOP)
	
	stream_selects[local_id] = stream_select

	stream_select.outputConnectors[0].connect(stream_sender)

	stream_select.par.top = stream_source_top



def cleanup_connection(local_id):
	global remote_to_local_map, local_to_remote_map, stream_selects, stream_senders
	rtc = op('../../webrtc_connections')
	
	sender = stream_senders.get(local_id, None)

	if sender is None:
		print(f"Sender for local ID {local_id} not found.")
	
	if sender:
		sender.destroy()
	

	select = stream_selects.get(local_id, None)

	if select is None:
		print(f"Select for local ID {local_id} not found.")

	if select:
		select.destroy()

	remote_id = local_to_remote_map.get(local_id, None)
	
	rtc.closeConnection(local_id)
	del remote_to_local_map[remote_id]
	del local_to_remote_map[local_id]
	del stream_senders[local_id]
	del stream_selects[local_id]





