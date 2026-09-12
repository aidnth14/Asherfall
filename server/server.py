import asyncio
import json
import logging
import random
import string
import time
import os
import websockets

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("relay")

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

PING_INTERVAL = 15
PING_TIMEOUT = 10
MAX_TOTAL_CONNECTIONS = 500
MAX_CONN_PER_IP = 32
MAX_NEW_CONN_PER_IP_PER_MIN = 60
MAX_MSGS_PER_SEC = 100
MAX_MESSAGE_BYTES = 4096
MAX_FAILED_JOINS_PER_IP = 12
FAILED_JOIN_WINDOW_SEC = 60
FAILED_JOIN_LOCKOUT_SEC = 120
ROOM_TTL_UNJOINED_SEC = 600
ROOM_CACHE_TTL_SEC = 1800
ROOM_CODE_LEN = 6
MIN_PLAYERS, MAX_PLAYERS = 2, 8
MAX_LOBBY_NAME_LEN = 32

class ServerState:
    def __init__(self):
        self.rooms = {}
        self.conns_per_ip = {}
        self.new_conn_times = {}
        self.failed_joins = {}
        self.blocked_until = {}
        self.total_connections = 0
        self.redis = None

    async def init_redis(self):
        if aioredis is None:
            log.info("redis package not installed; using in-memory cache")
            return
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1.0)
            await r.ping()
            self.redis = r
            log.info("Connected to Redis cache at %s", REDIS_URL)
        except Exception as e:
            log.info("Redis not reachable at %s (%s); operating with in-memory cache", REDIS_URL, e)
            self.redis = None

    async def cache_room(self, room):
        if not self.redis:
            return
        try:
            key = f"asherfall:room:{room.code}"
            data = {
                "code": room.code,
                "max_players": str(room.max_players),
                "lobby_name": room.lobby_name or "",
                "player_count": str(len(room.peers)),
                "host_session": room.host_session or "",
                "created": str(room.created),
            }
            await self.redis.hset(key, mapping=data)
            await self.redis.expire(key, ROOM_CACHE_TTL_SEC)
            await self.redis.sadd("asherfall:active_rooms", room.code)
        except Exception as e:
            log.warning("Redis cache_room error: %s", e)

    async def update_room_count(self, code, player_count):
        if not self.redis:
            return
        try:
            key = f"asherfall:room:{code}"
            await self.redis.hset(key, "player_count", str(player_count))
            await self.redis.expire(key, ROOM_CACHE_TTL_SEC)
        except Exception as e:
            log.warning("Redis update_room_count error: %s", e)

    async def remove_cached_room(self, code):
        if not self.redis:
            return
        try:
            await self.redis.delete(f"asherfall:room:{code}")
            await self.redis.srem("asherfall:active_rooms", code)
        except Exception as e:
            log.warning("Redis remove_cached_room error: %s", e)

    def gen_code(self):
        while True:
            c = "".join(random.choices(string.ascii_uppercase + string.digits, k=ROOM_CODE_LEN))
            if c not in self.rooms:
                return c

    def client_ip(self, ws):
        addr = ws.remote_address
        return addr[0] if addr else "unknown"

    def prune_old(self, timestamps, window):
        cutoff = time.time() - window
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

    async def is_blocked(self, ip):
        until = self.blocked_until.get(ip)
        if until and time.time() < until:
            return True
        if until:
            del self.blocked_until[ip]
        if self.redis:
            try:
                if await self.redis.get(f"asherfall:blocked:{ip}"):
                    return True
            except Exception:
                pass
        return False

    async def record_failed_join(self, ip):
        times = self.failed_joins.setdefault(ip, [])
        times.append(time.time())
        self.prune_old(times, FAILED_JOIN_WINDOW_SEC)
        if len(times) >= MAX_FAILED_JOINS_PER_IP:
            self.blocked_until[ip] = time.time() + FAILED_JOIN_LOCKOUT_SEC
            log.warning("ip %s locked out %ss", ip, FAILED_JOIN_LOCKOUT_SEC)
            if self.redis:
                try:
                    await self.redis.set(f"asherfall:blocked:{ip}", "1", ex=FAILED_JOIN_LOCKOUT_SEC)
                except Exception:
                    pass

    def sweep_stale_rooms(self):
        now = time.time()
        stale = [c for c, r in self.rooms.items() if not r.get("joined") and now - r.get("created", 0) > ROOM_TTL_UNJOINED_SEC]
        for c in stale:
            del self.rooms[c]
        if stale:
            log.info("swept %d stale unjoined room(s)", len(stale))

state = ServerState()

class Room:
    def __init__(self, code, max_players, lobby_name, host_ws, host_session):
        self.code = code
        self.max_players = max_players
        self.lobby_name = lobby_name
        self.peers = {host_ws}
        self.host_ws = host_ws
        self.host_session = host_session
        self.created = time.time()
        self.joined = False

    def add_peer(self, ws):
        self.peers.add(ws)
        self.joined = True

    def remove_peer(self, ws):
        self.peers.discard(ws)
        if ws == self.host_ws:
            if self.peers:
                self.host_ws = next(iter(self.peers))
                asyncio.create_task(self.host_ws.send(json.dumps({"type": "promote_to_host"})))
            else:
                self.host_ws = None

    async def broadcast(self, sender_ws, raw_msg):
        for peer in list(self.peers):
            if peer is not sender_ws:
                try:
                    await peer.send(raw_msg)
                except websockets.exceptions.ConnectionClosed:
                    pass

