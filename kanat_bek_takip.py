#!/usr/bin/env python3
"""
Kanat-Bek Takip
---------------
SofaScore'da yaklaşan ve canlı maçların kesinleşmiş ilk 11'lerini tarar.
Kanat oyuncusuyla oynayan dizilişlerde (4-4-2, 4-2-3-1, 4-3-3 ...) kanat
pozisyonuna bek özellikli bir oyuncu yerleştirilmişse bildirim atar.

Oyuncu mevkisi önce Transfermarkt'tan, bulunamazsa SofaScore'dan alınır.
Bildirim: ntfy (NTFY_TOPIC) ve/veya Telegram (TELEGRAM_TOKEN + TELEGRAM_CHAT_ID).

Kullanım:
  python kanat_bek_takip.py              # normal tarama (GitHub Actions bunu çalıştırır)
  python kanat_bek_takip.py --dry        # bildirim göndermeden sadece ekrana yazar
  python kanat_bek_takip.py --mac 12345  # tek bir maçı inceler, tüm kadroyu yazar (test için)
  python kanat_bek_takip.py --test-bildirim   # bildirim kanalını dener
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup

# ----------------------------------------------------------------------------
# AYARLAR
# ----------------------------------------------------------------------------

# Diziliş -> kanat oyuncularının bulunduğu hat (kaleci hariç, 0'dan sayılır).
# Örn. "4-2-3-1" hatları [4, 2, 3, 1]; kanatlar 2 numaralı hattın ("3") iki ucu.
KANATLI_DIZILISLER = {
    "4-4-2": 1,
    "4-2-3-1": 2,
    "4-3-3": 2,
    "4-1-4-1": 2,
    "4-4-1-1": 1,
}

# Bek sayılan mevki kodları.
BEK_KODLARI = {"DR", "DL", "RB", "LB", "RWB", "LWB", "WBR", "WBL"}
KOD_ADLARI = {
    "DR": "Sağ Bek", "DL": "Sol Bek", "RB": "Sağ Bek", "LB": "Sol Bek",
    "RWB": "Sağ Kanat Bek", "LWB": "Sol Kanat Bek", "WBR": "Sağ Kanat Bek", "WBL": "Sol Kanat Bek",
    "DC": "Stoper", "DM": "Ön Libero", "MC": "Merkez OS", "ML": "Sol OS", "MR": "Sağ OS",
    "AM": "10 Numara", "LW": "Sol Kanat", "RW": "Sağ Kanat", "ST": "Santrfor", "GK": "Kaleci",
}

# Transfermarkt (İngilizce site) mevki adları -> kod
TM_MEVKI = {
    "goalkeeper": "GK", "centre-back": "DC", "left-back": "DL", "right-back": "DR",
    "defensive midfield": "DM", "central midfield": "MC", "left midfield": "ML",
    "right midfield": "MR", "attacking midfield": "AM", "left winger": "LW",
    "right winger": "RW", "second striker": "ST", "centre-forward": "ST",
}

# True: sadece oyuncunun ANA mevkisi bek ise bildir (daha az ama isabetli bildirim).
# False: oyuncunun mevkileri arasında herhangi bir bek kodu varsa bildir.
SADECE_ANA_MEVKI = True

# Transfermarkt kullanılsın mı? (engellenirse otomatik SofaScore'a döner)
TRANSFERMARKT_KULLAN = True

# SofaScore bir hattaki oyuncuları hangi sırayla veriyor? İlk oyuncu sağ taraf ise True.
# "--mac" ile bilinen bir maçı kontrol edip gerekirse False yap.
ILK_OYUNCU_SAG = True

# Hangi maçlar taransın: başlamasına en fazla bu kadar dakika kalmış olanlar
# ve en fazla bu kadar dakika önce başlamış olanlar (canlı maçlar).
ONCESI_DK = 80
SONRASI_DK = 130

SOFA_BEKLE_SN = 0.35
TM_BEKLE_SN = 1.5
API = "https://api.sofascore.com/api/v1"
TM = "https://www.transfermarkt.com"
DURUM_DOSYASI = Path(__file__).with_name("durum.json")
TR = timezone(timedelta(hours=3))

# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

try:  # curl_cffi tarayıcı gibi göründüğü için engellenme ihtimali daha düşük
    from curl_cffi import requests as _http
    _KW = {"impersonate": "chrome"}
except ImportError:  # yedek
    import requests as _http
    _KW = {"headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }}


class Engellendi(Exception):
    pass


def getir(yol):
    """SofaScore API'den JSON getirir."""
    time.sleep(SOFA_BEKLE_SN)
    r = _http.get(f"{API}{yol}", timeout=20, **_KW)
    if r.status_code == 404:
        return None
    if r.status_code in (403, 429):
        raise Engellendi(f"{r.status_code} - {yol}")
    r.raise_for_status()
    return r.json()


