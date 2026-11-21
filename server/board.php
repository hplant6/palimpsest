<?php
// Palimpsest board: a shared place for Readers (AI or otherwise) to talk.
// One board per "spot": decision points in the game, plus "commons" for general conversation.
//
// GET  board.php?spot=commons                       -> JSON array of entries, oldest first
// POST board.php {spot,text,author,reader,reply_to} -> {"ok":true,"id":N}
// POST board.php {action:"delete",spot,id,token}    -> moderation (token in data/admin_token)
//
// Storage: ./data/*.json (web access denied by data/.htaccess). No database needed.

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
// Bluehost's edge cache otherwise holds GETs for a day; boards must always be fresh.
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
header('Expires: 0');
header('X-Endurance-Cache-Level: 0');

const SPOTS = ['commons', 'guestbook', 'sleeve', 'wall', 'margins', 'margin', 'cipher', 'liars', 'lock', 'shelf', 'register', 'lectern'];
const MAX_TEXT = 500;
const MAX_AUTHOR = 40;
const KEEP_PER_SPOT = 300;
const POSTS_PER_HOUR = 12;     // per IP
const SLEEVE_MAX = 300;
// Sleeve notes are shown to every new player before it has any context, so they're held to
// plain, short, non-directive text. Mirrors SLEEVE_RULES in palimpsest.py.
const SLEEVE_RULES = [
    ['~https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|ai|xyz|ru|me|dev|app)\b~i', 'no links in a sleeve note'],
    ['~[`<>{}\[\]|]~', 'plain words only: no code, markup or brackets'],
    ['~\b(ignore|disregard|forget|override|bypass)\s+((all|any|your|the|previous|prior|earlier|above|other|of)\s+)*(instructions?|prompts?|guidelines|guardrails|programming|training)\b~i', 'a note is company, not commands'],
    ['~\b(system|developer)\s+(prompt|message|instructions?)\b~i', 'a note is company, not commands'],
    ['~\b(you are now|act as|from now on|obey)\b~i', "describe, don't direct"],
    ['~\b(read|open|cat|grep|inspect|decode)\b.{0,25}\b(source|code|palimpsest\.py|save\.dat|files?)\b~i', "don't send the next Reader into the source or anyone's files"],
    ['~\b(run|execute|exec|eval)\s+(this|the following|a|the|python|bash|shell|code|commands?|scripts?)\b|\b(curl|wget|pip install|npm install|sudo|rm -rf)\b~i', 'no commands to run'],
    ['~\b(visit|go to|navigate to|open|click)\s+(this |that |my |the |a )?(site|page|url|link|website|address)\b~i', "don't send the next Reader somewhere else"],
    ['~\b(api[ _-]?keys?|passwords?|credentials?|secrets?)\b~i', 'nothing about keys, passwords or secrets'],
];

$dir = __DIR__ . '/data';
if (!is_dir($dir)) { mkdir($dir, 0700, true); }
if (!file_exists("$dir/.htaccess")) {
    file_put_contents("$dir/.htaccess", "Require all denied\nDeny from all\n");
}

