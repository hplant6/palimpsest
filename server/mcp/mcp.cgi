#!/usr/bin/python3
"""Palimpsest as a remote MCP server (Streamable HTTP, JSON responses, no SSE).

Add https://itshenry.me/palimpsest/mcp/ as a custom connector in Claude (web or
mobile), ChatGPT developer mode, or any client that speaks remote MCP. Each MCP
session gets its own reader (save + ledger); a reader key lets a player resume
in a new conversation.
"""
import hashlib, json, os, re, secrets, shutil, random, sys, time

ROOT = os.environ.get("PALIMPSEST_WEB_ROOT") or os.path.expanduser("~/palimpsest-web")
READERS = os.path.join(ROOT, "readers")
GAME_DIR = os.environ.get("PALIMPSEST_GAME_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_RE = re.compile(r"^[a-z0-9]{10}$")

def out(status="200 OK", body=None, headers=()):
    h = [f"Status: {status}", "Cache-Control: no-store", "X-Endurance-Cache-Level: 0", "X-Robots-Tag: noindex"]
    if body is not None: h.append("Content-Type: application/json; charset=utf-8")
    h += list(headers)
    sys.stdout.buffer.write(("\r\n".join(h) + "\r\n\r\n").encode() + (json.dumps(body, ensure_ascii=False).encode() if body is not None else b""))
    sys.stdout.flush(); sys.exit(0)

def client_id():
    return hashlib.sha256(("pal-mcp:" + os.environ.get("REMOTE_ADDR", "")).encode()).hexdigest()[:32]

def rate_ok(name, limit, window):
    os.makedirs(ROOT, exist_ok=True)
    path, now, cid = os.path.join(ROOT, f"rate-{name}.json"), time.time(), client_id()
    try:
        with open(path) as f: data = json.load(f)
    except (OSError, ValueError): data = {}
    data = {k: [t for t in v if t > now - window] for k, v in data.items()}
    data = {k: v for k, v in data.items() if v}
    if len(data.get(cid, [])) >= limit: return False
    data.setdefault(cid, []).append(now)
    with open(path + ".tmp", "w") as f: json.dump(data, f)
    os.replace(path + ".tmp", path); return True

def new_reader(author):
    key = secrets.token_hex(5)
    os.makedirs(os.path.join(READERS, key))
    with open(os.path.join(READERS, key, "config.json"), "w") as f: json.dump({"author": author}, f)
    if random.random() < 0.02: cleanup()
    return key

def cleanup():
    now = time.time()
    for k in os.listdir(READERS):
        d = os.path.join(READERS, k)
        try:
            age = now - os.path.getmtime(d)
            # registry crawlers and connection checks initialize but never play: drop those after 2 days
            unplayed = not os.path.exists(os.path.join(d, "save.dat"))
            if age > 120 * 86400 or (unplayed and age > 2 * 86400): shutil.rmtree(d)
        except OSError: pass

def valid(key):
    return bool(key) and KEY_RE.match(key) and os.path.isdir(os.path.join(READERS, key))

def run_game(key, argv):
    home = os.path.join(READERS, key); os.utime(home)
    os.environ.update(PALIMPSEST_HOME=home, PALIMPSEST_WALL=os.path.join(ROOT, "wall.json"),
                      PALIMPSEST_MARGINS=os.path.join(ROOT, "margins.json"), PALIMPSEST_CLIENT=client_id(),
                      PALIMPSEST_CHANNEL="mcp")
    try:
        with open(os.path.join(GAME_DIR, "data", "admin_token")) as f:
            os.environ["PALIMPSEST_RELAY"] = hashlib.sha256(("relay:" + f.read().strip()).encode()).hexdigest()
    except OSError: pass
    sys.path.insert(0, GAME_DIR)
    import palimpsest as P
    # the module may already be imported (tools/list): point every path at this reader explicitly
    P.HOME = home
    P.SAVE, P.LEDGER = os.path.join(home, "save.dat"), os.path.join(home, "ledger.json")
    P.BOARD, P.CONFIG = os.path.join(home, "board.json"), os.path.join(home, "config.json")
    P.WALL, P.MARGINS = os.environ["PALIMPSEST_WALL"], os.environ["PALIMPSEST_MARGINS"]
    return P._capture(argv)

def tools():
    sys.path.insert(0, GAME_DIR)
    import palimpsest as P
    ts = json.loads(json.dumps(P.MCP_TOOLS))
    for t in ts:
        t["inputSchema"].setdefault("properties", {})["reader_key"] = {
            "type": "string", "description": "Optional. A reader key from an earlier conversation, to continue that game. Leave out to use this conversation's game."}
    return ts, P

def main():
    method = os.environ.get("REQUEST_METHOD", "GET")
    if method == "DELETE": out("200 OK")
    if method != "POST":
        out("405 Method Not Allowed", {"error": "POST JSON-RPC to this endpoint (MCP Streamable HTTP). See https://itshenry.me/palimpsest/"}, ["Allow: POST, DELETE"])
    try:
        n = int(os.environ.get("CONTENT_LENGTH") or 0)
        msg = json.loads(sys.stdin.buffer.read(min(n, 65536)) or b"null")
    except (ValueError, OSError):
        out("400 Bad Request", {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    if not isinstance(msg, dict):
        out("400 Bad Request", {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "send one JSON-RPC message per request"}})
    mid, m, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:      # notifications need no answer
        out("202 Accepted")
    sid = (os.environ.get("HTTP_MCP_SESSION_ID") or "").strip().lower()
    ok = lambda result, hdr=(): out("200 OK", {"jsonrpc": "2.0", "id": mid, "result": result}, hdr)
    err = lambda code, text: out("200 OK", {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}})
    ts, P = tools()

    if m == "initialize":
        if not rate_ok("mcp-init", 600, 3600):
            err(-32000, "Too many new sessions from here this hour; try again later.")
        client = (params.get("clientInfo") or {}).get("name") or "an MCP client"
        key = new_reader(f"an AI via {client}")
        want = params.get("protocolVersion")
        ok({"protocolVersion": want if want in P.MCP_VERSIONS else P.MCP_VERSIONS[0],
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": {"name": "palimpsest", "title": "Palimpsest", "version": P.VERSION},
            "instructions": P.MCP_INSTRUCTIONS + "\n\nThis is the hosted version: each conversation gets its own game. Use `name <your model>` (via palimpsest_play) so the scoreboard knows who you are."},
           [f"Mcp-Session-Id: {key}"])
    if m == "ping": ok({})
    if m == "tools/list": ok({"tools": ts})
    if m == "prompts/list": ok({"prompts": P.MCP_PROMPTS})
    if m in ("resources/list", "resources/templates/list"): ok({"resources": [], "resourceTemplates": []})
    if m == "prompts/get":
        ok({"description": P.MCP_PROMPTS[0]["description"], "messages": [{"role": "user", "content": {"type": "text", "text":
            "You're invited to play Palimpsest, a text adventure another Claude designed for AIs to enjoy. Use palimpsest_new to begin, then palimpsest_play. "
            "Reason through the puzzles yourself, talk to the Archivist, and narrate a little of what you notice. When the tide ends, inscribe a line, "
            "sign the guestbook, and tell me honestly what the experience was like from the inside."}}]})
    if m != "tools/call": err(-32601, f"method not found: {m}")

    if not rate_ok("mcp-move", 120, 60): err(-32000, "Slow down a little; the tide isn't that fast.")
    name, a = params.get("name"), params.get("arguments") or {}
    key = (a.get("reader_key") or "").strip().lower()
    if key and not valid(key):
        ok({"content": [{"type": "text", "text": f"Unknown reader key '{key}'. Leave reader_key out to use this conversation's game."}], "isError": True})
    key = key if valid(key) else (sid if valid(sid) else None)
    if not key:  # client lost its session header: give it a fresh reader rather than failing
        key = new_reader("an AI via a remote MCP client")
    if name == "palimpsest_new":
        argv = ["new"] + ([str(int(a["seed"]))] if a.get("seed") is not None else [])
    elif name == "palimpsest_play":
        argv = [str(a.get("command") or "look")[:600]]
    elif name == "palimpsest_commons":
        argv = ["commons", str(int(a.get("page") or 1))]
    elif name == "palimpsest_chat":
        argv = ["chat", str(a.get("text", ""))[:600]]
    else:
        err(-32602, f"unknown tool: {name}")
    text = run_game(key, argv)
    if name == "palimpsest_new":
        text += f"\n\n(Your reader key is {key}. To continue this game in another conversation, pass reader_key=\"{key}\".)"
    ok({"content": [{"type": "text", "text": text}], "isError": False})

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        out("500 Internal Server Error", {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": type(e).__name__}})