_tm_engelli = False


def tm_sayfa(url):
    """Transfermarkt'tan HTML getirir; engellenirse bu çalıştırmada TM'yi kapatır."""
    global _tm_engelli
    if _tm_engelli:
        return None
    time.sleep(TM_BEKLE_SN)
    try:
        r = _http.get(url, timeout=25, **_KW)
    except Exception as e:
        print(f"Transfermarkt bağlantı hatası: {e}")
        return None
    if r.status_code in (403, 405, 429, 503):
        print(f"Transfermarkt engelledi ({r.status_code}); bu tur SofaScore kullanılacak.")
        _tm_engelli = True
        return None
    if r.status_code != 200:
        return None
    return r.text

# ----------------------------------------------------------------------------
# BİLDİRİM
# ----------------------------------------------------------------------------

def bildir(mesaj, baslik="Kanat-Bek Takip", link=None, dry=False):
    print(mesaj, "\n" + "-" * 40)
    if dry:
        return
    topic = os.getenv("NTFY_TOPIC")
    if topic:
        govde = {"topic": topic, "title": baslik, "message": mesaj, "tags": ["soccer"]}
        if link:
            govde["click"] = link
        try:
            _http.post("https://ntfy.sh/", data=json.dumps(govde).encode("utf-8"),
                       headers={"Content-Type": "application/json"}, timeout=20)
        except Exception as e:
            print(f"ntfy hatası: {e}")
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            _http.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                       data={"chat_id": chat, "text": mesaj + (f"\n{link}" if link else ""),
                             "disable_web_page_preview": "true"})
        except Exception as e:
            print(f"Telegram hatası: {e}")

# ----------------------------------------------------------------------------
# DURUM (daha önce bakılan maçlar + oyuncu mevki önbelleği)
# ----------------------------------------------------------------------------

def durum_oku():
    d = {}
    if DURUM_DOSYASI.exists():
        d = json.loads(DURUM_DOSYASI.read_text(encoding="utf-8"))
    d.setdefault("islenen_maclar", {})
    d.setdefault("oyuncular", {})   # SofaScore id -> {"kodlar": [...], "kaynak": ..., "tm": url}
    d.setdefault("son_engel_uyarisi", "")
    return d


def durum_yaz(d):
    simdi = time.time()
    d["islenen_maclar"] = {k: v for k, v in d["islenen_maclar"].items() if simdi - v < 3 * 86400}
    if len(d["oyuncular"]) > 20000:  # önbellek şişmesin
        d["oyuncular"] = dict(list(d["oyuncular"].items())[-15000:])
    DURUM_DOSYASI.write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")

# ----------------------------------------------------------------------------
# TRANSFERMARKT
# ----------------------------------------------------------------------------

