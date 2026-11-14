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


def al(u, n=None, t=8):
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
        al(v, 40000, 10)
        return max(res) if res else 0
    except Exception:
        return None


_ONBELLEK = {}


def coklu_dene(urller):
    yeni = [u for u in dict.fromkeys(urller) if u not in _ONBELLEK]
    with cf.ThreadPoolExecutor(64) as ex:
        for u, y in zip(yeni, ex.map(dene, yeni)):
            _ONBELLEK[u] = y
    return {u: _ONBELLEK.get(u) for u in urller}


def kalite_etiketi(yuk):
    if yuk >= 1080: return 'FHD'
    if yuk >= 720: return 'HD'
    return 'SD'


# ---------- Ek ülke kataloğu (TV'de "Ülke ekle" sekmesi) ----------
EK_ULKELER = {
    'TR': 'Türkiye', 'DE': 'Almanya', 'UK': 'İngiltere', 'US': 'ABD', 'IT': 'İtalya', 'ES': 'İspanya',
    'KR': 'Güney Kore', 'IN': 'Hindistan', 'QA': 'Katar', 'AE': 'BAE', 'SA': 'Suudi Arabistan', 'EG': 'Mısır',
    'GR': 'Yunanistan', 'NL': 'Hollanda', 'PT': 'Portekiz', 'BR': 'Brezilya', 'AR': 'Arjantin', 'MX': 'Meksika',
    'CA': 'Kanada', 'AU': 'Avustralya', 'PL': 'Polonya', 'UA': 'Ukrayna', 'AZ': 'Azerbaycan', 'KZ': 'Kazakistan',
    'UZ': 'Özbekistan', 'IR': 'İran', 'PK': 'Pakistan', 'ID': 'Endonezya', 'TH': 'Tayland', 'VN': 'Vietnam',
    'SE': 'İsveç', 'NO': 'Norveç', 'CH': 'İsviçre', 'AT': 'Avusturya', 'BE': 'Belçika', 'TW': 'Tayvan',
    'HK': 'Hong Kong', 'SG': 'Singapur', 'IL': 'İsrail', 'RO': 'Romanya', 'BG': 'Bulgaristan', 'HU': 'Macaristan',
    'CZ': 'Çekya', 'FI': 'Finlandiya', 'DK': 'Danimarka', 'IE': 'İrlanda', 'MA': 'Fas', 'DZ': 'Cezayir',
}
KATALOG_ADET = 12


def ulke_kodu(cc):
    # iptv-org Birleşik Krallık için 'UK' kullanıyor; bayrak/standart kod 'gb'
    return {'UK': 'gb'}.get(cc, cc.lower())
ONCELIK = ['news', 'documentary', 'culture', 'general', 'travel', 'science', 'education', 'entertainment',
           'kids', 'music', 'movies', 'series', 'lifestyle', 'cooking', 'animation', 'classic', 'family']


KAT_SIRA = ['news', 'documentary', 'general', 'culture', 'entertainment', 'movies', 'series', 'music', 'kids',
            'animation', 'sports', 'travel', 'science', 'education', 'lifestyle', 'cooking', 'outdoor', 'auto',
            'business', 'comedy', 'family', 'classic', 'weather', 'relax', 'legislative', 'religious', 'shop']


