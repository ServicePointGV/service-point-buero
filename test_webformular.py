"""
Automatisierte Tests fuer „Vollmacht + SEPA-Mandat online ausfuellen“ (Weg B: verschluesselt ins Buero).

Braucht – wie test_websync.py – eine laufende Annahme-Schnittstelle (web_annahme/annahme.php), z. B.
    php -S 127.0.0.1:8791 -t <ordner mit annahme.php>
Adresse und Schluessel kommen aus den Umgebungsvariablen ANNAHME_URL und ANNAHME_SCHLUESSEL.

Die Verschluesselung im Browser (RSA-OAEP/SHA-256 + AES-GCM, WebCrypto) wird hier mit 'cryptography' nachgebildet.
Laeuft gegen eine isolierte Test-Datenbank in einem temporaeren Ordner – NIE gegen die echten Daten.

Aufruf:
    py test_webformular.py
"""
import sys, os, re, json, base64, tempfile, urllib.request
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_tmpdir = Path(tempfile.mkdtemp(prefix='sp_webformular_'))
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

def encrypt_like_browser(obj, pk_b64):
    """Wie vfEncrypt() auf der Website: AES-GCM-Schluessel mit RSA-OAEP (SHA-256) verpackt."""
    pub = serialization.load_der_public_key(base64.b64decode(pk_b64))
    aes = AESGCM.generate_key(bit_length=256); iv = os.urandom(12)
    data = AESGCM(aes).encrypt(iv, json.dumps(obj).encode(), None)
    wrapped = pub.encrypt(aes, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b = lambda x: base64.b64encode(x).decode()
    return {'k': b(wrapped), 'iv': b(iv), 'd': b(data)}

def formular(nr, **over):
    d = {'v': 1, 'nr': nr, 'lang': 'de',
         'halter': {'first': 'Erika', 'last': 'Formtest', 'birth': '05.08.1985', 'tel': '02181 12345', 'street': 'Lindenstraße 12', 'zip': '41515', 'city': 'Grevenbroich'},
         'fzg': {'make': 'VW Golf', 'fin': 'WVWZZZ1KZAW000001', 'evb': 'A1B2C3D'},
         'zusatz': {'fein': True, 'art': 'SE', 'von': '04', 'bis': '10'},
         'kz': {'mode': 'wunsch', 'ne': 'AB 123', 'gv': 'EM 85', 'sonst': 'ermessen', 'alt': ''},
         'sepa': {'same': True, 'name': 'Erika Formtest', 'street': 'Lindenstraße 12', 'zip': '41515', 'city': 'Grevenbroich',
                  'iban': 'DE02120300000000202051', 'bic': 'BYLADEM1001', 'bank': 'DKB'}}
    for k, v in over.items(): d[k] = {**d[k], **v} if isinstance(v, dict) else v
    return d

def booking(day, name):
    return {'stva_date': day, 'process': 'Umschreibung', 'plate_transfer': 'Nein', 'vehicle_type': 'PKW', 'first_name': 'Erika',
            'customer': name, 'mobile': '0171 1234567', 'missing': '', 'new_signs': 'Ja', 'lang': 'de', 'website': ''}

def job(name):
    c = app.db(); r = c.execute('SELECT * FROM jobs WHERE customer=?', (name,)).fetchone(); c.close(); return dict(r) if r else {}

def offene_formulare():
    return app._web_post(URL, KEY, {'tage': app.web_capacity(app.db()), 'quittungen': [], 'formular_quittungen': []})['formulare']

app.db().close()
app.save_app_settings({'web_url': URL, 'web_token': KEY})
d1 = app.next_workday(date.today().isoformat()); d2 = app.next_workday(d1)

print('=== Schluessel ===')
check('Schluessel wird beim ersten Abgleich erzeugt', app.web_public_key() != '' and (_tmpdir / 'web_formular_key.pem').exists())
app.web_sync_once()
pk = http('GET', 'tage').get('pk', '')
check('Website bekommt den oeffentlichen Schluessel', pk == app.web_public_key(), pk[:30])
check('privater Schluessel steht NICHT in der Antwort', 'PRIVATE' not in json.dumps(http('GET', 'tage')))

print('=== Einsendung zu einer Vormerkung ===')
r = http('POST', 'vormerken', booking(d2, 'Formtest')); nr = r.get('nr', '')
check('Vormerkung angenommen', r.get('ok') is True, r)
r = http('POST', 'formular', {'nr': 'W-ZZZZZ', **encrypt_like_browser(formular('W-ZZZZZ'), pk)})
check('unbekannte Vormerkungsnummer abgelehnt', r.get('fehler') == 'nr_unbekannt', r)
r = http('POST', 'formular', {'nr': nr, 'k': 'kaputt!', 'iv': 'x', 'd': 'y'})
check('kaputte Einsendung abgelehnt', r.get('fehler') == 'eingabe', r)
r = http('POST', 'formular', {'nr': nr, **encrypt_like_browser(formular(nr), pk)})
check('verschluesselte Angaben angenommen', r.get('ok') is True, r)
roh = json.dumps(offene_formulare())
check('Webserver speichert keine lesbaren Angaben', 'Formtest' not in roh and 'DE0212' not in roh and 'Lindenstra' not in roh)

app.web_sync_once()
j = job('Formtest')
check('Auftrag zur Vormerkung angelegt', bool(j))
check('Geburtsdatum uebernommen', j.get('birthdate') == '05.08.1985', j.get('birthdate'))
check('Anschrift uebernommen', (j.get('address'), j.get('postal'), j.get('city')) == ('Lindenstraße 12', '41515', 'Grevenbroich'))
check('Fahrzeug uebernommen', (j.get('manufacturer'), j.get('fin')) == ('VW Golf', 'WVWZZZ1KZAW000001'))
check('IBAN und BIC/Bank uebernommen', j.get('iban') == 'DE02120300000000202051' and j.get('bic_bank') == 'BYLADEM1001 / DKB', (j.get('iban'), j.get('bic_bank')))
check('Wunschkennzeichen uebernommen', j.get('desired_plate') == 'NE-AB 123 oder GV-EM 85', j.get('desired_plate'))
check('Handynummer der Vormerkung bleibt, Telefon als Abweichung notiert', j.get('mobile') == '0171 1234567' and 'Telefon: 02181 12345' in (j.get('missing') or ''))
check('eVB-Nummer uebernommen', j.get('evb') == 'A1B2C3D', j.get('evb'))
check('Kennzeichen-Art und Feinstaubplakette in der Notiz', 'Kennzeichen: Saison- und E-Kennzeichen 04–10.' in (j.get('missing') or '') and 'Feinstaubplakette gewünscht.' in (j.get('missing') or ''), j.get('missing'))
o = app.get_lauf_options(j['id'])
check('Laufzettel vorbelegt: Feinstaubplakette, Saison, Zeitraum', o.get('feinstaub') is True and o.get('saison') is True and o.get('season') == '04–10', (o.get('feinstaub'), o.get('saison'), o.get('season')))
check('Hinweis in der Notiz', 'Vollmacht/SEPA online ausgefüllt' in (j.get('missing') or '') and 'nach unserem Ermessen' in (j.get('missing') or ''), j.get('missing'))
app.web_sync_once()
check('nach der Quittung liegt nichts mehr auf dem Webserver', offene_formulare() == [])
check('Hinweisfenster zeigt 📄', any(x['formular'] for x in app.web_unbestaetigt() if x['nr'] == nr))

print('=== Zweite Einsendung mit anderem Kontoinhaber ===')
r = http('POST', 'formular', {'nr': nr, **encrypt_like_browser(formular(nr, halter={'street': 'Neue Straße 1'},
        sepa={'same': False, 'name': 'Hans Zahler', 'street': 'Bahnstraße 3', 'zip': '41516', 'city': 'Grevenbroich', 'iban': 'DE89370400440532013000'}), pk)})
check('zweite Einsendung angenommen', r.get('ok') is True, r)
app.web_sync_once()
j = job('Formtest')
check('schon ausgefuellte Anschrift bleibt', j.get('address') == 'Lindenstraße 12')
check('abweichende Werte stehen in der Notiz', 'Straße: Neue Straße 1' in j['missing'] and 'IBAN: DE89370400440532013000' in j['missing'], j['missing'])
check('Kontoinhaber mit Anschrift uebernommen (SEPA)', (j.get('taxpayer_same_holder'), j.get('account_holder'), j.get('taxpayer_address'), j.get('taxpayer_postal'))
      == ('Nein', 'Hans Zahler', 'Bahnstraße 3', '41516'), (j.get('taxpayer_same_holder'), j.get('account_holder'), j.get('taxpayer_address')))

print('=== Druck auf dem Formular des Rhein-Kreises Neuss ===')
import pypdf
folder, files = app.fill_pdfs(j['id'])
vp = pypdf.PdfReader(Path(folder) / files[0]).pages[0]; sp = pypdf.PdfReader(Path(folder) / files[1]).pages[0]
vt = vp.extract_text(); st = re.sub(r'\s', '', sp.extract_text())   # Kammfelder: jedes Zeichen einzeln gesetzt
check('Vollmacht ist Seite 1 des Kreis-Formulars', 'Vollmacht zur Vorlage bei der Zulassungsbehörde' in vt, vt[:120])
check('Vollmacht: Halter, Geburtsdatum, Anschrift, Fahrzeug', all(x in vt for x in ['Formtest, Erika', '05.08.1985', 'Lindenstraße 12, 41515 Grevenbroich', 'VW Golf, FIN WVWZZZ1KZAW000001']), vt[:400])
check('Vollmacht: Wunschkennzeichen NE/GV eingetragen', 'AB 123' in vt and 'EM 85' in vt)
check('Vollmacht: ergaenzte Felder (eVB, Saison-Monate) auf dem Formular', all(x in vt for x in ['eVB-Nummer (elektronische Versicherungsbestätigung', 'A1B2C3D', 'E-Kennzeichen', 'Feinstaubplakette']) and '04' in vt and '10' in vt, vt[-500:])
check('Vollmacht: kein alter Zusatz-Kasten mehr', 'Zusatzangaben für den Zulassungsservice' not in vt)
check('SEPA ist Seite 3 des Kreis-Formulars (Hauptzollamt Krefeld)', 'HauptzollamtKrefeld' in st, st[:120])
check('SEPA: Kontoinhaber, IBAN, Halter', all(x in st for x in ['HansZahler', 'Bahnstraße3', 'DE02120300000000202051', 'ErikaFormtest']), st[:600])
check('gedruckte PDFs sind flach (keine Formularfelder)', '/Annots' not in vp and '/Annots' not in sp)
check('leere Formulare der Bibliothek vorhanden', all((app.BASE / 'templates' / x['file']).exists() for x in app.DOCUMENT_LIBRARY))

print('=== Nicht lesbare Einsendung (z. B. alter Schluessel) ===')
r = http('POST', 'vormerken', booking(d2, 'Formtest2')); nr2 = r.get('nr', '')
fremd = serialization.load_pem_private_key(
    __import__('cryptography.hazmat.primitives.asymmetric.rsa', fromlist=['rsa']).generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), None)
fremd_pk = base64.b64encode(fremd.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
http('POST', 'formular', {'nr': nr2, **encrypt_like_browser(formular(nr2), fremd_pk)})
app.web_sync_once(); app.web_sync_once()
j = job('Formtest2')
check('Hinweis "nicht gelesen werden" im Auftrag', 'konnte nicht gelesen werden' in (j.get('missing') or ''), j.get('missing'))
check('Auftrag sonst unveraendert', not j.get('iban') and not j.get('birthdate'))
check('auch die nicht lesbare Einsendung ist vom Webserver geloescht', offene_formulare() == [])

print('=== Ohne Paket cryptography ===')
app._WEB_KEY.clear(); real = app._web_key
app._web_key = lambda: None
app.web_sync_once()
check('Website bekommt dann keinen Schluessel (nur „PDF erstellen“)', http('GET', 'tage').get('pk') == '')
app._web_key = real; app.web_sync_once()
check('mit Paket wieder aktiv (gleicher Schluessel aus der Datei)', http('GET', 'tage').get('pk') == pk)

print()
print('ALLE TESTS OK' if not failures else f'{len(failures)} FEHLER: {failures}')
sys.exit(1 if failures else 0)
