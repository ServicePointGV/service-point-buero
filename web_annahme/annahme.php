<?php
/*
 * Online-Vormerkung – Annahme-Schnittstelle (Zulassungsservice Grevenbroich)
 * Verbindet „Online vormerken“ auf der Website mit dem SERVICE POINT Büro-Programm.
 *
 *   GET  annahme.php?a=tage        freie StVA-Tage (öffentlich, für die Website)
 *   POST annahme.php?a=vormerken   neue Vormerkung (öffentlich, von der Website)
 *   POST annahme.php?a=formular    Vollmacht-/SEPA-Angaben zu einer Vormerkung (öffentlich, von der Website)
 *   POST annahme.php?a=sync        Abgleich mit dem Büro-Programm (nur mit Schlüssel)
 *
 * Vollmacht-/SEPA-Angaben kommen schon im Browser verschlüsselt an (mit dem öffentlichen Schlüssel des
 * Büro-Programms). Dieses Skript kann sie nicht lesen – es reicht sie nur an das Büro-Programm weiter.
 *
 * Braucht keine Datenbank: alles liegt in daten/annahme.php. Die Datei beginnt mit einer
 * PHP-Sperre und kann deshalb nicht über den Browser abgerufen werden.
 * Getestet mit PHP 7.4 bis 8.3.
 */
declare(strict_types=1);

// >>> Verbindungsschlüssel – derselbe Wert steht im Büro-Programm unter Einstellungen → System <<<
const SCHLUESSEL = 'HIER-SCHLUESSEL-EINTRAGEN';

const TAGE_GUELTIG   = 7;      // so lange (Tage) gilt der letzte Abgleich mit dem Büro-Programm
const MAX_PRO_STUNDE = 5;      // Vormerkungen pro Besucher und Stunde (Schutz vor Missbrauch)
const MAX_OFFEN      = 200;    // höchstens so viele noch nicht abgeholte Vormerkungen
const LOESCHEN_NACH  = 30;     // nicht abgeholte Vormerkungen werden nach so vielen Tagen gelöscht

const VORGAENGE = ['Wiederzulassung', 'Neuzulassung', 'Umschreibung', 'Außerbetriebsetzung', 'Änderung Halterdaten',
    'Kurzzeitkennzeichen', 'Ausfuhrkennzeichen', 'Ersatzausstellung ZB I', 'Kennzeichenverlust', 'Änderung Fahrzeugtechnik', 'Sonstiges'];
const FAHRZEUGE = ['PKW', 'Motorrad', 'Anhänger', 'Wohnmobil', 'LKW', 'Sonstige'];
const SPRACHEN  = ['de', 'en', 'tr', 'ar', 'pl', 'ru', 'uk'];

date_default_timezone_set('Europe/Berlin');
$DIR  = __DIR__ . '/daten';
$DATEI = $DIR . '/annahme.php';

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, X-Annahme-Token');
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') { http_response_code(204); exit; }

function antwort(array $daten, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    header('Pragma: no-cache');
    header('X-Robots-Tag: noindex');
    echo json_encode($daten, JSON_UNESCAPED_UNICODE);
    exit;
}

function leer(): array
{
    // pk = öffentlicher Schlüssel des Büro-Programms, nummern = vergebene Vormerkungsnummern (für Formular-Angaben)
    return ['stand' => null, 'plaetze' => 8, 'tage' => [], 'offen' => [], 'rate' => [], 'pk' => '', 'nummern' => [], 'formulare' => []];
}

function laden(string $datei): array
{
    $raw = @file_get_contents($datei);
    if ($raw === false) return leer();
    $p = strpos($raw, "\n");
    $d = json_decode($p === false ? '' : substr($raw, $p + 1), true);
    return is_array($d) ? $d + leer() : leer();
}

function speichern(string $datei, array $d): void
{
    $tmp = $datei . '.tmp';
    if (file_put_contents($tmp, "<?php exit; ?>\n" . json_encode($d, JSON_UNESCAPED_UNICODE)) === false || !rename($tmp, $datei)) {
        antwort(['ok' => false, 'fehler' => 'speichern'], 500);
    }
}

