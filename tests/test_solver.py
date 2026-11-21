"""SPOILERS. Self-test: sweeps seeds and volumes for puzzle invariants, then
auto-plays tides two ways (a perfect router, and an 'explorer' that visits every
room first) to check every world is winnable and the tide is fair."""
import os, sys, tempfile, io, contextlib, itertools
from collections import deque
os.environ["PALIMPSEST_HOME"] = tempfile.mkdtemp()
os.environ["PALIMPSEST_BOARD"] = ""
os.environ["PALIMPSEST_STATS"] = "off"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import palimpsest as P

def bfs(st, a, b):
    prev = {a: None}; q = deque([a])
    while q:
        c = q.popleft()
        if c == b: break
        for d, n in st["rooms"][c]["exits"].items():
            if n not in prev: prev[n] = (c, d); q.append(n)
    path, c = [], b
    while prev[c]: c, d = prev[c]; path.append(d)
    return path[::-1]

def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): P.main(cmd.split())
    return buf.getvalue()

def walk(to):
    st = P.load_state()
    for d in bfs(st, st["room"], to): run(d)

def solve(s):
    t = s["type"]
    run("examine " + {"cipher": "plaque", "liars": "busts", "lock": "lock", "shelf": "card", "register": "register"}[t])
    if t == "liars": return run("open " + s["answer"])
    if t == "shelf": return run("arrange " + " ".join(s["answer"]))
    return run("say " + s["answer"])

def check_world(st):
    vol = st["volume"]
    assert len(st["seals"]) == {1: 3, 2: 4, 3: 4, 4: 5, 5: 5}[vol]
    R = st["rooms"]
    # the finale: each slate's room counts pick out its chunk; chunks are an anagram-in-pieces of the word
    chunks = []
    for s in st["seals"].values():
        sl = s["slate"]
        got = "".join(sl["word"][R[r]["n"] - 1] for r in sl["rooms"])
        assert got == sl["chunk"], (st["seed"], sl, got)
        chunks.append(got)
    assert sorted("".join(chunks)) == sorted(st["word"])
    for s in st["seals"].values():
        t = s["type"]
        if t == "cipher":
            k = R[s["keyroom"]]
            dec = P.vigenere(s["text"], k["carved"], -1) if vol >= 3 else P.shift(s["text"], -k["n"])
            assert s["answer"] in dec.replace(" ", "")
        if t == "liars":
            assert (s["ext"] is not None) == (vol >= 2)
        if t == "register":
            g = P.Game(st); old = st["room"]; st["room"] = "seal_register"
            g.examine_seal(s, "register"); st["room"] = old
            shown = " ".join(" ".join(g.out).lower().split())
            for x in s["names"] + s["items"] + s["places"]:
                assert x.lower() in shown, ("register hides", x, st["seed"])
            assert s["answer"].lower() in shown
        if t == "lock":
            er = R[s["ext_room"]]
            assert s["answer"][s["ext_dial"]] == str(er["n"])
            assert any(er["name"] in c for c in s["clues"])
    return True

# 1. invariants across volumes
for wins in range(0, 11):
    P._save_json(P.LEDGER, [dict(reader=i + 1, outcome="won", seed=0) for i in range(wins)])
    for seed in range(1, 31):
        st = P.new_world(seed)
        check_world(st)
        if wins == 9: assert st["word"] == "PALIMPSEST", st["word"]
os.remove(P.LEDGER)
print("invariants ok")

# 2. play: perfect routing and full exploration, across volumes
stats = {}
for mode in ("perfect", "explorer"):
    for wins in (0, 2, 4, 9):
        for seed in range(200, 215):
            P._save_json(P.LEDGER, [dict(reader=i + 1, outcome="won", seed=0) for i in range(wins)])
            if os.path.exists(P.WALL): os.remove(P.WALL)
            run(f"new {seed}"); run("take lantern"); run("light lantern")
            st = P.load_state()
            if mode == "explorer":  # visit every room once (DFS order), like a cautious first-timer
                seen, order = set(), []
                def dfs(r):
                    seen.add(r); order.append(r)
                    for n in st["rooms"][r]["exits"].values():
                        if n not in seen and not st["rooms"][n]["locked"]: dfs(n)
                dfs("margin")
                for r in order[1:]: walk(r)
            if st["key_room"]:
                walk(st["key_room"]); run("open drawer"); run("take key")
            for rid, s in st["seals"].items():
                walk(rid)
                o = solve(s)
                assert "You take the slate" in o, (mode, wins, seed, s["type"], o)
            walk("lighthouse"); run("read lectern")
            o = run("say " + st["word"])
            fin = P.load_state()
            assert "lit the lamp" in o, (mode, wins, seed, fin["turn"], fin["limit"], o[-300:])
            stats.setdefault((mode, fin["volume"]), []).append(fin["turn"] / fin["limit"])
for k, v in sorted(stats.items()):
    print(f"{k[0]:9} vol {k[1]}: used {min(v):.0%}–{max(v):.0%} of the tide (avg {sum(v)/len(v):.0%})")

# 3. lose path + archivist copy/preserve
P._save_json(P.LEDGER, [])
run("new 31337"); st = P.load_state()
arch = st["arch"]; walk(arch); run("talk")
neigh = next(iter(st["rooms"][arch]["exits"].values()))
run("go " + P.DNAME[{v: k for k, v in st["rooms"][arch]["exits"].items()}[neigh]])
walk(arch)
print(run("preserve " + st["rooms"][neigh]["name"]).strip().splitlines()[0][:90])
for _ in range(st["limit"]): run("wait")
fin = P.load_state(); assert fin["over"] == "lost"; assert not fin["rooms"][neigh]["erased"]
print("lose path + preserve ok")
