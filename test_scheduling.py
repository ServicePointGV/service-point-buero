"""
Automatisierte Tests fuer die Terminvergabe-Logik (Tagesplaetze, Puffer, Feiertage,
Schliesstage, Kennzeichenuebernahme) sowie den Papierkorb.

Laeuft komplett gegen eine isolierte Test-Datenbank in einem temporaeren Ordner,
ruehrt also NIE an der echten Datenbank in %LOCALAPPDATA%\\ServicePointBuero.

Aufruf:
    py test_scheduling.py
"""
import sys, tempfile, shutil
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

# --- Test-Datenbank isolieren, bevor irgendetwas anderes passiert ---
_tmpdir = Path(tempfile.mkdtemp(prefix='sp_test_'))
app.DATA = _tmpdir
app.DB = _tmpdir / 'test.db'

failures = []

def check(name, condition, detail=''):
    if condition:
        print(f'  OK   {name}')
    else:
        print(f'  FAIL {name}  {detail}')
        failures.append(name)

def reset_db():
    if app.DB.exists(): app.DB.unlink()
    c = app.db(); c.close()

def reset_settings():
    f = app._app_settings_file()
    if f.exists(): f.unlink()

def next_monday(from_date):
    d = from_date
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

print('=== Terminvergabe-Logik ===')
reset_db(); reset_settings()

base_monday = next_monday(date(2027, 3, 1))  # ein normaler Werktag ohne Feiertag in der Naehe
base = base_monday.isoformat()

print(f'-- Regulaere Kapazitaet (Standard 8) auffuellen --')
ids = []
for i in range(8):
    jid, actual = app.save_job({'customer': f'Kap{i}', 'stva_date': base})
    ids.append(jid)
    check(f'Auftrag {i+1}/8 landet auf {base}', actual == base, f'bekam {actual}')

jid9, actual9 = app.save_job({'customer': 'Ueberlauf', 'stva_date': base})
next_day = app.next_workday(base)
check('9. Auftrag rutscht auf naechsten Werktag', actual9 == next_day, f'bekam {actual9}, erwartet {next_day}')

print('-- Kennzeichenuebernahme belegt 2 reguläre Plaetze --')
reset_db(); reset_settings()
for i in range(7):
    app.save_job({'customer': f'Fill{i}', 'stva_date': base})
jid_kz, actual_kz = app.save_job({'customer': 'KZuebernahme', 'process': 'Wiederzulassung', 'plate_transfer': 'Ja', 'stva_date': base})
check('Kennzeichenuebernahme passt nicht mehr rein (nur 1 frei, braucht 2) -> naechster Tag',
      actual_kz == app.next_workday(base), f'bekam {actual_kz}')

print('-- Online-Abmeldung braucht keinen Platz --')
reset_db(); reset_settings()
jid_ab, actual_ab = app.save_job({'customer': 'Abmelder', 'process': 'Online-Abmeldung', 'stva_date': base})
check('Online-Abmeldung bekommt kein StVA-Datum', actual_ab == '', f'bekam {actual_ab!r}')

print('-- Wochenende wird uebersprungen --')
reset_db(); reset_settings()
saturday = base_monday - timedelta(days=(base_monday.weekday() - 5) % 7 or 2)
while saturday.weekday() != 5:
    saturday += timedelta(days=1)
jid_we, actual_we = app.save_job({'customer': 'WETest', 'stva_date': saturday.isoformat()})
check('Auftrag am Samstag landet auf einem Werktag', app.is_workday(date.fromisoformat(actual_we)), f'bekam {actual_we}')

print('-- Gesetzlicher Feiertag (Neujahr) wird uebersprungen --')
check('1. Januar gilt nicht als Werktag', not app.is_workday(date(2027, 1, 1)))

print('-- Eigene Schliesstage (Betriebsurlaub) werden respektiert --')
reset_db(); reset_settings()
app.save_app_settings({'closed_dates': {base: 'Testurlaub'}})
jid_cd, actual_cd = app.save_job({'customer': 'SchliesstagTest', 'stva_date': base})
check('Auftrag am eigenen Schliesstag rutscht auf den naechsten Werktag',
      actual_cd == app.next_workday(base), f'bekam {actual_cd}')
reset_settings()

print('-- Konfigurierbare Kapazitaet wird beachtet --')
reset_db(); reset_settings()
app.save_app_settings({'regular_slots': 2, 'buffer_slots': 1})
app.save_job({'customer': 'C1', 'stva_date': base})
app.save_job({'customer': 'C2', 'stva_date': base})
jid_c3, actual_c3 = app.save_job({'customer': 'C3', 'stva_date': base})
check('Bei regular_slots=2 rutscht der 3. Auftrag auf den naechsten Tag',
      actual_c3 == app.next_workday(base), f'bekam {actual_c3}')
reset_settings()

print('-- Pufferplaetze auffuellen --')
reset_db(); reset_settings()
app.save_app_settings({'regular_slots': 2, 'buffer_slots': 1})
day1 = base
day2 = app.next_workday(day1)
app.save_job({'customer': 'D1', 'stva_date': day1})
app.save_job({'customer': 'D2', 'stva_date': day1})
app.save_job({'customer': 'D3', 'stva_date': day2})
result = app.fill_buffers(day1)
check('Ein Auftrag wird in den Puffer von Tag 1 vorgezogen', result['moved'] == 1, f'moved={result["moved"]}')
reset_settings()

print()
print('=== Papierkorb ===')
reset_db(); reset_settings()
jid, _ = app.save_job({'customer': 'PapierkorbTest', 'mobile': '0176 1234567', 'stva_date': base})
app.delete_job(jid)
jobs_after_delete = app.rows()
check('Auftrag ist nach dem Loeschen nicht mehr in der aktiven Liste', all(j['id'] != jid for j in jobs_after_delete))
trash = app.list_deleted_jobs()
check('Auftrag erscheint im Papierkorb', any(t['id'] == jid for t in trash))
app.restore_deleted_job(jid)
jobs_after_restore = app.rows()
restored = next((j for j in jobs_after_restore if j['id'] == jid), None)
check('Auftrag ist nach Wiederherstellung wieder da', restored is not None)
check('Wiederhergestellte Daten stimmen (Kunde)', restored and restored['customer'] == 'PapierkorbTest')
check('Wiederhergestellte Daten stimmen (Mobil)', restored and restored['mobile'] == '0176 1234567')
trash_after = app.list_deleted_jobs()
check('Auftrag ist nach Wiederherstellung nicht mehr im Papierkorb', all(t['id'] != jid for t in trash_after))

cid = app.save_customer({'customer': 'KundenPapierkorbTest', 'first_name': 'Karl'})
app.delete_customer(cid)
check('Kunde ist nach dem Loeschen nicht mehr aktiv', not any(c['id'] == cid for c in app.all_customers() if c['id']))
ctrash = app.list_deleted_customers()
check('Kunde erscheint im Papierkorb', any(t['id'] == cid for t in ctrash))
app.restore_deleted_customer(cid)
restored_c = next((c for c in app.all_customers() if c['id'] == cid), None)
check('Kunde ist nach Wiederherstellung wieder da', restored_c is not None)

# --- Aufraeumen ---
try:
    shutil.rmtree(_tmpdir, ignore_errors=True)
except Exception:
    pass

print()
if failures:
    print(f'{len(failures)} Test(s) fehlgeschlagen: {", ".join(failures)}')
    sys.exit(1)
else:
    print('Alle Tests erfolgreich.')
    sys.exit(0)
