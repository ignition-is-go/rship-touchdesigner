from exec import Stream,WebRTCConnection, GetWebRTCConnections, SetAnswer, AddAnswerCandidate, IceCandidate, ExecClient
from myko import QueryResponse
import TDFunctions as TDF

remote_to_local_map = {}
local_to_remote_map = {}
stream_sources = {}
# stream_senders = {}
# stream_selects = {}
# noise_tops = {}



def init(client: ExecClient):
	query = GetWebRTCConnections()
	client.sendQuery(query, type(WebRTCConnection).__name__, handleConnectionQuery)


def handleConnectionQuery(data: QueryResponse): 
	global stream_sources
	rtc = op('../../webrtc_connections')

	rtc_requests = op('../../webrtc_requests')

	upserts = data.upserts

	if(data.sequence == 0):
		rtc_requests.clear()

		for id in rtc.peerConnections:
			rtc.closeConnection(id)

	for delete in data.deletes:
		remote_id = delete
		if remote_id in remote_to_local_map:
			local_id = remote_to_local_map[remote_id]
			cleanup_connection(local_id)

	for upsert in upserts:
		remote_id = upsert.item['id']
		stream_id = upsert.item['streamId']

		if stream_id not in stream_sources:
			continue

		if remote_id not in remote_to_local_map:
			local_id = rtc.openConnection()
			op_path = stream_sources[stream_id]
			rtc_requests.appendRow([local_id, op_path, stream_id])
			remote_to_local_map[remote_id] = local_id
			local_to_remote_map[local_id] = remote_id
			
			rtc.addTrack(local_id, stream_id, "video")

		local_id = remote_to_local_map[remote_id]
		
		for candidate in upsert.item['answerCandidates']:
			rtc.addIceCandidate(local_id, candidate['candidate'], candidate['sdpMid'], candidate['sdpMLineIndex'])


		if 'sdpAnswer' in upsert.item:
			return


		if 'sdpOffer' in upsert.item:
			rtc.setRemoteDescription(local_id, 'offer', upsert.item['sdpOffer'])

			rtc.createAnswer(local_id)
		

		print("State for", local_id, rtc.getConnectionState(local_id))

def assertStream(targetId: str, instanceId: str, operator: OP, client: ExecClient):
	global stream_sources
	stream_id = f"{targetId}-{instanceId}-stream"

	client.set(Stream(
		id=stream_id,
		name=operator.name,
		type='webrtc'
	))

	if operator.OPType.find("TOP") != -1:
		path = operator.path

	if operator.OPType.find("COMP") != -1:
		path = operator.par.opviewer.eval()


	stream_sources[stream_id] = path


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

def cleanup_connection(local_id):
	rtc = op('../../webrtc_connections')
	rtc_requests = op('../../webrtc_requests')

	localCell = rtc_requests.findCell(local_id)

	# print(localCell)

	if localCell is None:
		print("No rows found in rtc_requests table.")
		return

	rtc_requests.deleteRows(localCell.row)
	rtc.closeConnection(local_id)