def tum_listeler(akis_kanal, kanal_bilgi, logolar):
    """Her ülke için çalışan TÜM kanalları tum/<kod>.json'a yazar (TV'de 'Tüm kanallar' seçicisi)."""
    ulkeler = dict(ULKELER)
    ulkeler.update({cc: ulke_kodu(cc) for cc in EK_ULKELER})
    adaylar = {}
    for c in kanal_bilgi.values():
        if c.get('country') not in ulkeler or c.get('is_nsfw') or c.get('closed') or 'xxx' in (c.get('categories') or []):
            continue
        for s_ in akis_kanal.get(c['id'], []):
            lab = s_.get('labels') or []
            if 'Geo-blocked' in lab or s_.get('user_agent') or s_.get('referrer'):
                continue
            q = int(re.sub(r'\D', '', s_.get('quality') or '0') or 0)
            adaylar.setdefault(c['id'], []).append((q, 'Not 24/7' in lab, s_['url']))
    sonuc = coklu_dene([u for v in adaylar.values() for _, _, u in v])
    tdir = KOK / 'tum'
    tdir.mkdir(exist_ok=True)
    sayilar = {}
    for cc, kod in ulkeler.items():
        out = []
        for cid, akis in adaylar.items():
            c = kanal_bilgi[cid]
            if c['country'] != cc:
                continue
            calisan = sorted(((sonuc[u] or q, not n247, u) for q, n247, u in akis if sonuc.get(u) is not None), reverse=True)
            if not calisan:
                continue
            kat = c.get('categories') or ['general']
            out.append({'id': kod + '-' + re.sub(r'[^a-z0-9]', '', cid.lower())[:24], 'ad': c['name'],
                        'kat': kat[0], 'kalite': kalite_etiketi(calisan[0][0] or 480) if calisan[0][0] else '',
                        'logo': logolar.get(cid, ''), 'iptv': [cid], 'url': [u for _, _, u in calisan[:3]]})
        out.sort(key=lambda k: (KAT_SIRA.index(k['kat']) if k['kat'] in KAT_SIRA else 99, k['ad'].lower()))
        (tdir / f'{kod}.json').write_text(json.dumps({'ulke': kod, 'guncelleme': BUGUN.isoformat(), 'kanallar': out},
                                                     ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        sayilar[kod] = len(out)
    print('Tüm kanallar:', ', '.join(f'{k}:{v}' for k, v in sayilar.items()))
    return sayilar


def katalog(akis_kanal, kanal_bilgi, logolar, sayilar=None):
    kdir = KOK / 'katalog'
    kdir.mkdir(exist_ok=True)
    ozet = []
    gorevler = {}
    for cc in EK_ULKELER:
        kod = ulke_kodu(cc)
        eski = {}
        f = kdir / f'{kod}.json'
        if f.exists():
            for k in json.loads(f.read_text(encoding='utf-8')).get('kanallar', []):
                eski[k['iptv'][0]] = k
        aday = []
        for c in kanal_bilgi.values():
            if c.get('country') != cc or c.get('is_nsfw') or c.get('closed') or not set(c.get('categories') or []) & TURLER:
                continue
            for s in akis_kanal.get(c['id'], []):
                lab = s.get('labels') or []
                q = int(re.sub(r'\D', '', s.get('quality') or '0') or 0)
                if 'Geo-blocked' in lab or 'Not 24/7' in lab or s.get('user_agent') or s.get('referrer') or q < 480:
                    continue
                kat = c.get('categories') or []
                r = min([ONCELIK.index(x) for x in kat if x in ONCELIK] or [99])
                aday.append((0 if c['id'] in eski else 1, 0 if q >= 720 else 1, r, -q, c['id'], s['url'], q))
        aday.sort()
        secim, gorulen = [], set()
        for a in aday:
            if a[4] not in gorulen and len(secim) < KATALOG_ADET * 3:
                secim.append(a); gorulen.add(a[4])
        gorevler[cc] = secim
    tum = coklu_dene([a[5] for v in gorevler.values() for a in v])
    for cc, secim in gorevler.items():
        kod = ulke_kodu(cc); kanallar = []
        for a in secim:
            y = tum.get(a[5])
            if y is None or len(kanallar) >= KATALOG_ADET:
                continue
            c = kanal_bilgi[a[4]]
            kanallar.append({'id': kod + '-' + re.sub(r'[^a-z0-9]', '', a[4].lower())[:24], 'ad': c['name'],
                             'alt': ', '.join(c.get('categories') or [])[:30], 'ulke': kod,
                             'kalite': kalite_etiketi(y or a[6]), 'logo': logolar.get(a[4], ''),
                             'iptv': [a[4]], 'url': [a[5]]})
        if len(kanallar) >= 4:
            (kdir / f'{kod}.json').write_text(json.dumps({'ulke': kod, 'ad': EK_ULKELER[cc], 'guncelleme': BUGUN.isoformat(),
                                                         'kanallar': kanallar}, ensure_ascii=False, indent=1), encoding='utf-8')
            ozet.append({'kod': kod, 'ad': EK_ULKELER[cc], 'adet': len(kanallar), 'tum': (sayilar or {}).get(kod, 0)})
    ozet.sort(key=lambda x: x['ad'])
    (KOK / 'katalog.json').write_text(json.dumps({'guncelleme': BUGUN.isoformat(), 'ulkeler': ozet,
                                                  'tum': sayilar or {}},
                                                 ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'Katalog: {len(ozet)} ülke, {sum(o["adet"] for o in ozet)} kanal')


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
    sayilar = tum_listeler(akis_kanal, kanal_bilgi, logolar)
    katalog(akis_kanal, kanal_bilgi, logolar, sayilar)
    print(metin or 'Değişiklik yok.')
    calismayan = [k['ad'] for k in kanallar if durum['hata'].get(k['id'])]
    if calismayan:
        print('Bu hafta yanıt vermeyen (bu sunucudan):', ', '.join(calismayan))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