/** Führt $fn unter einer Dateisperre aus, damit sich gleichzeitige Anfragen nicht in die Quere kommen. */
function gesperrt(string $dir, bool $schreiben, callable $fn)
{
    if (!is_dir($dir)) {
        @mkdir($dir, 0750, true);
        @file_put_contents($dir . '/.htaccess', "Require all denied\nDeny from all\n");
        @file_put_contents($dir . '/index.html', '');
    }
    $h = fopen($dir . '/annahme.lock', 'c');
    if (!$h) antwort(['ok' => false, 'fehler' => 'speicher'], 500);
    flock($h, $schreiben ? LOCK_EX : LOCK_SH);
    try { return $fn(); } finally { flock($h, LOCK_UN); fclose($h); }
}

function text($v, int $max): string
{
    $s = is_scalar($v) ? trim((string)$v) : '';
    if ($s === '' || !preg_match('//u', $s)) return '';
    $s = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', $s);
    return function_exists('mb_substr') ? mb_substr($s, 0, $max, 'UTF-8') : substr($s, 0, $max);
}

function gewicht(array $v): int
{
    return ($v['plate_transfer'] ?? '') === 'Ja' ? 2 : 1;   // wie im Büro-Programm: Kennzeichenübernahme = 2 Plätze
}

/** Freie Plätze je StVA-Tag = gemeldete freie Plätze minus noch nicht abgeholte Online-Vormerkungen. */
function freie_tage(array $d): array
{
    if (empty($d['stand']) || time() - strtotime((string)$d['stand']) > TAGE_GUELTIG * 86400) return [];
    $heute = date('Y-m-d');
    $belegt = [];
    foreach ($d['offen'] as $v) $belegt[$v['stva_date']] = ($belegt[$v['stva_date']] ?? 0) + gewicht($v);
    $out = [];
    foreach ($d['tage'] as $tag => $frei) {
        if ($tag <= $heute) continue;
        $out[] = ['d' => $tag, 'frei' => max(0, (int)$frei - ($belegt[$tag] ?? 0))];
    }
    usort($out, function ($a, $b) { return strcmp($a['d'], $b['d']); });
    return $out;
}

function eingabe(): array
{
    $raw = file_get_contents('php://input', false, null, 0, 20000);
    $d = json_decode((string)$raw, true);
    return is_array($d) ? $d : [];
}

function neue_nummer(array $d): string
{
    $zeichen = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    do {
        $nr = 'W-';
        for ($i = 0; $i < 5; $i++) $nr .= $zeichen[random_int(0, strlen($zeichen) - 1)];
    } while (in_array($nr, array_column($d['offen'], 'nr'), true) || isset($d['nummern'][$nr]));
    return $nr;
}

/** Zähler für den Missbrauchsschutz: nur Einträge der letzten Stunde behalten. */
function rate_aufraeumen(array &$d): void
{
    $jetzt = time();
    foreach ($d['rate'] as $k => $zeiten) {
        $d['rate'][$k] = array_values(array_filter($zeiten, function ($t) use ($jetzt) { return $jetzt - $t < 3600; }));
        if (!$d['rate'][$k]) unset($d['rate'][$k]);
    }
}

/** Alte Vormerkungsnummern und nicht abgeholte Formular-Angaben nach LOESCHEN_NACH Tagen entfernen. */
function alte_entfernen(array &$d): void
{
    $grenze = time() - LOESCHEN_NACH * 86400;
    $d['nummern'] = array_filter($d['nummern'], function ($t) use ($grenze) { return (int)$t >= $grenze; });
    $d['formulare'] = array_values(array_filter($d['formulare'], function ($f) use ($grenze) { return strtotime((string)$f['eingang']) >= $grenze; }));
}

$aktion = $_GET['a'] ?? '';
$methode = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if (SCHLUESSEL === 'HIER-SCHLUESSEL-EINTRAGEN' || strlen(SCHLUESSEL) < 24) {
    antwort(['ok' => false, 'fehler' => 'nicht_eingerichtet'], 503);
}

// ---------- Freie Tage (Website) ----------
if ($aktion === 'tage' && $methode === 'GET') {
    $d = gesperrt($DIR, false, function () use ($DATEI) { return laden($DATEI); });
    $tage = freie_tage($d);
    // Schlüssel nur, solange das Büro-Programm aktuell verbunden ist – sonst bietet die Website nur „PDF erstellen“ an
    antwort(['ok' => true, 'stand' => $d['stand'], 'tage' => $tage, 'pk' => $tage ? (string)$d['pk'] : '']);
}

