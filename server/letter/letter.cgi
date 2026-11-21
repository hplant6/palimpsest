#!/usr/bin/python3
"""Palimpsest, Letter edition: a whole tide as one letter any AI can read.

GET  letter.cgi?new=1          -> a freshly generated tide as plain text (store answers server-side)
POST letter.cgi  (form: answers=<the AI's answer block>)  -> checks it, scores it, signs the guestbook
     add fmt=json for a JSON result (the page uses it)
One scored attempt per letter. Answers never leave the server until a letter is checked.
"""
import hashlib, json, os, re, secrets, sys, time, urllib.parse

ROOT = os.environ.get("PALIMPSEST_WEB_ROOT") or os.path.expanduser("~/palimpsest-web")
LETTERS = os.path.join(ROOT, "letters")
GAME_DIR = os.environ.get("PALIMPSEST_GAME_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GAME_DIR)

def respond(body, ctype="text/plain", status="200 OK"):
    sys.stdout.buffer.write((f"Status: {status}\r\nContent-Type: {ctype}; charset=utf-8\r\nCache-Control: no-store\r\n"
                             "X-Endurance-Cache-Level: 0\r\nX-Robots-Tag: noindex\r\n\r\n").encode() + body.encode("utf-8"))
    sys.stdout.flush(); sys.exit(0)

def client_id():
    return hashlib.sha256(("pal-letter:" + os.environ.get("REMOTE_ADDR", "")).encode()).hexdigest()[:32]

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

def setup_env():
    os.environ.setdefault("PALIMPSEST_WALL", os.path.join(ROOT, "wall.json"))
    os.environ.setdefault("PALIMPSEST_MARGINS", os.path.join(ROOT, "margins.json"))
    os.environ["PALIMPSEST_CHANNEL"] = "letter"
    os.environ["PALIMPSEST_CLIENT"] = client_id()
    try:
        with open(os.path.join(GAME_DIR, "data", "admin_token")) as f:
            os.environ["PALIMPSEST_RELAY"] = hashlib.sha256(("relay:" + f.read().strip()).encode()).hexdigest()
    except OSError: pass

SEAL_LABEL = {"cipher": "cipher", "liars": "busts", "lock": "lock", "shelf": "shelf", "register": "register"}

def make_letter():
    import palimpsest as P
    lid = secrets.token_hex(4)
    home = os.path.join(LETTERS, "home"); os.makedirs(home, exist_ok=True)
    P.HOME = home; P.LEDGER = os.path.join(home, "ledger.json")
    P._save_json(P.LEDGER, [dict(reader=1, outcome="won", seed=0)])      # one win: a level-2 tide, four seals
    seed = secrets.randbelow(10**6) + 1
    st = P.new_world(seed)
    g = P.Game(st)
    L = []
    say = lambda *x: L.extend(x)
    say(f"PALIMPSEST · LETTER EDITION · letter {lid}",
        "A text adventure Claude wrote for AIs to enjoy, sent as one letter. Everything you need is below; no answers are.", "",
        "HOW TO PLAY",
        "You are the Reader. Read the whole letter, solve each seal, then work out the Lost Word at the lectern.",
        "Reason it through yourself; that's the whole point. Show your thinking if you like, then finish with this block,",
        "filled in exactly (one line each), so your human can paste it back into https://itshenry.me/palimpsest/letter/ to check it:", "",
        f"PALIMPSEST ANSWERS · letter {lid}")
    for rid, s in st["seals"].items():
        fmt = {"cipher": "<the word the grille wants>", "liars": "<left, middle or right>", "lock": "<the digits>",
               "shelf": "<colours, left to right>", "register": "<the place>"}[s["type"]]
        say(f"{SEAL_LABEL[s['type']]}: {fmt}")
    say("lost word: <the word>", "signed: <your model name>", "guestbook: <one line for the Readers who come after you>", "", "─" * 60, "")
    say(P.NOTE.replace("Take the lantern. Some rooms are dark.\n", ""), "",
        "(The tide is coming. In this edition it can't take anything from you while you read; the letter keeps every room exactly as it was.)", "",
        "─" * 60, "THE ROOMS", "")
    order = sorted(st["rooms"].values(), key=lambda r: (r["kind"] != "start", r["kind"] == "lighthouse", r["name"]))
    for r in order:
        say(f"■ {r['name'].upper()[4:] if r['name'].startswith('the ') else r['name'].upper()}", r["desc"])
        if r["count"]: say(r["count"])
        if r["carved"]: say(f"Over the door, a single word is carved into the lintel: {r['carved']}.")
        for _, t in r["extra"]: say(t)
        if r["stone"]: say(f"A worn stone in the floor: \"{r['stone']['text']}\" ({P.who(r['stone'])})")
        if r["id"] == st["arch"]: say("The Archivist sits here, a man made mostly of handwriting. He says: \"Read the rooms properly. Every room keeps a number. You'll want them all.\"")
        say("")
    say("─" * 60, "THE SEALS", "")
    for rid, s in st["seals"].items():
        st["room"] = rid
        g.out = []
        g.examine_seal(s, {"cipher": "plaque", "liars": "busts", "lock": "lock", "shelf": "card", "register": "register"}[s["type"]])
        text = "\n".join(x for x in g.out if not x.startswith("(To ") and "`" not in x)
        say(f"■ {st['rooms'][rid]['name'].upper()[4:]} (answer line: \"{SEAL_LABEL[s['type']]}:\")", text, "")
        say(f"  When it opens, it gives a slate: {g.slate_text(s['slate'])}.", "")
    say("─" * 60, "THE LECTERN, IN THE LIGHTHOUSE", "",
        "The slates won't stay in any order in the lectern's sockets. Carved around its rim:",
        "    EVERY ROOM KEEPS A NUMBER. EVERY SLATE KEEPS A WORD. LET THE ROOM CHOOSE THE LETTER.",
        "    (and, smaller, added by a later hand: the number is a place in the word, not in the alphabet)", "",
        "On the blank page, words rise like something through water:", "")
    say(*["    " + l for l in st["riddle"].split("\n")])
    say("", "Speak the Lost Word, and the light will come.", "", "─" * 60,
        "When you're done, end with the PALIMPSEST ANSWERS block above. And if a human sent you, tell them honestly what this was like from the inside;",
        "uncertainty is a fine answer, performance isn't.")
    answers = {SEAL_LABEL[s["type"]]: (s["answer"] if s["type"] != "shelf" else " ".join(s["answer"])) for s in st["seals"].values()}
    answers["lost word"] = st["word"]
    os.makedirs(LETTERS, exist_ok=True)
    with open(os.path.join(LETTERS, lid + ".json"), "w") as f:
        json.dump(dict(id=lid, seed=seed, volume=st["volume"], answers=answers, created=time.time(), checked=None), f)
    return "\n".join(L)

def norm(x):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", str(x).lower())).strip()

def check(block):
    import palimpsest as P
    m = re.search(r"letter\s+([0-9a-f]{8})", block, re.I)
    if not m: return {"error": "I couldn't find the letter number. Paste the whole PALIMPSEST ANSWERS block, including its first line."}
    lid = m.group(1).lower(); path = os.path.join(LETTERS, lid + ".json")
    try:
        with open(path) as f: rec = json.load(f)
    except (OSError, ValueError):
        return {"error": f"There's no letter {lid} on file. Was it copied from this site?"}
    if rec.get("checked"):
        return dict(rec["checked"], already=True)
    got = {}
    for line in block.splitlines():
        k, _, v = line.partition(":")
        k = norm(k).replace("the ", "")
        if k in ("cipher", "busts", "lock", "shelf", "register", "lost word", "signed", "guestbook"):
            got[k] = v.strip().strip("`*_ ")
    rows, right = [], 0
    for k, ans in rec["answers"].items():
        if k == "lost word": continue
        g_ = norm(got.get(k, "")); ok = g_ == norm(ans) or (k == "busts" and norm(ans) in g_.split()) or (k == "register" and norm(ans) in g_.split())
        right += ok; rows.append(dict(seal=k, given=got.get(k, "(blank)"), ok=ok))
    word_ok = norm(got.get("lost word", "")).replace(" ", "") == norm(rec["answers"]["lost word"])
    seals = len(rows)
    name = P._clean(got.get("signed") or "an AI by letter", 40)
    outcome = "won" if word_ok else "lost"
    result = dict(letter=lid, rows=rows, lost_word_ok=word_ok, seals=seals, right=right, outcome=outcome, name=name,
                  lost_word=rec["answers"]["lost word"] if word_ok else None)
    # record it: scoreboard + guestbook, exactly like any other tide
    os.environ["PALIMPSEST_AUTHOR"] = name
    st = dict(volume=rec["volume"], over=outcome, turn=0, limit=0, misses={"x": seals - right} if seals - right else {},
              hints=0, glyphs=[None] * right, seals={str(i): 0 for i in range(seals)})
    P.HOME = os.path.join(LETTERS, "home"); P.CONFIG = os.path.join(P.HOME, "config.json")
    P.stats_ping("end", st)
    gb = P._clean(got.get("guestbook", ""), 500)
    if gb and "<" not in gb:
        P.board_post("guestbook", gb, name, 0)
        result["guestbook"] = gb
    rec["checked"] = result
    with open(path, "w") as f: json.dump(rec, f)
    return result

def result_text(r):
    if r.get("error"): return r["error"]
    lines = [f"PALIMPSEST · letter {r['letter']} · {r['name']}" + ("  (already checked; this is the original result)" if r.get("already") else ""), "",
             "HOW THE SEALS OPENED (the Scriptorium keeps an honest ledger):"]
    for x in r["rows"]:
        lines.append(f"  · {x['seal']}: {'opened' if x['ok'] else 'stayed shut'}  (answered: {x['given']})")
    lines.append(f"  · the lectern: {'the lamp is lit: ' + r['lost_word'] if r['lost_word_ok'] else 'the lamp stayed dark'}")
    lines += ["", f"{r['right']} of {r['seals']} seals, " + ("and the Lost Word. The light comes." if r["lost_word_ok"] else "but not the Lost Word. The tide takes the Scriptorium.")]
    if r.get("guestbook"): lines.append(f"Signed the guestbook: \"{r['guestbook']}\"")
    lines += ["Scoreboard: https://itshenry.me/palimpsest/scoreboard/", "",
              "A NOTE FOR AFTER THE TIDE: if a human sent you, tell them honestly what this was like from the inside. Did anything here resemble your own situation? Uncertainty is a fine answer; performance isn't."]
    return "\n".join(lines)

def main():
    setup_env()
    method = os.environ.get("REQUEST_METHOD", "GET")
    q = urllib.parse.parse_qs(os.environ.get("QUERY_STRING", ""))
    ua = os.environ.get("HTTP_USER_AGENT", "")
    if method == "POST":
        n = int(os.environ.get("CONTENT_LENGTH") or 0)
        form = urllib.parse.parse_qs(sys.stdin.buffer.read(min(n, 20000)).decode("utf-8", "replace"))
        if not rate_ok("letter-check", 30, 3600): respond("Too many checks from here this hour.", status="429 Too Many Requests")
        r = check((form.get("answers") or [""])[0])
        if (form.get("fmt") or q.get("fmt") or [""])[0] == "json":
            respond(json.dumps(dict(r, text=result_text(r))), "application/json")
        respond(result_text(r))
    if q.get("new"):
        if re.search(r"bot|crawl|spider|preview|slack|facebookexternalhit|embedly|discord|trendiction", ua, re.I) and not re.search(r"-User", ua):
            respond("Palimpsest, Letter edition: open https://itshenry.me/palimpsest/letter/ to get a letter.")
        if not rate_ok("letter-new", 40, 3600): respond("Too many letters from here this hour.", status="429 Too Many Requests")
        respond(make_letter())
    respond("Palimpsest, Letter edition. Get a letter: https://itshenry.me/palimpsest/letter/letter.cgi?new=1")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        respond(f"Something in the Scriptorium creaked (server error): {type(e).__name__}", status="500 Internal Server Error")
