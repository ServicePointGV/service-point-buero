"""
Automatisierte Tests fuer die Verbindung Buero-Programm <-> Website („Online vormerken“).

Braucht eine laufende Annahme-Schnittstelle (web_annahme/annahme.php), z. B. lokal mit
    php -S 127.0.0.1:8791 -t <ordner mit annahme.php>
Adresse und Schluessel kommen aus den Umgebungsvariablen ANNAHME_URL und ANNAHME_SCHLUESSEL.
Der Ordner daten/ der Test-Schnittstelle sollte vor dem Lauf leer sein.

Laeuft komplett gegen eine isolierte Test-Datenbank in einem temporaeren Ordner,
ruehrt also NIE an der echten Datenbank in %LOCALAPPDATA%\\ServicePointBuero.

Aufruf:
    py test_websync.py
"""
import sys, os, json, tempfile, urllib.request
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

_tmpdir = Path(tempfile.mkdtemp(prefix='sp_websync_'))
app.DATA = _tmpdir
app.DB = _tmpdir / 'test.db'

URL = os.environ.get('ANNAHME_URL', 'http://127.0.0.1:8791/annahme.php')
KEY = os.environ.get('ANNAHME_SCHLUESSEL', '')
failures = []

def check(name, condition, detail=''):
    print(f'  {"OK  " if condition else "FAIL"} {name}  {"" if condition else detail}')
    if not condition: failures.append(name)

