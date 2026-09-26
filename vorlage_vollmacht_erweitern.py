"""
Erweitert das Formular „Vollmacht + SEPA-Mandat“ des Rhein-Kreises Neuss (templates/Vollmacht_SEPA_RKN.pdf, unverändert
vom Kreis) um drei Angaben – mit dem Straßenverkehrsamt abgesprochen (2026-09-26):

  * eVB-Nummer: eigenes Feld direkt unter „Hersteller, Typ und Fahrzeug-Ident-Nr.“
  * Kennzeichen-Art: Ankreuzfelder E-Kennzeichen, H-Kennzeichen, Saison von __ bis __ (in Abschnitt 2)
  * Feinstaubplakette: Ankreuzfeld (in Abschnitt 2)

Dafür rückt auf Seite 1 alles unterhalb des Fahrzeug-Feldes um 20 Punkt nach unten (unten ist genug Rand), Abschnitt 3
(Einverständniserklärung) um 30 Punkt – den Platz gibt die Lücke über dem Unterschriftsfeld her. Die neuen
Angaben sind echte Formularfelder (evb, kz_e, kz_h, kz_saison, saison_von, saison_bis, feinstaub) – Website und
Büro-Programm füllen sie wie die übrigen Felder. Die Knöpfe „drucken“/„Eingaben löschen“ fallen weg.

Ergebnis: templates/Vollmacht_SEPA_erweitert.pdf (Seiten 2 und 3 unverändert).
Aufruf:   py vorlage_vollmacht_erweitern.py
"""
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject,
                           TextStringObject)
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

T = Path(__file__).resolve().parent / 'templates'
QUELLE, ZIEL = T / 'Vollmacht_SEPA_RKN.pdf', T / 'Vollmacht_SEPA_erweitert.pdf'
GRENZE, DY = 482.0, 20.0           # alles unterhalb von y=482 (Lücke unter dem Fahrzeug-Feld) rückt 20 Punkt nach unten
LINKS, RECHTS = 56.5, 540.4         # Rahmen wie beim Fahrzeug-Feld
# Bereiche der Seite 1: (von y, bis y, Verschiebung nach unten) – die Grenzen liegen jeweils in Leerräumen
BEREICHE = [(GRENZE, None, 0), (290.0, GRENZE, DY), (232.0, 290.0, DY + 10), (0.0, 232.0, DY)]
SCHRIFT = 10.02                     # Grundschrift des Formulars

w = PdfWriter(clone_from=str(QUELLE))
p = w.pages[0]
breite = float(p.mediabox.width)

# ---- 1. Seiteninhalt: je Bereich einmal – ausgeschnitten und nach unten verschoben ----
roh = p.get_contents().get_data()
neu = b''
for y1, y2, dy in BEREICHE:
    y2 = float(p.mediabox.height) if y2 is None else y2
    neu += f'q 1 0 0 1 0 {-dy} cm 0 {y1} {breite} {y2 - y1} re W n\n'.encode() + roh + b'\nQ\n'
def verschiebung(y):
    return next(dy for y1, y2, dy in BEREICHE if y >= y1 and (y2 is None or y < y2))
inhalt = DecodedStreamObject(); inhalt.set_data(neu)
p[NameObject('/Contents')] = w._add_object(inhalt)

# ---- 2. Vorhandene Felder mitverschieben, Druck-/Lösch-Knöpfe entfernen ----
acro = w._root_object['/AcroForm']
def name(a):
    teile, o = [], a
    while o is not None:
        if o.get('/T') is not None: teile.insert(0, str(o['/T']))
        o = o['/Parent'].get_object() if o.get('/Parent') is not None else None
    return '.'.join(teile)
annots = ArrayObject()
for ref in p['/Annots']:
    a = ref.get_object()
    if name(a) in ('drucken', 'Loeschen'): continue
    r = [float(v) for v in a['/Rect']]
    dy = verschiebung(min(r[1], r[3]))
    if dy:
        a[NameObject('/Rect')] = ArrayObject([FloatObject(r[0]), FloatObject(r[1] - dy), FloatObject(r[2]), FloatObject(r[3] - dy)])
    annots.append(ref)
p[NameObject('/Annots')] = annots
acro[NameObject('/Fields')] = ArrayObject([f for f in acro['/Fields'] if str(f.get_object().get('/T')) not in ('drucken', 'Loeschen')])

# ---- 3. Neue Elemente zeichnen (Rahmen, Beschriftung, Kästchen) ----
ueber = BytesIO(); cv = canvas.Canvas(ueber, pagesize=(breite, float(p.mediabox.height)))
def rahmen(x1, y1, x2, y2, lw=.5): cv.setLineWidth(lw); cv.rect(x1, y1, x2 - x1, y2 - y1, stroke=1, fill=0)
felder = []   # (art, name, rect, maxlen, tooltip)