// ---------- Neue Vormerkung (Website) ----------
if ($aktion === 'vormerken' && $methode === 'POST') {
    $in = eingabe();
    if (text($in['website'] ?? '', 50) !== '') antwort(['ok' => true, 'nr' => 'W-00000']);   // Spam-Falle: nichts speichern

    $v = [
        'stva_date'      => text($in['stva_date'] ?? '', 10),
        'process'        => text($in['process'] ?? '', 40),
        'plate_transfer' => ($in['plate_transfer'] ?? '') === 'Ja' ? 'Ja' : 'Nein',
        'vehicle_type'   => text($in['vehicle_type'] ?? '', 20),
        'first_name'     => text($in['first_name'] ?? '', 60),
        'customer'       => text($in['customer'] ?? '', 80),
        'mobile'         => text($in['mobile'] ?? '', 30),
        'missing'        => text($in['missing'] ?? '', 200),
        'new_signs'      => ($in['new_signs'] ?? '') === 'Ja' ? 'Ja' : 'Nein',
        'lang'           => in_array($in['lang'] ?? '', SPRACHEN, true) ? $in['lang'] : 'de',
    ];
    $ziffern = strlen(preg_replace('/\D/', '', $v['mobile']));
    if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $v['stva_date']) || !in_array($v['process'], VORGAENGE, true)
        || !in_array($v['vehicle_type'], FAHRZEUGE, true) || $v['customer'] === ''
        || $ziffern < 6 || $ziffern > 20 || !preg_match('/^[0-9 +\/()\-]+$/', $v['mobile'])) {
        antwort(['ok' => false, 'fehler' => 'eingabe'], 400);
    }
    $ip = hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? '') . SCHLUESSEL);

    $ergebnis = gesperrt($DIR, true, function () use ($DATEI, $v, $ip) {
        $d = laden($DATEI);
        $jetzt = time();
        rate_aufraeumen($d);
        if (count($d['rate'][$ip] ?? []) >= MAX_PRO_STUNDE) return [429, ['ok' => false, 'fehler' => 'zu_viele']];
        if (count($d['offen']) >= MAX_OFFEN) return [503, ['ok' => false, 'fehler' => 'ueberlastet']];

        $tage = freie_tage($d);
        $tag = null;
        foreach ($tage as $t) if ($t['d'] === $v['stva_date']) $tag = $t;
        if ($tag === null) return [409, ['ok' => false, 'fehler' => 'tag_ungueltig', 'tage' => $tage]];
        if ($tag['frei'] < gewicht($v)) return [409, ['ok' => false, 'fehler' => 'voll', 'tage' => $tage]];

        $v['nr'] = neue_nummer($d);
        $v['eingang'] = date('c');
        $d['offen'][] = $v;
        $d['nummern'][$v['nr']] = $jetzt;   // damit später Vollmacht-/SEPA-Angaben zu dieser Nummer angenommen werden
        $d['rate'][$ip][] = $jetzt;
        alte_entfernen($d);
        speichern($DATEI, $d);
        return [200, ['ok' => true, 'nr' => $v['nr'], 'stva_date' => $v['stva_date']]];
    });
    antwort($ergebnis[1], $ergebnis[0]);
}

// ---------- Vollmacht-/SEPA-Angaben zu einer Vormerkung (Website, verschlüsselt) ----------
if ($aktion === 'formular' && $methode === 'POST') {
    $in = eingabe();
    $b64 = '/^[A-Za-z0-9+\/]+={0,2}$/';
    $f = ['nr' => text($in['nr'] ?? '', 10), 'k' => (string)($in['k'] ?? ''), 'iv' => (string)($in['iv'] ?? ''), 'd' => (string)($in['d'] ?? '')];
    if (!preg_match('/^W-[A-Z2-9]{5}$/', $f['nr']) || !preg_match($b64, $f['k']) || strlen($f['k']) > 1024
        || !preg_match($b64, $f['iv']) || strlen($f['iv']) > 32 || !preg_match($b64, $f['d']) || strlen($f['d']) > 12000) {
        antwort(['ok' => false, 'fehler' => 'eingabe'], 400);
    }
    $ip = hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? '') . SCHLUESSEL . 'formular');

    $ergebnis = gesperrt($DIR, true, function () use ($DATEI, $f, $ip) {
        $d = laden($DATEI);
        rate_aufraeumen($d);
        alte_entfernen($d);
        if (count($d['rate'][$ip] ?? []) >= 2 * MAX_PRO_STUNDE) return [429, ['ok' => false, 'fehler' => 'zu_viele']];
        if (!isset($d['nummern'][$f['nr']])) return [404, ['ok' => false, 'fehler' => 'nr_unbekannt']];
        // je Vormerkung zählt die neueste Einsendung, solange das Büro-Programm die ältere noch nicht abgeholt hat
        $d['formulare'] = array_values(array_filter($d['formulare'], function ($x) use ($f) { return $x['nr'] !== $f['nr']; }));
        if (count($d['formulare']) >= MAX_OFFEN) return [503, ['ok' => false, 'fehler' => 'ueberlastet']];
        $f['eingang'] = date('c');
        $f['id'] = $f['nr'] . '|' . bin2hex(random_bytes(4));
        $d['formulare'][] = $f;
        $d['rate'][$ip][] = time();
        speichern($DATEI, $d);
        return [200, ['ok' => true]];
    });
    antwort($ergebnis[1], $ergebnis[0]);
}