async def handle(ws):
    ip = state.client_ip(ws)
    code = None

    if await state.is_blocked(ip):
        await ws.close(code=1008, reason="temporarily blocked")
        return

    if state.total_connections >= MAX_TOTAL_CONNECTIONS:
        await ws.close(code=1013, reason="server busy")
        return

    if state.conns_per_ip.get(ip, 0) >= MAX_CONN_PER_IP:
        await ws.close(code=1008, reason="too many connections")
        return

    window = state.new_conn_times.setdefault(ip, [])
    state.prune_old(window, 60)
    if len(window) >= MAX_NEW_CONN_PER_IP_PER_MIN:
        await ws.close(code=1008, reason="rate limited")
        return
    window.append(time.time())

    state.total_connections += 1
    state.conns_per_ip[ip] = state.conns_per_ip.get(ip, 0) + 1
    msg_times = []

    try:
        raw = await ws.recv()
        if len(raw) > MAX_MESSAGE_BYTES:
            return
        msg = json.loads(raw)

        if msg["type"] == "host":
            state.sweep_stale_rooms()
            session_id = msg.get("session_id")
            code = msg.get("room_code")
            
            if code and code in state.rooms and state.rooms[code].host_session == session_id:
                room = state.rooms[code]
                room.host_ws = ws
                room.add_peer(ws)
                await state.update_room_count(code, len(room.peers))
                await ws.send(json.dumps({
                    "type": "hosted", "code": code, "max_players": room.max_players,
                    "lobby_name": room.lobby_name, "player_count": len(room.peers)
                }))
            else:
                code = state.gen_code()
                try:
                    max_players = int(msg.get("max_players", MIN_PLAYERS))
                except:
                    max_players = MIN_PLAYERS
                max_players = max(MIN_PLAYERS, min(MAX_PLAYERS, max_players))
                lobby_name = str(msg.get("lobby_name", "")).strip()[:MAX_LOBBY_NAME_LEN]
                
                room = Room(code, max_players, lobby_name, ws, session_id)
                state.rooms[code] = room
                await state.cache_room(room)
                await ws.send(json.dumps({
                    "type": "hosted", "code": code, "max_players": max_players,
                    "lobby_name": lobby_name, "player_count": 1,
                }))
                log.info("room %s hosted by %s (active: %d)", code, ip, len(state.rooms))

        elif msg["type"] == "join":
            code = str(msg.get("code", "")).upper()[:ROOM_CODE_LEN]
            room = state.rooms.get(code)
            if not room or len(room.peers) >= room.max_players:
                await state.record_failed_join(ip)
                await ws.send(json.dumps({"type": "error", "msg": "room not found or full"}))
                return
            room.add_peer(ws)
            count = len(room.peers)
            await state.update_room_count(code, count)
            await ws.send(json.dumps({
                "type": "joined", "code": code, "max_players": room.max_players,
                "lobby_name": room.lobby_name, "player_count": count,
            }))
            await room.broadcast(ws, json.dumps({"type": "peer_joined", "player_count": count}))
            log.info("room %s joined (%d/%d) by %s", code, count, room.max_players, ip)

        else:
            return

        async for raw in ws:
            if len(raw) > MAX_MESSAGE_BYTES:
                continue
            
            now = time.time()
            msg_times.append(now)
            state.prune_old(msg_times, 1.0)
            if len(msg_times) > MAX_MSGS_PER_SEC:
                await ws.close(code=1008, reason="message rate limited")
                return

            try:
                inner_msg = json.loads(raw)
                if inner_msg.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong", "t": inner_msg.get("t")}))
                    continue
            except:
                pass
            
            room = state.rooms.get(code)
            if room:
                await room.broadcast(ws, raw)

    except (websockets.exceptions.ConnectionClosed, json.JSONDecodeError, KeyError) as e:
        log.info("session ended: %s", e.__class__.__name__)
    finally:
        state.total_connections -= 1
        state.conns_per_ip[ip] = max(0, state.conns_per_ip.get(ip, 1) - 1)
        if state.conns_per_ip[ip] == 0:
            del state.conns_per_ip[ip]
        
        room = state.rooms.get(code) if code else None
        if room:
            room.remove_peer(ws)
            if not room.peers:
                if code in state.rooms:
                    del state.rooms[code]
                await state.remove_cached_room(code)
                log.info("room %s closed (active: %d)", code, len(state.rooms))
            else:
                await state.update_room_count(code, len(room.peers))
                asyncio.create_task(room.broadcast(ws, json.dumps({"type": "peer_left", "player_count": len(room.peers)})))

async def main():
    await state.init_redis()
    log.info("Starting Asherfall Relay Server on %s:%s (capacity: %d connections)", HOST, PORT, MAX_TOTAL_CONNECTIONS)
    async with websockets.serve(
        handle, HOST, PORT,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_TIMEOUT,
        max_size=MAX_MESSAGE_BYTES,
    ):
        try:
            await asyncio.Future()
        finally:
            if state.redis:
                await state.redis.aclose()

if __name__ == "__main__":
    asyncio.run(main())
