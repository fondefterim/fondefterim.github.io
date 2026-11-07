#!/usr/bin/env python3
"""TCMB gösterge kurlarını (USD, EUR, GBP) çekip v1/kur.json'a yazar.

GitHub Actions her iş günü öğleden sonra çalıştırır; elle de çalıştırılabilir:
    python3 araclar/kur_guncelle.py
Yalnızca Python'un kendi kütüphanelerini kullanır. Yeni bülten yoksa dosyaya dokunmaz.
"""
import datetime, json, os, sys, urllib.request
import xml.etree.ElementTree as ET

KODLAR = [("USD", "ABD Doları"), ("EUR", "Euro"), ("GBP", "İngiliz Sterlini")]
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIKTI = os.path.join(KOK, "v1", "kur.json")


def indir(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fondefterim-kur/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def coz(xml_bytes):
    root = ET.fromstring(xml_bytes)
    g, a, y = root.attrib["Tarih"].split(".")
    tarih = f"{y}-{a}-{g}"
    kurlar = {}
    for c in root.findall("Currency"):
        kod = c.attrib.get("Kod")
        if kod not in dict(KODLAR):
            continue
        def sayi(etiket):
            t = (c.findtext(etiket) or "").strip()
            return float(t) if t else None
        birim = int((c.findtext("Unit") or "1").strip() or 1)
        kurlar[kod] = {"buying": sayi("ForexBuying"), "selling": sayi("ForexSelling"), "unit": birim}
    return tarih, root.attrib.get("Bulten_No"), kurlar


def onceki_bulten(tarih):
    """Bir önceki iş gününün bülteni (en fazla 10 gün geriye bakar)."""
    d = datetime.date.fromisoformat(tarih)
    for _ in range(10):
        d -= datetime.timedelta(days=1)
        url = f"https://www.tcmb.gov.tr/kurlar/{d:%Y%m}/{d:%d%m%Y}.xml"
        try:
            return coz(indir(url))
        except Exception:
            continue
    return None


def main():
    tarih, bulten, kurlar = coz(indir("https://www.tcmb.gov.tr/kurlar/today.xml"))
    eksik = [k for k, _ in KODLAR if not kurlar.get(k, {}).get("selling")]
    if eksik:
        sys.exit(f"TCMB dosyasında eksik kur: {eksik}")

    mevcut = None
    if os.path.exists(CIKTI):
        with open(CIKTI, encoding="utf-8") as f:
            mevcut = json.load(f)
    if mevcut and mevcut.get("date") == tarih:
        print(f"Yeni bülten yok ({tarih}).")
        return

    # Değişim için bir önceki bülten: dosyadaki eski kurlar ya da TCMB arşivi.
    if mevcut and mevcut.get("date", "") < tarih:
        onceki_tarih = mevcut["date"]
        onceki = {r["code"]: {"selling": r["selling"]} for r in mevcut.get("rates", [])}
    else:
        o = onceki_bulten(tarih)
        onceki_tarih, onceki = (o[0], o[2]) if o else (None, {})

    veri = {
        "format": 1,
        "source": "TCMB",
        "date": tarih,
        "bulletin": bulten,
        "previousDate": onceki_tarih,
        "fetchedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rates": [
            {
                "code": kod,
                "name": ad,
                "unit": kurlar[kod]["unit"],
                "buying": kurlar[kod]["buying"],
                "selling": kurlar[kod]["selling"],
                "previousSelling": (onceki.get(kod) or {}).get("selling"),
            }
            for kod, ad in KODLAR
        ],
    }
    os.makedirs(os.path.dirname(CIKTI), exist_ok=True)
    with open(CIKTI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Güncellendi: {tarih} (önceki {onceki_tarih}).")


if __name__ == "__main__":
    main()