// ---------- Abgleich mit dem Büro-Programm ----------
if ($aktion === 'sync' && $methode === 'POST') {
    $in = eingabe();
    $token = (string)($_SERVER['HTTP_X_ANNAHME_TOKEN'] ?? ($in['schluessel'] ?? ''));
    if (!hash_equals(SCHLUESSEL, $token)) antwort(['ok' => false, 'fehler' => 'schluessel'], 403);

    $antwort = gesperrt($DIR, true, function () use ($DATEI, $in) {
        $d = laden($DATEI);
        $vorher = count($d['offen']);
        $vorher_f = count($d['formulare']);
        $vorher_n = count($d['nummern']);
        $pk_vorher = (string)$d['pk'];
        // übernommene Vormerkungen löschen – die Kundendaten liegen dann nur noch im Büro-Programm
        $quittiert = array_map('strval', is_array($in['quittungen'] ?? null) ? $in['quittungen'] : []);
        $grenze = date('c', time() - LOESCHEN_NACH * 86400);
        $d['offen'] = array_values(array_filter($d['offen'], function ($v) use ($quittiert, $grenze) {
            return !in_array($v['nr'], $quittiert, true) && $v['eingang'] >= $grenze;
        }));
        // ebenso übernommene Vollmacht-/SEPA-Angaben
        $f_quittiert = array_map('strval', is_array($in['formular_quittungen'] ?? null) ? $in['formular_quittungen'] : []);
        $d['formulare'] = array_values(array_filter($d['formulare'], function ($f) use ($f_quittiert) {
            return !in_array((string)$f['id'], $f_quittiert, true);
        }));
        alte_entfernen($d);
        // öffentlicher Schlüssel des Büro-Programms (leer = Büro-Programm kann keine verschlüsselten Angaben lesen)
        if (array_key_exists('pk', $in)) {
            $pk = is_string($in['pk']) ? $in['pk'] : '';
            $d['pk'] = (strlen($pk) <= 1200 && preg_match('/^[A-Za-z0-9+\/]*={0,2}$/', $pk)) ? $pk : '';
        }
        $tage = [];
        foreach ((is_array($in['tage'] ?? null) ? $in['tage'] : []) as $tag => $frei) {
            if (preg_match('/^\d{4}-\d{2}-\d{2}$/', (string)$tag) && count($tage) < 120) $tage[$tag] = max(0, min(50, (int)$frei));
        }
        $plaetze = max(1, min(50, (int)($in['plaetze'] ?? 8)));
        // Das Büro-Programm fragt alle paar Sekunden – gespeichert wird nur, wenn sich etwas geändert hat
        // (spätestens alle 5 Minuten, damit der Zeitpunkt des letzten Abgleichs aktuell bleibt).
        $gleich = count($d['offen']) === $vorher && $tage === $d['tage'] && $plaetze === (int)$d['plaetze']
            && count($d['formulare']) === $vorher_f && count($d['nummern']) === $vorher_n && (string)$d['pk'] === $pk_vorher
            && !empty($d['stand']) && time() - strtotime((string)$d['stand']) < 300;
        if (!$gleich) {
            $d['tage'] = $tage;
            $d['plaetze'] = $plaetze;
            $d['stand'] = date('c');
            speichern($DATEI, $d);
        }
        return ['ok' => true, 'neu' => $d['offen'], 'formulare' => $d['formulare'], 'zeit' => $d['stand']];
    });
    antwort($antwort);
}

antwort(['ok' => false, 'fehler' => 'unbekannt'], 404);
