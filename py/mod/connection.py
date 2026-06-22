"""
Connection state machine for the Rship TouchDesigner executor.

This module owns the connection lifecycle only. It decides whether we are
UNINITIALIZED / DISCONNECTED / CONNECTED from observed signals and drives
reconnection. It performs no rship data modelling and makes no network calls
itself - TouchDesigner's WebSocket / Web Client / Timer DATs do the actual I/O,
and RshipExt feeds their callbacks in here as signals.

reconcile() is the ONLY method that changes self.state, so the reported state
is always derived from observed reality.

Connection truth is TouchDesigner's own socket state, surfaced through the
websocket DAT's onConnect / onDisconnect callbacks (and its idle `timeout`,
which fires onDisconnect on a dead socket). We do NOT tear a socket down on
heartbeat silence: not every rship server answers ping frames with pongs, so a
healthy-but-quiet link must stay up. The periodic ping in tick() is a keepalive
that also provokes TD to notice a dead socket sooner; a received ping/pong/text
(noteBeat) is treated only as proof the socket is open.
"""
import time
from enum import Enum
from typing import Callable


class ConnState(Enum):
    UNINITIALIZED = "uninitialized"  # no machine id yet - cannot operate
    DISCONNECTED = "disconnected"    # configured, but websocket is not healthy
    CONNECTED = "connected"          # websocket healthy (socket open + recent heartbeat)


class ConnectionManager:
    """Owns connection state + reconnection. Coordinates with the extension
    through two injected hooks; holds no rship data model."""

    # Reconnect backoff tuning (seconds). Plain constants so they are trivially
    # inspectable; promote to custom pars later if they need to be live-tunable.
    RECONNECT_BASE_S = 2.0      # first retry delay after a drop
    RECONNECT_MAX_S = 30.0      # backoff ceiling

    def __init__(
        self,
        ownerComp,
        onConnect: Callable[[], None],
        publishState: Callable[["ConnState"], None],
        sendPing: Callable[[], None],
    ):
        """
        ownerComp    - the rship COMP; used to read Address and pulse Reconnect.
        onConnect    - called once on each DISCONNECTED -> CONNECTED edge (push data).
        publishState - called on every state change so the extension can mirror
                       the state onto its TD-facing properties.
        sendPing     - sends a websocket ping frame; used to actively keep the
                       heartbeat fresh (we solicit pongs rather than waiting for
                       the server to ping us).
        """
        self.ownerComp = ownerComp
        self._onConnect = onConnect
        self._publishState = publishState
        self._sendPing = sendPing

        self.state = ConnState.UNINITIALIZED
        self._machineId = None

        # Liveness signals, written by the note* methods below.
        self._socketOpen = False     # TD socket state from onConnect/onDisconnect; the authority
        self._lastReconnectAt = 0.0  # time.monotonic() of last reconnect pulse
        self._reconnectBackoff = self.RECONNECT_BASE_S

    # region signals (called by RshipExt callback wrappers)

    def setMachineId(self, machineId):
        """Identity gate input. None/'' => we cannot operate (UNINITIALIZED)."""
        self._machineId = machineId or None

    def noteSocketOpen(self):
        self._socketOpen = True
        self.reconcile()

    def noteSocketClosed(self):
        self._socketOpen = False
        self.reconcile()

    def noteBeat(self):
        # Any inbound ws traffic (ping/pong/text) proves the socket is open; this
        # also heals the case where onConnect was skipped (e.g. extensions not
        # ready at connect time). It is never used to tear a connection down.
        self._socketOpen = True
        self.reconcile()

    # endregion signals

    @property
    def isConnected(self) -> bool:
        return self.state == ConnState.CONNECTED

    # region state machine

    def tick(self):
        """Called ~1Hz by the reconnect timer. While the socket is open we send a
        ping to solicit a pong (which routes back through noteBeat), keeping the
        heartbeat fresh on a live-but-quiet link. Then re-derive state."""
        if self._socketOpen:
            try:
                self._sendPing()
            except Exception as e:
                op.RS_LOG.Debug(f"[Connection]: ping send failed: {e}")
        self.reconcile()

    def reconcile(self):
        """Single decision point for connection state and recovery."""
        # 1. Identity gate - without a machine id we cannot operate.
        if self._machineId is None:
            self._setState(ConnState.UNINITIALIZED)
            return

        # 2. Healthy = TD reports the socket open.
        if self._socketOpen:
            if self.state != ConnState.CONNECTED:
                self._setState(ConnState.CONNECTED)
                self._onConnect()
            self._reconnectBackoff = self.RECONNECT_BASE_S
            return

        # 3. Socket closed - report disconnected and drive reconnect.
        self._setState(ConnState.DISCONNECTED)
        self._maybeReconnect()

    def _setState(self, newState: "ConnState"):
        if self.state == newState:
            return
        op.RS_LOG.Info(f"[Connection]: {self.state.value} -> {newState.value}")
        self.state = newState
        self._publishState(newState)

    def _maybeReconnect(self):
        """Pulse the (TD-owned) Reconnect par, rate-limited by exponential backoff."""
        address = self.ownerComp.par.Address.eval()
        if not address:
            return  # nothing to connect to yet

        now = time.monotonic()
        if now - self._lastReconnectAt < self._reconnectBackoff:
            return

        self._lastReconnectAt = now
        op.RS_LOG.Info(
            f"[Connection]: reconnecting to {address} (backoff {self._reconnectBackoff:.0f}s)"
        )
        self.ownerComp.par.Reconnect.pulse()
        self._reconnectBackoff = min(self._reconnectBackoff * 2, self.RECONNECT_MAX_S)

    # endregion state machine
