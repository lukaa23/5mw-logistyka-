import io, json, math, mimetypes, os, threading, uuid, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
FILES = DATA / 'documents'
DB = DATA / 'records.json'
LOCK = threading.Lock()
DATA.mkdir(exist_ok=True); FILES.mkdir(exist_ok=True)

PRESETS = [
 {'key':'1P×28','length':38.459,'purlins':30,'bearings':5,'dampers':2,'drive':1,'tubes':[('A1','S156×2.8 / L-7290-2.8',1),('A2','S156×2.8 / L-6590-2.8',1),('B1','S156×2.8 / L-6845-2.8',1),('C1','S156×2.8 / L-8603-2.8',1),('C2','S156×2.8 / L-9131-2.8',1)]},
 {'key':'1P×42','length':57.946,'purlins':44,'bearings':8,'dampers':2,'drive':1,'tubes':[('A5','S156×2.2 / L-5990-2.2',2),('B6','S156×2.2 / L-7045-2.2',4),('C5','S156×2.2 / L-8893-2.2',2)]},
 {'key':'1P×56','length':77.080,'purlins':58,'bearings':10,'dampers':2,'drive':1,'tubes':[('A3','S156×2.8 / L-6190-2.8',2),('B2','S156×2.8 / L-7345-2.8',2),('B3','S156×2.8 / L-7595-2.8',4),('C3','S156×2.8 / L-9815-2.8',2)]},
 {'key':'1P×70','length':95.481,'purlins':73,'bearings':12,'dampers':3,'drive':2,'tubes':[('A2','S156×2.8 / L-6590-2.8',2),('A4','S156×2.8 / L-7240-2.8',2),('B1','S156×2.8 / L-6845-2.8',2),('B4','S156×2.8 / L-7495-2.8',2),('B5','S156×2.8 / L-7645-2.8',1),('C4','S156×2.8 / L-8613-2.8',2),('D1','S156×2.8 / L-5730-2.8',1),('D2','S156×2.8 / L-9530-2.8',1)]}
]

STEPS = [
 ('Przygotowanie','5.3–5.8',['Potwierdź wariant trackera, aktualny BOM i rysunek wykonawczy.','Rozłóż elementy według oznaczeń i sprawdź kompletność.','Przygotuj klucz dynamometryczny i narzędzia.']),
 ('Podstawy przekładni i łożysk','5.3',['Ustaw podstawę równolegle do płaszczyzny słupa.','Podkładki dwuwarstwowe montuj po stronie nakrętki.','Sprawdź poziom; tolerancja skręcenia ≤ 0,5°.']),
 ('Przekładnia mechaniczna','5.4',['Ustaw przekładnię z silnikiem skierowanym na wschód.','Wprowadź śruby ręcznie i wypoziomuj w obu kierunkach.','Dokręć momentem z zatwierdzonego BOM.']),
 ('Obudowy łożysk','5.5',['Otwórz górną pokrywę i zamontuj obudowę na podstawie.','Wsuń łożysko polimerowe po ułożeniu rury.','Sprawdź kierunek obudowy i zamknij pokrywę.']),
 ('Rury przy przekładni','5.6.1',['Skieruj do przekładni koniec z ośmioma otworami Ø18.','Ustaw spaw rury od dołu.','Dokręcaj M16 według kolejności z rysunku 5.6.1-3.','Sprawdź współpłaszczyznowość ≤ 0,5°.']),
 ('Połączenia kolejnych rur','5.6.2',['Ułóż rury według tabeli wariantu.','Złóż śrubę zamkową, podkładkę samohamowną i nakrętkę.','Dokręć w dwóch przejściach.','Sprawdź sąsiednie rury ≤ 0,5° i cały rząd ±2°.']),
 ('Płatwie','5.7 / dodatek 2.4.1',['Rozpocznij od środka rzędu.','Ustaw płatwie prostopadle do osi rury.','Śruby U dokręcaj naprzemiennie.','Nakrętki M10: 25–32 N·m.']),
 ('Amortyzatory','5.8',['Zamontuj uchwyty, obejmy i amortyzator.','Większa średnica ma być skierowana ku górze.','Montuj symetrycznie.','Rozchyl zawleczkę powyżej 180°.']),
 ('Kontrola mechaniczna','Dodatek 1',['Sprawdź każde połączenie kluczem dynamometrycznym.','Oznacz sprawdzone połączenia linią.','Zapisz odbiór i niezgodności.']),
 ('Zaślepki rur','5.13',['Załóż zaślepki na obu końcach rury.','Sprawdź osadzenie i brak uszkodzeń.'])
]