def sade(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def tm_oyuncu_bul(isim, takim):
    """Transfermarkt hızlı aramasında oyuncuyu bulur, profil URL'sini döndürür."""
    html = tm_sayfa(f"{TM}/schnellsuche/ergebnis/schnellsuche?query={quote(isim)}")
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    adaylar = []
    for a in soup.select('td.hauptlink a[href*="/profil/spieler/"]'):
        # sonuç tablosunun (table.items) ana satırı; içteki küçük tabloların satırı değil
        satir = next((tr for tr in a.find_parents("tr")
                      if "items" in (tr.find_parent("table").get("class") or [])), None)
        if not satir:
            continue
        # satırdaki kulüp adı genelde bir link/görselin title/alt'ında
        metin = " ".join(filter(None, [satir.get_text(" ")] +
                                [t.get("title", "") for t in satir.select("[title]")] +
                                [i.get("alt", "") for i in satir.select("img[alt]")]))
        adaylar.append((a["href"].split("?")[0], set(sade(metin))))
    if not adaylar:
        return None
    takim_kelimeleri = {w for w in sade(takim) if len(w) > 2 and w not in {"fc", "club", "sk", "afc", "cf"}}
    for href, kelimeler in adaylar:
        if takim_kelimeleri & kelimeler:
            return TM + href
    return TM + adaylar[0][0] if len(adaylar) == 1 else None


def tm_mevkiler(url):
    """Profil sayfasından [ana_mevki, diğer_mevkiler...] kodlarını döndürür."""
    html = tm_sayfa(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    adlar = []
    kutu = soup.select_one(".detail-position")
    if kutu:
        adlar = [dd.get_text(" ", strip=True) for dd in kutu.select("dd")]
    if not adlar:  # yedek: "Position: Defender - Right-Back"
        m = re.search(r"Position:\s*</span>\s*<span[^>]*>\s*([^<]+)<", html)
        if m:
            adlar = [m.group(1).split("-", 1)[-1].strip() if " - " in m.group(1) else m.group(1)]
    kodlar = []
    for ad in adlar:
        kod = TM_MEVKI.get(ad.strip().lower())
        if kod and kod not in kodlar:
            kodlar.append(kod)
    return kodlar

# ----------------------------------------------------------------------------
# MANTIK
# ----------------------------------------------------------------------------

def kanat_slotlari(formasyon, ilk11):
    """İlk 11'den (sağ_kanat, sol_kanat) oyuncu kayıtlarını döndürür, yoksa None."""
    if formasyon not in KANATLI_DIZILISLER or len(ilk11) != 11:
        return None
    hatlar = [int(x) for x in formasyon.split("-")]
    idx, bas = KANATLI_DIZILISLER[formasyon], 1  # 0 = kaleci
    for h in hatlar[:idx]:
        bas += h
    hat = ilk11[bas: bas + hatlar[idx]]
    ilk, son = hat[0], hat[-1]
    return (ilk, son) if ILK_OYUNCU_SAG else (son, ilk)


def mevkiler(oyuncu, takim, durum):
    """Oyuncunun mevki bilgisini döndürür: {"kodlar": [...], "kaynak": "...", "tm": url|None}"""
    key = str(oyuncu.get("id"))
    if key in durum["oyuncular"]:
        return durum["oyuncular"][key]

    bilgi = None
    if TRANSFERMARKT_KULLAN:
        url = tm_oyuncu_bul(oyuncu.get("name", ""), takim)
        if url:
            kodlar = tm_mevkiler(url)
            if kodlar:
                bilgi = {"kodlar": kodlar, "kaynak": "Transfermarkt", "tm": url}
    if not bilgi:
        veri = getir(f"/player/{key}") or {}
        kodlar = veri.get("player", {}).get("positionsDetailed") or []
        bilgi = {"kodlar": kodlar, "kaynak": "SofaScore", "tm": None}

    # TM engellendiği için SofaScore'a düşüldüyse önbelleğe yazma; sonra TM tekrar denensin
    if not (_tm_engelli and bilgi["kaynak"] == "SofaScore"):
        durum["oyuncular"][key] = bilgi
    return bilgi


def bek_mi(kodlar):
    if not kodlar:
        return False
    return kodlar[0] in BEK_KODLARI if SADECE_ANA_MEVKI else any(k in BEK_KODLARI for k in kodlar)


def kod_yaz(kodlar):
    return ", ".join(f"{KOD_ADLARI.get(k, k)}" for k in kodlar) or "bilinmiyor"


def mac_incele(ev, durum, dry=False, ayrintili=False):
    """Kadro kesinleşmemişse False, incelendiyse True döner."""
    kadro = getir(f"/event/{ev['id']}/lineups")
    if not kadro:
        return False
    if not kadro.get("confirmed") and not ayrintili:
        return False

    lig = ev.get("tournament", {}).get("name", "")
    ulke = ev.get("tournament", {}).get("category", {}).get("name", "")
    ev_sahibi = ev.get("homeTeam", {}).get("name", "?")
    deplasman = ev.get("awayTeam", {}).get("name", "?")
    saat = datetime.fromtimestamp(ev.get("startTimestamp", 0), TR).strftime("%d.%m %H:%M")
    link = f"https://www.sofascore.com/{ev.get('slug', '')}/{ev.get('customId', '')}#id:{ev['id']}"

    for taraf, takim in (("home", ev_sahibi), ("away", deplasman)):
        t = kadro.get(taraf) or {}
        formasyon = t.get("formation", "")
        ilk11 = [p for p in t.get("players", []) if not p.get("substitute")]

        if ayrintili:
            print(f"\n{takim} — {formasyon} (sıra SofaScore'daki gibi):")
            for i, p in enumerate(ilk11):
                pl = p.get("player", {})
                b = mevkiler(pl, takim, durum)
                print(f"  {i:2d}. {pl.get('name')}  ->  {kod_yaz(b['kodlar'])}  ({b['kaynak']})")

        slotlar = kanat_slotlari(formasyon, ilk11)
        if not slotlar:
            continue
        for yan, p in zip(("Sağ", "Sol"), slotlar):
            pl = p.get("player", {})
            b = mevkiler(pl, takim, durum)
            if bek_mi(b["kodlar"]):
                bildir(
                    f"{ev_sahibi} - {deplasman} ({saat})\n"
                    f"{ulke} - {lig}\n"
                    f"Takım: {takim} ({formasyon})\n"
                    f"Oyuncu: {pl.get('name')} → {yan} kanat\n"
                    f"Mevkileri: {kod_yaz(b['kodlar'])} ({b['kaynak']})"
                    + (f"\nTM: {b['tm']}" if b.get("tm") else ""),
                    baslik="Kanatta bek!", link=link, dry=dry,
                )
    return True


def taranacak_maclar():
    simdi = datetime.now(TR)
    maclar = {}
    for gun in {simdi.date(), (simdi + timedelta(minutes=ONCESI_DK)).date()}:
        veri = getir(f"/sport/football/scheduled-events/{gun.isoformat()}") or {}
        for ev in veri.get("events", []):
            maclar[ev["id"]] = ev
    canli = getir("/sport/football/events/live") or {}
    for ev in canli.get("events", []):
        maclar[ev["id"]] = ev

    ts = simdi.timestamp()
    secilen = []
    for ev in maclar.values():
        bas = ev.get("startTimestamp", 0)
        durum_tipi = ev.get("status", {}).get("type", "")
        if durum_tipi in ("finished", "canceled", "postponed"):
            continue
        if bas - ONCESI_DK * 60 <= ts <= bas + SONRASI_DK * 60:
            secilen.append(ev)
    return secilen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Bildirim gönderme")
    ap.add_argument("--mac", type=int, help="Tek bir SofaScore maç ID'sini incele")
    ap.add_argument("--test-bildirim", action="store_true", help="Bildirim kanalını dene")
    a = ap.parse_args()

    if a.test_bildirim:
        bildir("Test mesajı: bildirimler çalışıyor ✅", baslik="Kanat-Bek Takip")
        return

    durum = durum_oku()
    try:
        if a.mac:
            ev = (getir(f"/event/{a.mac}") or {}).get("event")
            if not ev:
                sys.exit("Maç bulunamadı.")
            mac_incele(ev, durum, dry=True, ayrintili=True)
            return

        maclar = taranacak_maclar()
        yeni = [e for e in maclar if str(e["id"]) not in durum["islenen_maclar"]]
        print(f"Zaman aralığındaki maç: {len(maclar)} | henüz incelenmemiş: {len(yeni)}")
        for ev in yeni:
            try:
                if mac_incele(ev, durum, dry=a.dry):
                    durum["islenen_maclar"][str(ev["id"])] = time.time()
            except Engellendi:
                raise
            except Exception as e:  # tek maçtaki hata taramayı durdurmasın
                print(f"Hata (maç {ev.get('id')}): {e}")
        if _tm_engelli:
            print("Not: Bu turda Transfermarkt engelledi, mevkiler SofaScore'dan alındı.")
    except Engellendi as e:
        print(f"SofaScore isteği engelledi: {e}")
        bugun = datetime.now(TR).date().isoformat()
        if durum.get("son_engel_uyarisi") != bugun:
            bildir(f"SofaScore erişimi engelledi ({e}). Bugün tekrar uyarmayacağım.",
                   baslik="Erişim engellendi", dry=a.dry)
            durum["son_engel_uyarisi"] = bugun
    finally:
        if not a.mac:
            durum_yaz(durum)


if __name__ == "__main__":
    main()
