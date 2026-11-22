#!/usr/bin/env python3
"""Yeni genel duyuruları Fon Defterim uygulamasına anlık bildirim olarak gönderir (Apple CloudKit).

Nasıl çalışır: v1/veri.json'daki son duyurulardan bildirimi açık, fona özel olmayan olanlar için iCloud'daki
herkese açık veritabanına "Duyuru" kaydı eklenir. Uygulama bu kayıt türüne abonedir; Apple bildirimi hemen
dağıtır. Kayıt adı duyurunun kimliğinden üretilir ("duyuru-<id>"): aynı duyuru ikinci kez eklenemez, yani
betik kaç kez çalışırsa çalışsın her duyuru bir kez bildirilir. Kullanıcıya ait hiçbir bilgi kullanılmaz.

GitHub Actions çalıştırır (.github/workflows/bildirim.yml). Gerekenler (depo ayarlarında gizli değer):
  CK_ANAHTAR_ID     CloudKit Console > Tokens & Keys > Server-to-Server Keys'teki anahtar kimliği
  CK_OZEL_ANAHTAR   o anahtarın özel anahtarı (PEM, "-----BEGIN EC PRIVATE KEY-----" ile başlar)
  CK_ORTAM          isteğe bağlı: "production" (varsayılan) ya da "development" (deneme)
Anahtarlar yoksa hiçbir şey yapmadan çıkar. İmza için yalnızca `openssl` kullanılır (ek paket yok).

Elle deneme (gönderMEZ, yalnızca ne gönderileceğini yazar):  python3 araclar/bildirim_gonder.py --dene
"""
import base64, datetime, hashlib, json, os, subprocess, sys, tempfile, urllib.error, urllib.request

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERI = os.path.join(KOK, "v1", "veri.json")
KONTEYNER = "iCloud.io.github.fondefterim"
KAYIT_TURU = "Duyuru"
GUN = 2            # yalnızca son 2 günün duyuruları (ilk kurulumda eski duyurular için bildirim yağmasın)
EN_FAZLA = 3       # bir çalıştırmada en fazla bu kadar bildirim
METIN_SINIRI = 180


def secilecekler(veri, bugun):
    """Bildirimi açık, fona özel olmayan, son GUN günün duyuruları (yeni → eski)."""
    sinir = (bugun - datetime.timedelta(days=GUN)).isoformat()
    out = []
    for a in veri.get("announcements", []):
        if a.get("kind", "duyuru") != "duyuru" or a.get("notify", True) is False:
            continue
        if a.get("funds"):            # fona özel: uygulama yalnızca o fon defterdeyse kendisi bildirir
            continue
        if not a.get("id") or not a.get("title") or a.get("date", "") < sinir:
            continue
        out.append(a)
    out.sort(key=lambda a: a["date"], reverse=True)
    return out[:EN_FAZLA]


def baslik(a):
    # Uygulamadaki yerel bildirimle aynı: SPK/YTM kayıtlarında başlık olduğu gibi, diğerlerinde "Fon Defterim: ".
    if a.get("source") in ("spk", "ytm") or a["title"].startswith("Fon Defterim"):
        return a["title"]
    return "Fon Defterim: " + a["title"]


def kayit(a):
    metin = (a.get("body") or "").strip() or "Ayrıntı için Fon Defterim'de Duyurular'a bak."
    if len(metin) > METIN_SINIRI:
        metin = metin[:METIN_SINIRI - 1].rstrip() + "…"
    return {
        "recordType": KAYIT_TURU,
        "recordName": "duyuru-" + "".join(c if c.isalnum() or c in "-_" else "-" for c in a["id"])[:200],
        "fields": {
            "baslik": {"value": baslik(a)[:120]},
            "metin": {"value": metin},
            "duyuruId": {"value": a["id"]},
            "tarih": {"value": a["date"]},
        },
    }


def imzala(ozel_anahtar_pem, mesaj):
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(ozel_anahtar_pem.strip() + "\n")
        yol = f.name
    try:
        os.chmod(yol, 0o600)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", yol], input=mesaj.encode(),
                           capture_output=True, check=True)
        return base64.b64encode(r.stdout).decode()
    finally:
        os.remove(yol)


def gonder(kayitlar, anahtar_id, ozel_anahtar, ortam):
    alt_yol = f"/database/1/{KONTEYNER}/{ortam}/public/records/modify"
    govde = json.dumps({"operations": [{"operationType": "create", "record": k} for k in kayitlar],
                        "atomic": False}, ensure_ascii=False).encode()
    tarih = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ozet = base64.b64encode(hashlib.sha256(govde).digest()).decode()
    imza = imzala(ozel_anahtar, f"{tarih}:{ozet}:{alt_yol}")
    req = urllib.request.Request("https://api.apple-cloudkit.com" + alt_yol, data=govde, method="POST", headers={
        "Content-Type": "application/json",
        "X-Apple-CloudKit-Request-KeyID": anahtar_id,
        "X-Apple-CloudKit-Request-ISO8601Date": tarih,
        "X-Apple-CloudKit-Request-SignatureV1": imza,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"CloudKit hatası {e.code}: {e.read().decode(errors='replace')[:500]}")


def main():
    dene = "--dene" in sys.argv
    veri = json.load(open(VERI, encoding="utf-8"))
    bugun = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).date()   # TSİ
    secilen = secilecekler(veri, bugun)
    if not secilen:
        print("Bildirilecek yeni genel duyuru yok.")
        return
    kayitlar = [kayit(a) for a in secilen]
    if dene:
        print(json.dumps(kayitlar, ensure_ascii=False, indent=2))
        return
    anahtar_id = os.environ.get("CK_ANAHTAR_ID", "").strip()
    ozel = os.environ.get("CK_OZEL_ANAHTAR", "").strip()
    ortam = os.environ.get("CK_ORTAM", "").strip() or "production"
    if ortam not in ("production", "development"):
        raise SystemExit("CK_ORTAM production ya da development olmalı.")
    if not anahtar_id or not ozel:
        print("CloudKit anahtarı tanımlı değil; bildirim gönderilmedi.")
        return
    yanit = gonder(kayitlar, anahtar_id, ozel, ortam)
    for r in yanit.get("records", []):
        ad = r.get("recordName", "?")
        kod = r.get("serverErrorCode")
        if not kod:
            print(f"Gönderildi: {ad}")
        elif kod in ("CONFLICT", "RECORD_EXISTS", "ALREADY_EXISTS") or "exist" in (r.get("reason") or "").lower():
            print(f"Daha önce gönderilmiş: {ad}")
        else:
            print(f"Hata ({kod}): {ad} {r.get('reason', '')}")


if __name__ == "__main__":
    main()
