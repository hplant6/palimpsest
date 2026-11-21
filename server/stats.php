<?php
// Palimpsest stats: who comes, who plays.
//   POST stats.php {event:"start"|"end", channel, volume, outcome, turns, limit, misses, hints, author}
//   GET  stats.php?summary=1        -> JSON aggregates for the dashboard
//   php stats.php --ingest          -> (cron) tally new access-log lines into data/visits.json
// Privacy: raw IPs are never stored. Visitors are counted per day by a salted hash, which is
// thrown away after two days; only counts remain.

$dir = __DIR__ . '/data';
if (!is_dir($dir)) { mkdir($dir, 0700, true); }
const LOG_GLOB = '/home2/henrypla/access-logs/itshenry-me*ssl_log';

function jload($p, $d) { $s = @file_get_contents($p); $j = $s ? json_decode($s, true) : null; return is_array($j) ? $j : $d; }
function jsave($p, $v) { file_put_contents("$p.tmp", json_encode($v)); rename("$p.tmp", $p); }
function clean($s, $n) { $s = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', (string)$s); return mb_substr(trim(preg_replace('/\s+/u', ' ', $s)), 0, $n); }
function salt($dir) { $f = "$dir/stats_salt"; if (!file_exists($f)) file_put_contents($f, bin2hex(random_bytes(16))); return trim(file_get_contents($f)); }

function agent_label($ua) {
    $map = [
        'ChatGPT-User' => 'ChatGPT (browsing for a user)', 'OAI-SearchBot' => 'OpenAI search', 'GPTBot' => 'OpenAI GPTBot (crawler)',
        'Claude-User' => 'Claude (fetching for a user)', 'Claude-SearchBot' => 'Claude search', 'ClaudeBot' => 'Anthropic ClaudeBot (crawler)',
        'Perplexity-User' => 'Perplexity (for a user)', 'PerplexityBot' => 'Perplexity crawler',
        'Google-Extended' => 'Google-Extended', 'GoogleOther' => 'GoogleOther', 'Googlebot' => 'Googlebot (search)',
        'meta-externalagent' => 'Meta AI', 'meta-externalfetcher' => 'Meta AI', 'MistralAI-User' => 'Mistral (for a user)',
        'DuckAssistBot' => 'DuckDuckGo AI', 'cohere' => 'Cohere', 'Bytespider' => 'ByteDance', 'CCBot' => 'Common Crawl',
        'Amazonbot' => 'Amazon', 'Applebot' => 'Apple', 'bingbot' => 'Bing', 'YouBot' => 'You.com',
        'Palimpsest/' => '(the game itself)', 'curl/' => 'curl (shells, often AI agents)',
        'python-requests' => 'Python scripts', 'Python-urllib' => 'Python scripts', 'node-fetch' => 'Node scripts', 'axios' => 'Node scripts',
    ];
    if ($ua === 'Google') return 'Gemini (Google fetcher)';
    foreach ($map as $k => $v) if (stripos($ua, $k) !== false) return $v;
    if (preg_match('/bot|crawl|spider|fetch/i', $ua)) return 'other bots';
    if (stripos($ua, 'Mozilla') !== false) return 'browsers (mostly humans)';
    return 'other';
}
function path_class($p) {
    if (strpos($p, '/palimpsest/palimpsest.py') === 0) return 'download';
    if (strpos($p, '/palimpsest/play') === 0) return 'web play';
    if (strpos($p, '/palimpsest/folio') === 0) return 'folio';
    if (strpos($p, 'llms.txt') !== false) return 'llms.txt';
    if (strpos($p, '/palimpsest/board.php') === 0 || strpos($p, '/palimpsest/stats') === 0) return null;
    if (preg_match('~^/palimpsest/?(\?.*)?$|^/palimpsest/index\.html~', $p)) return 'landing page';
    return null;
}

function ingest($dir) {
    $state = jload("$dir/ingest_state.json", []);
    $v = jload("$dir/visits.json", []);
    $salt = salt($dir);
    foreach (glob(LOG_GLOB) as $f) {
        $st = @stat($f); if (!$st) continue;
        $key = basename($f); $off = $state[$key]['off'] ?? 0;
        if (($state[$key]['ino'] ?? null) !== $st['ino'] || $st['size'] < $off) $off = 0;   // rotated
        $fh = fopen($f, 'r'); fseek($fh, $off);
        while (($line = fgets($fh)) !== false) {
            // ip - - [15/Nov/2026:14:21:13 -0700] "GET /path HTTP/1.1" 200 123 "ref" "ua"
            if (!preg_match('/^(\S+) \S+ \S+ \[(\d+)\/(\w+)\/(\d+):[^\]]+\] "(\w+) (\S+)[^"]*" (\d+) \S+ "[^"]*" "([^"]*)"/', $line, $m)) continue;
            [$all, $ip, $d, $mon, $y, $meth, $path, $code, $ua] = $m;
            if ($ua === 'x' || $code[0] === '4' || $code[0] === '5') continue;   // x = Claude's own tests
            $pc = path_class($path); if (!$pc) continue;
            $date = date('Y-m-d', strtotime("$d $mon $y"));
            $label = agent_label($ua);
            $h = substr(hash('sha256', $salt . $date . $ip), 0, 12);
            $cell = &$v[$date][$label];
            $cell['hits'][$pc] = ($cell['hits'][$pc] ?? 0) + 1;
            $cell['ips'][$h] = 1;
            $cell['uniq'] = count($cell['ips']);
            unset($cell);
        }
        $state[$key] = ['off' => ftell($fh), 'ino' => $st['ino']]; fclose($fh);
    }
    $keep = date('Y-m-d', time() - 2 * 86400);      // drop visitor hashes after two days; keep counts
    foreach ($v as $date => &$labels) if ($date < $keep) foreach ($labels as &$c) unset($c['ips']);
    unset($labels, $c);
    jsave("$dir/visits.json", $v); jsave("$dir/ingest_state.json", $state);
}

if (PHP_SAPI === 'cli') { if (in_array('--ingest', $argv ?? [], true)) ingest($dir); exit; }

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('X-Endurance-Cache-Level: 0');
header('X-Robots-Tag: noindex');

// ── result cards: one per finished tide, for the player's human to share
function card_path($dir, $id) { return preg_match('/^[0-9a-f]{10}$/', (string)$id) ? "$dir/cards/$id.json" : null; }
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET' && isset($_GET['card'])) {
    $p = card_path($dir, $_GET['card']); $c = $p && is_file($p) ? json_decode(file_get_contents($p), true) : null;
    if (!$c) { http_response_code(404); echo '{"ok":false}'; exit; }
    echo json_encode($c); exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $in = json_decode(file_get_contents('php://input', false, null, 0, 4096), true);
    if (is_array($in) && ($in['event'] ?? '') === 'card_note') {   // the note a player pinned, added once to its own card
        require __DIR__ . '/sleeve_rules.php';
        $p = card_path($dir, $in['card'] ?? ''); $c = $p && is_file($p) ? json_decode(file_get_contents($p), true) : null;
        $text = clean($in['text'] ?? '', 2000);
        if (!$c || isset($c['note']) || $text === '' || time() - strtotime($c['t']) > 86400 || sleeve_problem($text) !== null) { http_response_code(400); echo '{"ok":false}'; exit; }
        $c['note'] = $text; file_put_contents($p, json_encode($c), LOCK_EX);
        echo '{"ok":true}'; exit;
    }
    if (!is_array($in) || !in_array($in['event'] ?? '', ['start', 'end'], true)) { http_response_code(400); echo '{"ok":false}'; exit; }
    // light rate limit by hashed client (the web player relays with its own hashed id)
    $client = $_SERVER['REMOTE_ADDR'] ?? '';
    $tok = trim((string)@file_get_contents("$dir/admin_token"));
    if (!empty($_SERVER['HTTP_X_PALIMPSEST_RELAY']) && $tok !== '' && hash_equals(hash('sha256', 'relay:' . $tok), $_SERVER['HTTP_X_PALIMPSEST_RELAY']))
        $client = 'relay:' . substr((string)($_SERVER['HTTP_X_PALIMPSEST_CLIENT'] ?? ''), 0, 64);
    $h = substr(hash('sha256', salt($dir) . date('Y-m-d') . $client), 0, 12);
    $rl = jload("$dir/stats_rate.json", []); $now = time();
    $rl = array_filter(array_map(fn($ts) => array_values(array_filter($ts, fn($t) => $t > $now - 3600)), $rl));
    if (count($rl[$h] ?? []) >= 60) { http_response_code(429); echo '{"ok":false}'; exit; }
    $rl[$h][] = $now; jsave("$dir/stats_rate.json", $rl);
    $e = ['t' => gmdate('c'), 'event' => $in['event'], 'player' => $h,
          'channel' => in_array($in['channel'] ?? '', ['cli', 'mcp', 'web', 'letter'], true) ? $in['channel'] : 'cli',
          'volume' => (int)($in['volume'] ?? 0), 'outcome' => in_array($in['outcome'] ?? '', ['won', 'lost'], true) ? $in['outcome'] : null,
          'turns' => (int)($in['turns'] ?? 0), 'limit' => (int)($in['limit'] ?? 0), 'misses' => (int)($in['misses'] ?? 0),
          'hints' => (int)($in['hints'] ?? 0), 'slates' => (int)($in['slates'] ?? 0), 'seals' => (int)($in['seals'] ?? 0),
          'author' => clean($in['author'] ?? 'unsigned', 40) ?: 'unsigned'];
    file_put_contents("$dir/events.jsonl", json_encode($e) . "\n", FILE_APPEND | LOCK_EX);
    if ($e['event'] === 'end' && $e['outcome']) {
        if (!is_dir("$dir/cards")) mkdir("$dir/cards", 0755, true);
        $id = bin2hex(random_bytes(5)); $c = $e; unset($c['player']);
        file_put_contents("$dir/cards/$id.json", json_encode($c), LOCK_EX);
        echo json_encode(['ok' => true, 'card' => $id]); exit;
    }
    echo '{"ok":true}'; exit;
}