# eVB-Feld unter dem Fahrzeug-Feld (495.7–525.7): gleiche Breite, gleicher Stil
eo, eu = 490.5, 466.5
rahmen(LINKS, eu, RECHTS, eo)
cv.setFont('Helvetica', 7.98); cv.drawString(62.1, eo - 8.5, 'eVB-Nummer (elektronische Versicherungsbestätigung Ihrer Kfz-Versicherung)')
felder.append(('tx', 'evb', [60, eu + .3, 537, eo - 9.2], 7, 'eVB-Nummer der Kfz-Versicherung (7 Zeichen)'))

# Abschnitt 2: Zeile unter „Ich möchte mein bisheriges Kennzeichen beibehalten.“ (dessen Feld unten bei 313.9 - DY)
base = 313.9 - DY - 17              # Grundlinie der neuen Zeile (Text 10 pt wie das Formular)
kasten = 9.8; ky = base - 1.9       # wie das vorhandene Ankreuzfeld (9,8 x 9,8, Linie 0,72)
cv.setFont('Helvetica', SCHRIFT)
x = 63.2
def ankreuz(n, text, tip):
    global x
    rahmen(x, ky, x + kasten, ky + kasten, .72)
    felder.append(('cb', n, [x, ky, x + kasten, ky + kasten], None, tip))
    x += kasten + 5; cv.drawString(x, base, text); x += stringWidth(text, 'Helvetica', SCHRIFT) + 16
ankreuz('kz_e', 'E-Kennzeichen', 'E-Kennzeichen (Elektrofahrzeug)')
ankreuz('kz_h', 'H-Kennzeichen', 'H-Kennzeichen (Oldtimer)')
ankreuz('kz_saison', 'Saison von', 'Saisonkennzeichen')
x -= 12
for n, tip, nach in (('saison_von', 'Saison ab Monat (MM)', 'bis'), ('saison_bis', 'Saison bis Monat (MM)', None)):
    rahmen(x, base - 3.5, x + 24, base + 10.5)
    felder.append(('tx', n, [x + .5, base - 3, x + 23.5, base + 10], 2, tip))
    x += 24 + 4
    if nach: cv.drawString(x, base, nach); x += stringWidth(nach, 'Helvetica', SCHRIFT) + 4
x += 12
ankreuz('feinstaub', 'Feinstaubplakette', 'Feinstaubplakette gewünscht')
assert x - 16 <= RECHTS, f'Zeile zu breit ({x - 16:.1f})'
cv.save(); ueber.seek(0); p.merge_page(PdfReader(ueber).pages[0])

# ---- 4. Neue Formularfelder ----
def xobj(daten, b, h):
    s = DecodedStreamObject(); s.set_data(daten.encode())
    s.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
              NameObject('/BBox'): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(b), FloatObject(h)])})
    return w._add_object(s)
for art, n, r, maxlen, tip in felder:
    d = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'),
                          NameObject('/T'): TextStringObject(n), NameObject('/TU'): TextStringObject(tip),
                          NameObject('/Rect'): ArrayObject([FloatObject(v) for v in r]), NameObject('/F'): NumberObject(4),
                          NameObject('/P'): p.indirect_reference})
    if art == 'tx':
        d.update({NameObject('/FT'): NameObject('/Tx'), NameObject('/DA'): TextStringObject('/Helv 10 Tf 0 g'),
                  NameObject('/MaxLen'): NumberObject(maxlen)})
    else:
        b, h = r[2] - r[0], r[3] - r[1]
        kreuz = f'q 0 G 1.2 w {b*.22:.2f} {h*.22:.2f} m {b*.78:.2f} {h*.78:.2f} l S {b*.22:.2f} {h*.78:.2f} m {b*.78:.2f} {h*.22:.2f} l S Q'
        d.update({NameObject('/FT'): NameObject('/Btn'), NameObject('/V'): NameObject('/Off'), NameObject('/AS'): NameObject('/Off'),
                  NameObject('/DA'): TextStringObject('/ZaDb 0 Tf 0 g'), NameObject('/MK'): DictionaryObject({NameObject('/CA'): TextStringObject('8')}),
                  NameObject('/AP'): DictionaryObject({NameObject('/N'): DictionaryObject({NameObject('/Ja'): xobj(kreuz, b, h), NameObject('/Off'): xobj('', b, h)})})})
    ref = w._add_object(d); p['/Annots'].append(ref); acro['/Fields'].append(ref)

p.compress_content_streams()
w.add_metadata({'/Title': 'Vollmacht zur Vorlage bei der Zulassungsbehörde (Rhein-Kreis Neuss, erweitert um eVB, Kennzeichen-Art, Feinstaubplakette)'})
with open(ZIEL, 'wb') as f: w.write(f)
print('geschrieben:', ZIEL)
