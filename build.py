#!/usr/bin/env python3
"""Генератор цифровых визиток BI Property.
Читает data/employees.json и data/site.json, создаёт папку dist/ со страницами,
файлами контактов (.vcf) и QR-кодами (PNG + SVG). Запускается автоматически на GitHub."""
import json, os, re, shutil, sys, uuid
from html import escape
from pathlib import Path
import segno

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
errors = []

def err(msg): errors.append(msg)

TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяәіңғүұқөһ",
 ["a","b","v","g","d","e","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","kh","ts","ch","sh","shch","","y","","e","yu","ya","a","i","n","g","u","u","q","o","h"]))
def slugify(text):
    t = "".join(TR.get(c, c) for c in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")

def load(name):
    p = ROOT / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"ОШИБКА: не найден файл {p.name}")
    except json.JSONDecodeError as e:
        sys.exit(f"ОШИБКА в файле {name}: строка {e.lineno}, позиция {e.colno}: {e.msg}. "
                 "Обычно это забытая или лишняя запятая либо кавычка.")

site = load("site.json")
people = load("employees.json")
if not isinstance(people, list): sys.exit("ОШИБКА: employees.json должен начинаться с [ и заканчиваться ]")

base = (os.environ.get("BASE_URL") or site.get("base_url") or "https://USERNAME.github.io/REPOSITORY").rstrip("/")
noindex = site.get("hide_from_search_engines", True)

def clean(v): return str(v).strip() if v is not None else ""
def is_url(u): return bool(re.match(r"^https?://[^\s]+\.[^\s]+$", u))
def tel_href(p): return re.sub(r"[^\d+]", "", p)

# ---------- vCard ----------
def esc(v): return v.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75: return line
    out, cur = [], b""
    for ch in line:
        c = ch.encode("utf-8")
        if len(cur) + len(c) > (75 if not out else 74):
            out.append(cur.decode("utf-8")); cur = c
        else: cur += c
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)

def make_vcf(e):
    L = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//BI Property//Digital Card//RU",
         f"N:{esc(e['last_name'])};{esc(e['first_name'])};;;", f"FN:{esc(e['full_name'])}",
         f"ORG:{esc(e['company'])}"]
    if e["position"]: L.append(f"TITLE:{esc(e['position'])}")
    if e["phone"]: L.append(f"TEL;TYPE=CELL,VOICE:{tel_href(e['phone'])}")
    if e["email"]: L.append(f"EMAIL;TYPE=INTERNET,WORK:{e['email']}")
    if e["website"]: L.append(f"URL:{e['website']}")
    if e["address"]: L.append(f"ADR;TYPE=WORK:;;{esc(e['address'])};;;;")
    for l in e["links"]: L.append(f"URL:{l['url']}")
    L += [f"UID:urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, base + '/card/' + e['slug'])}", "END:VCARD"]
    return "\r\n".join(fold(x) for x in L) + "\r\n"

