import json, os, sqlite3, sys, webbrowser, threading, urllib.parse, urllib.request, ssl, time, zipfile, re, subprocess, platform, shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from pathlib import Path

VERSION='1.0.1'
BASE=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
# Produktivdaten liegen unter Windows ausserhalb des Versionsordners. So bleiben Auftraege,
# Mitarbeiter, Notizen und Scans bei einem Update auf einen neuen ZIP-Ordner erhalten.
# Fuer Entwicklung/andere Systeme bleibt der bisherige lokale data-Ordner erhalten.
if os.name=='nt' and os.environ.get('LOCALAPPDATA'):
    DATA=Path(os.environ['LOCALAPPDATA'])/'ServicePointBuero'
    DATA.mkdir(parents=True,exist_ok=True)
    legacy=BASE/'data'
    if legacy.exists() and not (DATA/'auftraege.db').exists():
        for item in legacy.iterdir():
            target=DATA/item.name
            if target.exists():
                continue
            try:
                shutil.copytree(item,target) if item.is_dir() else shutil.copy2(item,target)
            except Exception:
                pass
else:
    DATA=BASE/'data'; DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'auftraege.db'
HOST='127.0.0.1'; PORT=8765

SINGLE_USER_ID=1

def personal_notes():
    c=db(); out=[dict(x) for x in c.execute('SELECT id,created,updated,title,body,done FROM personal_notes WHERE employee_id=? ORDER BY done,updated DESC',(SINGLE_USER_ID,))]; c.close(); return out

def save_personal_note(d):
    c=db(); now=datetime.now().isoformat(timespec='seconds'); nid=int(d.get('id') or 0); title=(d.get('title') or 'Notiz').strip(); body=(d.get('body') or '').strip(); done=1 if d.get('done') else 0
    if nid:
        c.execute('UPDATE personal_notes SET title=?,body=?,done=?,updated=? WHERE id=? AND employee_id=?',(title,body,done,now,nid,SINGLE_USER_ID))
    else:
        c.execute('INSERT INTO personal_notes (employee_id,created,updated,title,body,done) VALUES (?,?,?,?,?,?)',(SINGLE_USER_ID,now,now,title,body,done)); nid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.commit(); c.close(); return nid

def delete_personal_note(nid):
    c=db(); c.execute('DELETE FROM personal_notes WHERE id=? AND employee_id=?',(int(nid),SINGLE_USER_ID)); c.commit(); c.close()

RADIO_STREAMS={
    '1live':'https://wdr-1live-live.icecastssl.wdr.de/wdr/1live/live/mp3/128/stream.mp3',
    'jamfm':'https://stream.jam.fm/jamfm-live/mp3-192/',
    'bollerwagen':'https://stream.ffn.de/radiobollerwagen/mp3-192/stream.mp3',
    'bigfm':'https://stream.bigfm.de/deutschland/mp3-128/private',
    'swr3':'https://liveradio.swr.de/sw282p3/swr3/play.mp3',
    'wdr4':'https://wdr-wdr4-live.icecastssl.wdr.de/wdr/wdr4/live/mp3/128/stream.mp3',
    'bob':'https://streams.radiobob.de/bob-national/mp3-128/stream.mp3',
    'sunshine':'https://stream.sunshine-live.de/sunshine-live/mp3-128/stream.mp3',
}
_INSECURE_SSL=ssl.create_default_context(); _INSECURE_SSL.check_hostname=False; _INSECURE_SSL.verify_mode=ssl.CERT_NONE
_RADIO_CACHE={}

def _icy_title(url):
    req=urllib.request.Request(url,headers={'Icy-MetaData':'1','User-Agent':'VLC/3.0.0'})
    try:
        resp=urllib.request.urlopen(req,timeout=6)
    except Exception:
        try: resp=urllib.request.urlopen(req,timeout=6,context=_INSECURE_SSL)
        except Exception: return None
    try:
        metaint=resp.headers.get('icy-metaint')
        if not metaint: return None
        metaint=int(metaint)
        resp.read(metaint)
        length=resp.read(1)[0]*16
        if not length: return None
        meta=resp.read(length).decode('utf-8',errors='replace')
        m=re.search(r"StreamTitle='([^']*)'",meta)
        title=m.group(1).strip() if m else None
        return title or None
    except Exception:
        return None
    finally:
        resp.close()