def http(method, action, body=None):
    req = urllib.request.Request(f'{URL}?a={action}', method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'text/plain'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return json.loads(e.read().decode())

def free_on(day):
    return next((t['frei'] for t in http('GET', 'tage')['tage'] if t['d'] == day), None)

def booking(day, name, plate='Nein'):
    return {'stva_date': day, 'process': 'Umschreibung', 'plate_transfer': plate, 'vehicle_type': 'PKW', 'first_name': 'Test',
            'customer': name, 'mobile': '0171 1234567', 'missing': 'Testlauf', 'new_signs': 'Ja', 'lang': 'de', 'website': ''}

def fill(day, count, prefix):
    for i in range(count): app.save_job({'customer': f'{prefix}{i}', 'stva_date': day})

def jobs_named(name):
    c = app.db(); r = [dict(x) for x in c.execute('SELECT * FROM jobs WHERE customer=?', (name,))]; c.close(); return r

app.db().close()
app.save_app_settings({'web_url': URL, 'web_token': KEY})
d1 = app.next_workday(date.today().isoformat()); d2 = app.next_workday(d1); d3 = app.next_workday(d2); d4 = app.next_workday(d3)

print('=== Abgleich freie Plaetze ===')
fill(d1, 8, 'Voll'); fill(d2, 6, 'Halb')
app.web_sync_once()
check(f'{d1} voll -> 0 frei auf der Website', free_on(d1) == 0, free_on(d1))
check(f'{d2} 6 von 8 belegt -> 2 frei', free_on(d2) == 2, free_on(d2))
check(f'{d3} leer -> 8 frei', free_on(d3) == 8, free_on(d3))

print('=== Online-Vormerkung ===')
r = http('POST', 'vormerken', booking(d2, 'Online1', 'Ja'))
check('Vormerkung mit Kennzeichenuebernahme (2 Plaetze) angenommen', r.get('ok') is True, r)
check('Tag danach sofort voll', free_on(d2) == 0, free_on(d2))
r = http('POST', 'vormerken', booking(d2, 'Online2'))
check('weitere Vormerkung fuer vollen Tag abgelehnt', r.get('fehler') == 'voll', r)
r = http('POST', 'vormerken', booking(d1, 'Online3'))
check('Vormerkung fuer schon vollen Buero-Tag abgelehnt', r.get('fehler') == 'voll', r)

neu = app.web_sync_once()
check('Abgleich uebernimmt genau 1 neue Vormerkung', len(neu) == 1, neu)
j = jobs_named('Online1')
check('Auftrag angelegt, Status VORGEPLANT', len(j) == 1 and j[0]['status'] == 'VORGEPLANT', j)
check('auf dem Wunschtag eingeplant', j and j[0]['stva_date'] == d2, j and j[0]['stva_date'])
check('Kennzeichenuebernahme -> 2 Plaetze', j and j[0]['plate_transfer'] == 'Ja' and app.day_count(app.db(), d2) == 8)
check('Vorgang und Handynummer uebernommen', j and j[0]['process'] == 'Umschreibung' and j[0]['mobile'] == '0171 1234567')
check('Vormerkungsnummer in der Notiz', j and 'Online-Vormerkung W-' in (j[0]['missing'] or ''), j and j[0]['missing'])
check('nach Quittung keine offenen Vormerkungen mehr', app._web_post(URL, KEY, {'tage': app.web_capacity(app.db()), 'quittungen': []})['neu'] == [])
check('Website zeigt weiter 0 frei', free_on(d2) == 0, free_on(d2))

print('=== Tag wird im Buero voll, bevor die Vormerkung abgeholt ist ===')
r = http('POST', 'vormerken', booking(d3, 'Online4'))
check('Vormerkung fuer freien Tag angenommen', r.get('ok') is True, r)
fill(d3, 8, 'Buero')
app.web_sync_once()
j = jobs_named('Online4')
check('Auftrag auf naechsten freien Tag verschoben', j and j[0]['stva_date'] == d4, j and j[0]['stva_date'])
check('Status Rueckfrage', j and j[0]['status'] == 'Rückfrage', j and j[0]['status'])
check('Hinweis in der Notiz', j and 'war schon voll' in (j[0]['missing'] or ''), j and j[0]['missing'])

print('=== Laufkunde im Buero kurz nach einer Online-Vormerkung ===')
d5 = app.next_workday(d4); d6 = app.next_workday(d5)
fill(d5, 7, 'Fast'); app.web_sync_once()
check(f'{d5}: noch 1 Platz frei', free_on(d5) == 1, free_on(d5))
r = http('POST', 'vormerken', booking(d5, 'OnlineLetzter'))
check('Online-Kunde bekommt den letzten Platz', r.get('ok') is True, r)
# Laufkunde wird eingetragen, BEVOR der regulaere Abgleich gelaufen ist – wie im Handler /api/save
app.web_sync_before_booking()
jid, actual = app.save_job({'customer': 'Laufkunde', 'stva_date': d5})
j = jobs_named('OnlineLetzter')
check('Online-Kunde behaelt seinen Tag (keine Rueckfrage)', j and j[0]['stva_date'] == d5 and j[0]['status'] == 'VORGEPLANT', j and (j[0]['stva_date'], j[0]['status']))
check('Laufkunde landet automatisch auf dem naechsten freien Tag', actual == d6, actual)

print('=== WhatsApp-Bestaetigung ===')
offen = {x['name']: x for x in app.web_unbestaetigt()}
check('Online-Vormerkungen stehen in der Liste "Bestaetigung offen"', 'Test Online1' in offen and 'Test OnlineLetzter' in offen, list(offen))
nr = offen['Test Online1']['nr']
txt = app.web_confirm_text(nr)
check('Text enthaelt Name, Nummer und Zulassungstag', 'Test Online1' in txt['text'] and nr in txt['text'] and app._tag_lang(d2) in txt['text'], txt['text'])
bring = app._tag_lang(d1)
check('Text nennt die Abgabe-Frist am Werktag davor', f'bis spätestens {bring}' in txt['text'], txt['text'])
check('Text nennt den Abholtag (Werktag danach)', app._tag_lang(d3) in txt['text'])
check('Handynummer fuer WhatsApp dabei', txt['mobile'] == '0171 1234567')
moved = offen['Test Online4']
check('verschobene Vormerkung ist markiert', moved['verschoben'] is True)
check('Text fuer verschobene Vormerkung fragt nach', 'ausgebucht' in app.web_confirm_text(moved['nr'])['text'])
app.web_mark_confirmed(nr)
check('nach dem Senden nicht mehr offen', nr not in [x['nr'] for x in app.web_unbestaetigt()])
check('Vermerk im Auftrag', 'Bestätigung per WhatsApp' in (jobs_named('Online1')[0]['missing'] or ''))
app.web_mark_confirmed(moved['nr'], skip=True)
check('ueberspringen entfernt aus der Liste', moved['nr'] not in [x['nr'] for x in app.web_unbestaetigt()])

print('=== Keine doppelten Auftraege ===')
b = booking(d4, 'Doppelt'); b['nr'] = 'W-TEST1'; b['eingang'] = '2026-01-01T10:00:00'
first = app.web_import(b); second = app.web_import(b)
check('zweite Uebernahme derselben Nummer wird ignoriert', first and second is None and len(jobs_named('Doppelt')) == 1)

print()
print('ALLE TESTS OK' if not failures else f'{len(failures)} FEHLER: {failures}')
sys.exit(1 if failures else 0)
