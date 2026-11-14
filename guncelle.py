"""Dünya TV kanal listesini haftalık günceller (GitHub Actions'ta çalışır).

1. Her kanalın yayın adreslerini dener.
2. Hiç adresi çalışmayan kanal için iptv-org'da yeni adres arar, bulursa EKLER (eskiyi silmez;
   bazı adresler yalnızca Türkiye'den çalışabilir, burası yurt dışı sunucu).
3. 3 hafta üst üste hiç çalışmayan kanalı "pasif" işaretler (uygulama soluk gösterir, silmez).
4. iptv-org'a bu ülkelerden YENİ eklenen kanallardan HD (720p+), çalışan, uygun türdekileri ekler
   (ülke başına haftada en fazla 3). İlk çalıştırmada yalnızca mevcut kanalları "görüldü" sayar.
5. Değişiklikleri DEGISIKLIKLER.md'ye ve degisiklik.txt'ye (bildirim için) yazar.
Yalnızca standart kütüphane kullanır.
"""
import concurrent.futures as cf
import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

KOK = Path(__file__).parent
API = 'https://iptv-org.github.io/api/'
LOGO_TABAN = 'https://raw.githubusercontent.com/ahmet3ddd/dunya-tv-kanallar/main/logo/'
ULKELER = {'CN': 'cn', 'JP': 'jp', 'RU': 'ru', 'FR': 'fr'}
TURLER = {'general', 'news', 'documentary', 'culture', 'education', 'science', 'travel', 'entertainment',
          'movies', 'series', 'music', 'kids', 'animation', 'cooking', 'lifestyle', 'classic', 'family'}
HAFTALIK_YENI = 3
PASIF_ESIGI = 3
YENI_GUN = 14
H = {'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/537.36 Chrome/63 Safari/537.36'}
BUGUN = dt.date.today()


def al(u, n=None, t=10):
    r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=t)
    return r.read(n) if n else r.read()


def dene(u):
    """Çalışıyorsa en yüksek dikey çözünürlüğü (bilinmiyorsa 0), çalışmıyorsa None döner."""
    try:
        t = al(u, 300000).decode('utf-8', 'ignore')
        if '#EXTM3U' not in t:
            return None
        res = [int(x) for x in re.findall(r'RESOLUTION=\d+x(\d+)', t)]
        s = [l for l in t.splitlines() if l.strip() and not l.startswith('#')]
        if not s:
            return None
        v = urljoin(u, s[-1].strip())
        if res:
            s2 = [l for l in al(v, 300000).decode('utf-8', 'ignore').splitlines() if l.strip() and not l.startswith('#')]
            v = urljoin(v, s2[-1].strip())
        al(v, 40000, 15)
        return max(res) if res else 0
    except Exception:
        return None


def coklu_dene(urller):
    with cf.ThreadPoolExecutor(24) as ex:
        return dict(zip(urller, ex.map(dene, urller)))


def kalite_etiketi(yuk):
    if yuk >= 1080: return 'FHD'
    if yuk >= 720: return 'HD'
    return 'SD'


