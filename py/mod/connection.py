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
import json
from collections import deque
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


class RegistrationCoordinator:
    """Tracks registration readiness without changing socket ownership."""

    SENSITIVE_COMMANDS = frozenset((
        "ExecTargetAction",
        "BatchTargetAction",
        "CompactBatchTargetAction",
        "ResendEmitterValue",
    ))

    def __init__(self, clock=time.monotonic, reject=None, max_commands=1024,
                 max_bytes=16 * 1024 * 1024):
        self._clock = clock
        self._reject = reject
        self._maxCommands = max_commands
        self._maxBytes = max_bytes
        self._queue = deque()
        self._queuedBytes = 0
        self._generation = 0
        self._socketOpen = False
        self._active = False
        self._draining = False
        self._retryAt = 0.0
        self._retryDelay = 1.0

    @property
    def generation(self):
        return self._generation

    @property
    def is_active(self):
        return self._socketOpen and self._active

    @property
    def is_loading(self):
        return self._socketOpen and (not self._active or self._draining)

    @property
    def queued_count(self):
        return len(self._queue)

    @property
    def retry_delay(self):
        return self._retryDelay

    def socket_opened(self):
        self._generation += 1
        self._socketOpen = True
        self._active = False
        self._draining = False
        self._clear_queue()
        self._retryAt = 0.0
        self._retryDelay = 1.0
        return self._generation

    def socket_closed(self):
        self._generation += 1
        self._socketOpen = False
        self._active = False
        self._draining = False
        self._clear_queue()
        self._retryAt = 0.0
        self._retryDelay = 1.0
        return self._generation

    def begin_refresh(self):
        if not self._socketOpen:
            return None
        self._active = False
        self._draining = bool(self._queue)
        self._retryAt = 0.0
        return self._generation

    def is_current(self, generation):
        return self._socketOpen and generation == self._generation

    def registration_succeeded(self, generation):
        if not self.is_current(generation):
            return False
        self._active = True
        self._draining = bool(self._queue)
        self._retryAt = 0.0
        self._retryDelay = 1.0
        return True

    def registration_failed(self, generation):
        if not self.is_current(generation):
            return False
        self._active = False
        self._draining = False
        self._retryAt = self._clock() + self._retryDelay
        self._retryDelay = min(self._retryDelay * 2.0, 30.0)
        return True

    def retry_due(self):
        return self._socketOpen and not self._active and self._clock() >= self._retryAt

    def defer_if_loading(self, raw_text):
        if not self.is_loading:
            return False
        command_id, tx = self._sensitive_command(raw_text)
        if command_id is None:
            return False
        size = len(raw_text.encode("utf-8"))
        if len(self._queue) >= self._maxCommands or self._queuedBytes + size > self._maxBytes:
            if self._reject is not None:
                self._reject(tx, command_id, "Executor loading queue is full")
            return True
        self._queue.append((raw_text, size))
        self._queuedBytes += size
        return True

    def drain(self, dispatch, command_limit=16, time_limit=0.004):
        if not self._socketOpen or not self._active:
            return False
        deadline = self._clock() + time_limit
        processed = 0
        while self._queue and processed < command_limit and self._clock() <= deadline:
            raw_text, size = self._queue.popleft()
            self._queuedBytes -= size
            dispatch(raw_text)
            processed += 1
        self._draining = bool(self._queue)
        return self._draining

    def _clear_queue(self):
        self._queue.clear()
        self._queuedBytes = 0

    def _sensitive_command(self, raw_text):
        try:
            message = json.loads(raw_text)
        except (TypeError, ValueError):
            return None, None
        if not isinstance(message, dict):
            return None, None
        event = message.get("event")
        data = message.get("data") or {}
        if not isinstance(data, dict):
            return None, None
        if event == "ws:m:command":
            command_id = data.get("commandId")
            if command_id not in self.SENSITIVE_COMMANDS:
                return None, None
            command = data.get("command") or {}
            tx = command.get("tx", "") if isinstance(command, dict) else ""
            return command_id, tx
        if event == "ws:m:event" and data.get("itemType") == "ResendEmitterValue":
            item = data.get("item") or {}
            tx = item.get("tx", "") if isinstance(item, dict) else ""
            return "ResendEmitterValue", tx
        return None, None