TOOLS = [('Klucz elektryczny','M5–M18',1),('Klucz dynamometryczny','0–450 N·m',1),('Poziomnica','1 m',1),('Kątomierz','±90°',1),('Młotek gumowy','średni',1),('Taśma miernicza','10 m',1),('Klucz 16 mm','',1),('Klucz 18 mm','',2),('Klucz 21 mm','',2),('Klucz 24 mm','',2),('Klucz 27 mm','',2),('Szczypce długie','4 cale',1)]

def load():
    if not DB.exists(): return {'documents':[],'hours':[],'progress':[],'quality':[],'equipment':[]}
    try: return json.loads(DB.read_text('utf-8'))
    except Exception: return {'documents':[],'hours':[],'progress':[],'quality':[],'equipment':[]}

def save(data):
    with LOCK:
        tmp=DB.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8'); tmp.replace(DB)

def calculate(length, rows, reserve):
    length=float(length); rows=int(rows); reserve=float(reserve)
    if not 5<=length<=150 or not 1<=rows<=10000 or not 0<=reserve<=25: raise ValueError('Długość 5–150 m, rzędy 1–10000, zapas 0–25%.')
    p=min(PRESETS,key=lambda x:abs(x['length']-length)); exact=lambda q:q*rows; extra=lambda q:math.ceil(q*rows*(1+reserve/100))
    items=[{'group':'Rury','name':'Rura '+n,'spec':s,'qty':exact(q),'reserve':extra(q),'source':'Dodatek 2.2'} for n,s,q in p['tubes']]
    n=p['purlins']; items += [
      {'group':'Płatwie','name':'Płatew','spec':'J60×30×1.8' if p['key']!='1P×70' else 'J60×30×1.6','qty':exact(n),'reserve':extra(n),'source':'Dodatek 2.4.1'},
      {'group':'Płatwie','name':'Śruba U','spec':'UM10×166×188×30','qty':exact(n),'reserve':extra(n),'source':'Dodatek 2.4.1'},
      {'group':'Płatwie','name':'Podkładka płatwi','spec':'28×43.5×42','qty':exact(n),'reserve':extra(n),'source':'Dodatek 2.4.1'},
      {'group':'Płatwie','name':'Podkładka wzmacniająca','spec':'3×22×35','qty':exact(2*n),'reserve':extra(2*n),'source':'Dodatek 2.4.1'},
      {'group':'Mocowania','name':'Nakrętka kołnierzowa','spec':'M10 · 25–32 N·m','qty':exact(2*n),'reserve':extra(2*n),'source':'Dodatek 2.4.1'},
      {'group':'Zespoły','name':'Podstawa i przekładnia','spec':'BP064/BP088 — sprawdź BOM','qty':exact(p['drive']),'reserve':exact(p['drive']),'source':'5.3–5.4'},
      {'group':'Zespoły','name':'Obudowa i łożysko','spec':'BP094-200/BP090/BP092','qty':exact(p['bearings']),'reserve':extra(p['bearings']),'source':'5.5'},
      {'group':'Zespoły','name':'Amortyzator z mocowaniem','spec':'BP168/BP093 — sprawdź typ','qty':exact(p['dampers']),'reserve':extra(p['dampers']),'source':'5.8'}]
    verify=[
      ('Podstawa przekładni','M16×50×30 lub M14×40×30 + podkładka płaska + podkładka dwuwarstwowa + nakrętka','5.3'),
      ('Przekładnia','M18×80×50 lub M16×75×50 + 2 duże podkładki + sprężysta + 2 nakrętki','5.4'),
      ('Obudowa łożyska','M10×90×26 + nakrętka + zawleczka 2.5×18; M16×45×30 + podkładki + nakrętka','5.5'),
      ('Rura do przekładni','M16×30×30 + podkładka dwuwarstwowa samohamowna','5.6.1'),
      ('Połączenia rur','MC10×31×29 + podkładka samohamowna + nakrętka; 1P×70 również M12/MC12','5.6.2'),
      ('Amortyzator','UM12×168×195×35; M12×40×25; M14×80×25 + właściwe podkładki, nakrętki i zawleczki','5.8')]
    return {'preset':p['key'],'reference':p['length'],'difference':round(length-p['length'],3),'match':abs(length-p['length'])<=2,'items':items,'verify':[{'name':a,'spec':b,'source':c} for a,b,c in verify],'tools':[{'name':a,'spec':b,'qty':c} for a,b,c in TOOLS]}

