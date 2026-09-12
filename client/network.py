import asyncio
import json
import logging
import queue
import socket
import ssl
import threading
import time
import websockets

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_RECONNECTING = "reconnecting"

log = logging.getLogger("network")

class Connection:
    def __init__(self):
        self.state = STATE_DISCONNECTED
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self.addr = None
        self.first_message = None
        self.session_id = None
        self._thread = None
        self._loop = None
        self._shutdown = threading.Event()

    def connect(self, addr, first_message, session_id):
        self.close()
        # Drain queues
        while not self.incoming.empty():
            try: self.incoming.get_nowait()
            except queue.Empty: break
        while not self.outgoing.empty():
            try: self.outgoing.get_nowait()
            except queue.Empty: break
        self.addr = addr
        self.first_message = first_message
        self.session_id = session_id
        self.state = STATE_CONNECTING
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()

    def _run_thread(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        except Exception as e:
            log.exception("Network thread crashed")
        finally:
            self.state = STATE_DISCONNECTED
            self._loop.close()

    async def _run_async(self):
        retry_delay = 0.5
        max_delay = 10.0
        attempts = 0
        max_attempts = 4
        
        while not self._shutdown.is_set():
            attempts += 1
            self._set_state(STATE_CONNECTING if attempts == 1 else STATE_RECONNECTING)
            
            try:
                async with websockets.connect(self.addr, ping_interval=15, ping_timeout=10, open_timeout=5) as ws:
                    self._set_state(STATE_CONNECTED)
                    attempts = 0
                    retry_delay = 0.5
                    
                    # Authenticate
                    auth_msg = dict(self.first_message)
                    auth_msg["session_id"] = self.session_id
                    await ws.send(json.dumps(auth_msg))
                    
                    sender_task = asyncio.create_task(self._sender(ws))
                    receiver_task = asyncio.create_task(self._receiver(ws))
                    
                    done, pending = await asyncio.wait(
                        [sender_task, receiver_task], 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    for task in pending:
                        task.cancel()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"Connection attempt {attempts} failed: {e}")
                if attempts >= max_attempts:
                    self.incoming.put({"type": "connect_error", "error": f"Connection failed ({e})."})
                    break
                
            if self._shutdown.is_set():
                break
                
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_delay)

    async def _sender(self, ws):
        while not self._shutdown.is_set():
            try:
                msg = self.outgoing.get_nowait()
                await ws.send(json.dumps(msg))
            except queue.Empty:
                await asyncio.sleep(0.01)
            except Exception as e:
                log.error(f"Send error: {e}")
                break

    async def _receiver(self, ws):
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    self.incoming.put(msg)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            log.error(f"Receive error: {e}")

    def send(self, msg):
        if self.state == STATE_CONNECTED:
            self.outgoing.put(msg)

    def close(self):
        self._shutdown.set()
        self.state = STATE_DISCONNECTED

    def _set_state(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.incoming.put({"type": "network_state", "state": new_state})

def install_dns_fallback():
    pass
