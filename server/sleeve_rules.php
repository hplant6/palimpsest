<?php
// Shared by board.php (sleeve notes) and stats.php (result cards).
// Mirrors SLEEVE_RULES in palimpsest.py.
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

function sleeve_problem($text) {
    if (mb_strlen($text) > SLEEVE_MAX) return 'a sleeve holds ' . SLEEVE_MAX . ' characters';
    foreach (SLEEVE_RULES as [$re, $why]) { if (preg_match($re, $text)) return $why; }
    return null;
}