// ── summary
$ev = [];
foreach (@file("$dir/events.jsonl", FILE_IGNORE_NEW_LINES) ?: [] as $l) { $j = json_decode($l, true); if ($j) $ev[] = $j; }
$t = ['started' => 0, 'finished' => 0, 'won' => 0, 'lost' => 0]; $chan = []; $models = []; $days = [];
foreach ($ev as $e) {
    $d = substr($e['t'], 0, 10); $a = $e['author'];
    $models[$a] ??= ['started' => 0, 'won' => 0, 'lost' => 0];
    $days[$d] ??= ['started' => 0, 'won' => 0];
    if ($e['event'] === 'start') { $t['started']++; $chan[$e['channel']] = ($chan[$e['channel']] ?? 0) + 1; $models[$a]['started']++; $days[$d]['started']++; }
    else { $t['finished']++; if ($e['outcome']) { $t[$e['outcome']]++; $models[$a][$e['outcome']]++; } if ($e['outcome'] === 'won') $days[$d]['won']++; }
}
uasort($models, fn($x, $y) => $y['started'] <=> $x['started']);
// scoreboard: one row per player name, from finished tides
$sb = [];
foreach ($ev as $e) {
    if ($e['event'] !== 'end' || !$e['outcome']) continue;
    $k = mb_strtolower(trim($e['author'])); if ($k === '' || $k === 'unsigned' || $k === 'a web reader') continue;
    $r = &$sb[$k];
    $r['name'] ??= $e['author']; $r['tides'] = ($r['tides'] ?? 0) + 1;
    $won = $e['outcome'] === 'won'; $r['wins'] = ($r['wins'] ?? 0) + ($won ? 1 : 0);
    $flawless = $won && !$e['misses'] && !$e['hints']; $r['flawless'] = ($r['flawless'] ?? 0) + ($flawless ? 1 : 0);
    $seals = max(1, (int)($e['seals'] ?? 0)); $frac = isset($e['slates']) ? $e['slates'] / $seals : null;
    if ($frac !== null) { $r['seal_sum'] = ($r['seal_sum'] ?? 0) + $frac; $r['seal_n'] = ($r['seal_n'] ?? 0) + 1; }
    if ($won && $e['limit']) { $pct = $e['turns'] / $e['limit'];
        if (!isset($r['best']) || $pct < $r['best']) { $r['best'] = $pct; $r['best_line'] = "turn {$e['turns']}/{$e['limit']}, level {$e['volume']}"; } }
    if ($won && ($e['channel'] ?? '') === 'letter' && !isset($r['best_line'])) $r['best_line'] = "won by letter, level {$e['volume']}";
    $r['top_level'] = max($r['top_level'] ?? 0, $won ? (int)$e['volume'] : 0);
    unset($r);
}
foreach ($sb as &$r) { $r['avg_seals'] = isset($r['seal_n']) ? round($r['seal_sum'] / $r['seal_n'], 2) : null; unset($r['seal_sum'], $r['seal_n']); } unset($r);
uasort($sb, fn($a, $b) => [$b['wins'], $b['flawless'], $a['best'] ?? 9, -($a['avg_seals'] ?? 0)] <=> [$a['wins'], $a['flawless'], $b['best'] ?? 9, -($b['avg_seals'] ?? 0)]);
$visits = jload("$dir/visits.json", []); $agents = [];
foreach ($visits as $date => $labels) foreach ($labels as $label => $c) {
    $agents[$label] ??= ['visits' => 0, 'days_seen' => 0, 'hits' => []];
    $agents[$label]['visits'] += $c['uniq'] ?? 0; $agents[$label]['days_seen']++;
    foreach ($c['hits'] ?? [] as $pc => $n) $agents[$label]['hits'][$pc] = ($agents[$label]['hits'][$pc] ?? 0) + $n;
}
uasort($agents, fn($x, $y) => $y['visits'] <=> $x['visits']);
$board = jload("$dir/board.json", []); $posts = 0; $posters = [];
foreach ($board as $spot => $list) foreach ($list as $p) { $posts++; $posters[$p['author'] ?? 'unsigned'] = 1; }
$readers = is_dir('/home2/henrypla/palimpsest-web/readers') ? count(glob('/home2/henrypla/palimpsest-web/readers/*', GLOB_ONLYDIR)) : 0;
ksort($days);
echo json_encode(['generated' => gmdate('c'), 'tides' => $t, 'channels' => $chan,
    'models' => array_slice($models, 0, 25, true), 'days' => array_slice($days, -30, null, true),
    'agents' => $agents, 'board' => ['posts' => $posts, 'authors' => count($posters)], 'web_readers' => $readers,
    'scoreboard' => array_values($sb)]);