def main():
    veri = json.loads((KOK / 'kanallar.json').read_text(encoding='utf-8'))
    durum_yolu = KOK / 'durum.json'
    durum = json.loads(durum_yolu.read_text(encoding='utf-8')) if durum_yolu.exists() else {'gorulen': [], 'hata': {}}
    kanallar = veri['kanallar']
    notlar = []

    akislar = json.loads(al(API + 'streams.json', t=60))
    kanal_bilgi = {c['id']: c for c in json.loads(al(API + 'channels.json', t=60))}
    logolar = {}
    for l in json.loads(al(API + 'logos.json', t=60)):
        if l.get('channel') and l['channel'] not in logolar:
            logolar[l['channel']] = l['url']
    akis_kanal = {}
    for s in akislar:
        if s.get('channel'):
            akis_kanal.setdefault(s['channel'], []).append(s)

    # 1-3: mevcut kanallar
    tum = sorted({u for k in kanallar for u in k['url']})
    sonuc = coklu_dene(tum)
    for k in kanallar:
        calisan = [u for u in k['url'] if sonuc.get(u) is not None]
        if calisan:
            durum['hata'].pop(k['id'], None)
            if k.pop('pasif', None):
                notlar.append(f"✅ {k['ad']} yeniden yayında")
            continue
        durum['hata'][k['id']] = durum['hata'].get(k['id'], 0) + 1
        adaylar = [s['url'] for i in k.get('iptv', []) for s in akis_kanal.get(i, [])
                   if s['url'] not in k['url'] and 'Geo-blocked' not in (s.get('labels') or [])
                   and not s.get('user_agent') and not s.get('referrer')]
        bulunan = sorted(((y, u) for u, y in coklu_dene(adaylar).items() if y is not None), reverse=True)[:2]
        if bulunan:
            k['url'] += [u for _, u in bulunan]
            notlar.append(f"🔧 {k['ad']}: çalışmıyordu, {len(bulunan)} yeni yayın adresi eklendi")
            durum['hata'].pop(k['id'], None)
        elif durum['hata'][k['id']] >= PASIF_ESIGI and not k.get('pasif'):
            k['pasif'] = True
            notlar.append(f"⚠️ {k['ad']}: {PASIF_ESIGI} haftadır yayın yok, pasif işaretlendi")
        # Liste çok uzamasın: 5'ten fazla adres varsa çalışmayan eskileri at
        if len(k['url']) > 5:
            k['url'] = [u for u in k['url'] if sonuc.get(u) is not None or u not in sonuc][-5:]

    # 4: yeni kanallar
    bizdeki = {i for k in kanallar for i in k.get('iptv', [])}
    uygun = [c for c in kanal_bilgi.values()
             if c.get('country') in ULKELER and not c.get('is_nsfw') and not c.get('closed')
             and set(c.get('categories') or []) & TURLER]
    gorulen = set(durum['gorulen'])
    ilk_calisma = not gorulen
    yeni_idler = [c['id'] for c in uygun if c['id'] not in gorulen and c['id'] not in bizdeki]
    durum['gorulen'] = sorted(gorulen | {c['id'] for c in uygun})
    if not ilk_calisma and yeni_idler:
        eklenen = {u: 0 for u in ULKELER.values()}
        aday_akis = []
        for cid in yeni_idler:
            for s in akis_kanal.get(cid, []):
                lab = s.get('labels') or []
                q = int(re.sub(r'\D', '', s.get('quality') or '0') or 0)
                if q >= 720 and 'Geo-blocked' not in lab and 'Not 24/7' not in lab and not s.get('user_agent') and not s.get('referrer'):
                    aday_akis.append((cid, s['url']))
        oncelik = ['documentary', 'culture', 'news', 'general', 'travel', 'science', 'education']
        def sira(a):
            kat = kanal_bilgi[a[0]].get('categories') or []
            return min([oncelik.index(x) for x in kat if x in oncelik] or [len(oncelik)])
        aday_akis.sort(key=sira)
        test = coklu_dene([u for _, u in aday_akis])
        for cid, u in aday_akis:
            y = test.get(u)
            c = kanal_bilgi[cid]
            ulke = ULKELER[c['country']]
            if y is None or (y and y < 720) or eklenen[ulke] >= HAFTALIK_YENI or cid in bizdeki:
                continue
            kid = re.sub(r'[^a-z0-9]', '', cid.lower())[:24]
            kanallar.append({'id': kid, 'ad': c['name'], 'alt': ', '.join(c.get('categories') or [])[:30],
                             'ulke': ulke, 'kalite': kalite_etiketi(y or 720), 'logo': logolar.get(cid, ''),
                             'iptv': [cid], 'url': [u], 'yeni': BUGUN.isoformat()})
            bizdeki.add(cid); eklenen[ulke] += 1
            notlar.append(f"🆕 {c['name']} ({c['country']}) eklendi")

    # Yeni etiketi YENI_GUN gün sonra kalkar
    for k in kanallar:
        if k.get('yeni') and (BUGUN - dt.date.fromisoformat(k['yeni'])).days > YENI_GUN:
            k.pop('yeni')

    if notlar:
        veri['surum'] += 1
        veri['guncelleme'] = BUGUN.isoformat()
    (KOK / 'kanallar.json').write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding='utf-8')
    durum_yolu.write_text(json.dumps(durum, ensure_ascii=False, indent=0), encoding='utf-8')
    metin = '\n'.join('- ' + n for n in notlar)
    (KOK / 'degisiklik.txt').write_text(metin, encoding='utf-8')
    if notlar:
        log = KOK / 'DEGISIKLIKLER.md'
        eski = log.read_text(encoding='utf-8') if log.exists() else '# Değişiklikler\n'
        bas, _, govde = eski.partition('\n')
        log.write_text(f"{bas}\n\n## {BUGUN.isoformat()}\n{metin}\n{govde}", encoding='utf-8')
    print(metin or 'Değişiklik yok.')
    calismayan = [k['ad'] for k in kanallar if durum['hata'].get(k['id'])]
    if calismayan:
        print('Bu hafta yanıt vermeyen (bu sunucudan):', ', '.join(calismayan))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