def radio_now_playing(station):
    now=time.time(); cached=_RADIO_CACHE.get(station)
    if cached and now-cached[0]<15: return cached[1]
    title=None
    if station=='bollerwagen':
        try:
            req=urllib.request.Request('https://radiobollerwagen.de/fileadmin/content/playlist-xml/radiobollerwagen.json',headers={'User-Agent':'Mozilla/5.0'})
            try: raw=urllib.request.urlopen(req,timeout=6).read()
            except Exception: raw=urllib.request.urlopen(req,timeout=6,context=_INSECURE_SSL).read()
            data=json.loads(raw)
            s=data['songs'][0]; title=f"{s['artist']} - {s['title']}"
        except Exception:
            title=None
    if not title and station in RADIO_STREAMS:
        title=_icy_title(RADIO_STREAMS[station])
    _RADIO_CACHE[station]=(now,title)
    return title

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, stva_date TEXT, customer TEXT, first_name TEXT, mobile TEXT, birthdate TEXT, birthplace TEXT, birthname TEXT, address TEXT, postal TEXT, city TEXT, vehicle_type TEXT, manufacturer TEXT, plate TEXT, process TEXT, sign_size TEXT, signs TEXT, sign_count TEXT, plate_transfer TEXT, docs TEXT, missing TEXT, status TEXT, fin TEXT, zb2 TEXT, evb TEXT, desired_plate TEXT, iban TEXT, bic_bank TEXT, account_holder TEXT, country TEXT DEFAULT 'Deutschland')''')
    c.execute('CREATE TABLE IF NOT EXISTS laufzettel_options (job_id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS intake_checklists (job_id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS personal_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS deleted_jobs (id INTEGER PRIMARY KEY, deleted_at TEXT, data TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS deleted_customers (id INTEGER PRIMARY KEY, deleted_at TEXT, data TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, updated TEXT, customer TEXT, first_name TEXT, mobile TEXT, address TEXT, postal TEXT, city TEXT, notes TEXT)')
    # V18.6: separate Steuerzahlerdaten fuer SEPA-/Steuerfaelle, update-sicher migriert.
    existing={r[1] for r in c.execute('PRAGMA table_info(jobs)').fetchall()}
    for col,sqltype,default in [('taxpayer_same_holder','TEXT','Ja'),('taxpayer_first_name','TEXT',''),('taxpayer_name','TEXT',''),('taxpayer_address','TEXT',''),('taxpayer_postal','TEXT',''),('taxpayer_city','TEXT',''),('account_holder_same_taxpayer','TEXT','Ja'),('sign_count','TEXT',''),('need_gbr','TEXT','Nein'),('need_kurzzeit','TEXT','Nein'),('need_ausland_kz','TEXT','Nein'),('need_erhalt','TEXT','Nein'),('final_price','TEXT',''),('landline','TEXT',''),('pickup_notified_at','TEXT','')]:
        if col not in existing:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {sqltype} DEFAULT '{default}'")
    existing_cust={r[1] for r in c.execute('PRAGMA table_info(customers)').fetchall()}
    if 'customer_type' not in existing_cust:
        c.execute("ALTER TABLE customers ADD COLUMN customer_type TEXT DEFAULT ''")
    c.commit(); return c

def rows():
    c=db(); r=[dict(x) for x in c.execute('SELECT * FROM jobs ORDER BY COALESCE(stva_date,created) DESC,id DESC')]; c.close(); return r

def export_jobs_csv():
    import csv,io
    cols=['id','stva_date','status','customer','first_name','mobile','landline','address','postal','city','vehicle_type','manufacturer','plate','desired_plate','process','plate_transfer','sign_size','signs','docs','missing','final_price','created']
    buf=io.StringIO(); w=csv.writer(buf,delimiter=';'); w.writerow(cols)
    for j in rows(): w.writerow([j.get(k,'') for k in cols])
    return buf.getvalue().encode('utf-8-sig')

def export_customers_csv():
    import csv,io
    cols=['customer','first_name','customer_type','mobile','address','postal','city','notes','job_count','last_date']
    buf=io.StringIO(); w=csv.writer(buf,delimiter=';'); w.writerow(cols)
    for c in all_customers(): w.writerow([c.get(k,'') for k in cols])
    return buf.getvalue().encode('utf-8-sig')

def _cust_key(name,first_name=''):
    return (name or '').strip().lower()+'|'+(first_name or '').strip().lower()

def all_customers():
    c=db()
    manual=[dict(x) for x in c.execute('SELECT * FROM customers')]
    jobrows=[dict(x) for x in c.execute("SELECT customer,first_name,mobile,address,postal,city,stva_date,created FROM jobs WHERE customer!=''")]
    c.close()
    agg={}
    for m in manual:
        k=_cust_key(m['customer'],m['first_name'])
        ctype=m.get('customer_type') or ('Firma' if not (m['first_name'] or '').strip() else 'Privat')
        agg[k]={'id':m['id'],'customer':m['customer'],'first_name':m['first_name'],'mobile':m['mobile'],'address':m['address'],'postal':m['postal'],'city':m['city'],'notes':m['notes'],'customer_type':ctype,'job_count':0,'last_date':''}
    for j in jobrows:
        k=_cust_key(j['customer'],j['first_name'])
        if k not in agg:
            ctype='Firma' if not (j['first_name'] or '').strip() else 'Privat'
            agg[k]={'id':None,'customer':j['customer'],'first_name':j['first_name'],'mobile':j['mobile'],'address':j['address'],'postal':j['postal'],'city':j['city'],'notes':'','customer_type':ctype,'job_count':0,'last_date':''}
        agg[k]['job_count']+=1
        dte=j.get('stva_date') or j.get('created') or ''
        if dte>agg[k]['last_date']: agg[k]['last_date']=dte
    return sorted(agg.values(),key=lambda x:(x['customer'] or '').lower())

def customer_jobs(name,first_name):
    c=db(); jobs=[dict(x) for x in c.execute('SELECT * FROM jobs')]; c.close()
    k=_cust_key(name,first_name)
    return sorted([j for j in jobs if _cust_key(j.get('customer'),j.get('first_name'))==k],key=lambda x:x.get('stva_date') or x.get('created') or '',reverse=True)

def save_customer(d):
    c=db(); now=datetime.now().isoformat(timespec='seconds')
    cols=['customer','first_name','mobile','address','postal','city','notes','customer_type']
    vals=[d.get(x,'') for x in cols]
    if d.get('id'):
        cid=int(d['id']); c.execute(f"UPDATE customers SET {','.join(x+'=?' for x in cols)},updated=? WHERE id=?",vals+[now,cid])
    else:
        c.execute(f"INSERT INTO customers(created,updated,{','.join(cols)}) VALUES(?,?,{','.join('?' for _ in cols)})",[now,now]+vals); cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    old_c=d.get('old_customer',''); old_f=d.get('old_first_name','')
    new_c=d.get('customer',''); new_f=d.get('first_name','')
    if old_c and (old_c,old_f)!=(new_c,new_f):
        c.execute('UPDATE jobs SET customer=?,first_name=? WHERE customer=? AND first_name=?',(new_c,new_f,old_c,old_f))
    c.commit(); c.close(); return cid

def delete_customer(cid):
    c=db()
    row=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone()
    if row: c.execute('INSERT OR REPLACE INTO deleted_customers(id,deleted_at,data) VALUES(?,?,?)',(cid,datetime.now().isoformat(timespec='seconds'),json.dumps(dict(row),ensure_ascii=False)))
    c.execute('DELETE FROM customers WHERE id=?',(cid,)); c.commit(); c.close()

def _prune_trash(c,table):
    cutoff=(datetime.now()-timedelta(days=7)).isoformat(timespec='seconds')
    c.execute(f'DELETE FROM {table} WHERE deleted_at<?',(cutoff,))

def list_deleted_jobs():
    c=db(); _prune_trash(c,'deleted_jobs'); c.commit()
    out=[]
    for r in c.execute('SELECT id,deleted_at,data FROM deleted_jobs ORDER BY deleted_at DESC'):
        d=json.loads(r['data']); out.append({'id':r['id'],'deleted_at':r['deleted_at'],'customer':d.get('customer',''),'first_name':d.get('first_name',''),'stva_date':d.get('stva_date','')})
    c.close(); return out

def restore_deleted_job(jid):
    c=db(); row=c.execute('SELECT data FROM deleted_jobs WHERE id=?',(jid,)).fetchone()
    if not row: c.close(); raise RuntimeError('Gelöschter Auftrag nicht gefunden (evtl. abgelaufen).')
    d=json.loads(row['data']); cols=list(d.keys())
    c.execute(f"INSERT OR REPLACE INTO jobs ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",[d[k] for k in cols])
    c.execute('DELETE FROM deleted_jobs WHERE id=?',(jid,)); c.commit(); c.close(); return jid

def list_deleted_customers():
    c=db(); _prune_trash(c,'deleted_customers'); c.commit()
    out=[]
    for r in c.execute('SELECT id,deleted_at,data FROM deleted_customers ORDER BY deleted_at DESC'):
        d=json.loads(r['data']); out.append({'id':r['id'],'deleted_at':r['deleted_at'],'customer':d.get('customer',''),'first_name':d.get('first_name','')})
    c.close(); return out

def restore_deleted_customer(cid):
    c=db(); row=c.execute('SELECT data FROM deleted_customers WHERE id=?',(cid,)).fetchone()
    if not row: c.close(); raise RuntimeError('Gelöschter Kunde nicht gefunden (evtl. abgelaufen).')
    d=json.loads(row['data']); cols=list(d.keys())
    c.execute(f"INSERT OR REPLACE INTO customers ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",[d[k] for k in cols])
    c.execute('DELETE FROM deleted_customers WHERE id=?',(cid,)); c.commit(); c.close(); return cid

def backup_db_daily():
    """Create one local SQLite backup per day and retain the latest 14 backups."""
    try:
        if not DB.exists():
            return
        folder=DATA/'backups'; folder.mkdir(parents=True,exist_ok=True)
        target=folder/f"auftraege_{datetime.now().date().isoformat()}.db"
        if not target.exists():
            src=sqlite3.connect(DB); dst=sqlite3.connect(target)
            try: src.backup(dst)
            finally: dst.close(); src.close()
        backups=sorted(folder.glob('auftraege_*.db'),key=lambda x:x.stat().st_mtime,reverse=True)
        for old in backups[14:]:
            try: old.unlink()
            except Exception: pass
    except Exception:
        # Eine fehlgeschlagene Sicherung darf den Bueroablauf nicht blockieren.
        pass

def backup_db_now():
    """Create a timestamped manual SQLite backup and return its filename."""
    folder=DATA/'backups'; folder.mkdir(parents=True,exist_ok=True)
    target=folder/f"auftraege_manuell_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
    src=sqlite3.connect(DB); dst=sqlite3.connect(target)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    return target.name

def list_backups():
    folder=DATA/'backups'
    if not folder.exists(): return []
    files=sorted(folder.glob('auftraege_*.db'),key=lambda p:p.stat().st_mtime,reverse=True)
    return [{'name':f.name,'size':f.stat().st_size,'mtime':datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec='seconds')} for f in files]

def restore_backup(name):
    folder=DATA/'backups'; src=folder/Path(name or '').name
    if not src.exists() or src.parent.resolve()!=folder.resolve(): raise RuntimeError('Sicherung nicht gefunden.')
    backup_db_now()
    shutil.copy2(src,DB)
    return {'ok':True}

GITHUB_REPO='ServicePointGV/service-point-buero'

def find_update():
    url=f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
    req=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'ServicePointBuero'})
    try:
        with urllib.request.urlopen(req,timeout=8) as r: rel=json.loads(r.read().decode('utf-8'))
    except Exception as e:
        raise RuntimeError('Update-Server nicht erreichbar. Internetverbindung prüfen. ('+str(e)+')')
    v=(rel.get('tag_name') or '').lstrip('vV')
    asset=next((a for a in rel.get('assets',[]) if a.get('name','').lower().endswith('.zip')),None)
    if v and v!=VERSION and asset:
        return {'available':True,'version':v,'current':VERSION,'url':asset['browser_download_url']}
    return {'available':False,'current':VERSION}

def apply_update(url):
    if not getattr(sys,'frozen',False):
        raise RuntimeError('Update ist nur in der installierten Programmversion möglich, nicht im Entwicklungsmodus.')
    if not url: raise RuntimeError('Kein Update-Download angegeben.')
    tmp_zip=Path(os.environ['TEMP'])/'sp_update_download.zip'
    req=urllib.request.Request(url,headers={'User-Agent':'ServicePointBuero'})
    try:
        with urllib.request.urlopen(req,timeout=60) as r, open(tmp_zip,'wb') as f: shutil.copyfileobj(r,f)
    except Exception as e:
        raise RuntimeError('Download fehlgeschlagen: '+str(e))
    extract_dir=Path(os.environ['TEMP'])/'sp_update_extracted'
    if extract_dir.exists(): shutil.rmtree(extract_dir,ignore_errors=True)
    with zipfile.ZipFile(tmp_zip) as z: z.extractall(extract_dir)
    payload=extract_dir
    inner=[p for p in extract_dir.iterdir() if p.is_dir()]
    if not (extract_dir/'ServicePointBuero.exe').exists() and len(inner)==1:
        payload=inner[0]
    if not (payload/'ServicePointBuero.exe').exists():
        raise RuntimeError('Update-Paket ist unvollständig (ServicePointBuero.exe fehlt).')
    exe=Path(sys.executable)
    bat=Path(os.environ['TEMP'])/'sp_update.bat'
    bat.write_text(
        '@echo off\r\n'
        'timeout /t 2 /nobreak >nul\r\n'
        f'robocopy "{payload}" "{BASE}" /E /MIR /R:3 /W:1 >nul\r\n'
        f'start "" "{exe}"\r\n'
        'del "%~f0"\r\n', encoding='utf-8')
    subprocess.Popen(['cmd','/c',str(bat)],creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS,close_fds=True)
    threading.Timer(0.6,lambda:os._exit(0)).start()
    return {'ok':True}

def easter_sunday(year):
    a=year%19; b=year//100; c=year%100; d=b//4; e=b%4; f=(b+8)//25; g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30; i=c//4; k=c%4; l=(32+2*e+2*i-h-k)%7; m=(a+11*h+22*l)//451
    month=(h+l-7*m+114)//31; day=((h+l-7*m+114)%31)+1
    return datetime(year,month,day).date()

def nrw_holiday_name(d):
    y=d.year; e=easter_sunday(y)
    fixed={(1,1):'Neujahr',(5,1):'Tag der Arbeit',(10,3):'Tag der Deutschen Einheit',(11,1):'Allerheiligen',(12,25):'1. Weihnachtstag',(12,26):'2. Weihnachtstag'}
    if (d.month,d.day) in fixed:return fixed[(d.month,d.day)]
    moving={e-timedelta(days=2):'Karfreitag',e+timedelta(days=1):'Ostermontag',e+timedelta(days=39):'Christi Himmelfahrt',e+timedelta(days=50):'Pfingstmontag',e+timedelta(days=60):'Fronleichnam'}
    if d in moving: return moving[d]
    return (get_app_settings().get('closed_dates') or {}).get(d.isoformat(),'')

def is_workday(d): return d.weekday()<5 and not nrw_holiday_name(d)

def next_workday(date_s):
    d=datetime.strptime(date_s,'%Y-%m-%d').date()+timedelta(days=1)
    while not is_workday(d): d+=timedelta(days=1)
    return d.isoformat()

def slot_weight(plate_transfer, process=''):
    p=str(process or '').lower()
    if 'online-abmeldung' in p or 'kauf / verkauf' in p or 'kauf/verkauf' in p: return 0
    return 2 if str(plate_transfer or '').strip().lower() in ('ja','yes','1','true') else 1

def day_count(c,date_s,exclude_id=None):
    sql='SELECT id,plate_transfer,process FROM jobs WHERE stva_date=?'; args=[date_s]
    if exclude_id: sql+=' AND id<>?'; args.append(exclude_id)
    return sum(slot_weight(r['plate_transfer'],r['process']) for r in c.execute(sql,args).fetchall())

def auto_date(c,requested,exclude_id=None,needed_slots=1):
    date_s=requested or datetime.now().date().isoformat()
    d=datetime.strptime(date_s,'%Y-%m-%d').date()
    while not is_workday(d):
        date_s=next_workday((d-timedelta(days=1)).isoformat()); d=datetime.strptime(date_s,'%Y-%m-%d').date()
    reg=regular_slots()
    while day_count(c,date_s,exclude_id)+needed_slots>reg: date_s=next_workday(date_s)
    return date_s

def fill_buffers(date_s):
    c=db(); used=day_count(c,date_s); reg=regular_slots(); total=reg+buffer_slots()
    # Puffer wird nur genutzt, wenn die regulaeren Plaetze bereits belegt sind.
    # Kennzeichenuebernahmen brauchen zwei regulaere Plaetze und duerfen nie in den Puffer gezogen werden.
    if used<reg or used>=total: c.close(); return {'moved':0,'from_date':'','ids':[]}
    free=total-used; src=next_workday(date_s); selected=[]
    for _ in range(366):
        candidates=c.execute('SELECT id,plate_transfer,process FROM jobs WHERE stva_date=? ORDER BY id',(src,)).fetchall()
        remaining=free; selected=[]
        for r in candidates:
            w=slot_weight(r['plate_transfer'],r['process'])
            if w!=1: continue
            if w<=remaining:
                selected.append(r); remaining-=w
            if remaining<=0: break
        if selected: break
        src=next_workday(src)
    ids=[x['id'] for x in selected]
    for jid in ids: c.execute('UPDATE jobs SET stva_date=? WHERE id=?',(date_s,jid))
    c.commit(); c.close(); return {'moved':len(ids),'from_date':src if ids else '','ids':ids}

def move_job(jid,target):
    try: target_date=datetime.strptime(target,'%Y-%m-%d').date()
    except Exception: raise RuntimeError('Bitte einen gültigen StVA-Tag auswählen.')
    c=db()
    if not c.execute('SELECT 1 FROM jobs WHERE id=?',(jid,)).fetchone(): c.close(); raise RuntimeError('Auftrag nicht gefunden.')
    row=c.execute('SELECT plate_transfer,process FROM jobs WHERE id=?',(jid,)).fetchone(); needed=slot_weight(row['plate_transfer'] if row else '',row['process'] if row else '')
    if needed==0:
        c.close(); raise RuntimeError('Dieser Vorgang benötigt keinen StVA-Platz und kann nicht in die Tagesplanung verschoben werden.')
    if not is_workday(target_date):
        reason=nrw_holiday_name(target_date) or 'Wochenende'
        c.close(); raise RuntimeError(f'{target} ist kein StVA-Arbeitstag ({reason}).')
    if day_count(c,target,jid)+needed>regular_slots(): c.close(); raise RuntimeError(f'Dieser StVA-Tag hat nicht genügend freie reguläre Plätze (max. {regular_slots()}).')
    c.execute('UPDATE jobs SET stva_date=? WHERE id=?',(target,jid)); c.commit(); c.close(); return target

def save_job(d):
    cols=['stva_date','customer','first_name','mobile','birthdate','birthplace','birthname','address','postal','city','vehicle_type','manufacturer','plate','process','sign_size','signs','sign_count','plate_transfer','docs','missing','status','fin','zb2','evb','desired_plate','iban','bic_bank','account_holder','country','taxpayer_same_holder','taxpayer_first_name','taxpayer_name','taxpayer_address','taxpayer_postal','taxpayer_city','account_holder_same_taxpayer','need_gbr','need_kurzzeit','need_ausland_kz','need_erhalt','final_price','landline','pickup_notified_at']
    c=db(); now=datetime.now().isoformat(timespec='seconds'); requested=d.get('stva_date','') or next_workday(datetime.now().date().isoformat())
    if d.get('id'):
        jid=int(d['id']); current=c.execute('SELECT stva_date FROM jobs WHERE id=?',(jid,)).fetchone()
        needed=slot_weight(d.get('plate_transfer'),d.get('process'))
        if needed==0:
            # Online-Abmeldung und andere 0-Slot-Vorgänge dürfen nicht versehentlich
            # in „Heute im StVA“ oder einem späteren StVA-Tag stehen bleiben.
            d['stva_date']=''
        else:
            try:
                requested_date=datetime.strptime(requested,'%Y-%m-%d').date()
            except Exception:
                requested_date=datetime.strptime(next_workday(datetime.now().date().isoformat()),'%Y-%m-%d').date()
                requested=requested_date.isoformat()
            if not is_workday(requested_date):
                # Gleiche Schutzlogik wie bei neuen Aufträgen: Wochenende/NRW-Feiertag
                # automatisch auf den nächsten StVA-Arbeitstag verschieben.
                requested=auto_date(c,requested,exclude_id=jid,needed_slots=needed)
            elif current and requested!=current['stva_date'] and day_count(c,requested,jid)+needed>regular_slots():
                c.close(); raise RuntimeError(f'Dieser StVA-Tag hat nicht genügend freie reguläre Plätze (max. {regular_slots()}).')
            d['stva_date']=requested
        vals=[d.get(k,'') for k in cols]+[jid]; c.execute('UPDATE jobs SET '+','.join(f'{k}=?' for k in cols)+' WHERE id=?',vals)
    else:
        earliest=next_workday(datetime.now().date().isoformat())
        try:
            if datetime.strptime(requested,'%Y-%m-%d').date() < datetime.strptime(earliest,'%Y-%m-%d').date(): requested=earliest
        except Exception:
            requested=earliest
        needed=slot_weight(d.get('plate_transfer'),d.get('process'))
        d['stva_date']='' if needed==0 else auto_date(c,requested,needed_slots=needed)
        vals=[now]+[d.get(k,'') for k in cols]; c.execute('INSERT INTO jobs (created,'+','.join(cols)+') VALUES ('+','.join('?' for _ in vals)+')',vals); jid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.commit(); actual=d['stva_date']; c.close(); return jid,actual

def remove_from_today(jid):
    c=db()
    cur=c.execute('UPDATE jobs SET stva_date=? WHERE id=?',('',jid))
    c.commit(); changed=cur.rowcount; c.close(); return changed

def delete_job(jid):
    c=db()
    row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
    if row: c.execute('INSERT OR REPLACE INTO deleted_jobs(id,deleted_at,data) VALUES(?,?,?)',(jid,datetime.now().isoformat(timespec='seconds'),json.dumps(dict(row),ensure_ascii=False)))
    c.execute('DELETE FROM intake_checklists WHERE job_id=?',(jid,))
    c.execute('DELETE FROM laufzettel_options WHERE job_id=?',(jid,))
    cur=c.execute('DELETE FROM jobs WHERE id=?',(jid,))
    c.commit(); changed=cur.rowcount; c.close(); return changed

def excel_col(ref):
    letters=re.match(r'[A-Z]+',ref).group(); n=0
    for ch in letters:n=n*26+ord(ch)-64
    return n-1

def import_xlsx(path):
    import xml.etree.ElementTree as ET
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(path) as z:
        ss=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si',ns): ss.append(''.join(t.text or '' for t in si.iter('{%s}t'%ns['m'])))
        wb=ET.fromstring(z.read('xl/workbook.xml')); rel=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        relmap={x.attrib['Id']:x.attrib['Target'] for x in rel}
        count=0
        for sh in wb.find('m:sheets',ns):
            name=sh.attrib['name']
            if name=='Listen': continue
            target=relmap[sh.attrib['{%s}id'%ns['r']]]; target=target.lstrip('/')
            if not target.startswith('xl/'): target='xl/'+target
            root=ET.fromstring(z.read(target)); data=root.find('m:sheetData',ns)
            if data is None: continue
            for row in data.findall('m:row',ns)[1:]:
                vals=['']*13
                for cell in row.findall('m:c',ns):
                    idx=excel_col(cell.attrib['r']); v=cell.find('m:v',ns)
                    if v is None or idx>=13: continue
                    val=v.text or ''
                    if cell.attrib.get('t')=='s': val=ss[int(val)]
                    vals[idx]=val
                if not any(vals[2:]): continue
                date=''
                try: date=(datetime(1899,12,30)+timedelta(days=float(vals[1]))).date().isoformat()
                except: date=str(vals[1])
                d=dict(stva_date=date,customer=vals[2],mobile=vals[3],vehicle_type=vals[4],plate=vals[5],process=vals[6],sign_size=vals[7],signs=vals[8],plate_transfer=vals[9],docs=vals[10],missing=vals[11],status=vals[12] or 'Offen')
                save_job(d); count+=1
        return count

def get_intake(jid):
    c=db(); row=c.execute('SELECT data FROM intake_checklists WHERE job_id=?',(jid,)).fetchone(); c.close()
    if not row: return {}
    try: return json.loads(row['data'])
    except: return {}

def save_intake(jid,data):
    c=db(); c.execute('INSERT INTO intake_checklists(job_id,data) VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET data=excluded.data',(jid,json.dumps(data,ensure_ascii=False))); c.commit(); c.close()

def scan_dir():
    p=DATA/'scans'/'pending'; p.mkdir(parents=True,exist_ok=True); return p

def clear_pending_scans():
    """Remove temporary customer scans so files can never leak into the next order."""
    p=scan_dir(); removed=0
    for x in p.iterdir():
        if x.is_file() and (x.suffix.lower() in ('.jpg','.jpeg','.png','.json') or x.name.startswith('OCR-')):
            try: x.unlink(); removed+=1
            except Exception: pass
    return {'ok':True,'removed':removed}

def _wia_set_prop(item, prop_id, value):
    """Best-effort WIA property setter. Drivers may expose only a subset."""
    try:
        props=item.Properties
        for i in range(1, props.Count+1):
            pr=props.Item(i)
            if int(pr.PropertyID)==int(prop_id):
                pr.Value=value
                return True
    except Exception:
        pass
    return False

def _wia_scan_to(dest, profile='full'):
    """Scan via WIA. For ID cards, request only a high-resolution top-left card area.

    This is deliberately different from OCR 3.2: instead of scanning A4 and trying to
    rescue a tiny card afterwards, the scanner itself is asked for a ~100 x 75 mm area
    at 600 dpi (300 dpi fallback). The user places the document at the top-left corner.
    """
    if os.name!='nt':
        raise RuntimeError('Die Scanner-Automatik kann nur unter Windows verwendet werden.')
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise RuntimeError('Windows-Scannerkomponente fehlt. Bitte INSTALLIEREN.bat einmal ausführen.')
    pythoncom.CoInitialize()
    try:
        manager=win32com.client.Dispatch('WIA.DeviceManager')
        if manager.DeviceInfos.Count < 1:
            raise RuntimeError('Kein WIA-Scanner gefunden.')
        device=manager.DeviceInfos.Item(1).Connect()
        if device.Items.Count < 1:
            raise RuntimeError('Scanner gefunden, aber keine Scanquelle verfügbar.')
        item=device.Items.Item(1)

        if profile=='id_card':
            # WIA_IPS_XRES/YRES, XPOS/YPOS, XEXTENT/YEXTENT.
            # 100 x 75 mm gives an ID-1 card generous reserve on every side.
            # Try 600 dpi first; many office flatbeds support it. If a driver refuses,
            # retry with 300 dpi. Extents are pixels at the selected resolution.
            configured=False
            for dpi in (600,300):
                try:
                    okx=_wia_set_prop(item,6147,dpi)
                    oky=_wia_set_prop(item,6148,dpi)
                    _wia_set_prop(item,6149,0); _wia_set_prop(item,6150,0)
                    ex=max(600,round((100/25.4)*dpi))
                    ey=max(450,round((75/25.4)*dpi))
                    oke=_wia_set_prop(item,6151,ex) and _wia_set_prop(item,6152,ey)
                    if okx and oky and oke:
                        configured=True
                        break
                except Exception:
                    continue
            # If the driver cannot set extents, transfer still works; diagnostics will
            # identify that fallback and OCR can use the manual/full-scan path.
        try:
            image=item.Transfer('{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}')
        except Exception:
            image=item.Transfer()
        dest=Path(dest); dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists(): dest.unlink()
        image.SaveFile(str(dest))
        if not dest.exists() or dest.stat().st_size < 1000:
            raise RuntimeError('Der Scanner hat keine verwertbare Bilddatei geliefert.')
        return dest
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError('WIA-Scan fehlgeschlagen: '+str(e))
    finally:
        try: pythoncom.CoUninitialize()
        except Exception: pass

def _make_id_a4():
    """Builds the familiar A4 ID copy from front/back scans, locally and without printing."""
    from PIL import Image
    p=scan_dir(); front=p/'Ausweis-Vorne.jpg'; back=p/'Ausweis-Hinten.jpg'; out=p/'Ausweis-A4.jpg'
    if not front.exists() or not back.exists(): return None
    def card(path):
        im=Image.open(path).convert('RGB')
        im,_,_= _apply_calibrated_crop(im)
        if im.height > im.width:
            im=im.rotate(-90,expand=True)
        return im
    a4=Image.new('RGB',(2480,3508),'white')
    for src,y in ((front,650),(back,1550)):
        c=card(src).resize((1011,756),Image.Resampling.LANCZOS)
        a4.paste(c,((2480-1011)//2,y))
    a4.save(out,'JPEG',quality=94,dpi=(300,300))
    return out

def scan_direct(kind, side='', doc_type=''):
    """Direct integrated scanner entry point used by the browser UI."""
    p=scan_dir()
    if kind=='id':
        if side not in ('front','back'):
            raise RuntimeError('Bitte Vorder- oder Rückseite auswählen.')
        doc_type=(doc_type or 'personalausweis').strip().lower()
        if side=='front':
            # A new identity scan must never inherit the back side from a previous customer.
            for old in (p/'Ausweis-Hinten.jpg',p/'Ausweis-A4.jpg'):
                try:
                    if old.exists(): old.unlink()
                except Exception: pass
            try: (p/'scan_context.json').write_text(json.dumps({'id_type':doc_type}),encoding='utf-8')
            except Exception: pass
        dest=p/('Ausweis-Vorne.jpg' if side=='front' else 'Ausweis-Hinten.jpg')
        _wia_scan_to(dest, 'full')
        if side=='back': _make_id_a4()
        return {'ok':True,'kind':'id','side':side,'file':dest.name,'a4_ready':(p/'Ausweis-A4.jpg').exists(),'id_type':doc_type}
    if kind=='taxpayer_id':
        if side not in ('front','back'):
            raise RuntimeError('Bitte Vorder- oder Rückseite auswählen.')
        doc_type=(doc_type or 'personalausweis').strip().lower()
        dest=p/('Steuerzahler-Ausweis-Vorne.jpg' if side=='front' else 'Steuerzahler-Ausweis-Hinten.jpg')
        _wia_scan_to(dest, 'full')
        return {'ok':True,'kind':'taxpayer_id','side':side,'file':dest.name,'id_type':doc_type}
    if kind=='bank': dest=p/'Bank.jpg'
    elif kind=='extra': dest=p/'Zusatzdokument.jpg'
    elif kind=='handelsregister': dest=p/'Handelsregisterauszug.jpg'
    elif kind=='gewerbeanmeldung': dest=p/'Gewerbeanmeldung.jpg'
    else: raise RuntimeError('Unbekannter Scanvorgang.')
    _wia_scan_to(dest)
    return {'ok':True,'kind':kind,'file':dest.name}

def _setup_tesseract():
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError('OCR-Komponenten fehlen. Bitte INSTALLIEREN.bat ausführen.')
    candidates=[r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe',r'C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe']
    for x in candidates:
        if Path(x).exists(): pytesseract.pytesseract.tesseract_cmd=x; break
    try: pytesseract.get_tesseract_version()
    except Exception as e: raise RuntimeError('Tesseract OCR ist nicht verfügbar. Bitte INSTALLIEREN.bat erneut ausführen. '+str(e))
    return pytesseract

DEFAULT_PICKUP_MESSAGE=("Guten Tag,\n\nIhre Unterlagen liegen bei uns Fertig und Abholbereit.\n\n"
    "Die Gesamtkosten belaufen sich auf {price} €.\n\nUnsere Öffnungszeiten sind:\n\n"
    "Montag und Mittwochs von 07:30 bis 16:30\nDienstags und Donnerstags von 07:30 bis 15:30\nFreitags von 07:30 bis 13:00\n\n"
    "Mit freundlichen Grüßen \nZulassungsservice Grevenbroich")
DEFAULT_APP_SETTINGS={'regular_slots':8,'buffer_slots':2,'pickup_message':DEFAULT_PICKUP_MESSAGE,'closed_dates':{},'enabled_radios':['1live','jamfm','bollerwagen','bigfm','swr3','wdr4','bob','sunshine']}

def _app_settings_file():
    return DATA/'app_settings.json'

def get_app_settings():
    f=_app_settings_file(); out=dict(DEFAULT_APP_SETTINGS)
    if f.exists():
        try: out.update({k:v for k,v in json.loads(f.read_text(encoding='utf-8')).items() if k in DEFAULT_APP_SETTINGS})
        except Exception: pass
    out['regular_slots']=max(1,min(20,int(out.get('regular_slots') or 8)))
    out['buffer_slots']=max(0,min(20,int(out.get('buffer_slots') or 0)))
    return out

def save_app_settings(patch):
    cur=get_app_settings()
    if 'regular_slots' in patch: cur['regular_slots']=max(1,min(20,int(patch['regular_slots'])))
    if 'buffer_slots' in patch: cur['buffer_slots']=max(0,min(20,int(patch['buffer_slots'])))
    if 'pickup_message' in patch: cur['pickup_message']=str(patch['pickup_message'] or DEFAULT_PICKUP_MESSAGE)
    if 'closed_dates' in patch and isinstance(patch['closed_dates'],dict):
        cur['closed_dates']={str(k):str(v) for k,v in patch['closed_dates'].items() if re.match(r'^\d{4}-\d{2}-\d{2}$',str(k))}
    if 'enabled_radios' in patch and isinstance(patch['enabled_radios'],list):
        cur['enabled_radios']=[str(x) for x in patch['enabled_radios'] if str(x) in DEFAULT_APP_SETTINGS['enabled_radios']]
    _app_settings_file().write_text(json.dumps(cur,ensure_ascii=False),encoding='utf-8')
    return cur

def regular_slots(): return get_app_settings()['regular_slots']
def buffer_slots(): return get_app_settings()['buffer_slots']

def _calibration_file():
    return DATA/'scanner_calibration.json'

def get_scanner_calibration():
    f=_calibration_file()
    if not f.exists(): return {'configured':False}
    try:
        d=json.loads(f.read_text(encoding='utf-8'))
        box=d.get('id_box') or []
        if len(box)==4 and all(0 <= float(v) <= 1 for v in box):
            return {'configured':True,'id_box':[float(v) for v in box]}
    except Exception: pass
    return {'configured':False}

def save_scanner_calibration(box):
    if not isinstance(box,list) or len(box)!=4: raise RuntimeError('Ungültiger Kalibrierungsbereich.')
    box=[float(v) for v in box]
    x1,y1,x2,y2=box
    if not (0<=x1<x2<=1 and 0<=y1<y2<=1): raise RuntimeError('Kalibrierungsbereich liegt außerhalb des Scans.')
    if (x2-x1)<.03 or (y2-y1)<.03: raise RuntimeError('Der markierte Bereich ist zu klein.')
    _calibration_file().write_text(json.dumps({'id_box':box},indent=2),encoding='utf-8')
    return {'ok':True,'configured':True,'id_box':box}

def reset_scanner_calibration():
    f=_calibration_file()
    if f.exists(): f.unlink()
    return {'ok':True,'configured':False}

def _apply_calibrated_crop(im):
    """V18.2: deterministic top-left card crop for the office flatbed.

    The HP flatbed always delivers the complete A4 glass. The user places ID/bank
    cards flush in the top-left corner. An ID-1 card is 85.60 x 53.98 mm; when its
    long side is vertical this occupies roughly 29% x 26% of an A4 portrait scan.
    We deliberately take a generous 32% x 31% safety area so small placement
    differences do not cut the document. If the user has manually calibrated the
    scan area (Einstellungen > Arbeitsplatz), that saved box takes precedence.
    """
    w,h=im.size
    cal=get_scanner_calibration()
    if cal.get('configured'):
        x1,y1,x2,y2=cal['id_box']
        box=(round(x1*w),round(y1*h),round(x2*w),round(y2*h))
        return im.crop(box),box,True
    # If an upstream driver ever really returns only the card, keep the full image.
    ratio=w/max(1,h)
    if (0.58 <= ratio <= 1.75) and min(w,h) < 900 and max(w,h) < 1400:
        return im,(0,0,w,h),False
    x2=max(250,min(w,round(w*0.31)))
    y2=max(360,min(h,round(h*0.32)))
    card=im.crop((0,0,x2,y2))
    return card,(0,0,x2,y2),True

def _document_crop(path, outpath=None):
    """Crop the known top-left document zone from the full A4 flatbed scan."""
    from PIL import Image
    im=Image.open(path).convert('RGB')
    id_type=''
    try:
        ctx=scan_dir()/'scan_context.json'
        if ctx.exists(): id_type=(json.loads(ctx.read_text(encoding='utf-8')).get('id_type') or '').lower()
    except Exception: pass
    if id_type=='reisepass' and Path(path).name.lower().startswith('ausweis-'):
        # Passport data pages are much larger than ID-1 cards. Keep a generous top-left
        # area; orientation detection below decides whether it must be rotated.
        w,h=im.size; x2=max(500,min(w,round(w*.66))); y2=max(500,min(h,round(h*.48)))
        card=im.crop((0,0,x2,y2)); box=(0,0,x2,y2)
    else:
        card,box,_=_apply_calibrated_crop(im)
    if outpath: card.save(outpath,'JPEG',quality=97)
    return card,box

def _prepare_ocr_image(im, mode='gray', target=2400):
    from PIL import ImageOps, ImageEnhance
    g=ImageOps.grayscale(im)
    # The old pipeline over-contrasted holograms. Keep the original document texture
    # and enlarge only after the physical card has been cropped from the A4 bed.
    if g.width<target:
        sc=target/max(1,g.width)
        g=g.resize((int(g.width*sc),int(g.height*sc)), resample=__import__('PIL').Image.Resampling.LANCZOS)
    g=ImageOps.autocontrast(g, cutoff=.35)
    g=ImageEnhance.Sharpness(g).enhance(1.25)
    g=ImageEnhance.Contrast(g).enhance(1.12)
    if mode=='binary':
        # Binary is diagnostic/fallback only; soft grayscale is better on holograms.
        hist=g.histogram(); total=sum(hist); acc=0; med=175
        for i,n in enumerate(hist):
            acc+=n
            if acc>=total*.70: med=i; break
        threshold=max(135,min(210,med-12))
        g=g.point(lambda x: 255 if x>threshold else 0)
    return g

def _save_ocr_previews(card, deg, base):
    """Save exactly what OCR sees so office diagnostics can be checked without exposing scans externally."""
    oriented=card.rotate(deg,expand=True)
    crop_path=base.with_name(base.stem+'-Ausschnitt.jpg')
    gray_path=base.with_name(base.stem+'-Optimiert.jpg')
    bin_path=base.with_name(base.stem+'-SW.jpg')
    oriented.save(crop_path,'JPEG',quality=94)
    _prepare_ocr_image(oriented,'gray').save(gray_path,'JPEG',quality=94)
    _prepare_ocr_image(oriented,'binary').save(bin_path,'JPEG',quality=94)
    return [crop_path.name,gray_path.name,bin_path.name]

def _ocr_processed(im, psm_values=(6,11), whitelist=''):
    pytesseract=_setup_tesseract(); texts=[]
    available=[]
    try: available=pytesseract.get_languages(config='')
    except Exception: pass
    langs='deu+eng' if ('deu' in available and 'eng' in available) else ('deu' if 'deu' in available else ('eng' if 'eng' in available else None))
    extra=(f' -c tessedit_char_whitelist={whitelist}' if whitelist else '')
    for psm in psm_values:
        try:
            cfg=f'--psm {psm}{extra}'
            texts.append(pytesseract.image_to_string(im,lang=langs,config=cfg) if langs else pytesseract.image_to_string(im,config=cfg))
        except Exception: pass
    return '\n'.join(x for x in texts if x)

def _ocr_structure_score(text, kind='id'):
    up=(text or '').upper()
    score=min(len(text or ''),1600)*.012 + len(re.findall(r'[A-ZÄÖÜ]{3,}',up))*1.5
    if kind=='bank':
        if re.search(r'DE(?:\s*\d){20}',up): score+=250
        if 'IBAN' in up: score+=80
        return score
    labels=('NAME','SURNAME','VORNAM','GIVEN NAME','GEBURT','PLACE OF BIRTH','ANSCHRIFT','ADDRESS','ADRESSE','DEUTSCHLAND','PERSONALAUSWEIS')
    score += sum(35 for x in labels if x in up)
    if re.search(r'\b\d{5}\s+[A-ZÄÖÜ][A-ZÄÖÜ .\-]{2,}',up): score+=100
    if 'IDD' in up or 'P<' in up or '<<' in up: score+=110
    if len(re.findall(r'<',up))>=12: score+=80
    return score

def _prepare_label_region(im, target=2200):
    from PIL import ImageOps, ImageEnhance
    g=ImageOps.grayscale(im)
    if g.width<target:
        sc=target/max(1,g.width)
        g=g.resize((int(g.width*sc),int(g.height*sc)),resample=__import__('PIL').Image.Resampling.LANCZOS)
    g=ImageOps.autocontrast(g,cutoff=.10)
    g=ImageEnhance.Contrast(g).enhance(1.05)
    g=ImageEnhance.Sharpness(g).enhance(1.10)
    return g

def _ocr_best_orientation(path, processed_path, kind='id'):
    """V18.3: fixed top-left card crop; back side tests both reader orientations and prefers a plausible address."""
    card,box=_document_crop(path)
    rotations=(-90,90) if card.height>=card.width else (0,180)
    quick=[]
    for deg in rotations:
        oriented=card.rotate(deg,expand=True)
        im=_prepare_ocr_image(oriented,'gray',target=1450)
        text=_ocr_processed(im,(11,))
        quick.append((_ocr_structure_score(text,kind),deg,text))
    _,deg,quick_text=max(quick,key=lambda x:x[0])
    oriented=card.rotate(deg,expand=True)
    name=Path(path).name.lower()
    detail=[]
    # Front side: a whole-card pass works well after the A4 bed has been removed.
    if kind=='id' and not ('hinten' in name or 'back' in name):
        soft=_prepare_ocr_image(oriented,'gray',target=2500)
        full_text=_ocr_processed(soft,(6,11))
        text='\n'.join(x for x in [full_text,quick_text] if x)
    elif kind=='id':
        # Back side: the customer may turn the card in either direction. Test both
        # landscape reader orientations and prefer the one that yields a plausible
        # German address (5-digit PLZ); MRZ remains a secondary signal.
        back_candidates=[]
        for bdeg in (-90,90):
            bo=card.rotate(bdeg,expand=True); w,h=bo.size
            addr=bo.crop((round(w*.34),round(h*.00),w,max(1,round(h*.44))))
            addr_text=_ocr_processed(_prepare_label_region(addr,target=2600),(6,11))
            mrz=bo.crop((0,max(0,round(h*.48)),w,h))
            mrz_text=_ocr_processed(_prepare_ocr_image(mrz,'gray',target=2700),(6,),whitelist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<')
            combined='\n'.join(x for x in [addr_text,mrz_text] if x)
            addr_bonus=500 if re.search(r'\b\d{5}\s+[A-Za-zÄÖÜäöüß]',addr_text) else 0
            street_bonus=120 if re.search(r'[A-Za-zÄÖÜäöüß]{3,}.{0,30}\b\d{1,4}[A-Za-z]?\b',addr_text) else 0
            back_candidates.append((_ocr_structure_score(combined,kind)+addr_bonus+street_bonus,bdeg,combined,bo))
        _,deg,text,oriented=max(back_candidates,key=lambda x:x[0])
        soft=_prepare_ocr_image(oriented,'gray',target=2500)
    else:
        soft=_prepare_ocr_image(oriented,'gray',target=2500)
        w,h=oriented.size
        centre=oriented.crop((0,round(h*.12),w,h))
        detail_text=_ocr_processed(_prepare_ocr_image(centre,'gray',target=2500),(6,11))
        text='\n'.join(x for x in [detail_text,quick_text] if x)
    score=_ocr_structure_score(text,kind)
    try:
        soft.save(processed_path,'JPEG',quality=94)
        previews=_save_ocr_previews(card,deg,Path(processed_path))
    except Exception:
        previews=[]
    return text,deg,box,round(score,1),previews

def _iban_valid(iban):
    iban=re.sub(r'\s+','',iban or '').upper()
    if not re.fullmatch(r'DE\d{20}',iban): return False
    rearr=iban[4:]+iban[:4]
    digits=''.join(str(ord(ch)-55) if ch.isalpha() else ch for ch in rearr)
    rem=0
    for ch in digits: rem=(rem*10+int(ch))%97
    return rem==1

def _clean_iban(text):
    """Extract only a checksum-valid German IBAN from noisy card OCR.

    Card OCR commonly confuses O/0, I/1, L/1, S/5 and B/8. We correct those
    *only inside an IBAN candidate*, never in arbitrary text, and still require
    DE + 20 digits plus MOD-97 before accepting it.
    """
    up=(text or '').upper().replace('\n',' ')
    # Prefer text following an IBAN label, then inspect all DE-looking runs.
    chunks=[]
    for m in re.finditer(r'IBAN\s*[:;|\-]?\s*([^\n]{10,60})', (text or '').upper()):
        chunks.append('DE'+m.group(1) if 'DE' not in m.group(1)[:6] else m.group(1))
    chunks += [m.group(0) for m in re.finditer(r'D[E3][A-Z0-9\s\-]{18,40}',up)]
    trans=str.maketrans({'O':'0','Q':'0','D':'0','I':'1','L':'1','S':'5','B':'8','G':'6','Z':'2'})
    for raw in chunks:
        compact=re.sub(r'[^A-Z0-9]','',raw)
        if compact.startswith('D3'): compact='DE'+compact[2:]
        if not compact.startswith('DE') and compact.startswith('D'):
            compact='DE'+compact[1:]
        if not compact.startswith('DE'): continue
        digits=compact[2:].translate(trans)
        # OCR may have trailing text: test every 20-character numeric window after DE.
        for i in range(0,max(1,len(digits)-19)):
            cand='DE'+digits[i:i+20]
            if _iban_valid(cand): return cand
    # Exact clean fallback.
    compact=re.sub(r'[^A-Z0-9]','',up)
    for m in re.finditer(r'DE[A-Z0-9]{20}',compact):
        cand='DE'+m.group(0)[2:].translate(trans)
        if _iban_valid(cand): return cand
    return ''

def _date_from_text(text):
    m=re.search(r'\b(\d{2})[. /-](\d{2})[. /-](\d{4})\b',text)
    return '.'.join(m.groups()) if m else ''

def _after_label(text, labels):
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    for i,line in enumerate(lines):
        low=line.lower()
        if any(lbl.lower() in low for lbl in labels):
            tail=line
            for lbl in labels:
                pos=low.find(lbl.lower())
                if pos>=0: tail=line[pos+len(lbl):].strip(' :;|-/'); break
            if tail and len(tail)>1: return tail
            if i+1<len(lines): return lines[i+1].strip(' :;|')
    return ''

def _mrz_check(data, digit):
    if not digit or not str(digit).isdigit(): return False
    weights=(7,3,1); total=0
    for i,ch in enumerate(data):
        if ch.isdigit(): v=int(ch)
        elif 'A'<=ch<='Z': v=ord(ch)-55
        elif ch=='<': v=0
        else: return False
        total += v*weights[i%3]
    return total%10 == int(digit)

def _mrz_date(s):
    if not re.fullmatch(r'\d{6}',s or ''): return ''
    yy,mm,dd=int(s[:2]),int(s[2:4]),int(s[4:6])
    # Birth dates in ID documents: choose the plausible past century.
    from datetime import date
    now=date.today(); century=(now.year//100)*100
    year=century+yy
    if year>now.year: year-=100
    try: return f'{dd:02d}.{mm:02d}.{year:04d}'
    except Exception: return ''

def _mrz_candidates(text):
    out=[]
    for raw in text.upper().splitlines():
        u=re.sub(r'[^A-Z0-9<]','',raw)
        if len(u)>=25 and ('<' in u or re.search(r'\d{6}',u)):
            out.append(u)
    return out

def _parse_mrz(text):
    """Conservative ICAO MRZ parsing for name extraction from noisy scanner OCR."""
    lines=_mrz_candidates(text)
    best={'valid':False,'surname':'','given_names':'','birthdate':'','lines':[],'format':''}

    # TD1 / German ID: OCR often reorders the three lines, so identify them by shape
    # rather than requiring adjacency in the raw OCR output.
    doc_lines=[x for x in lines if len(x)>=25 and (x.startswith('ID') or x.startswith('I<') or x.startswith('AC'))]
    data_lines=[x for x in lines if len(x)>=25 and re.match(r'^\d{6}[0-9A-Z]<\d{6}',x)]
    name_lines=[]
    for x in lines:
        if '<<' not in x or x.startswith('P<') or x.startswith('ID'): continue
        if sum(ch.isdigit() for ch in x)>2: continue
        parts=x.split('<<',1)
        left=re.sub(r'[^A-Z<]','',parts[0])
        right=re.sub(r'[^A-Z<]','',parts[1]) if len(parts)>1 else ''
        if len(left)>=2 and len(re.sub(r'<','',right))>=2:
            name_lines.append(x)
    if name_lines:
        # Prefer a line near standard TD1 length and with the most alphabetic content.
        c=max(name_lines,key=lambda x:(-abs(len(x)-30),sum(ch.isalpha() for ch in x)))
        cc=c[:30].ljust(30,'<')
        parts=cc.split('<<',1)
        sur=' '.join(t for t in re.sub(r'<+',' ',parts[0]).split() if len(t)>=2)
        giv=' '.join(t for t in re.sub(r'<+',' ',parts[1]).split() if len(t)>=2) if len(parts)>1 else ''
        birth=''; birth_ok=False
        if data_lines:
            b=data_lines[0][:30].ljust(30,'<')
            birth=b[:6]
            birth_ok=_mrz_check(birth,b[6]) if len(b)>6 else False
        if sur and giv:
            best={'valid':True,'surname':sur.title(),'given_names':giv.title(),
                  'birthdate':_mrz_date(birth) if birth_ok else '',
                  'lines':([doc_lines[0]] if doc_lines else [])+([data_lines[0]] if data_lines else [])+[cc],
                  'format':'TD1','score':7 if birth_ok else 5}

    # TD3 passport: line 1 starts P< and contains the name; line 2 holds dates.
    for a in [x for x in lines if x.startswith('P<') and len(x)>=40]:
        aa=a[:44].ljust(44,'<')
        name=aa[5:]; parts=name.split('<<',1)
        sur=re.sub(r'<+',' ',parts[0]).strip(); giv=re.sub(r'<+',' ',parts[1]).strip() if len(parts)>1 else ''
        for b in [x for x in lines if len(x)>=40 and x is not a]:
            bb=b[:44].ljust(44,'<')
            birth=bb[13:19]; birth_ok=_mrz_check(birth,bb[19]) if len(bb)>19 else False
            cand={'valid':bool(sur and giv),'surname':sur.title(),'given_names':giv.title(),
                  'birthdate':_mrz_date(birth) if birth_ok else '',
                  'lines':[aa,bb],'format':'TD3','score':7 if birth_ok else 4}
            if cand['valid'] and cand['score']>best.get('score',-1): best=cand
    return best

def _mrz_names(text):
    m=_parse_mrz(text)
    return m.get('surname',''),m.get('given_names','')

def _focused_identity_fields(front_text, back_text):
    """Return only the five office-critical identity fields.

    Front: surname / given names. Back: German residence address. MRZ is used as a
    strong secondary source for names. Unsupported international layouts stay empty
    rather than inventing data.
    """
    out={'customer':'','first_name':'','address':'','postal':'','city':''}
    mrz=_parse_mrz((back_text or '')+'\n'+(front_text or ''))
    if mrz.get('surname'): out['customer']=mrz['surname']
    if mrz.get('given_names'): out['first_name']=mrz['given_names']
    if not out['customer']:
        out['customer']=_after_label(front_text,['Familienname','Name/Surname/Nom','Surname','Nom','Name'])
    if not out['first_name']:
        out['first_name']=_after_label(front_text,['Vornamen','Given names','Given name','Prénoms','Vorname'])

    lines=[re.sub(r'\s+',' ',x).strip(' |:;') for x in (back_text or '').splitlines() if x.strip()]
    for i,line in enumerate(lines):
        m=re.search(r'\b(\d{5})\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .\-]{1,45})\b',line)
        if not m: continue
        city=m.group(2).strip(' .,:;')
        city=re.sub(r'\b(?:ANSCHRIFT|ADDRESS|ADRESSE)\b.*$','',city,flags=re.I).strip(' .,:;')
        if '<' in city or len(re.sub(r'[^A-Za-zÄÖÜäöüß]','',city))<2: continue
        street=''
        # On German IDs the street is normally the next line after PLZ/city. Search
        # both directions because OCR can reorder blocks.
        order=list(range(i+1,min(len(lines),i+4)))+list(range(i-1,max(-1,i-4),-1))
        for j in order:
            cand=lines[j]
            if '<' in cand or re.search(r'\b\d{5}\b',cand): continue
            if not re.search(r'\b\d{1,4}\s*[A-Za-z]?\b',cand): continue
            cand=re.sub(r'^(Anschrift|Address|Adresse)\s*[:\-]?\s*','',cand,flags=re.I)
            cand=re.sub(r'\bSTRABE\b','STRASSE',cand,flags=re.I)
            cand=re.sub(r'\bSTRASSE\s+(\d)',r'STRASSE \1',cand,flags=re.I)
            # Keep plausible street text only.
            if 4<=len(cand)<=65 and len(re.sub(r'[^A-Za-zÄÖÜäöüß]','',cand))>=3:
                street=cand.strip(' .,:;'); break
        out.update({'postal':m.group(1),'city':city,'address':street})
        break
    return out

def _pretty_person_text(value):
    """Conservative display casing for OCR person/place text."""
    value=re.sub(r'\s+',' ',value or '').strip(' :;|')
    if not value: return ''
    parts=[]
    particles={'von','van','de','der','den','zu','zur','zum','am','an','im'}
    for i,w in enumerate(value.split(' ')):
        if not w: continue
        # Preserve hyphenated names while normalizing all-uppercase OCR.
        bits=w.split('-')
        bits=[(b[:1].upper()+b[1:].lower()) if b else b for b in bits]
        nw='-'.join(bits)
        if i>0 and nw.lower() in particles: nw=nw.lower()
        parts.append(nw)
    return ' '.join(parts)

def _pretty_street(value):
    """Clean harmless OCR prefixes and format a German street for review."""
    value=re.sub(r'\s+',' ',value or '').strip()
    # OCR can prepend punctuation / fragments before the real street. A German street
    # must start with a letter; discard everything before the first letter.
    value=re.sub(r'^[^A-Za-zÄÖÜäöüß]+','',value).strip(' :;|,.-_')
    if not value: return ''
    # Typical scanner artefact seen before an otherwise clean uppercase street,
    # e.g. "pen WILLIBRORDUSSTRASSE 60". Only drop a very short lower-case token
    # when the following token is clearly an uppercase street word.
    value=re.sub(r'^[a-zäöüß]{1,4}\s+(?=[A-ZÄÖÜ]{5,}(?:STRASSE|STRAẞE|WEG|PLATZ|ALLEE|RING|GASSE|DAMM|UFER|MARKT)\b)','',value)
    value=re.sub(r'\bSTRABE\b','STRASSE',value,flags=re.I)
    # OCR from German IDs commonly prints STRASSE in capitals; present it naturally.
    words=[]
    for w in value.split(' '):
        if re.fullmatch(r'\d+[A-Za-z]?',w):
            words.append(w.upper() if w[-1:].isalpha() else w); continue
        bits=w.split('-')
        bits=[(b[:1].upper()+b[1:].lower()) if b else b for b in bits]
        words.append('-'.join(bits))
    value=' '.join(words)
    value=re.sub(r'(?<!-)Strasse\b','straße',value,flags=re.I)
    value=re.sub(r'-Strasse\b','-Straße',value,flags=re.I)
    return value

def _pretty_ocr_fields(result):
    result['customer']=_pretty_person_text(result.get('customer',''))
    result['first_name']=_pretty_person_text(result.get('first_name',''))
    result['city']=_pretty_person_text(result.get('city',''))
    result['address']=_pretty_street(result.get('address',''))
    return result

def _ocr_bank_card(path, processed_path):
    """Targeted bank-card OCR: fixed top-left crop, all reader orientations, IBAN first."""
    card,box=_document_crop(path)
    candidates=[]
    for deg in (0,90,-90,180):
        oriented=card.rotate(deg,expand=True)
        # Whole card + two contrast variants. IBAN is usually small and widely spaced.
        gray=_prepare_ocr_image(oriented,'gray',target=3200)
        binary=_prepare_ocr_image(oriented,'binary',target=3200)
        txt='\n'.join(x for x in [_ocr_processed(gray,(6,11,12)),_ocr_processed(binary,(6,11))] if x)
        iban=_clean_iban(txt)
        score=_ocr_structure_score(txt,'bank') + (1000 if iban else 0)
        candidates.append((score,deg,txt,iban,gray))
    score,deg,text,iban,gray=max(candidates,key=lambda x:x[0])
    try:
        gray.save(processed_path,'JPEG',quality=94)
        previews=_save_ocr_previews(card,deg,Path(processed_path))
    except Exception:
        previews=[]
    return text,deg,box,round(score,1),previews

def _bank_holder_from_text(text):
    """Conservative holder extraction. Return blank rather than invent a name."""
    lines=[re.sub(r'\s+',' ',x).strip(' :;|') for x in (text or '').splitlines() if x.strip()]
    labels=('KONTOINHABER','KARTENINHABER','CARDHOLDER','CARD HOLDER','INHABER')
    for i,line in enumerate(lines):
        up=line.upper()
        for label in labels:
            pos=up.find(label)
            if pos>=0:
                tail=line[pos+len(label):].strip(' :;|-')
                cand=tail or (lines[i+1] if i+1<len(lines) else '')
                if re.fullmatch(r"[A-Za-zÄÖÜäöüß .'-]{3,50}",cand) and not any(x in cand.upper() for x in ('IBAN','BANK','DEBIT','VISA','MASTERCARD')):
                    return _pretty_person_text(cand)
    return ''

def recognize_scan(kind):
    import time
    t0=time.perf_counter(); p=scan_dir()
    paths=[p/'Ausweis-Vorne.jpg',p/'Ausweis-Hinten.jpg'] if kind=='id' else [p/'Bank.jpg']
    paths=[x for x in paths if x.exists()]
    if not paths: raise RuntimeError('Kein passender Scan gefunden. Bitte zuerst im Zulassungsassistenten scannen.')
    texts=[]; processed=[]; rotations=[]; crops=[]; scores=[]; preview_files=[]
    for x in paths:
        op=p/('OCR-'+x.name)
        txt,rot,box,score,prev=(_ocr_bank_card(x,op) if kind=='bank' else _ocr_best_orientation(x,op,kind))
        texts.append(txt); processed.append(op.name if op.exists() else '')
        rotations.append(rot); crops.append(box); scores.append(score); preview_files.append(prev)
    text='\n'.join(texts)
    result={'raw':text,'processed':processed,'scan_files':[x.name for x in paths],
            'ocr_ok':bool(text.strip()),'iban':_clean_iban(text),'iban_valid':False,
            'birthdate':'','first_name':'','customer':'','birthplace':'','address':'','postal':'','city':'','account_holder':'',
            'rotations':rotations,'crop_boxes':crops,'ocr_scores':scores,'preview_files':preview_files,'mrz_found':False,'mrz_valid':False,'mrz_format':'','mrz_lines':[],'field_sources':{},'duration_ms':0,'calibrated':False,'scan_mode':'Feste Position oben links'}
    result['iban_valid']=_iban_valid(result['iban']) if result['iban'] else False
    if kind=='id':
        front_text=texts[0] if texts else ''
        back_text=texts[1] if len(texts)>1 else ''
        focused=_focused_identity_fields(front_text,back_text)
        for fk,fv in focused.items():
            if fv:
                result[fk]=fv; result['field_sources'][fk]='MRZ/OCR gezielt'
        mrz=_parse_mrz(text)
        result['mrz_found']=bool(mrz.get('lines'))
        result['mrz_valid']=bool(mrz.get('valid'))
        result['mrz_format']=mrz.get('format','')
        result['mrz_lines']=mrz.get('lines',[])
        # MRZ wins for empty fields only; never overwrite a stronger targeted value.
        if not result['customer']:
            if mrz.get('surname'):
                result['customer']=mrz['surname']; result['field_sources']['customer']='MRZ'
            else:
                result['customer']=_after_label(text,['Name/Surname/Nom','Familienname','Surname','Nom']); result['field_sources']['customer']='OCR' if result['customer'] else ''
        if not result['first_name']:
            if mrz.get('given_names'):
                result['first_name']=mrz['given_names']; result['field_sources']['first_name']='MRZ'
            else:
                result['first_name']=_after_label(text,['Vornamen/Given names/Prénoms','Given names','Vornamen','Given name','Prénoms']); result['field_sources']['first_name']='OCR' if result['first_name'] else ''
        result['birthplace']=_after_label(text,['Geburtsort/Place of birth','Place of birth','Geburtsort','Lieu de naissance'])
        if result['birthplace']: result['field_sources']['birthplace']='OCR'
        if mrz.get('birthdate'):
            result['birthdate']=mrz['birthdate']; result['field_sources']['birthdate']='MRZ geprüft'
        else:
            dm=re.search(r'(?:Geburtsdatum|Date of birth|Date de naissance)[^0-9]{0,40}(\d{2}[. /-]\d{2}[. /-]\d{4})',text,re.I)
            result['birthdate']=dm.group(1).replace('/','.').replace('-','.') if dm else _date_from_text(text)
            if result['birthdate']: result['field_sources']['birthdate']='OCR'
        lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
        for i,line in enumerate(lines):
            m=re.search(r'\b(\d{5})\s+([A-Za-zÄÖÜäöüß .-]{2,40})',line)
            if m:
                if not result['postal']: result['postal']=m.group(1)
                if not result['city']: result['city']=m.group(2).strip(' .,:;')
                for cand in lines[max(0,i-2):min(len(lines),i+3)]:
                    if re.search(r'\b\d{1,4}[A-Za-z]?\b',cand) and not re.search(r'\d{2}[.]\d{2}[.]\d{4}',cand) and cand!=line:
                        if not result['address']: result['address']=cand.strip()
                        break
                break
        mrz_sur,mrz_given=_mrz_names(text)
        if not result['customer'] and mrz_sur: result['customer']=mrz_sur
        if not result['first_name'] and mrz_given: result['first_name']=mrz_given
        if result['address']:
            result['address']=re.sub(r'STRABE\b','STRASSE',result['address'],flags=re.I)
    else:
        # Bank card: only checksum-valid German IBANs are accepted. Holder is optional.
        result['account_holder']=_bank_holder_from_text(text)
        if result['account_holder']: result['field_sources']['account_holder']='OCR gezielt'
        if result['iban']: result['field_sources']['iban']='DE-IBAN + MOD-97 geprüft'
    # Never offer field labels / OCR fragments as customer names.
    bad_name_tokens=('GIVEN NAMES','PRÉNOMS','PRENOMS','SURNAME','FAMILIENNAME','VORNAMEN','PERSONALAUSWEIS')
    for nk in ('customer','first_name'):
        val=(result.get(nk) or '').strip()
        up=val.upper()
        if any(t in up for t in bad_name_tokens) or len(val)>45 or len(re.sub(r'[^A-Za-zÄÖÜäöüß]','',val))<2:
            result[nk]=''; result['field_sources'].pop(nk,None)
    for k in ('customer','first_name','birthplace','city','address','account_holder'):
        result[k]=re.sub(r'\s+',' ',result.get(k,'')).strip(' :;|')
    if kind=='id': _pretty_ocr_fields(result)
    result['duration_ms']=int((time.perf_counter()-t0)*1000)
    return result

def _safe_folder_name(name,first_name=''):
    raw=f"{(name or '').strip()}_{(first_name or '').strip()}".strip('_')
    return re.sub(r'[<>:"/\\|?*]','',raw) or 'Unbekannt'

def _customer_folder(customer,first_name):
    return DATA/'Kundenunterlagen'/_safe_folder_name(customer,first_name)

CUSTOMER_DOC_LABELS={'Ausweis-Vorne.jpg':'Personalausweis Vorderseite','Ausweis-Hinten.jpg':'Personalausweis Rückseite','Ausweis-A4.jpg':'Ausweis / Reisepass (A4-Scan)','Zusatzdokument.jpg':'Meldebescheinigung / Firmenunterlage','Handelsregisterauszug.jpg':'Handelsregisterauszug','Gewerbeanmeldung.jpg':'Gewerbeanmeldung'}

def customer_documents(customer,first_name):
    d=_customer_folder(customer,first_name)
    if not d.exists(): return []
    return [{'file':f.name,'label':CUSTOMER_DOC_LABELS.get(f.name,f.name)} for f in sorted(d.iterdir()) if f.is_file() and f.suffix.lower() in ('.jpg','.jpeg','.png')]

def attach_pending_scans(jid,customer='',first_name=''):
    pending=scan_dir(); dest=DATA/f'Auftrag_{jid:05d}'/'Scans'; dest.mkdir(parents=True,exist_ok=True)
    mapping={'Ausweis-Vorne.jpg':'Ausweis-Vorne.jpg','Ausweis-Hinten.jpg':'Ausweis-Hinten.jpg','Ausweis-A4.jpg':'Ausweis-A4.jpg','Bank.jpg':'Bank.jpg','Zusatzdokument.jpg':'Zusatzdokument.jpg','Steuerzahler-Ausweis-Vorne.jpg':'Steuerzahler-Ausweis-Vorne.jpg','Steuerzahler-Ausweis-Hinten.jpg':'Steuerzahler-Ausweis-Hinten.jpg','Handelsregisterauszug.jpg':'Handelsregisterauszug.jpg','Gewerbeanmeldung.jpg':'Gewerbeanmeldung.jpg'}
    persist=('Ausweis-Vorne.jpg','Ausweis-Hinten.jpg','Ausweis-A4.jpg','Zusatzdokument.jpg','Handelsregisterauszug.jpg','Gewerbeanmeldung.jpg')
    cust_dir=_customer_folder(customer,first_name) if ((customer or '').strip() or (first_name or '').strip()) else None
    copied=[]
    for a,b in mapping.items():
        src=pending/a
        if src.exists():
            shutil.copy2(src,dest/b); copied.append(b)
            if cust_dir and a in persist:
                cust_dir.mkdir(parents=True,exist_ok=True); shutil.copy2(src,cust_dir/b)
    # Temporary scans belong to exactly one customer. Remove them after successful copy.
    clear_pending_scans()
    return copied

DOCUMENT_LIBRARY = [
 {'id':'vollmacht','title':'Vollmacht','file':'Vollmacht.pdf','kind':'Standardformular'},
 {'id':'sepa','title':'SEPA-Lastschriftmandat','file':'SEPA.pdf','kind':'Standardformular'},
 {'id':'laufzettel','title':'SERVICE POINT Laufzettel','file':'Laufzettel.pdf','kind':'Intern'},
 {'id':'verlust_zbi','title':'Verlust Fahrzeugschein / ZB I','file':'Verlust_Fahrzeugschein.pdf','kind':'Sonderformular'},
 {'id':'verlust_kz','title':'Kennzeichen-Verlustanzeige','file':'Verlust_Kennzeichen.pdf','kind':'Sonderformular'},
 {'id':'kurzzeit','title':'Empfangsbevollmächtigter Kurzzeitkennzeichen','file':'Kurzzeitkennzeichen.pdf','kind':'Sonderformular'},
 {'id':'gbr','title':'Haftungserklärung GbR','file':'Haftungserklaerung.pdf','kind':'Sonderformular'},
 {'id':'ust_eu','title':'Mitteilung für Umsatzsteuerzwecke / EU-Neufahrzeug','file':'Mitteilung_Umsatzsteuerzwecke.pdf','kind':'Sonderformular'},
 {'id':'kz_abtritt','title':'Abtrittserklärung Kennzeichen','file':'Abtrittserklaerung_Kennzeichen.pdf','kind':'Sonderformular'},
 {'id':'ausland_kz','title':'Verbleib ausländischer Kennzeichen','file':'Verbleib_auslaendische_Kennzeichen.pdf','kind':'Sonderformular'},
 {'id':'erhalt','title':'Bestätigung Erhalt Fahrzeugpapiere','file':'Erhalt_Fahrzeugpapiere.pdf','kind':'Kundendokument'},
 {'id':'online_zul_fehler','title':'Fehlgeschlagene Online-Zulassung','file':'Fehlgeschlagene_Online_Zulassung.pdf','kind':'Sonderformular'},
 {'id':'online_ab_fehler','title':'Fehlgeschlagene Online-Abmeldung','file':'Fehlgeschlagene_Online_Abmeldung.pdf','kind':'Sonderformular'},
 {'id':'kaufvertrag','title':'KFZ-Kaufvertrag - neutral','file':'KFZ_Kaufvertrag_neutral.pdf','kind':'Kauf / Verkauf'},
 {'id':'veraeusserung','title':'Veräußerungsanzeige / Empfangsbestätigung','file':'Veräusserungsanzeige_RKN.pdf','kind':'Kauf / Verkauf'},
]

def relevant_documents(process, plate_transfer=''):
    p=(process or '').lower(); ids=['laufzettel']
    no_tax = any(x in p for x in ['außerbetrieb','abmeldung','online-abmeldung','kauf / verkauf','kauf/verkauf','ersatzausstellung','kennzeichenverlust','änderung fahrzeugtechnik','änderung halterdaten','kurzzeit'])
    if not any(x in p for x in ['kauf / verkauf','kauf/verkauf']): ids += ['vollmacht']
    if not no_tax: ids += ['sepa']
    if 'ersatz' in p and ('zb i' in p or 'zbi' in p): ids += ['verlust_zbi']
    if 'kennzeichenverlust' in p or 'kennzeichen-verlust' in p: ids += ['verlust_kz']
    if 'kurzzeit' in p: ids += ['kurzzeit']
    if 'online-zulassung fehlgeschlagen' in p: ids += ['online_zul_fehler']
    if 'online-abmeldung fehlgeschlagen' in p: ids += ['online_ab_fehler']
    if 'kauf / verkauf' in p or 'kauf/verkauf' in p: ids += ['kaufvertrag','veraeusserung']
    if str(plate_transfer or '').lower()=='ja': ids += ['kz_abtritt']
    ids += ['erhalt']
    seen=set(); return [x for x in DOCUMENT_LIBRARY if x['id'] in ids and not (x['id'] in seen or seen.add(x['id']))]

def job_documents(jid):
    c=db(); r=c.execute('SELECT process,plate_transfer FROM jobs WHERE id=?',(jid,)).fetchone(); c.close()
    if not r:return []
    return relevant_documents(r['process'],r['plate_transfer'])

def fill_pdfs(jid):
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
    except ImportError: raise RuntimeError('pypdf/reportlab fehlt. Bitte INSTALLIEREN.bat ausführen.')
    from io import BytesIO
    c=db(); r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone(); c.close()
    if not r: raise RuntimeError('Auftrag nicht gefunden')
    d=dict(r); out=DATA/f"Auftrag_{jid:05d}"; out.mkdir(exist_ok=True)
    full=(d.get('customer') or '').strip(); first=(d.get('first_name') or '').strip()
    addr=' '.join(x for x in [d.get('address',''),d.get('postal',''),d.get('city','')] if x).strip()
    today=datetime.now().strftime('%d.%m.%Y'); plate=d.get('plate') or d.get('desired_plate','')
    maps=[('Vollmacht.pdf',{'halter_name':full,'halter_vorname':first,'geburtsdatum':d.get('birthdate',''),'geburtsort':d.get('birthplace',''),'geburtsname':d.get('birthname',''),'anschrift':addr,'telefon':d.get('mobile',''),'hersteller_typ':d.get('manufacturer',''),'zb2_nr':d.get('zb2',''),'fin':d.get('fin',''),'kennzeichen':d.get('plate',''),'wunschkennzeichen':d.get('desired_plate',''),'evb_referenz':d.get('evb',''),'ort_datum':f"{d.get('city','')}, {today}"}),
    ('SEPA.pdf',{'kontoinhaber':d.get('account_holder') or (first+' '+full).strip(),'strasse_hausnr':(d.get('taxpayer_address') if d.get('account_holder_same_taxpayer','Ja')=='Ja' and d.get('taxpayer_same_holder','Ja')!='Ja' else d.get('address','')),'plz':(d.get('taxpayer_postal') if d.get('account_holder_same_taxpayer','Ja')=='Ja' and d.get('taxpayer_same_holder','Ja')!='Ja' else d.get('postal','')),'ort':(d.get('taxpayer_city') if d.get('account_holder_same_taxpayer','Ja')=='Ja' and d.get('taxpayer_same_holder','Ja')!='Ja' else d.get('city','')),'land':d.get('country') or 'Deutschland','iban':d.get('iban',''),'bic_bank':d.get('bic_bank',''),'ort_unterschrift':d.get('city',''),'datum_unterschrift':today,'halter_name':(first+' '+full).strip(),'amtliches_kennzeichen':plate})]
    if d.get('need_gbr')=='Ja':
        maps.append(('Haftungserklaerung.pdf',{'BezeichnungGbR':full,'Verantwortlich':(first+' '+full).strip(),'kennzeichen':plate,'fin':d.get('fin',''),'hersteller':d.get('manufacturer',''),'name':full,'vorname':first,'hausnr':d.get('address',''),'ort':d.get('city',''),'gesellschafter.eins.datum':today},{'name','vorname','hausnr','ort'}))
    if d.get('need_kurzzeit')=='Ja':
        maps.append(('Kurzzeitkennzeichen.pdf',{'Firma':full,'Name':(first+' '+full).strip(),'Strasse':d.get('address',''),'Kurzzeitkennzeichen':plate,'Ort-Datum':f"{d.get('city','')}, {today}"},set()))
    if d.get('need_ausland_kz')=='Ja':
        maps.append(('Verbleib_auslaendische_Kennzeichen.pdf',{'name':full,'vorname':first,'anschrift':addr,'kennzeichen':plate,'fin':d.get('fin',''),'ort':d.get('city',''),'datum':today},set()))
    if d.get('need_erhalt')=='Ja':
        maps.append(('Erhalt_Fahrzeugpapiere.pdf',{'kunde':(first+' '+full).strip(),'anschrift':addr,'erhaltsdatum':today,'zb2_nummer':d.get('zb2',''),'fin':d.get('fin',''),'kennzeichen':plate,'ort':d.get('city',''),'datum':today},set()))
    files=[]
    for entry in maps:
        fn,fields=entry[0],entry[1]; firstonly=entry[2] if len(entry)>2 else set(); seen_first=set()
        reader=PdfReader(BASE/'templates'/fn)
        for page in reader.pages:
            packet=BytesIO(); cv=canvas.Canvas(packet,pagesize=(float(page.mediabox.width),float(page.mediabox.height)))
            for ref in page.get('/Annots',[]):
                a=ref.get_object(); name=str(a.get('/T') or ''); rect=a.get('/Rect')
                if name in firstonly:
                    if name in seen_first:
                        continue
                    seen_first.add(name)
                if rect and 'unterschrift' in name.lower() and name not in fields:
                    # In den vorbereiteten Templates liegen unter einigen leeren
                    # Signatur-Widgets technische X-Platzhalter. Diese muessen in
                    # der flachen Druck-PDF sicher abgedeckt bleiben.
                    x1,y1,x2,y2=[float(v) for v in rect]
                    cv.setFillColorRGB(1,1,1); cv.rect(x1,y1,x2-x1,y2-y1,stroke=0,fill=1); cv.setFillColorRGB(0,0,0)
                if name in fields and fields[name] and rect:
                    x1,y1,x2,y2=[float(v) for v in rect]; size=9
                    cv.setFont('Helvetica',size); cv.drawString(x1+2,y2-size-1,str(fields[name])[:100])
            cv.save(); packet.seek(0); ov=PdfReader(packet)
            if ov.pages: page.merge_page(ov.pages[0])
            # Wichtig: Die leeren AcroForm-Widgets liegen in Browsern/Readern
            # ueber dem gestempelten Text und koennen ihn unsichtbar machen.
            # Fuer Vorschau und Druck erzeugen wir deshalb eine echte, flache PDF.
            if '/Annots' in page:
                del page['/Annots']
        dest=out/(fn.replace('.pdf',f'_Auftrag_{jid:05d}.pdf')); writer=PdfWriter()
        for pg in reader.pages: writer.add_page(pg)
        with open(dest,'wb') as f: writer.write(f)
        files.append(dest.name)
    return str(out),files


def get_lauf_options(jid):
    c=db(); row=c.execute('SELECT data FROM laufzettel_options WHERE job_id=?',(jid,)).fetchone(); c.close()
    if row:
        try:return json.loads(row['data'])
        except:return {}
    c=db(); r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone(); c.close()
    if not r:return {}
    d=dict(r); proc=(d.get('process') or '').lower(); signs=(d.get('signs') or '').lower(); vt=(d.get('vehicle_type') or '').lower()
    return {
      'name':' '.join(x for x in [d.get('first_name',''),d.get('customer','')] if x).strip(), 'mobile':d.get('mobile',''),
      'date':datetime.now().strftime('%d.%m.%Y'),'invoice':'','evb':d.get('evb',''),'desired_plate':d.get('desired_plate',''),
      'sign_count':'','sign_size':d.get('sign_size',''),'season':'','other_service':'','other_docs':'','other_vehicle':'',
      'neuzulassung':'neu' in proc,'zulassung':('zulassung' in proc and 'neu' not in proc and 'online' not in proc),'umschreibung':'ummeld' in proc or 'umschreib' in proc,
      'ausserbetrieb':'abmeld' in proc or 'außerbetrieb' in proc,'aenderung_technik':'eintragung' in proc or 'fahrzeugtechnik' in proc,'aenderung_halter':'adress' in proc or 'halterdaten' in proc,
      'ersatz_zbi':'ersatz' in proc,'ausfuhr':'ausfuhr' in proc,'kurzzeit':'kurzzeit' in proc,'saison':'saison' in proc,'online':'online' in proc,
      'wunsch':bool(d.get('desired_plate')),'kz_uebernahme':(d.get('plate_transfer') or '').lower()=='ja','feinstaub':False,'plakette100':False,
      'zbii':False,'zbi':False,'tuev':False,'evb_doc':bool(d.get('evb')),'evb_von_uns':False,'pkw':'pkw' in vt,'motorrad':'motorrad' in vt,'anhaenger':'anhänger' in vt or 'anhaenger' in vt,
      'sonstige_kfz':bool(vt and not any(x in vt for x in ['pkw','motorrad','anhänger','anhaenger'])),'schild_neu':'neu' in signs,'schild_spezial':False,'schild_vorhanden':'vorhanden' in signs or 'bleiben' in signs,'kein_schild':'keine' in signs
    }

def save_lauf_options(jid,data):
    c=db(); c.execute('INSERT INTO laufzettel_options(job_id,data) VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET data=excluded.data',(jid,json.dumps(data,ensure_ascii=False))); c.commit(); c.close()

def create_laufzettel(jid, options=None):
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
    except ImportError: raise RuntimeError('pypdf/reportlab fehlt. Bitte INSTALLIEREN.bat ausführen.')
    from io import BytesIO
    c=db(); r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone(); c.close()
    if not r: raise RuntimeError('Auftrag nicht gefunden')
    o=options or get_lauf_options(jid); out=DATA/f"Auftrag_{jid:05d}"; out.mkdir(exist_ok=True)
    reader=PdfReader(BASE/'templates'/'Laufzettel.pdf')

    # Die Positionen werden direkt aus den echten Formularfeldern des neuen
    # Laufzettels gelesen. Keine handgeschätzten X/Y-Koordinaten mehr.
    textvals={
      'kunde':o.get('name',''),'mobil':o.get('mobile',''),'datum':o.get('date',''),
      'kennzeichen':o.get('desired_plate',''),'evb':o.get('evb',''),'rechnung':o.get('invoice',''),
      'sonstige_unterlagen':o.get('other_docs',''),'schild_anzahl':o.get('sign_count',''),
      'schild_mass':o.get('sign_size',''),'besonderheiten':o.get('special_notes',''),'notizen':o.get('notes','')
    }
    checks={
      'dl_neu':'neuzulassung','dl_zul':'zulassung','dl_um':'umschreibung','dl_ab':'ausserbetrieb',
      'dl_tech':'aenderung_technik','dl_halter':'aenderung_halter','dl_ersatz':'ersatz_zbi','dl_ausfuhr':'ausfuhr',
      'dl_kurz':'kurzzeit','dl_saison':'saison','dl_online':'online','dl_wunsch':'wunsch','dl_ueber':'kz_uebernahme',
      'dl_fein':'feinstaub','dl_100':'plakette100','u_zb2':'zbii','u_zb1':'zbi','u_hu':'tuev','u_evb':'evb_doc',
      'u_evbuns':'evb_von_uns','u_ausweis':'ausweis','u_sepa':'sepa_mandat','u_vollmacht':'vollmacht',
      'k_pkw':'pkw','k_moto':'motorrad','k_anhaenger':'anhaenger','k_sonst':'sonstige_kfz','s_neu':'schild_neu',
      's_vorh':'schild_vorhanden','s_keine':'kein_schild','s_spez':'schild_spezial',
      'intern_vollstaendig':'intern_vollstaendig','intern_rueckfrage':'intern_rueckfrage','intern_stva':'intern_stva'
    }
    page=reader.pages[0]; packet=BytesIO(); cv=canvas.Canvas(packet,pagesize=(float(page.mediabox.width),float(page.mediabox.height)))
    for ref in page.get('/Annots',[]):
        a=ref.get_object(); name=str(a.get('/T') or ''); rect=a.get('/Rect')
        if not name or not rect: continue
        x1,y1,x2,y2=[float(v) for v in rect]
        # Formularrahmen statisch zeichnen, damit die finale PDF nach dem
        # Flatten genauso aussieht, aber keine leeren Widgets mehr darueberliegen.
        cv.setLineWidth(0.6); cv.rect(x1,y1,x2-x1,y2-y1,stroke=1,fill=0)
        if name in textvals and textvals[name]:
            val=str(textvals[name]); size=9
            if name in ('sonstige_unterlagen','besonderheiten','notizen'): size=8
            cv.setFont('Helvetica',size); cv.drawString(x1+3, y2-size-2, val[:120])
        elif name in checks and o.get(checks[name]):
            cv.setFont('Helvetica-Bold',10); cv.drawCentredString((x1+x2)/2, y1+2, 'X')
    cv.save(); packet.seek(0); overlay=PdfReader(packet); page.merge_page(overlay.pages[0])
    if '/Annots' in page:
        del page['/Annots']
    dest=out/f'Laufzettel_Auftrag_{jid:05d}.pdf'; writer=PdfWriter()
    for pg in reader.pages: writer.add_page(pg)
    with open(dest,'wb') as f: writer.write(f)
    return dest

def _image_to_a4_pdf(img_path,pdf_path):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    W,H=A4; im=Image.open(img_path); iw,ih=im.size
    scale=min(W/iw,H/ih); dw,dh=iw*scale,ih*scale
    cv=canvas.Canvas(str(pdf_path),pagesize=A4); cv.drawImage(ImageReader(im),(W-dw)/2,(H-dh)/2,dw,dh,preserveAspectRatio=True); cv.save()
    return pdf_path

def create_print_package(jid, selected=None):
    from pypdf import PdfReader, PdfWriter
    selected=set(selected or ['id','bank','extra','lauf','vollmacht','sepa'])
    folder=DATA/f'Auftrag_{jid:05d}'; folder.mkdir(exist_ok=True)
    scans=folder/'Scans'; w=PdfWriter(); added=[]
    def add_pdf(path,label):
        if path and Path(path).exists():
            for page in PdfReader(path).pages: w.add_page(page)
            added.append(label)
    if 'id' in selected:
        p=scans/'Ausweis-A4.jpg'
        if p.exists(): add_pdf(_image_to_a4_pdf(p,folder/'_Ausweiskopie.pdf'),'Ausweiskopie')
    if 'bank' in selected:
        p=scans/'Bank.jpg'
        if p.exists(): add_pdf(_image_to_a4_pdf(p,folder/'_Bankkopie.pdf'),'Bankkopie')
    if 'extra' in selected:
        p=scans/'Zusatzdokument.jpg'
        if p.exists(): add_pdf(_image_to_a4_pdf(p,folder/'_Zusatzdokument.pdf'),'Zusatzdokument')
    if 'lauf' in selected: add_pdf(create_laufzettel(jid),'Laufzettel')
    pdf_folder,files=fill_pdfs(jid); pdf_folder=Path(pdf_folder)
    if 'vollmacht' in selected: add_pdf(next(pdf_folder.glob('Vollmacht_Auftrag_*.pdf'),None),'Vollmacht')
    if 'sepa' in selected: add_pdf(next(pdf_folder.glob('SEPA_Auftrag_*.pdf'),None),'SEPA')
    if not added: raise RuntimeError('Keine ausgewählten Dokumente sind vorhanden.')
    dest=folder/f'DRUCKPAKET_Auftrag_{jid:05d}.pdf'
    with open(dest,'wb') as f:w.write(f)
    return dest

STATIC=BASE/'static'
STATIC_TYPES={'.css':'text/css; charset=utf-8','.js':'application/javascript; charset=utf-8','.html':'text/html; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.svg':'image/svg+xml'}
class H(BaseHTTPRequestHandler):
    def sendj(self,obj,code=200):
        b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
    def serve_static(self,rel):
        target=(STATIC/rel).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            raise RuntimeError('Datei nicht gefunden.')
        b=target.read_bytes(); ct=STATIC_TYPES.get(target.suffix.lower(),'application/octet-stream')
        self.send_response(200); self.send_header('Content-Type',ct); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u=urllib.parse.urlparse(self.path)
        try:
            if u.path=='/':
                b=(STATIC/'index.html').read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path.startswith('/static/'):
                self.serve_static(u.path[len('/static/'):])
            elif u.path=='/brand-hero':
                b=(BASE/'service-point-hero.jpg').read_bytes(); self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Cache-Control','no-cache'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path in ('/matrix-stva-hero','/matrix-login'):
                b=(BASE/'service-point-hero.jpg').read_bytes(); self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Cache-Control','no-cache'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/calibration-preview':
                side=urllib.parse.parse_qs(u.query).get('side',['front'])[0]
                name='Ausweis-Vorne.jpg' if side=='front' else 'Ausweis-Hinten.jpg'
                target=scan_dir()/name
                if not target.exists(): raise RuntimeError('Bitte zuerst den Ausweis scannen.')
                # WIA files can contain a valid image stream that browsers do not reliably decode despite a .jpg suffix.
                # Normalize the preview through Pillow to a real RGB JPEG before sending it to the calibration canvas.
                from PIL import Image
                from io import BytesIO
                with Image.open(target) as pim:
                    pim=pim.convert('RGB')
                    pim.thumbnail((1800,1800),Image.Resampling.LANCZOS)
                    buf=BytesIO(); pim.save(buf,'JPEG',quality=92); b=buf.getvalue()
                self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/api/calibration': self.sendj(get_scanner_calibration())
            elif u.path=='/api/app-settings': self.sendj(get_app_settings())
            elif u.path=='/api/backups': self.sendj(list_backups())
            elif u.path=='/api/update-check': self.sendj(find_update())
            elif u.path=='/scan-preview':
                name=Path(urllib.parse.parse_qs(u.query).get('file',[''])[0]).name
                if not name.startswith('OCR-') or not name.lower().endswith(('.jpg','.jpeg','.png')):
                    raise RuntimeError('Ungültige OCR-Vorschau.')
                target=scan_dir()/name
                if not target.exists(): raise RuntimeError('OCR-Vorschau nicht gefunden.')
                b=target.read_bytes(); self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/manual-pdf':
                did=urllib.parse.parse_qs(u.query).get('doc',[''])[0]
                allowed={x['id']:x for x in DOCUMENT_LIBRARY}
                if did not in allowed: raise RuntimeError('Unbekanntes Formular.')
                target=BASE/'templates'/allowed[did]['file']; b=target.read_bytes(); self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Disposition',f'inline; filename={target.name}'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/praege-pdf':
                key=urllib.parse.parse_qs(u.query).get('doc',[''])[0]
                docs={'one':'Arbeitsanweisung_1-zeilig.pdf','two':'Arbeitsanweisung_2-zeilig.pdf','sh49':'Arbeitsanweisung_SH49.pdf'}
                if key not in docs: raise RuntimeError('Unbekannte Arbeitsanweisung.')
                target=BASE/'templates'/docs[key]; b=target.read_bytes(); self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Disposition',f'inline; filename={target.name}'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/logo':
                b=(BASE/'service-point-logo.png').read_bytes(); self.send_response(200); self.send_header('Content-Type','image/png'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/print':
                qs=urllib.parse.parse_qs(u.query); jid=int(qs.get('id',['0'])[0]); selected=[x for x in qs.get('include',[''])[0].split(',') if x] or None; dest=create_print_package(jid,selected); b=Path(dest).read_bytes(); self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Disposition',f'inline; filename=DRUCKPAKET_Auftrag_{jid:05d}.pdf'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/api/lauf-options':
                jid=int(urllib.parse.parse_qs(u.query).get('id',['0'])[0]); self.sendj(get_lauf_options(jid))
            elif u.path=='/preview/laufzettel':
                jid=int(urllib.parse.parse_qs(u.query).get('id',['0'])[0]); dest=create_laufzettel(jid); b=Path(dest).read_bytes(); self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path in ['/preview/vollmacht','/preview/sepa']:
                jid=int(urllib.parse.parse_qs(u.query).get('id',['0'])[0]); folder,files=fill_pdfs(jid); target=Path(folder)/(next(x for x in files if ('Vollmacht' if u.path.endswith('vollmacht') else 'SEPA') in x)); b=target.read_bytes(); self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/api/intake':
                jid=int(urllib.parse.parse_qs(u.query).get('id',['0'])[0]); self.sendj(get_intake(jid))
            elif u.path=='/api/job-documents':
                jid=int(urllib.parse.parse_qs(u.query).get('id',['0'])[0]); self.sendj(job_documents(jid))
            elif u.path=='/document':
                qs=urllib.parse.parse_qs(u.query); jid=int(qs.get('id',['0'])[0]); did=qs.get('doc',[''])[0]; allowed={x['id']:x for x in job_documents(jid)}
                if did not in allowed: raise RuntimeError('Dokument ist für diesen Auftrag nicht freigegeben.')
                target=BASE/'templates'/allowed[did]['file']; b=target.read_bytes(); self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Disposition',f'inline; filename={target.name}'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/api/personal-notes': self.sendj(personal_notes())
            elif u.path=='/api/jobs': self.sendj(rows())
            elif u.path=='/api/customers': self.sendj(all_customers())
            elif u.path=='/api/deleted-jobs': self.sendj(list_deleted_jobs())
            elif u.path=='/api/deleted-customers': self.sendj(list_deleted_customers())
            elif u.path=='/export/jobs.csv':
                b=export_jobs_csv(); self.send_response(200); self.send_header('Content-Type','text/csv; charset=utf-8'); self.send_header('Content-Disposition','attachment; filename=auftraege.csv'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/export/customers.csv':
                b=export_customers_csv(); self.send_response(200); self.send_header('Content-Type','text/csv; charset=utf-8'); self.send_header('Content-Disposition','attachment; filename=kunden.csv'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/api/customer-jobs':
                qs=urllib.parse.parse_qs(u.query); self.sendj(customer_jobs(qs.get('name',[''])[0],qs.get('first_name',[''])[0]))
            elif u.path=='/api/customer-documents':
                qs=urllib.parse.parse_qs(u.query); self.sendj(customer_documents(qs.get('customer',[''])[0],qs.get('first_name',[''])[0]))
            elif u.path=='/customer-document':
                qs=urllib.parse.parse_qs(u.query); folder=_customer_folder(qs.get('customer',[''])[0],qs.get('first_name',[''])[0]); target=(folder/Path(qs.get('file',[''])[0]).name).resolve()
                if folder.resolve() not in target.parents or not target.is_file(): raise RuntimeError('Dokument nicht gefunden.')
                b=target.read_bytes(); self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
            elif u.path=='/api/radio-nowplaying':
                qs=urllib.parse.parse_qs(u.query); self.sendj({'title':radio_now_playing(qs.get('station',[''])[0])})
            elif u.path=='/api/import': self.sendj({'count':import_xlsx(BASE/'Was ist im STVA 2026.xlsx')})
            elif u.path=='/api/pdfs':
                jid=int(urllib.parse.parse_qs(u.query).get('id',['0'])[0]); folder,files=fill_pdfs(jid); files.append(create_laufzettel(jid).name); self.sendj({'folder':folder,'files':files})
            else: self.send_error(404)
        except Exception as e: self.sendj({'error':str(e)},500)
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0')); d=json.loads(self.rfile.read(n))
            if self.path=='/api/backup-now':
                self.sendj({'ok':True,'file':backup_db_now()})
            elif self.path=='/api/personal-notes':
                self.sendj({'id':save_personal_note(d)})
            elif self.path=='/api/personal-note-delete':
                delete_personal_note(d.get('id')); self.sendj({'ok':True})
            elif self.path=='/api/customer-save':
                self.sendj({'id':save_customer(d)})
            elif self.path=='/api/customer-delete':
                delete_customer(int(d.get('id'))); self.sendj({'ok':True})
            elif self.path=='/api/job-restore':
                self.sendj({'ok':True,'id':restore_deleted_job(int(d.get('id')))})
            elif self.path=='/api/customer-restore':
                self.sendj({'ok':True,'id':restore_deleted_customer(int(d.get('id')))})
            elif self.path=='/api/calibration':
                self.sendj(save_scanner_calibration(d.get('box')) if d.get('box') else reset_scanner_calibration())
            elif self.path=='/api/app-settings':
                self.sendj(save_app_settings(d))
            elif self.path=='/api/backup-restore':
                self.sendj(restore_backup(d.get('name','')))
            elif self.path=='/api/update-apply':
                self.sendj(apply_update(d.get('url','')))
            elif self.path=='/api/scans/clear':
                self.sendj(clear_pending_scans())
            elif self.path=='/api/ocr':
                self.sendj(recognize_scan(d.get('kind','id')))
            elif self.path=='/api/scanner':
                self.sendj(scan_direct(d.get('kind','extra'),d.get('side',''),d.get('doc_type','')))
            elif self.path=='/api/intake':
                jid=int(d.get('id',0)); save_intake(jid,d.get('data') or {}); self.sendj({'ok':True})
            elif self.path=='/api/lauf-options':
                jid=int(d.get('id',0)); save_lauf_options(jid,d.get('data') or {}); self.sendj({'ok':True})
            elif self.path=='/api/save':
                jid,actual=save_job(d); attach_pending_scans(jid,d.get('customer',''),d.get('first_name','')); self.sendj({'id':jid,'stva_date':actual})
            elif self.path=='/api/fill-buffers': self.sendj(fill_buffers(d.get('date') or datetime.now().date().isoformat()))
            elif self.path=='/api/move': self.sendj({'ok':True,'stva_date':move_job(int(d.get('id',0)),d.get('date',''))})
            elif self.path=='/api/job-delete': self.sendj({'ok':bool(delete_job(int(d.get('id',0))))})
            elif self.path=='/api/remove-today':
                jid=int(d.get('id',0)); changed=remove_from_today(jid)
                if not changed: self.sendj({'error':'Auftrag nicht gefunden'},404)
                else: self.sendj({'ok':True})
            else: self.send_error(404)
        except Exception as e:self.sendj({'error':str(e)},500)
    def log_message(self,*a): pass

def main():
    db().close(); backup_db_daily()
    srv=ThreadingHTTPServer((HOST,PORT),H); threading.Timer(.7,lambda:webbrowser.open(f'http://{HOST}:{PORT}')).start(); print('Zulassungsassistent läuft. Dieses Fenster offen lassen.'); print(f'http://{HOST}:{PORT}');
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
if __name__=='__main__':main()