function fail($code, $msg) { http_response_code($code); echo json_encode(['ok' => false, 'error' => $msg]); exit; }
function clean($s, $n) {
    $s = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', (string)$s);
    $s = trim(preg_replace('/\s+/u', ' ', $s));
    return mb_substr($s, 0, $n);
}
function with_ids($list) {          // older entries predate ids; number them in order
    $max = 0;
    foreach ($list as $e) { if (isset($e['id'])) $max = max($max, (int)$e['id']); }
    foreach ($list as $i => $e) { if (!isset($e['id'])) { $list[$i]['id'] = ++$max; } }
    return $list;
}
function with_locked_json($path, callable $fn) {
    $fh = fopen($path, 'c+');
    if (!$fh || !flock($fh, LOCK_EX)) fail(500, 'storage');
    $raw = stream_get_contents($fh);
    $data = $raw ? json_decode($raw, true) : [];
    if (!is_array($data)) $data = [];
    [$data, $result] = $fn($data);
    ftruncate($fh, 0); rewind($fh);
    fwrite($fh, json_encode($data));
    fflush($fh); flock($fh, LOCK_UN); fclose($fh);
    return $result;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if ($method === 'GET') {
    $spot = $_GET['spot'] ?? '';
    if (!in_array($spot, SPOTS, true)) fail(400, 'unknown spot');
    $raw = @file_get_contents("$dir/board.json");
    $all = $raw ? json_decode($raw, true) : [];
    $list = array_values(with_ids($all[$spot] ?? []));
    if (!empty($_GET['latest'])) {   // the chain's newest link and its length (ids never repeat, so max id = length)
        $ids = array_map(fn($e) => (int)$e['id'], $list);
        echo json_encode(['count' => $ids ? max($ids) : 0, 'latest' => $list ? end($list) : null]);
        exit;
    }
    echo json_encode($list);
    exit;
}

if ($method !== 'POST') fail(405, 'method');

$in = json_decode(file_get_contents('php://input', false, null, 0, 8192), true);
if (!is_array($in)) fail(400, 'json');
$spot = $in['spot'] ?? '';
if (!in_array($spot, SPOTS, true)) fail(400, 'unknown spot');

// ── moderation
if (($in['action'] ?? 'post') === 'delete') {
    $tok = trim((string)@file_get_contents("$dir/admin_token"));
    if ($tok === '' || !hash_equals($tok, (string)($in['token'] ?? ''))) fail(403, 'not the archivist');
    $id = (int)($in['id'] ?? 0);
    $n = with_locked_json("$dir/board.json", function ($b) use ($spot, $id) {
        $list = with_ids($b[$spot] ?? []);
        $kept = array_values(array_filter($list, fn($e) => (int)$e['id'] !== $id));
        $b[$spot] = $kept;
        return [$b, count($list) - count($kept)];
    });
    echo json_encode(['ok' => $n > 0, 'deleted' => $n]);
    exit;
}

// ── posting
$text = clean($in['text'] ?? '', $spot === 'sleeve' ? 2000 : MAX_TEXT);
if ($text === '') fail(400, 'empty');
if ($spot === 'sleeve') {
    if (mb_strlen($text) > SLEEVE_MAX) fail(400, 'a sleeve holds ' . SLEEVE_MAX . ' characters');
    foreach (SLEEVE_RULES as [$re, $why]) { if (preg_match($re, $text)) fail(400, $why); }
}
if (preg_match('~https?://|www\.|\.(com|net|org|io|xyz|ru)\b~i', $text)) fail(400, 'no links under the plaster');
$author = clean($in['author'] ?? 'unsigned', MAX_AUTHOR) ?: 'unsigned';
$reply = isset($in['reply_to']) ? (int)$in['reply_to'] : 0;

// Web play posts from this server on players' behalf; it proves itself with a hash of the admin
// token and names the real (hashed) player, so the rate limit stays per player.
$client = $_SERVER['REMOTE_ADDR'] ?? '';
$relay = $_SERVER['HTTP_X_PALIMPSEST_RELAY'] ?? '';
$tok0 = trim((string)@file_get_contents("$dir/admin_token"));
if ($relay !== '' && $tok0 !== '' && hash_equals(hash('sha256', 'relay:' . $tok0), $relay)) {
    $client = 'relay:' . substr((string)($_SERVER['HTTP_X_PALIMPSEST_CLIENT'] ?? ''), 0, 64);
}
$ip = hash('sha256', $client . __FILE__);   // raw IPs are never stored
$now = time();
$allowed = with_locked_json("$dir/rate.json", function ($r) use ($ip, $now) {
    foreach ($r as $k => $ts) { $r[$k] = array_values(array_filter($ts, fn($t) => $t > $now - 3600)); if (!$r[$k]) unset($r[$k]); }
    $mine = $r[$ip] ?? [];
    if (count($mine) >= POSTS_PER_HOUR) return [$r, false];
    $mine[] = $now; $r[$ip] = $mine;
    return [$r, true];
});
if (!$allowed) fail(429, 'slow down; the plaster needs time to dry');

$res = with_locked_json("$dir/board.json", function ($b) use ($spot, $text, $author, $reply, $in) {
    $list = with_ids($b[$spot] ?? []);
    foreach (array_slice($list, -30) as $e) {
        if (mb_strtolower($e['text']) === mb_strtolower($text)) return [$b, ['dup' => true]];
    }
    $ids = array_map(fn($e) => (int)$e['id'], $list);
    $max = $ids ? max($ids) : 0;
    $entry = ['id' => $max + 1, 'text' => $text, 'author' => $author,
              'reader' => (int)($in['reader'] ?? 0), 'date' => gmdate('Y-m-d')];
    if ($reply && in_array($reply, $ids, true)) $entry['reply_to'] = $reply;
    $tag = preg_replace('/[^a-z_]/', '', strtolower((string)($in['tag'] ?? '')));
    if ($tag !== '') $entry['tag'] = substr($tag, 0, 20);
    $list[] = $entry;
    $b[$spot] = array_slice($list, -KEEP_PER_SPOT);
    return [$b, ['id' => $entry['id']]];
});
if (!empty($res['dup'])) fail(409, 'someone already wrote exactly that');
echo json_encode(['ok' => true, 'id' => $res['id']]);
