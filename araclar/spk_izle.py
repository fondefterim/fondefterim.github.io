#!/usr/bin/env python3
"""SPK bültenlerini ve basın duyurularını izler; yenilerini v1/veri.json'daki duyurulara ekler.

GitHub Actions saatte bir çalıştırır; elle de çalıştırılabilir:  python3 araclar/spk_izle.py
- Yalnızca resmî başlık, tarih ve SPK bağlantısı eklenir; yorum eklenmez.
- Bülten PDF'inde ya da duyuru metninde tasfiye listesindeki bir fonun kodu/adı ya da tasfiyeyle ilgili
  bir anahtar kelime geçiyorsa duyuru "önemli" işaretlenir (notify) ve ilgili fonlar yazılır;
  uygulama yalnızca bunlar için bildirim gönderir.
- İlk çalıştırmada 16.09.2026'dan sonraki kayıtlar eklenir. Yeni kayıt yoksa dosyaya dokunmaz.
PDF metni için pypdf kullanılır (yoksa yalnızca başlık eklenir).
"""
import datetime, html, io, json, os, re, sys, urllib.request

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERI = os.path.join(KOK, "v1", "veri.json")
SITE = "https://spk.gov.tr"
UA = "fondefterim-izleme/1.0 (+https://fondefterim.github.io)"
BASLANGIC = "2026-09-16"
EN_FAZLA_SPK = 200          # dosyada tutulacak en fazla SPK kaydı
ANAHTAR = ["tasfiye", "7596", "temerrüt", "temerrut", "ara ödeme", "ara odeme", "pblk", "iade talimat"]
AYLAR = {"oca": 1, "şub": 2, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7,
         "ağu": 8, "agu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12}


def indir(url, bayt=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = r.read()
    return d if bayt else d.decode("utf-8", "replace")


def tarih(metin):
    """'06 Kasım 2026 Cuma' / '09 Kas 2026' → '2026-11-06'"""
    m = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})", metin)
    if not m:
        return None
    ay = AYLAR.get(m.group(2).lower().replace("İ", "i")[:3])
    return f"{int(m.group(3)):04d}-{ay:02d}-{int(m.group(1)):02d}" if ay else None