def extract_pdf(path):
    try:
        from pypdf import PdfReader
        return '\n'.join(page.extract_text() or '' for page in PdfReader(path).pages)
    except Exception: return ''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def out(self, body, code=200, mime='application/json; charset=utf-8', headers=None):
        if isinstance(body,(dict,list)): body=json.dumps(body,ensure_ascii=False).encode()
        elif isinstance(body,str): body=body.encode()
        self.send_response(code); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(body))); self.send_header('X-Content-Type-Options','nosniff')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/state':
            d=load(); manual=next((x for x in d['documents'] if 'torque tube' in x.get('text','').lower() or 'installation manual' in x.get('text','').lower()),None)
            return self.out(d|{'presets':[{k:v for k,v in p.items() if k!='tubes'} for p in PRESETS],'instructions':[{'number':i+1,'title':a,'section':b,'steps':c,'source':manual['name'] if manual else 'Instrukcja wbudowana — wgraj manual do potwierdzenia','confirmed':bool(manual)} for i,(a,b,c) in enumerate(STEPS)]})
        if path.startswith('/api/document/'):
            ident=path.rsplit('/',1)[-1]; doc=next((x for x in load()['documents'] if x['id']==ident),None)
            if not doc or not (FILES/doc['file']).exists(): return self.out({'error':'Brak pliku'},404)
            return self.out((FILES/doc['file']).read_bytes(),mime='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{doc["name"].encode("ascii","ignore").decode() or "document"}"'})
        static={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if path in static:
            f=ROOT/'static'/static[path]; return self.out(f.read_bytes(),mime=mimetypes.guess_type(f)[0] or 'application/octet-stream')
        return self.out({'error':'Nie znaleziono'},404)
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>32*1024*1024: raise ValueError('Limit pliku wynosi 32 MB.')
            raw=self.rfile.read(size); path=urlparse(self.path).path
            if path=='/api/calculate':
                b=json.loads(raw); return self.out(calculate(b['length'],b.get('rows',1),b.get('reserve',3)))
            if path=='/api/upload':
                name=Path(unquote(self.headers.get('X-File-Name','document.pdf'))).name; ext=Path(name).suffix.lower()
                if ext not in ('.pdf','.dwg','.dxf'): raise ValueError('Dozwolone pliki: PDF, DWG, DXF.')
                ident=uuid.uuid4().hex; fn=ident+ext; (FILES/fn).write_bytes(raw); text=extract_pdf(FILES/fn) if ext=='.pdf' else ''
                status='Tekst odczytany' if text else ('Rysunek CAD — zapisany' if ext!='.pdf' else 'Skan lub PDF bez tekstu')
                d=load(); d['documents'].insert(0,{'id':ident,'name':name,'file':fn,'size':size,'status':status,'text':text}); save(d); return self.out({'id':ident},201)
            kind=path.removeprefix('/api/record/')
            if kind not in ('hours','progress','quality','equipment'): return self.out({'error':'Nieznany rejestr'},404)
            b=json.loads(raw); b['id']=uuid.uuid4().hex
            if kind=='hours': b['labor']=round(float(b['people'])*float(b['hours']),2)
            d=load(); d[kind].insert(0,b); save(d); return self.out(b,201)
        except (ValueError,KeyError,json.JSONDecodeError) as e: return self.out({'error':str(e)},400)
    def do_DELETE(self):
        ident=urlparse(self.path).path.removeprefix('/api/record/'); d=load()
        for kind in ('hours','progress','quality','equipment'): d[kind]=[x for x in d[kind] if x.get('id')!=ident]
        save(d); self.out({'ok':True})

if __name__=='__main__':
    port=int(os.environ.get('PORT','8765')); print(f'Logistyka Struktury: http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
