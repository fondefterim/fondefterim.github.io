#!/usr/bin/env python3
"""Yatırımcı Tazmin Merkezi (YTM) duyurularını izler; yenilerini v1/veri.json'daki duyurulara ekler.

GitHub Actions saatte bir çalıştırır (spk_izle.py sonunda çağrılır); elle de çalıştırılabilir:  python3 araclar/ytm_izle.py
- YTM'nin herkese açık duyuru sayfası (ytm.gov.tr/Home/Duyurular) okunur; yalnızca başlık, tarih, metnin ilk
  cümlesi ve YTM bağlantısı eklenir, yorum eklenmez.
- 16.09.2026'dan önceki duyurular eklenmez (tasfiye ve Tera Yatırım süreci bu tarihten sonra).
- İlk çalıştırmada var olan duyurular bildirim göndermeden eklenir (notify: false); sonrakiler bildirim gönderir.
- Yeni kayıt yoksa dosyaya dokunmaz.
"""
import html, json, os, re, sys, urllib.request

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERI = os.path.join(KOK, "v1", "veri.json")
SITE = "https://www.ytm.gov.tr"
UA = "fondefterim-izleme/1.0 (+https://fondefterim.github.io)"
BASLANGIC = "2026-09-16"


def indir(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def temiz(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).replace("​", "").strip()


def sade(s):
    return (s.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
            .translate(str.maketrans("çğöşü", "cgosu")))


OZEL_ADLAR = [("yatırımcı tazmin merkezi", "Yatırımcı Tazmin Merkezi"), ("tera yatırım menkul değerler aş", "Tera Yatırım Menkul Değerler AŞ"),
              ("tera yatırım", "Tera Yatırım"), ("ytm", "YTM"), ("spk", "SPK")]


def cumle_duzeni(s):
    """Tamamı büyük harfli metni cümle düzenine çevirir; özel adları korur."""
    harfler = [c for c in re.sub(r"\(.*?\)", "", s) if c.isalpha()]
    if not harfler or any(c.islower() for c in harfler):
        return s
    k = s.replace("I", "ı").replace("İ", "i").lower()
    for kucuk, dogru in OZEL_ADLAR:
        k = re.sub(re.escape(kucuk), dogru, k)
    return k[:1].replace("i", "İ").replace("ı", "I").upper() + k[1:]


def baslik_yap(ham):
    """YTM'nin genel başlıkları ("YATIRIMCI TAZMİN MERKEZİ DUYURUSU (…)") kısaltılır."""
    parantez = re.search(r"\((.*?)\)", ham)
    ek = f" ({parantez.group(1)})" if parantez else ""
    if sade(re.sub(r"\(.*?\)", "", ham)).strip().startswith("yatirimci tazmin merkez"):
        return "YTM duyurusu" + ek
    return "YTM: " + cumle_duzeni(ham)


def ilk_cumle(metin, en_fazla=200):
    m = re.match(r"(.+?[.!?])(\s|$)", metin)
    s = (m.group(1) if m else metin).strip()
    return s if len(s) <= en_fazla else s[: en_fazla - 1].rsplit(" ", 1)[0] + "…"


def liste():
    sayfa = indir(f"{SITE}/Home/Duyurular")
    out = []
    for no, baslik, gun, ay, yil in re.findall(
            r'<a href="/Home/Duyuru/(\d+)">(.*?)</a>\s*</div>\s*<div class="col-md-2">\s*(\d{2})\.(\d{2})\.(\d{4})', sayfa, re.S):
        out.append({"no": no, "title": temiz(baslik), "date": f"{yil}-{ay}-{gun}"})
    return out


def govde(no):
    sayfa = indir(f"{SITE}/Home/Duyuru/{no}")
    m = re.search(r"<article>(.*?)</article>", sayfa, re.S)
    return temiz(m.group(1)) if m else ""


def main():
    with open(VERI, encoding="utf-8") as f:
        veri = json.load(f)
    mevcut = {a["id"] for a in veri["announcements"]}
    ilk_calisma = not any(a.get("source") == "ytm" for a in veri["announcements"])
    yeni = []
    for d in liste():
        kimlik = "ytm-" + d["no"]
        if kimlik in mevcut or d["date"] < BASLANGIC:
            continue
        try:
            metin = govde(d["no"])
        except Exception as e:
            print("Duyuru okunamadı, sonra yeniden denenecek:", d["no"], e, file=sys.stderr)
            continue
        baslik = baslik_yap(d["title"])
        ozet = cumle_duzeni(ilk_cumle(metin)) if metin else None
        if ozet and sade(ozet).strip(" .") in sade(baslik):
            ozet = None   # metin yalnızca başlığı tekrar ediyorsa (ör. tek bir PDF bağlantısı) gövde koyma
        a = {"id": kimlik, "date": d["date"], "kind": "duyuru", "source": "ytm",
             "notify": not ilk_calisma,
             "title": baslik[:150],
             "body": ozet,
             "url": f"{SITE}/Home/Duyuru/{d['no']}"}
        yeni.append({k: v for k, v in a.items() if v is not None})

    if not yeni:
        print("Yeni YTM duyurusu yok.")
        return
    veri["announcements"] = sorted(yeni + veri["announcements"], key=lambda a: a["date"], reverse=True)
    with open(VERI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(yeni)} yeni YTM duyurusu eklendi" + (" (ilk çalışma: bildirimsiz)." if ilk_calisma else "."))
    for a in yeni:
        print(" ", a["date"], a["title"][:100], "|", a.get("body", "")[:120])


if __name__ == "__main__":
    main()