# ---------- проверка данных ----------
emps, seen = [], set()
for i, raw in enumerate(people, 1):
    if not isinstance(raw, dict): err(f"Запись №{i}: должна быть в фигурных скобках {{ }}"); continue
    e = {k: clean(raw.get(k)) for k in ("slug","first_name","last_name","position","phone","email","website","address")}
    who = f"Запись №{i} ({e['first_name']} {e['last_name']})".replace(" )", ")")
    if not e["first_name"] or not e["last_name"]: err(f"{who}: заполните first_name и last_name"); continue
    if not e["slug"]: e["slug"] = slugify(f"{e['first_name']}-{e['last_name']}")
    e["slug"] = e["slug"].lower()
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", e["slug"]): err(f"{who}: slug «{e['slug']}» — допустимы только латинские буквы, цифры и дефис"); continue
    if e["slug"] in seen: err(f"{who}: slug «{e['slug']}» уже занят другим сотрудником"); continue
    seen.add(e["slug"])
    if raw.get("hidden") is True: continue
    if e["phone"] and len(re.sub(r"\D", "", e["phone"])) < 7: err(f"{who}: телефон выглядит неверно: {e['phone']}"); e["phone"] = ""
    if e["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e["email"]): err(f"{who}: неверный email: {e['email']}"); e["email"] = ""
    e["company"] = clean(raw.get("company")) or clean(site.get("company_name")) or "Bi Property"
    e["website"] = e["website"] or clean(site.get("website"))
    e["address"] = e["address"] or clean(site.get("address"))
    if e["website"] and not is_url(e["website"]): err(f"{who}: сайт должен начинаться с https://"); e["website"] = ""
    e["links"] = []
    for l in raw.get("links") or []:
        t, u = clean(l.get("title")), clean(l.get("url"))
        if t and is_url(u): e["links"].append({"title": t, "url": u})
        elif t or u: err(f"{who}: дополнительная ссылка «{t}» неверна (нужны title и url с https://)")
    e["full_name"] = f"{e['first_name']} {e['last_name']}"
    emps.append(e)

if errors:
    print("НАЙДЕНЫ ОШИБКИ В ДАННЫХ — сайт не обновлён:\n" + "\n".join("  • " + x for x in errors)); sys.exit(1)

# ---------- страницы ----------
ICON = {
 "phone": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
 "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
 "web": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
 "pin": '<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
 "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'}
def row(kind, text, href=None):
    ic = f'<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">{ICON[kind]}</svg>'
    inner = f'{ic}<span>{escape(text)}</span>'
    if href: return f'<li><a href="{escape(href, True)}"' + (' target="_blank" rel="noopener"' if href.startswith("http") else "") + f'>{inner}</a></li>'
    return f'<li class="plain">{inner}</li>'

def page(e):
    rows = []
    if e["phone"]: rows.append(row("phone", e["phone"], "tel:" + tel_href(e["phone"])))
    if e["email"]: rows.append(row("mail", e["email"], "mailto:" + e["email"]))
    if e["website"]: rows.append(row("web", re.sub(r"^https?://(www\.)?|/$", "", e["website"]), e["website"]))
    if e["address"]: rows.append(row("pin", e["address"]))
    for l in e["links"]: rows.append(row("link", l["title"], l["url"]))
    sub = "".join(f"<p>{escape(x)}</p>" for x in (e["position"], e["company"]) if x)
    robots = '<meta name="robots" content="noindex, nofollow">' if noindex else ""
    fname = escape(e["slug"]) + ".vcf"
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{escape(e["full_name"])} — {escape(e["company"])}</title>
<meta name="description" content="Цифровая визитка: {escape(e["full_name"])}, {escape(e["position"])}">
<meta name="theme-color" content="#00234A">{robots}
<link rel="icon" href="../../assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../../assets/style.css">
</head><body><main class="card">
<div class="orn" aria-hidden="true"></div>
<img class="logo" src="../../assets/logo-bi-group.svg" alt="BI Group — We build happiness">
<section class="who"><h1>{escape(e["full_name"])}</h1>{sub}</section>
<ul class="contacts">{"".join(rows)}</ul>
<a class="save" href="{fname}" download="{fname}" type="text/vcard">Сохранить контакт</a>
<p class="hint">Откроется карточка контакта — подтвердите добавление в телефонную книгу.</p>
</main></body></html>
'''

if DIST.exists(): shutil.rmtree(DIST)
(DIST / "card").mkdir(parents=True); (DIST / "qr").mkdir()
(DIST / "assets").mkdir()
for f in list(ROOT.glob("*.woff2")) + [ROOT / n for n in ("style.css", "favicon.svg", "logo-bi-group.svg", "ornament.svg")]:
    if not f.exists(): sys.exit(f"ОШИБКА: не загружен файл {f.name}")
    shutil.copy(f, DIST / "assets" / f.name)
(DIST / ".nojekyll").write_text("")
stub = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>{t}</title><link rel="stylesheet" href="{p}assets/style.css"><body class="bare"><main class="msg"><img src="{p}assets/logo-bi-group.svg" alt="BI Group"><p>{m}</p></main></body></html>'
(DIST / "index.html").write_text(stub.format(t="BI Property", p="", m="Цифровые визитки сотрудников BI Property"), encoding="utf-8")
(DIST / "404.html").write_text(stub.format(t="Страница не найдена", p="/" + base.split("/", 3)[3] + "/" if base.count("/") > 2 else "/", m="Визитка не найдена. Проверьте ссылку или обратитесь к сотруднику."), encoding="utf-8")

for e in emps:
    d = DIST / "card" / e["slug"]; d.mkdir()
    (d / "index.html").write_text(page(e), encoding="utf-8")
    (d / f"{e['slug']}.vcf").write_text(make_vcf(e), encoding="utf-8", newline="")
    url = f"{base}/card/{e['slug']}/"
    qr = segno.make(url, error="q")
    qr.save(DIST / "qr" / f"{e['slug']}.svg", scale=10, border=4, dark="#000000", light="#ffffff", xmldecl=True)
    qr.save(DIST / "qr" / f"{e['slug']}.png", scale=30, border=4, dark="#000000", light="#ffffff", dpi=300)
    print(f"OK  {e['full_name']:<30} {url}")
print(f"\nГотово: {len(emps)} визиток. Адрес сайта: {base}/")