def temiz(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def pdf_metni(url):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        r = PdfReader(io.BytesIO(indir(url, bayt=True)))
        return "\n".join((p.extract_text() or "") for p in r.pages[:60])
    except Exception as e:
        print("PDF okunamadı:", url, e, file=sys.stderr)
        return ""


def ilgili(metin, fonlar):
    """Metinde geçen fon kodları (tam kelime) ve fon adları; tasfiye anahtar kelimeleri."""
    if not metin:
        return [], False
    kucuk = metin.lower()
    kodlar = []
    for f in fonlar:
        kod = f["code"]
        ad = (f.get("name") or "").lower()
        if re.search(rf"(?<![A-Za-z0-9ÇĞİÖŞÜ]){re.escape(kod)}(?![A-Za-z0-9ÇĞİÖŞÜ])", metin) or (len(ad) > 12 and ad in kucuk):
            kodlar.append(kod)
    anahtar = any(a in kucuk for a in ANAHTAR)
    return kodlar, anahtar or bool(kodlar)


def duyuru_metni(sayfa):
    """Detay sayfasından yalnızca duyurunun kendi metni (menü ve yan listeler hariç)."""
    spot = re.search(r'<div class="spot">(.*?)</div>', sayfa, re.S)
    govde = re.search(r'<div class="icerik styled-content">(.*?)(?:<div class="line|</main>)', sayfa, re.S)
    return temiz(" ".join(m.group(1) for m in (spot, govde) if m))


def kisa_liste(kodlar, en_fazla=8):
    return ", ".join(kodlar) if len(kodlar) <= en_fazla else ", ".join(kodlar[:en_fazla]) + f" ve {len(kodlar) - en_fazla} fon daha"


def ilk_cumle(metin, en_fazla=120):
    c = re.split(r"(?<=[.!?])\s", metin.strip(), maxsplit=1)[0] if metin else ""
    return c if len(c) <= en_fazla else c[: en_fazla - 1].rsplit(" ", 1)[0] + "…"


def bultenler():
    yil = datetime.date.today().year
    sayfa = indir(f"{SITE}/spk-bultenleri/{yil}-yili-spk-bultenleri")
    out = []
    for h, no, yay in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*class="link"[^>]*>.*?Bülten No\s*:\s*([0-9/]+).*?Yayımlanma\s*:\s*([^<]+)<', sayfa, re.S):
        out.append({"no": no.strip(), "date": tarih(html.unescape(yay)), "url": h if h.startswith("http") else SITE + h})
    return out


def basin_duyurulari():
    yil = datetime.date.today().year
    sayfa = indir(f"{SITE}/duyurular/basin-duyurulari/{yil}")
    out = []
    for h, govde in re.findall(r'<a href="(/duyurular/basin-duyurulari/[^"]+)" class="link">\s*<div class="liste-item">(.*?)</a>', sayfa, re.S):
        t = re.search(r'class="liste-tarih">([^<]+)<', govde)
        b = re.search(r'class="liste-baslik">(.*?)</div>', govde, re.S)
        o = re.search(r'class="liste-icerik[^"]*">(.*?)</div>', govde, re.S)
        if t and b:
            out.append({"slug": h.rstrip("/").split("/")[-1], "date": tarih(html.unescape(t.group(1))), "title": temiz(b.group(1)),
                        "summary": temiz(o.group(1)) if o else "", "url": SITE + h})
    return out


def main():
    with open(VERI, encoding="utf-8") as f:
        veri = json.load(f)
    fonlar = veri["funds"]
    mevcut = {a["id"] for a in veri["announcements"]}
    yeni = []

    for b in bultenler():
        kimlik = "spk-bulten-" + b["no"].replace("/", "-")
        if kimlik in mevcut or not b["date"] or b["date"] < BASLANGIC:
            continue
        kodlar, onemli = ilgili(pdf_metni(b["url"]), fonlar)
        govde = f"{b['no']} sayılı SPK Bülteni yayımlandı."
        if kodlar:
            govde += " Bültende geçen fonlar: " + kisa_liste(kodlar) + "."
        elif onemli:
            govde += " Bültende fon tasfiyesiyle ilgili ifadeler geçiyor."
        yeni.append({"id": kimlik, "date": b["date"], "kind": "duyuru", "source": "spk", "notify": onemli,
                     "title": f"SPK Bülteni {b['no']}", "body": govde, "url": b["url"], "funds": kodlar or None})

    for d in basin_duyurulari():
        kimlik = "spk-basin-" + d["slug"][:80]
        if kimlik in mevcut or not d["date"] or d["date"] < BASLANGIC:
            continue
        try:
            metin = duyuru_metni(indir(d["url"]))
        except Exception:
            metin = ""
        kodlar, onemli = ilgili(" ".join([d["title"], d["summary"], metin]), fonlar)
        baslik = d["title"]
        if baslik.lower() in ("basın duyurusu", "basın açıklaması"):
            ek = d["summary"] or ilk_cumle(metin)
            if ek:
                baslik = f"{baslik}: {ek}"
        yeni.append({"id": kimlik, "date": d["date"], "kind": "duyuru", "source": "spk", "notify": onemli,
                     "title": "SPK: " + baslik[:160], "body": d["summary"] or None, "url": d["url"], "funds": kodlar or None})

    if not yeni:
        print("Yeni SPK kaydı yok.")
        return
    for a in yeni:
        for k in [k for k, v in a.items() if v is None]:
            del a[k]
    duyurular = yeni + veri["announcements"]
    spk = [a for a in duyurular if a.get("source") == "spk"]
    if len(spk) > EN_FAZLA_SPK:                       # en eski SPK kayıtlarını at
        at = {a["id"] for a in sorted(spk, key=lambda a: a["date"])[: len(spk) - EN_FAZLA_SPK]}
        duyurular = [a for a in duyurular if a["id"] not in at]
    veri["announcements"] = sorted(duyurular, key=lambda a: a["date"], reverse=True)
    with open(VERI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(yeni)} yeni SPK kaydı eklendi ({sum(a['notify'] for a in yeni)} önemli).")
    for a in yeni:
        print(" ", a["date"], "★" if a["notify"] else " ", a["title"][:90], a.get("funds", ""))


if __name__ == "__main__":
    main()
