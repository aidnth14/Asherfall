"""Push-to-talk voice chat over the same relay the game already uses.

Mic audio is captured at 8 kHz mono, crushed to 8-bit, base64'd and sent as
small JSON packets; incoming packets are mixed into a jitter buffer and played
back. Everything degrades gracefully — if PortAudio / a mic isn't available the
module just reports unavailable and the game runs on without voice.

Note: voice needs headroom the public relay's rate limit doesn't give, so it's
meant for the bundled/self-hosted relay (server/ raises the caps). Text chat and
movement stay well within the public relay's budget.
"""
import base64
import collections
import threading

SR = 8000            # sample rate (Hz) — telephone-ish, plenty for chat
CHUNK = 1024         # samples per packet (~128 ms) -> ~8 packets/sec

try:
    import numpy as np
    import sounddevice as sd
    _HAVE_AUDIO = True
except Exception:               # missing dep or no audio backend
    _HAVE_AUDIO = False


def encode(int16_block):
    """int16 mono samples -> base64 str of 8-bit PCM (half the bytes)."""
    small = (int16_block >> 8).astype("int8")
    return base64.b64encode(small.tobytes()).decode("ascii")


def decode(b64):
    """base64 8-bit PCM -> int16 numpy block."""
    raw = base64.b64decode(b64.encode("ascii"))
    return np.frombuffer(raw, dtype="int8").astype("int16") << 8


class Voice:
    def __init__(self):
        self.available = _HAVE_AUDIO
        self.talking = False
        self.error = "" if _HAVE_AUDIO else "install sounddevice + numpy for voice"
        self._outbox = collections.deque(maxlen=32)      # encoded chunks to send
        self._play = collections.deque(maxlen=SR * 2)    # int16 samples to play
        self._lock = threading.Lock()
        self._in_stream = None
        self._out_stream = None

    def _ensure_out_stream(self):
        if self._out_stream is None and _HAVE_AUDIO:
            try:
                self._out_stream = sd.OutputStream(
                    samplerate=SR, channels=1, dtype="int16", blocksize=CHUNK,
                    callback=self._out_cb)
                self._out_stream.start()
            except Exception as e:
                self.available = False
                self.error = f"audio out failed: {e}"

    def _out_cb(self, outdata, frames, time_info, status):
        with self._lock:
            if not self._play:
                outdata.fill(0)
                return
            for i in range(frames):
                outdata[i, 0] = self._play.popleft() if self._play else 0

    def push_incoming(self, b64):
        if not self.available:
            return
        self._ensure_out_stream()
        try:
            block = decode(b64)
        except Exception:
            return
        with self._lock:
            for s in block:                 # mix by append (overlapping talkers sum-ish)
                self._play.append(int(s))

    # --- capture: only while the talk key is held ---
    def _in_cb(self, indata, frames, time_info, status):
        block = (indata[:, 0] * 32767).astype("int16") if indata.dtype.kind == "f" \
            else indata[:, 0].astype("int16")
        self._outbox.append(encode(block))

    def start_talk(self):
        if not self.available or self.talking:
            return
        try:
            self._in_stream = sd.InputStream(
                samplerate=SR, channels=1, dtype="int16", blocksize=CHUNK,
                callback=self._in_cb)
            self._in_stream.start()
            self.talking = True
        except Exception as e:
            self.error = f"mic failed: {e}"

    def stop_talk(self):
        self.talking = False
        st, self._in_stream = self._in_stream, None
        if st:
            try:
                st.stop(); st.close()
            except Exception:
                pass

    def poll_outgoing(self):
        """Return queued encoded chunks to transmit, clearing the outbox."""
        out = []
        while self._outbox:
            out.append(self._outbox.popleft())
        return out

    def close(self):
        self.stop_talk()
        if self._out_stream:
            try:
                self._out_stream.stop(); self._out_stream.close()
            except Exception:
                pass
