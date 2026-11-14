#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stav_pack.py — postavi OFFLINE MAPOVY PACK z OSM .pbf.

⭐ PROC to vzniklo (24. 8. 2026): kamera precte kulatou ceduli, ale NEUMI tri veci,
   ktere rozhoduji o tom, jaky limit doopravdy plati:
     1) jsem v OBCI? (implicitnich 50) a jak se jmenuje — na ceduli s nazvem obce
        je bily obdelnik s textem, OCR na to je nespolehlive
     2) projel jsem KRIZOVATKU? (v CR tim konci platnost znacky) — z kamery nepoznatelne
     3) jake je CISLO SILNICE (D11) do chipu
   ⛔ Limit ze znacky ma PREDNOST (rozhodl uzivatel): cedule na silnici je pravne
      zavazna a aktualni, OSM jsou komunitni data. Mapa jen DOPLNUJE, co kamera neumi.

⭐⭐ VERZE 3 (3. 10. 2026, rozbor jizd 28. 9. a 3. 10.) — co se zmenilo a proc:
   K1  KRIZOVATKA = uzel s >=3 rameny a >=2 RUZNYMI silnicemi (ref/name). Do v1 byl
       krizovatkou kazdy uzel sdileny dvema cestami — 36 % z nich bylo jen ROZDELENI
       OSM cesty (casto prave u znacky) a limit z kamery se rusil hned za cedulí.
       ⚠️ `krizovatky.bin` zustava SE VSEMI sdilenymi uzly (stary Mapa.kt ve voze ho cte
          beze zmeny); ktere z nich jsou skutecne krizovatky, rika novy `kriz_druh.bin`.
   F1  usek BEZ udaje (bez maxspeed, bez priznaku, ne dalnice/MV) zdedi „v obci",
       kdyz prvni urceny usek TEZE silnice (ref) na OBOU stranach je v obci <=50 a cela
       mezera (vlevo + usek + vpravo) ma nejvys 200 m.
       Na Hradecke karta preskakovala obec/mimo na kratkych kouscich bez maxspeed.
   F1b usek s explicitnim maxspeed > 50 NEDOSTANE „v obci" z budov (Stare Hradiste 90).
       Hustota budov se navic bere ze VZORKU kazdych 20 m podel cele cesty s vyhlazenim
       (dira <= 80 m se zaplni, ostruvek < 40 m se zahodi) — ne z jednoho stredu useku.
       Dlouhy usek, na kterem se zastavba meni, se v miste zmeny ROZDELI (Tribrichy: 630 m usek).
   MV  „silnice pro motorova vozidla" z `motorroad=yes`, NE z `highway=trunk`.
       (I/36 v Pardubicich je trunk s maxspeed 50 a karta tam hlasila 110.)
   F4  vrstva ceduli obce z OSM `traffic_sign=city_limit` (8 620 uzlu v CR) + mistni casti
       s vazbou na obec („Pardubice – Drazkovice").
       ⛔ Cedule z mapy je jen OCEKAVANE MISTO s toleranci (rozhodl uzivatel 3. 10.:
          „obcas je znacka jinde nez bod na mape") — kamera ji prebije, kde chybi nebo
          je spatne, plati stavajici logika. Proto se uklada i odstup od silnice a smer.
   GRAF navaznost useku pro chuzi „co plati D m pred vozem PO SILNICI" (nahled). Neuklada
       se zadny dalsi index: useky jedne cesty jsou v souboru ZA SEBOU a konce sdilene
       s jinou cestou jsou oznacene bitem — soused se pak najde v mrizce podle presne
       shodne souradnice konce. Pamet: +0 B na useku.

VSTUP:  czech-republic-latest.osm.pbf (Geofabrik, ~0,88 GB)
VYSTUP: slozka (viz FORMAT nize) — na jednotku se kopiruje cela

FORMAT (male soubory vedle sebe, ne jeden blok — snaz se ladi a portuje do Kotlinu):
  hlavicka.json        bbox, mrizka, pocty, verze, statistika stavby
  segmenty.bin         n × 16 B: lat0,lon0,lat1,lon1 (int32, stupne×1e7)
  seg_meta.bin         n × 4 B:  limit u8 (km/h, 0=neuveden), priznak u8, ref_id u16
                       priznak: bit0 v obci · bit1 dalnice · bit2 silnice pro mot.voz. (motorroad)
                                bit3 konec A je sdileny uzel · bit4 konec B je sdileny uzel
                                bit5 „v obci" jen ODHADEM (budovy/polygon) · bit6 „v obci" ZDEDENO (F1)
                                bit7 jednosmerka ve smeru A->B (oneway=-1 se pri stavbe otoci)
  seg_off.bin/val.bin  CSR mrizka: pro kazdou bunku seznam indexu segmentu
  krizovatky.bin       n × 8 B: lat,lon (int32) — VSECHNY uzly sdilene 2+ vyskyty (jako v1)
  kriz_druh.bin        n × 1 B: 1 = skutecna krizovatka (K1), 0 = jen navazani/rozdeleni cesty
  kriz_off.bin/val.bin CSR mrizka krizovatek
  mista.bin            n × 11 B: lat,lon (int32), typ u8 (1 mesto..4 osada), name_id u16 (jako v1)
  casti.bin            n × 13 B: lat,lon (int32), typ u8, name_id u16, obec_id u16 (0xFFFF = neznama)
                       typ: 1 city 2 town 3 village 4 hamlet 5 suburb 6 quarter 7 neighbourhood
  cedule_obci.bin      n × 20 B: lat,lon (int32), seg i32 (-1 = neprichycena), t u16 (poloha na
                       useku ×65535 od A), name_id u16, smer u8 (0 obe/neuvedeno, 1 po smeru A->B,
                       2 proti), druh u8 (bit0 uzel silnice, bit1 city_limit_end), odstup u16 (dm)
                       — SERAZENO podle seg (binarni hledani pri chuzi po silnici)
  retezce.txt          UTF-8, jeden na radek; index = cislo radku (0-based)

POUZITI:  python stav_pack.py czech-republic-latest.osm.pbf mapa-cz-v3
⚠️ Spoustet ze slozky s .pbf a s RELATIVNI cestou — pyosmium na Windows neprelouska
   diakritiku v ceste („Čínská auta") a spadne na UnicodeDecodeError.
"""
import heapq
import json
import math
import os
import struct
import sys
import time
from array import array

import numpy as np
import osmium

# Silnice, ktere nas zajimaji. ⛔ service/track/path/footway/cycleway vedome VEN —
# je jich vic nez vseho ostatniho dohromady a na limit ani obec nemaji vliv.
SILNICE = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
}
MISTA = {"city": 1, "town": 2, "village": 3, "hamlet": 4}
# ⭐ v3: mistni casti pro text „Obec – Cast". ⛔ locality (pomistni nazvy polí) a
#    isolated_dwelling (samoty) vedome VEN — to nejsou sidla s cedulí.
CASTI = {"city": 1, "town": 2, "village": 3, "hamlet": 4,
         "suburb": 5, "quarter": 6, "neighbourhood": 7}

# ⭐⭐ ZASTAVBA — druhy zdroj priznaku „v obci" (pridano 27. 9. 2026 vecer).
#
# PROC: puvodni pravidlo [je_v_obci] stoji na znackach `maxspeed:type`/`source:maxspeed`
# a na typu silnice. ZMERENO na ceskem .pbf:
#     silnicnich cest celkem            514 603
#     z nich se `maxspeed:type`/`source`  84 006 = 16,3 %
#     PRUTAHY (secondary/tertiary/uncl.) 175 308
#       z nich BEZ jakekoli rychl. znacky 92 441 = 52,7 %  <- slepy bod
# Prave po prutazich se jezdi skrz vesnice, takze uzivateli karta hlasila „mimo obec"
# 144 bodu za sebou, zatimco projizdel ctyrmi vesnicemi (mereno za jizdy 27. 9.).
#
# RESENI: v OSM je 58 333 polygonu `landuse=residential` + 7 430 `farmyard` — hustota,
# kterou ma prakticky kazda ceska vesnice. Usek, jehoz stred lezi uvnitr zastavby,
# bereme jako „v obci".
#
# ⚠️ Zastavena plocha NENI totez co cedule IZ4a — ta stava casto desitky metru pred
#    prvnim domem. Polygon je DOBRY ODHAD, autoritou zustava kamera. Proto se priznak
#    jen PRIDAVA, nikdy neodebira: co uz rozhodly znacky u silnice, zustava.
ZASTAVBA = {"residential", "farmyard", "retail", "commercial"}

# ⭐⭐⭐ HUSTOTA BUDOV — silnejsi signal nez polygony (pridano 27. 9. 2026 vecer).
#
# PROC: polygony `landuse` kresli dobrovolnici rucne a chybi presne tam, kde je
# potrebujeme — Tribrichy i Drazkovice, dve vesnice, kterymi uzivatel PROKAZATELNE
# projel, kolem sebe zadny `residential` nemaji (jen railway/farmland/industrial).
# Budovy jsou naproti tomu v ceskem OSM importovane z RUIAN, je jich 5 034 220
# a nechybi nikde. A „zastavene uzemi" je presne to, co cedule IZ4a znaci.
#
# ZMERENO (budov v okoli ±1 bunky, tj. ~±55 m na sever / ±36 m na vychod):
#     Drazkovice 18 · Tribrichy 19 · Nemosice 21 · Pardubice centrum 14
#     pole mezi vesnicemi 0 · D11 u Podebrad 0 · les 0
# Oddeleni je ciste, zadna seda zona — proto staci prosty prah.
BUD_KROK = 5000      # bunka 0,0005 stupne ≈ 55 × 36 m
BUD_PRAH = 6         # kolik budov v okoli 3×3 bunek znamena „zastavene uzemi"
#                      (stredy obci maji 14-21, okraje 6-10, volna krajina 0-2)

# ⭐⭐ v3 (3. 10. 2026): HUSTOTA PODEL CELE CESTY, NE JEDEN STRED USEKU.
#    Stred useku je jediny vzorek — dlouhy usek s vesnici na jednom konci dopadl podle
#    toho, kam padl stred, a kratke useky u okraje vesnice se preklapely jeden po druhem.
#    Ted se vzorkuje kazdych VZOREK_M podel cele OSM cesty, vzorky se vyhladi
#    (dira <= DIRA_M mezi zastavenymi vzorky se zaplni, zastaveny ostruvek < OSTRUVEK_M
#    se zahodi — samota u silnice neni vesnice) a usek je „v obci", kdyz je zastavena
#    aspon polovina jeho vzorku.
VZOREK_M = 20.0
DIRA_M = 80.0
OSTRUVEK_M = 40.0
DELENI_MIN_M = 40.0   # kratsi usek se nedeli (rozhodne vetsina vzorku)

# ⭐ F1 (3. 10. 2026): jak daleko po TEZE silnici hledat urceny usek na obou stranach.
F1_DOSAH_M = 200.0

# ⭐ F4: samostatna cedule (ne uzel cesty) se prichyti k nejblizsi silnici do tolika metru.
CEDULE_PRICHYT_M = 30.0

# ⚠️ Souradnice drzime jako stupne × 1e7 (int32 staci: 51 × 1e7 < 2^31).
#    Bunka mrizky = 0,01 stupne = 100_000 techto jednotek ≈ 1,1 km na sever, 0,7 km na vychod.
BUNKA = 100_000
M_LAT = 111_132.0


def deg(x):
    return int(round(x * 1e7))


def parse_limit(v):
    """OSM `maxspeed` -> km/h, nebo 0. Zvlada „50", „50 km/h"; „none"/„walk"/„signals" -> 0."""
    if not v:
        return 0
    v = v.strip().lower()
    if v.startswith("cz:"):        # zonove znaceni, ne cislo
        return 0
    cislo = ""
    for ch in v:
        if ch.isdigit():
            cislo += ch
        else:
            break
    if not cislo:
        return 0
    n = int(cislo)
    if "mph" in v:
        n = int(n * 1.609)
    return n if 5 <= n <= 250 else 0


def je_v_obci(t, hw, limit):
    """
    Odhad „uvnitr obce" (v CR = implicitnich 50).
    Poradi podle spolehlivosti: explicitni typ maxspeedu > typ silnice > hodnota 50.
    ⚠️ Je to ODHAD z komunitnich dat, ne pravni skutecnost — proto ma cedule prednost.
    """
    for k in ("maxspeed:type", "source:maxspeed", "zone:maxspeed"):
        val = t.get(k, "")
        if "urban" in val or "zone" in val:
            return True
        if "rural" in val or "motorway" in val or "trunk" in val:
            return False
    if hw in ("residential", "living_street"):
        return True
    if limit and limit <= 50 and hw in ("unclassified", "tertiary", "secondary"):
        return True
    return False


def je_jednosmerka(t, hw):
    """(jednosmerka, otocit). oneway=-1 se pri stavbe OTOCI, at bit7 vzdy znamena A->B."""
    ow = t.get("oneway", "")
    if ow == "-1":
        return True, True
    if ow in ("yes", "true", "1"):
        return True, False
    if ow == "no":
        return False, False
    # implicitni jednosmernost podle OSM wiki: dalnice a kruhovy objezd
    if hw == "motorway" or t.get("junction") in ("roundabout", "circular"):
        return True, False
    return False, False


def smer_cedule(tg):
    """Smer cedule z tagu uzlu VUCI SMERU CESTY: 1 forward, 2 backward, 0 obe/neuvedeno."""
    for k in ("direction", "traffic_sign:direction"):
        v = tg.get(k, "")
        if v == "forward":
            return 1
        if v == "backward":
            return 2
    return 0


def stav(pbf, out, kod_statu=None):
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    stat = {}

    retezce, retezce_id = [], {}
    # ⭐ 13. 11. 2026 (Evropa): index retezcu je u16 → nejvys 65 535. Dosud se nad stropem nazvy
    #    POTICHU zahodily (u CR 23 842, nehrozilo). U velkych statu hrozi → pocitat a hlasit,
    #    pack se pak musi rozdelit na mensi regiony (viz evropa.py).
    zahozeno = [0]

    def sid(s):
        if not s:
            return 0xFFFF
        k = retezce_id.get(s)
        if k is None:
            if len(retezce) >= 0xFFFF:
                zahozeno[0] += 1
                return 0xFFFF
            k = len(retezce)
            retezce_id[s] = k
            retezce.append(s)
        return k

    # ── PRUCHOD 0: uzly — cedule obce (city_limit) a mista/casti ──
    # Jen uzly s filtrem → par sekund.
    print("[0/4] cedule obci a mista…", flush=True)
    cedule = {}               # osm id -> dict
    mista_raw = []            # (lat7, lon7, typ_v1, jmeno)
    casti_raw = []            # (lat7, lon7, typ_v3, jmeno)
    for o in (osmium.FileProcessor(pbf, osmium.osm.NODE)
              .with_filter(osmium.filter.KeyFilter("traffic_sign", "place"))):
        tg = o.tags
        ts = tg.get("traffic_sign", "")
        if "city_limit" in ts:
            cedule[o.id] = dict(lat=deg(o.location.lat), lon=deg(o.location.lon),
                                jm=tg.get("name"), smer=smer_cedule(tg),
                                konec=("city_limit_end" in ts), seg=-1, t=0.0, uzel=False)
        p = tg.get("place")
        jm = tg.get("name")
        if p and jm:
            la, lo = deg(o.location.lat), deg(o.location.lon)
            if p in MISTA:
                mista_raw.append((la, lo, MISTA[p], jm))
            if p in CASTI:
                casti_raw.append((la, lo, CASTI[p], jm))
    print("    cedule obci: %d · mist: %d · casti: %d (%.0f s)"
          % (len(cedule), len(mista_raw), len(casti_raw), time.time() - t0), flush=True)

    # ── PRUCHOD 1: ktere uzly patri 2+ silnicim; ramena a ruzne silnice pro K1 ──
    # Pole + numpy sort je pametove daleko levnejsi nez slovnik (desitky milionu polozek).
    print("[1/4] hledam krizovatky (K1: >=3 ramena a >=2 ruzne silnice)…", flush=True)
    occ_n = array("q")        # osm id uzlu
    occ_a = array("b")        # ramena: koncovy uzel cesty 1, vnitrni 2 (duplicitni konec uzavrene 0)
    occ_k = array("q")        # klic silnice: ref, jinak name, jinak -id cesty
    klic_id = {}
    n_cest = 0
    for o in osmium.FileProcessor(pbf, osmium.osm.WAY).with_filter(osmium.filter.KeyFilter("highway")):
        hw = o.tags.get("highway")
        if hw not in SILNICE:
            continue
        n_cest += 1
        r = o.tags.get("ref")
        nm = o.tags.get("name")
        if r:
            k = klic_id.setdefault("r:" + r, len(klic_id) + 1)
        elif nm:
            k = klic_id.setdefault("n:" + nm, len(klic_id) + 1)
        else:
            k = -o.id
        ns = [nd.ref for nd in o.nodes]
        n = len(ns)
        uzavrena = n > 2 and ns[0] == ns[-1]
        for i in range(n):
            occ_n.append(ns[i])
            if uzavrena:
                # ⚠️ uzaviraci uzel je v seznamu dvakrat: ramena ma 2, ne 4 — ale jako
                #    „sdileny" ho brat MUSIME (chuze po grafu z posledniho useku na prvni)
                occ_a.append(2 if i < n - 1 else 0)
            else:
                occ_a.append(1 if (i == 0 or i == n - 1) else 2)
            occ_k.append(k)
    print("    silnicnich cest: %d, odkazu na uzly: %d (%.0f s)" % (n_cest, len(occ_n), time.time() - t0), flush=True)

    N = np.frombuffer(occ_n, dtype=np.int64)
    A = np.frombuffer(occ_a, dtype=np.int8)
    K = np.frombuffer(occ_k, dtype=np.int64)
    poradi = np.lexsort((K, N))
    Ns = N[poradi]
    Ks = K[poradi]
    As = A[poradi].astype(np.int32)
    del poradi, N, A, K, occ_n, occ_a, occ_k
    novy_uzel = np.empty(len(Ns), dtype=bool)
    novy_uzel[0] = True
    novy_uzel[1:] = Ns[1:] != Ns[:-1]
    start = np.flatnonzero(novy_uzel)
    pocet = np.diff(np.append(start, len(Ns)))
    ramena = np.add.reduceat(As, start)
    novy_klic = novy_uzel.copy()
    novy_klic[1:] |= Ks[1:] != Ks[:-1]
    ruznych = np.add.reduceat(novy_klic.astype(np.int32), start)
    uzly = Ns[start]
    sdil_mask = pocet >= 2
    k1_mask = sdil_mask & (ramena >= 3) & (ruznych >= 2)
    sdilene = set(uzly[sdil_mask].tolist())
    k1 = set(uzly[k1_mask].tolist())
    stat["uzlu_sdilenych_v1"] = len(sdilene)
    stat["krizovatek_k1"] = len(k1)
    stat["sdilene_2_ramena"] = int((sdil_mask & (ramena == 2)).sum())
    stat["sdilene_3plus_ramen_tataz_silnice"] = int((sdil_mask & (ramena >= 3) & (ruznych < 2)).sum())
    del Ns, Ks, As, novy_uzel, novy_klic, start, pocet, ramena, ruznych, uzly, sdil_mask, k1_mask
    print("    sdilenych uzlu (v1 „krizovatky“): %d · z toho K1: %d (%.0f s)"
          % (stat["uzlu_sdilenych_v1"], len(k1), time.time() - t0), flush=True)

    # ── PRUCHOD 2: segmenty + souradnice krizovatek + zastavba + budovy ──
    print("[2/4] ctu geometrii…", flush=True)
    segs = array("i")          # lat0,lon0,lat1,lon1 po ctverici
    meta = bytearray()         # limit u8, priznak u8, ref_id u16
    kriz_xy = array("i")       # lat,lon po dvojici
    kriz_druh = bytearray()
    cesty = array("i")         # zacatek usekù kazde cesty (pro vyhlazeni hustoty podel cesty)

    # ⚠️⚠️ VÝKON: NEiterovat pres vsechny uzly. Cesky .pbf jich ma ~150 milionu a Python
    #    loop pres ne bezi minuty az desitky minut. Souradnice krizovatek pritom dostaneme
    #    ZADARMO — `with_locations()` je doplni primo do uzlu cesty, kterou stejne ctem.
    # ⭐ Polygony zastavby se ctou v TOMTEZ pruchodu. Duvod je vykon: `with_locations()`
    #    stavi index poloh vsech ~150 M uzlu a je to nejdrazsi cast cele stavby —
    #    delat ji dvakrat by build zbytecne zdvojnasobilo.
    poly = []                  # [(lat_min, lat_max, lon_min, lon_max, array('i') lat,lon…)]
    n_poly_otev = 0
    budovy = {}                # bunka -> pocet budov
    n_budov = 0
    n_trunk_bez_mr = 0         # useky: trunk BEZ motorroad=yes (v1 je mel jako silnici pro MV)
    n_mr_ne_trunk = 0          # useky: motorroad=yes na necem jinem nez trunk (v1 je nemel)
    n_trunk_mr = 0

    hotovo_kriz = set()
    for o in (osmium.FileProcessor(pbf)
              .with_locations()
              .with_filter(osmium.filter.KeyFilter("highway", "landuse", "building"))):
        # ⭐ budova staci jako JEDEN bod (prvni uzel) — jde o hustotu, ne o tvar
        if "building" in o.tags:
            if o.type_str() == "w":
                nd = o.nodes[0] if len(o.nodes) else None
                if nd is None or not nd.location.valid():
                    continue
                bla, blo = deg(nd.location.lat), deg(nd.location.lon)
            elif o.type_str() == "n":
                bla, blo = deg(o.location.lat), deg(o.location.lon)
            else:
                continue
            k = (bla // BUD_KROK, blo // BUD_KROK)
            budovy[k] = budovy.get(k, 0) + 1
            n_budov += 1
            continue

        if o.type_str() != "w":
            continue

        lu = o.tags.get("landuse")
        if lu in ZASTAVBA:
            uzly_c = o.nodes
            # jen UZAVRENE cesty; multipolygonove relace v1 vedome vynechava
            if len(uzly_c) >= 4 and uzly_c[0].ref == uzly_c[-1].ref:
                body = array("i")
                for nd in uzly_c:
                    if nd.location.valid():
                        body.append(deg(nd.location.lat))
                        body.append(deg(nd.location.lon))
                if len(body) >= 8:
                    la = body[0::2]; lo = body[1::2]
                    poly.append((min(la), max(la), min(lo), max(lo), body))
            else:
                n_poly_otev += 1
            continue

        hw = o.tags.get("highway")
        if hw not in SILNICE:
            continue
        t = o.tags
        limit = parse_limit(t.get("maxspeed"))
        pr = 0
        if je_v_obci(t, hw, limit):
            pr |= 1
        if hw.startswith("motorway"):
            pr |= 2
        # ⭐⭐ v3: silnice pro motorova vozidla = `motorroad=yes`, NE `highway=trunk`.
        #    Trunk je v CR casto obycejna silnice I. tridy (I/36 v Pardubicich, maxspeed 50)
        #    a v1 na ni hlasil 110. Zakonne IP8 je v OSM prave `motorroad=yes`.
        mr = t.get("motorroad") == "yes"
        if mr and not hw.startswith("motorway"):
            pr |= 4
        jedn, otocit = je_jednosmerka(t, hw)
        if jedn:
            pr |= 128
        rid = sid(t.get("ref"))
        uzly_c = list(o.nodes)
        if otocit:
            uzly_c.reverse()
        cesty.append(len(segs) // 4)
        pred = None
        pred_ref = 0
        for nd in uzly_c:
            if not nd.location.valid():
                pred = None
                continue
            b = (deg(nd.location.lat), deg(nd.location.lon))
            # souradnice krizovatky rovnou odtud — usetri to cely pruchod pres uzly
            if nd.ref in sdilene and nd.ref not in hotovo_kriz:
                hotovo_kriz.add(nd.ref)
                kriz_xy.append(b[0]); kriz_xy.append(b[1])
                kriz_druh.append(1 if nd.ref in k1 else 0)
            if pred is not None:
                i_seg = len(segs) // 4
                segs.append(pred[0]); segs.append(pred[1])
                segs.append(b[0]);    segs.append(b[1])
                p2 = pr
                if pred_ref in sdilene:
                    p2 |= 8
                if nd.ref in sdilene:
                    p2 |= 16
                meta += struct.pack("<BBH", min(limit, 255), p2, rid)
                if hw.startswith("trunk"):
                    if mr:
                        n_trunk_mr += 1
                    else:
                        n_trunk_bez_mr += 1
                elif mr and not hw.startswith("motorway"):
                    n_mr_ne_trunk += 1
                # ⭐ F4: cedule obce, ktera je UZLEM silnice → presne misto na useku
                for oid, tt in ((pred_ref, 0.0), (nd.ref, 1.0)):
                    c = cedule.get(oid)
                    if c is not None and c["seg"] < 0:
                        c["seg"] = i_seg; c["t"] = tt; c["uzel"] = True
                        if c["smer"] and otocit:
                            c["smer"] = 3 - c["smer"]
            pred = b
            pred_ref = nd.ref
    cesty.append(len(segs) // 4)
    stat["useku_trunk_bez_motorroad"] = n_trunk_bez_mr
    stat["useku_trunk_s_motorroad"] = n_trunk_mr
    stat["useku_motorroad_mimo_trunk"] = n_mr_ne_trunk
    print("    zastavba: %d polygonu (%d otevrenych preskoceno) · budov %d ve %d bunkach (%.0f s)"
          % (len(poly), n_poly_otev, n_budov, len(budovy), time.time() - t0), flush=True)
    print("    MV: trunk bez motorroad %d useku (v1 MV, v3 ne) · motorroad mimo trunk %d (v1 ne, v3 MV)"
          % (n_trunk_bez_mr, n_mr_ne_trunk), flush=True)

    n_seg = len(segs) // 4
    S = np.frombuffer(segs, dtype=np.int32).reshape(-1, 4)
    MT = np.frombuffer(bytes(meta), dtype=np.uint8).reshape(-1, 4)
    LIM = MT[:, 0].astype(np.int32)
    PR0 = MT[:, 1].copy()
    RID = MT[:, 2].astype(np.int32) | (MT[:, 3].astype(np.int32) << 8)
    del MT

    # delky useku v metrech (rovinna aproximace, kazdy usek svou sirkou)
    cosl = np.cos(np.radians((S[:, 0].astype(np.float64) + S[:, 2]) / 2e7))
    DL = np.hypot((S[:, 2] - S[:, 0]) / 1e7 * M_LAT, (S[:, 3] - S[:, 1]) / 1e7 * M_LAT * cosl)

    # ── ⭐⭐ DOPLNENI PRIZNAKU „V OBCI" Z BUDOV (vzorky podel cesty) A Z POLYGONU ZASTAVBY ──
    bk = np.array(sorted(budovy.keys()), dtype=np.int64).reshape(-1, 2) if budovy else np.zeros((0, 2), np.int64)
    BKEY = (bk[:, 0] << 21) + bk[:, 1]
    poradi = np.argsort(BKEY)
    BKEY = BKEY[poradi]
    BCNT = np.array([budovy[(int(a), int(b))] for a, b in bk], dtype=np.int32)[poradi]
    del bk, poradi

    def husto(la7, lo7):
        """Budov v okoli 3×3 bunek (~±55 m na sever, ±36 m na vychod) — vektorove."""
        cy = la7 // BUD_KROK
        cx = lo7 // BUD_KROK
        s = np.zeros(len(la7), dtype=np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                q = ((cy + dy) << 21) + (cx + dx)
                ix = np.searchsorted(BKEY, q)
                ix[ix >= len(BKEY)] = 0
                s += np.where(BKEY[ix] == q, BCNT[ix], 0)
        return s

    # kandidat: neni v obci podle tagu, neni dalnice/MV a (F1b) nema maxspeed > 50
    # ⛔⛔ NA DALNICI A SILNICI PRO MOT. VOZIDLA CEDULE OBCE ZE ZAKONA NESTOJI.
    #    Bez tehle vyjimky vyskocily falesne „obce" na dalnicich z 301 na 2396
    #    (a na silnicich pro mot. voz. z 3 657 na 11 374) — zmereno 27. 9. 2026.
    # ⭐ F1b (3. 10. 2026): usek s explicitnim maxspeed > 50 neni „v obci" jen kvuli
    #    budovam. Stare Hradiste: secondary s maxspeed 90 vede kolem domu a karta hlasila
    #    „obec" s devadesatkou — hustota budov rikala obec, cedule mimo obec.
    kand0 = ((PR0 & 1) == 0) & ((PR0 & 6) == 0)
    kand = kand0 & (LIM <= 50)

    # pro srovnani: stare pravidlo (jeden stred useku) na stejnych kandidatech v1
    mid_la = (S[:, 0].astype(np.int64) + S[:, 2]) // 2
    mid_lo = (S[:, 1].astype(np.int64) + S[:, 3]) // 2
    idx0 = np.flatnonzero(kand0)
    stare = np.zeros(n_seg, dtype=bool)
    stare[idx0] = husto(mid_la[idx0], mid_lo[idx0]) >= BUD_PRAH
    stat["v1_stred_useku_obci_z_budov"] = int(stare.sum())
    # F1b: kolik useku s maxspeed > 50 by v1 (stred useku) udelal „v obci" z budov a v3 uz ne
    stat["f1b_useku_vyrazeno"] = int((stare & (LIM > 50)).sum())

    # vzorky kazdych VZOREK_M podel kandidatnich useku
    ik = np.flatnonzero(kand)
    nv = np.maximum(1, np.ceil(DL[ik] / VZOREK_M).astype(np.int64))
    v_seg = np.repeat(ik, nv)
    zac = np.cumsum(nv) - nv
    poz = np.arange(len(v_seg)) - np.repeat(zac, nv)
    frac = (poz + 0.5) / np.repeat(nv, nv)
    v_la = (S[v_seg, 0] + frac * (S[v_seg, 2] - S[v_seg, 0])).astype(np.int64)
    v_lo = (S[v_seg, 1] + frac * (S[v_seg, 3] - S[v_seg, 1])).astype(np.int64)
    v_hust = husto(v_la, v_lo) >= BUD_PRAH
    v_del = np.repeat(DL[ik] / nv, nv)
    del v_la, v_lo, frac, poz, zac
    print("    vzorku hustoty: %d na %d kandidatnich usecich (%.0f s)" % (len(v_seg), len(ik), time.time() - t0), flush=True)

    # vyhlazeni PODEL CESTY: cesty jsou v souboru za sebou → vzorky jedne cesty taky
    cesta_useku = np.zeros(n_seg, dtype=np.int64)
    C = np.frombuffer(cesty, dtype=np.int32)
    C2 = C[1:-1]
    cesta_useku[C2[C2 < n_seg]] = 1
    cesta_useku = np.cumsum(cesta_useku)
    v_cesta = cesta_useku[v_seg]
    hranice = np.flatnonzero(np.diff(v_cesta)) + 1
    hranice = np.concatenate(([0], hranice, [len(v_seg)]))
    vyhl = v_hust.copy()
    vh = v_hust.tolist(); vd = v_del.tolist()
    vy = vyhl.tolist()
    n_dir = n_ostr = 0
    for a, b in zip(hranice[:-1].tolist(), hranice[1:].tolist()):
        if b - a < 2:
            continue
        # behy stejne hodnoty: (hodnota, od, do, delka_m)
        behy = []
        i = a
        while i < b:
            j = i; dl = 0.0
            while j < b and vh[j] == vh[i]:
                dl += vd[j]; j += 1
            behy.append([vh[i], i, j, dl])
            i = j
        # 1) dira mezi dvema zastavenymi behy <= DIRA_M → zastaveno
        for q in range(1, len(behy) - 1):
            h, i0, i1, dl = behy[q]
            if not h and behy[q - 1][0] and behy[q + 1][0] and dl <= DIRA_M:
                for x in range(i0, i1):
                    vy[x] = True
                n_dir += 1
        # 2) zastaveny ostruvek < OSTRUVEK_M (po zaplneni der) → nezastaveno
        i = a
        while i < b:
            j = i; dl = 0.0
            while j < b and vy[j] == vy[i]:
                dl += vd[j]; j += 1
            if vy[i] and dl < OSTRUVEK_M:
                for x in range(i, j):
                    vy[x] = False
                n_ostr += 1
            i = j
    vyhl = np.array(vy, dtype=bool)
    # usek je „v obci", kdyz je zastavena aspon polovina jeho vzorku
    zast = np.bincount(v_seg, weights=vyhl.astype(np.float64), minlength=n_seg)
    vsech = np.bincount(v_seg, minlength=n_seg)
    obec_bud = np.zeros(n_seg, dtype=bool)
    obec_bud[ik] = zast[ik] >= 0.5 * vsech[ik]
    stat["v3_zaplnenych_der"] = n_dir
    stat["v3_zahozenych_ostruvku"] = n_ostr

    # ── ⭐⭐ DELENI DLOUHYCH USEKU NA HRANICI ZASTAVBY (3. 10. 2026) ──
    #    Usek je mezi dvema uzly OSM a na rovince za vesnici byva i 600 m dlouhy (III/32232
    #    u Tribrichu: jediny usek 630 m, vesnice zabira jeho druhou pulku). Jeden priznak na
    #    cely usek = hranice obce se posune o stovky metru (Tribrichy 28. 9.: 34 s „mimo obec"
    #    uvnitr vesnice). Kde se vyhlazene vzorky na useku MENI, usek se rozdeli v miste zmeny
    #    na kusy. Kusy jdou v souboru ZA SEBOU, vnitrni spoje nejsou sdilene uzly (bity 3/4
    #    jen na puvodnich koncich) → chuze po grafu i stary Mapa.kt je ctou beze zmeny.
    zac_v = np.cumsum(nv) - nv
    smis = np.flatnonzero((zast[ik] > 0) & (zast[ik] < vsech[ik]) & (DL[ik] >= DELENI_MIN_M))
    deleni = {}
    for q in smis.tolist():
        i = int(ik[q]); n = int(nv[q]); a = int(zac_v[q])
        fl = vy[a:a + n]
        kusy = []
        k0 = 0
        for k in range(1, n + 1):
            if k == n or fl[k] != fl[k0]:
                kusy.append((k0 / n, k / n, fl[k0]))
                k0 = k
        if len(kusy) > 1:
            deleni[i] = kusy
    del v_seg, v_hust, v_del, vh, vd, vy, vyhl, zast, vsech, v_cesta
    pocet_kusu = np.ones(n_seg, dtype=np.int64)
    for i, kusy in deleni.items():
        pocet_kusu[i] = len(kusy)
    nove_od = np.cumsum(pocet_kusu) - pocet_kusu
    n2 = int(pocet_kusu.sum())
    S2 = np.empty((n2, 4), dtype=np.int32)
    jeden = pocet_kusu == 1
    S2[nove_od[jeden]] = S[jeden]
    LIM_2 = np.repeat(LIM, pocet_kusu)
    PR0_2 = np.repeat(PR0, pocet_kusu)
    RID_2 = np.repeat(RID, pocet_kusu)
    kand_2 = np.repeat(kand, pocet_kusu)
    obec_bud_2 = np.repeat(obec_bud, pocet_kusu)
    for i, kusy in deleni.items():
        z = int(nove_od[i])
        la0, lo0, la1, lo1 = (int(x) for x in S[i])
        body = [(la0, lo0)]
        for f0, f1, _fl in kusy[:-1]:
            body.append((int(round(la0 + f1 * (la1 - la0))), int(round(lo0 + f1 * (lo1 - lo0)))))
        body.append((la1, lo1))
        for q, (f0, f1, fl) in enumerate(kusy):
            S2[z + q] = (body[q][0], body[q][1], body[q + 1][0], body[q + 1][1])
            p = int(PR0[i])
            if q > 0:
                p &= ~8          # vnitrni spoj neni sdileny uzel
            if q < len(kusy) - 1:
                p &= ~16
            PR0_2[z + q] = p
            obec_bud_2[z + q] = bool(fl)
    # cedule obce na uzlu silnice: t=0 → prvni kus, t=1 → posledni kus
    for c in cedule.values():
        if c["seg"] >= 0:
            c["seg"] = int(nove_od[c["seg"]]) if c["t"] == 0.0 else int(nove_od[c["seg"]] + pocet_kusu[c["seg"]] - 1)
    stat["v3_rozdelenych_useku"] = len(deleni)
    stat["v3_useku_po_deleni"] = n2
    print("    rozdeleno %d useku na hranici zastavby → %d useku celkem (bylo %d)"
          % (len(deleni), n2, n_seg), flush=True)
    n_seg = n2
    S = S2
    LIM, PR0, RID, kand, obec_bud = LIM_2, PR0_2, RID_2, kand_2, obec_bud_2
    del S2, LIM_2, PR0_2, RID_2, kand_2, obec_bud_2
    segs = array("i")
    segs.frombytes(S.tobytes())
    cosl = np.cos(np.radians((S[:, 0].astype(np.float64) + S[:, 2]) / 2e7))
    DL = np.hypot((S[:, 2] - S[:, 0]) / 1e7 * M_LAT, (S[:, 3] - S[:, 1]) / 1e7 * M_LAT * cosl)
    mid_la = (S[:, 0].astype(np.int64) + S[:, 2]) // 2
    mid_lo = (S[:, 1].astype(np.int64) + S[:, 3]) // 2
    stat["v3_vzorky_obci_z_budov"] = int(obec_bud.sum())


    # polygon zastavby — doplnek tam, kde budovy nestaci (stred useku, jako v1)
    idx = {}
    for pi in range(len(poly)):
        la0, la1, lo0, lo1, _b = poly[pi]
        for cy in range(la0 // BUNKA, la1 // BUNKA + 1):
            for cx in range(lo0 // BUNKA, lo1 // BUNKA + 1):
                idx.setdefault((cy, cx), []).append(pi)

    # ⛔⛔ ZKOUSENO A ZAMITNUTO 27. 9. 2026: tolerance 25 m od hrany polygonu
    #    + test OBOU KONCU useku misto jen stredu. Vypadalo to jako zlepseni,
    #    MERENI to zamitlo:
    #        varianta          v obci   falesne „obec" na DALNICI   stopa uzivatele
    #        puvodni           57,3 %              207                 0/144
    #        stred useku       66,5 %              301                68/144   <- nasazeno
    #        +25 m + konce     71,2 %             2180                80/144
    #    Dvanact bodu navic na stope za DESETINASOBEK falesnych obci na dalnicich
    #    je spatny obchod — tolerance chyta silnice, ktere kolem zastavby jen projedou.
    def uvnitr(pi, lat, lon):
        """Paprskovy test nad celociselnymi souradnicemi (stupne × 1e7)."""
        la0, la1, lo0, lo1, b = poly[pi]
        if lat < la0 or lat > la1 or lon < lo0 or lon > lo1:
            return False
        je = False
        n = len(b) // 2
        j = n - 1
        for i in range(n):
            yi = b[2 * i]; xi = b[2 * i + 1]
            yj = b[2 * j]; xj = b[2 * j + 1]
            if (yi > lat) != (yj > lat):
                if xi + (lat - yi) * (xj - xi) / (yj - yi) > lon:
                    je = not je
            j = i
        return je

    z_polygonu = 0
    obec_pol = np.zeros(n_seg, dtype=bool)
    for i in np.flatnonzero(kand & ~obec_bud).tolist():
        lat = int(mid_la[i]); lon = int(mid_lo[i])
        kd = idx.get((lat // BUNKA, lon // BUNKA))
        if not kd:
            continue
        for pi in kd:
            if uvnitr(pi, lat, lon):
                obec_pol[i] = True
                z_polygonu += 1
                break
    stat["v3_obci_z_polygonu"] = z_polygonu
    PR = PR0.copy()
    PR[obec_bud | obec_pol] |= 1 | 32
    del poly, idx, budovy, BKEY, BCNT
    print("    doplneno: %d useku z BUDOV (v1 stredem by bylo %d) + %d z polygonu · F1b vyradilo %d (%.0f s)"
          % (int(obec_bud.sum()), int(stare.sum()), z_polygonu, stat["f1b_useku_vyrazeno"], time.time() - t0), flush=True)

    # ── ⭐⭐ F1: neurceny usek zdedi „v obci <=50" od TEZE silnice na obou stranach ──
    #    Na Hradecke (II/324) mezi useky s maxspeed 50 lezely kratke kousky BEZ maxspeed
    #    a bez budov — karta na nich skocila na „mimo obec 90" a za 20 m zpet na 50.
    #    ⚠️ Dedi se jen z USEKU S UDAJEM (puvodni stav), ne retezove z jiz zdedenych.
    LIM2 = LIM.copy()
    urceny = (LIM > 0) | ((PR & 7) != 0)
    sref = RID != 0xFFFF
    nekand = np.flatnonzero(~urceny & sref)
    stat["f1_kandidatu"] = int(len(nekand))
    ri = np.flatnonzero(sref)
    kA = (S[ri, 0].astype(np.int64) << 31) + S[ri, 1]
    kB = (S[ri, 2].astype(np.int64) << 31) + S[ri, 3]
    EK = np.concatenate((kA, kB))
    ES = np.concatenate((ri, ri)).astype(np.int64)
    poradi = np.argsort(EK, kind="stable")
    EK = EK[poradi]; ES = ES[poradi]
    del kA, kB, poradi
    EKl = EK  # pro searchsorted
    S_l = S
    urc_l = urceny
    obec_l = (PR & 1) != 0

    def sousedi(key):
        a = int(np.searchsorted(EKl, key, "left"))
        b = a
        n = len(EKl)
        while b < n and EKl[b] == key:
            b += 1
        return ES[a:b].tolist()

    def prvni_urceny(i, konec):
        """Dijkstra po usecich se stejnym ref od konce `konec` (0=A, 1=B) do F1_DOSAH_M."""
        r = RID[i]
        if konec == 0:
            k0 = (int(S_l[i, 0]) << 31) + int(S_l[i, 1])
        else:
            k0 = (int(S_l[i, 2]) << 31) + int(S_l[i, 3])
        vid = {i}
        fr = [(0.0, k0)]
        while fr:
            d, key = heapq.heappop(fr)
            for j in sousedi(key):
                if j in vid or RID[j] != r:
                    continue
                vid.add(j)
                if urc_l[j]:
                    return j, d
                L = DL[j]
                if d + L > F1_DOSAH_M:
                    continue
                ka = (int(S_l[j, 0]) << 31) + int(S_l[j, 1])
                dal = (int(S_l[j, 2]) << 31) + int(S_l[j, 3]) if ka == key else ka
                heapq.heappush(fr, (d + L, dal))
        return -1, 0.0

    # ⛔⛔ CELA MEZERA <= F1_DOSAH_M (oprava 3. 10. 2026 po prehrani jizdy 28. 9.):
    #    prvni verze brala „do 200 m na kazde strane" BEZ delky useku samotneho — jediny
    #    630 m dlouhy usek mezi Drenici a dalsi vesnici (III/32232) tak zdedil „obec"
    #    a karta by hlasila 50 v poli mezi cedulemi (19 z 25 s spatne). Dedi se jen kratka
    #    dira: vzdalenost k urcenemu useku vlevo + delka useku + vpravo <= 200 m.
    n_f1 = 0
    for i in nekand.tolist():
        a, da = prvni_urceny(i, 0)
        if a < 0 or not obec_l[a] or LIM[a] > 50 or da + DL[i] > F1_DOSAH_M:
            continue
        b, db = prvni_urceny(i, 1)
        if b < 0 or not obec_l[b] or LIM[b] > 50 or da + DL[i] + db > F1_DOSAH_M:
            continue
        PR[i] |= 1 | 64
        LIM2[i] = LIM[a] if LIM[a] == LIM[b] else 0
        n_f1 += 1
    stat["f1_zdedeno"] = n_f1
    del EK, ES
    print("    F1: %d neurcenych useku s ref, zdedilo „v obci“ %d (%.0f s)"
          % (len(nekand), n_f1, time.time() - t0), flush=True)

    meta_np = np.zeros((n_seg, 4), dtype=np.uint8)
    meta_np[:, 0] = np.minimum(LIM2, 255)
    meta_np[:, 1] = PR
    meta_np[:, 2] = RID & 0xFF
    meta_np[:, 3] = RID >> 8
    meta = meta_np.tobytes()
    del meta_np

    # ── mista (v1 beze zmeny) + mistni casti s vazbou na obec ──
    mista = bytearray()
    for la, lo, typ, jm in mista_raw:
        mista += struct.pack("<iiBH", la, lo, typ, sid(jm))
    obce_casti = priradit_obce(pbf, [(c[0], c[1]) for c in casti_raw], t0)
    casti = bytearray()
    n_s_obci = 0
    for (la, lo, typ, jm), ob in zip(casti_raw, obce_casti):
        oid = sid(ob) if ob else 0xFFFF
        if oid != 0xFFFF:
            n_s_obci += 1
        casti += struct.pack("<iiBHH", la, lo, typ, sid(jm), oid)
    stat["casti_s_obci"] = n_s_obci

    n_kriz = len(kriz_xy) // 2
    print("    segmentu: %d · krizovatek se souradnici: %d (K1 %d) · mist: %d · casti %d (%.0f s)"
          % (n_seg, n_kriz, sum(kriz_druh), len(mista) // 11, len(casti) // 13, time.time() - t0), flush=True)

    # ── PRUCHOD 3: prostorova mrizka (CSR) ──
    print("[3/4] stavim mrizku…", flush=True)
    lat_min = min(segs[0::4]) if n_seg else 0
    lat_max = max(segs[0::4]) if n_seg else 0
    lon_min = min(segs[1::4]) if n_seg else 0
    lon_max = max(segs[1::4]) if n_seg else 0
    # bunky pocitame od zaokrouhlenych hranic, at je mrizka stabilni
    lat0 = (lat_min // BUNKA) * BUNKA
    lon0 = (lon_min // BUNKA) * BUNKA
    nx = int((lon_max - lon0) // BUNKA) + 1
    ny = int((lat_max - lat0) // BUNKA) + 1

    def bunky_segmentu(i):
        """Segment muze protnout vic bunek — zapiseme ho do bunek obou koncu i mezi ne."""
        a_y = (segs[4 * i] - lat0) // BUNKA
        a_x = (segs[4 * i + 1] - lon0) // BUNKA
        b_y = (segs[4 * i + 2] - lat0) // BUNKA
        b_x = (segs[4 * i + 3] - lon0) // BUNKA
        for yy in range(min(a_y, b_y), max(a_y, b_y) + 1):
            for xx in range(min(a_x, b_x), max(a_x, b_x) + 1):
                if 0 <= xx < nx and 0 <= yy < ny:
                    yield yy * nx + xx

    def csr(pocet_polozek, gen):
        pocty = array("i", bytes(4 * (nx * ny)))
        for i in range(pocet_polozek):
            for c in gen(i):
                pocty[c] += 1
        off = array("i", bytes(4 * (nx * ny + 1)))
        s = 0
        for c in range(nx * ny):
            off[c] = s
            s += pocty[c]
        off[nx * ny] = s
        kur = array("i", off[:nx * ny])
        val = array("i", bytes(4 * s))
        for i in range(pocet_polozek):
            for c in gen(i):
                val[kur[c]] = i
                kur[c] += 1
        return off, val

    seg_off, seg_val = csr(n_seg, bunky_segmentu)

    def bunky_kriz(i):
        yy = (kriz_xy[2 * i] - lat0) // BUNKA
        xx = (kriz_xy[2 * i + 1] - lon0) // BUNKA
        if 0 <= xx < nx and 0 <= yy < ny:
            yield yy * nx + xx

    kriz_off, kriz_val = csr(n_kriz, bunky_kriz)

    # ── [4/4] cedule obci: samostatne uzly prichytit k nejblizsi silnici ──
    print("[4/4] cedule obci…", flush=True)
    n_prich = n_neprich = 0
    for c in cedule.values():
        la7, lo7 = c["lat"], c["lon"]
        m_lon = M_LAT * math.cos(math.radians(la7 / 1e7))
        if c["seg"] >= 0:
            i = c["seg"]
            # uzel cesty: presne na konci useku, odstup 0
            c["odstup"] = 0.0
            continue
        x0 = (lo7 - lon0) // BUNKA
        y0 = (la7 - lat0) // BUNKA
        nej, nej_d, nej_t = -1, 1e18, 0.0
        for yy in range(y0 - 1, y0 + 2):
            if not (0 <= yy < ny):
                continue
            for xx in range(x0 - 1, x0 + 2):
                if not (0 <= xx < nx):
                    continue
                cc = yy * nx + xx
                for i in seg_val[seg_off[cc]:seg_off[cc + 1]]:
                    ax = (segs[4 * i + 1] - lo7) / 1e7 * m_lon; ay = (segs[4 * i] - la7) / 1e7 * M_LAT
                    bx = (segs[4 * i + 3] - lo7) / 1e7 * m_lon; by = (segs[4 * i + 2] - la7) / 1e7 * M_LAT
                    dx, dy = bx - ax, by - ay
                    dd = dx * dx + dy * dy
                    tt = 0.0 if dd == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / dd))
                    d = math.hypot(ax + tt * dx, ay + tt * dy)
                    if d < nej_d:
                        nej, nej_d, nej_t = i, d, tt
        if nej >= 0 and nej_d <= CEDULE_PRICHYT_M:
            c["seg"] = nej; c["t"] = nej_t; c["odstup"] = nej_d
            c["smer"] = 0      # smer forward/backward bez cesty nema vyznam
            n_prich += 1
        else:
            c["odstup"] = 0.0
            n_neprich += 1
    stat["cedule_uzel_silnice"] = sum(1 for c in cedule.values() if c["uzel"])
    stat["cedule_prichyceno"] = n_prich
    stat["cedule_neprichyceno"] = n_neprich
    print("    cedule: %d uzlem silnice, %d prichyceno do %.0f m, %d bez silnice"
          % (stat["cedule_uzel_silnice"], n_prich, CEDULE_PRICHYT_M, n_neprich), flush=True)
    ced = sorted(cedule.values(), key=lambda c: (c["seg"] if c["seg"] >= 0 else 1 << 31, c["t"]))
    cedule_bin = bytearray()
    for c in ced:
        cedule_bin += struct.pack("<iiiHHBBH", c["lat"], c["lon"], c["seg"],
                                  int(round(c["t"] * 65535)), sid(c["jm"]), c["smer"],
                                  (1 if c["uzel"] else 0) | (2 if c["konec"] else 0),
                                  min(65535, int(round(c["odstup"] * 10))))

    # ── zapis ──
    def zapis(jm, data):
        with open(os.path.join(out, jm), "wb") as f:
            f.write(data)
        return os.path.getsize(os.path.join(out, jm))

    velikosti = {}
    velikosti["segmenty.bin"] = zapis("segmenty.bin", segs.tobytes())
    velikosti["seg_meta.bin"] = zapis("seg_meta.bin", bytes(meta))
    velikosti["seg_off.bin"] = zapis("seg_off.bin", seg_off.tobytes())
    velikosti["seg_val.bin"] = zapis("seg_val.bin", seg_val.tobytes())
    velikosti["krizovatky.bin"] = zapis("krizovatky.bin", kriz_xy.tobytes())
    velikosti["kriz_druh.bin"] = zapis("kriz_druh.bin", bytes(kriz_druh))
    velikosti["kriz_off.bin"] = zapis("kriz_off.bin", kriz_off.tobytes())
    velikosti["kriz_val.bin"] = zapis("kriz_val.bin", kriz_val.tobytes())
    velikosti["mista.bin"] = zapis("mista.bin", bytes(mista))
    velikosti["casti.bin"] = zapis("casti.bin", bytes(casti))
    velikosti["cedule_obci.bin"] = zapis("cedule_obci.bin", bytes(cedule_bin))
    # konce radku NATVRDO LF (viz poznamka u formatu) — jinak Windows zapise CRLF
    with open(os.path.join(out, "retezce.txt"), "w", encoding="utf-8", newline=chr(10)) as f:
        f.write("\n".join(s.replace("\n", " ") for s in retezce))
    velikosti["retezce.txt"] = os.path.getsize(os.path.join(out, "retezce.txt"))

    hl = {
        "verze": 3, "zdroj": os.path.basename(pbf),
        "lat0": lat0, "lon0": lon0, "bunka": BUNKA, "nx": nx, "ny": ny,
        "n_seg": n_seg, "n_kriz": n_kriz, "n_mist": len(mista) // 11,
        "n_retezcu": len(retezce),
        "n_kriz_k1": int(sum(kriz_druh)), "n_casti": len(casti) // 13,
        "n_cedul": len(cedule_bin) // 20,
        "postaveno_s": round(time.time() - t0, 1),
        "statistika": stat,
    }
    # ⭐ 13. 11. 2026 (Evropa): klice jen kdyz jsou potreba → pack CR zustava stejny jako dosud
    if kod_statu:
        hl["stat"] = kod_statu
    if zahozeno[0]:
        hl["retezce_zahozeno"] = zahozeno[0]
        print("\n⛔ PRETEKL STROP RETEZCU (65 535): zahozeno %d nazvu/ref — pack ROZDELIT na regiony!"
              % zahozeno[0], flush=True)
    with open(os.path.join(out, "hlavicka.json"), "w", encoding="utf-8") as f:
        json.dump(hl, f, ensure_ascii=False, indent=1)

    celkem = sum(velikosti.values())
    print("\nHOTOVO za %.0f s -> %s" % (time.time() - t0, out))
    for k, v in sorted(velikosti.items(), key=lambda x: -x[1]):
        print("   %-16s %8.2f MB" % (k, v / 1048576))
    print("   %-16s %8.2f MB" % ("CELKEM", celkem / 1048576))
    print("   mrizka %d×%d bunek" % (nx, ny))
    print(json.dumps(stat, ensure_ascii=False, indent=1))


def priradit_obce(pbf, body, t0):
    """
    ⭐ v3: ke kazde mistni casti najde OBEC (hranice admin_level=8), ve ktere lezi —
    at jde na karte napsat „Pardubice – Drazkovice". Bod mista ma jen `ref:cobe`
    (kod casti obce), vazbu na obec v nem OSM nema, proto hranice.
    Vraci seznam jmen obci (None = nenalezeno). Vic obci obsahuje bod → bere se ta
    s nejmensi obalkou (enklavy).
    """
    print("    hranice obci (admin_level=8)…", flush=True)
    obce = []
    fp = (osmium.FileProcessor(pbf)
          .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
          .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA))
          .with_filter(osmium.filter.TagFilter(("admin_level", "8"))))
    for a in fp:
        jm = a.tags.get("name")
        if not jm:
            continue
        for outer in a.outer_rings():
            r = np.array([(n.lat, n.lon) for n in outer], dtype=np.float64)
            if len(r) >= 4:
                obce.append((jm, r))
    print("    obci (vnejsich prstencu): %d (%.0f s)" % (len(obce), time.time() - t0), flush=True)
    if not body:
        return []
    P = np.array(body, dtype=np.float64) / 1e7
    vys = [None] * len(body)
    plocha = np.full(len(body), np.inf)
    for jm, r in obce:
        la0, lo0 = r[:, 0].min(), r[:, 1].min()
        la1, lo1 = r[:, 0].max(), r[:, 1].max()
        m = np.flatnonzero((P[:, 0] >= la0) & (P[:, 0] <= la1) & (P[:, 1] >= lo0) & (P[:, 1] <= lo1))
        if not len(m):
            continue
        y = P[m, 0][:, None]; x = P[m, 1][:, None]
        yi = r[:-1, 0][None, :]; xi = r[:-1, 1][None, :]
        yj = r[1:, 0][None, :]; xj = r[1:, 1][None, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            kriz = ((yi > y) != (yj > y)) & (x < xi + (y - yi) * (xj - xi) / (yj - yi))
        uvn = (kriz.sum(axis=1) % 2) == 1
        pl = (la1 - la0) * (lo1 - lo0)
        for k in m[uvn].tolist():
            if pl < plocha[k]:
                plocha[k] = pl
                vys[k] = jm
    return vys


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    # 3. argument (nepovinny): ISO kod statu do hlavicky, napr. „DE" (Evropa, 13. 11. 2026)
    stav(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
