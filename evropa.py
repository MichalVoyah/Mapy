#!/usr/bin/env python3
"""
🌍 EVROPA — stáhne státy Evropy z Geofabriku a postaví TSR pack PO STÁTECH (13. 11. 2026).

Proč po státech: jeden evropský pack nejde — index řetězců je u16 (strop 65 535, viz
stav_pack.py), mřížka přes celý bbox Evropy by byla ~2 × 100 MB prázdného moře a stavba by
nevešla do RAM. Velký stát (zdroj nad --prah-gb) se staví po REGIONECH Geofabriku (Německo
po spolkových zemích…); každý region dostane v hlavičce `"stat"` kód svého státu.

⛔ Běží ve WSL (Ubuntu): na Windows osmium blokuje Smart App Control (13. 11. 2026).

    python3 evropa.py                     # celá Evropa (bez --bez)
    python3 evropa.py --jen at,sk         # jen vybrané státy (ISO kódy)
    python3 evropa.py --suchy             # jen vypíše plán (velikosti, rozdělení), nic nestahuje

☁️ Cloud (GitHub Actions, 14. 11. 2026 — `.github/workflows/mapy.yml`, `publikuj.py`):
    python3 evropa.py --suchy --plan-ven plan.json         # plán JEDNOU (velikosti se na Geofabriku mění)
    python3 evropa.py --plan plan.json --dil 3/8 --zip-do dist --uklid
        → jen 3. z 8 dílů plánu, každý pack zabalí do dist/<id>.zip + řádek do dist/manifest-3.tsv,
          zdroj i rozbalený pack hned smaže (disk runneru)

Pracovní složka ~/mapy-evropa:
    pbf/<id>.osm.pbf     zdroje (zůstávají — měsíční aktualizace je pak jen přestavba)
    out/<id>/            hotové packy (id s „/" → „__", např. germany__bayern)
    souhrn.tsv           řádek na pack: id, stát, MB zdroje, MB packu, úseků, řetězců, zahozeno, s, RAM MB
    evropa.log           průběh

Opakované spuštění POKRAČUJE: hotový pack (out/<id>/hlavicka.json) se přeskočí, rozestavěný
(out/<id>.tmp) se staví znovu. Stahuje vždy o jeden stát NAPŘED, ať stavba nečeká na síť.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

INDEX_URL = "https://download.geofabrik.de/index-v1-nogeom.json"
UA = {"User-Agent": "tsr-pack-builder/1.0"}          # obecné jméno, žádné osobní údaje
STAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stav_pack.py")
PRAC = os.path.expanduser(os.environ.get("TSR_MAPY_PRAC", "~/mapy-evropa"))
PBF, OUT = os.path.join(PRAC, "pbf"), os.path.join(PRAC, "out")
LOG, SOUHRN = os.path.join(PRAC, "evropa.log"), os.path.join(PRAC, "souhrn.tsv")
# Mimo Evropskou unii a okolí, kam se autem reálně nejezdí, nebo převážně v Asii (velké zdroje).
BEZ_VYCHOZI = "by,ru,ua,tr,ge"
STROP_STAVBY_S = 2700


def log(m):
    s = "[%s] %s" % (time.strftime("%H:%M:%S"), m)
    print(s, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


def http(url, metoda="GET"):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=metoda), timeout=60)


def velikost(url):
    with http(url, "HEAD") as r:
        return int(r.headers.get("Content-Length", "0"))


def bezpecne(id_):
    return id_.replace("/", "__")


# Regiony mimo evropskou pevninu (jiné kontinenty), kam se autem nejede — vynechat.
# ⚠️ 14. 11. 2026: Geofabrik má id BEZ „france/" — se starým zápisem se zámoří stavělo (Martinik v cloudu).
VYNECHAT_REGIONY = {"guadeloupe", "guyane", "martinique", "mayotte", "reunion",
                    "france/guadeloupe", "france/guyane", "france/martinique", "france/mayotte", "france/reunion"}

# Státy, které Geofabrik vede bez ISO 3166-1 kódu, ale autem se přes ně jezdí (13. 11. 2026).
ISO_NAVIC = {"kosovo": "XK"}


def iso(p):
    a = p.get("iso3166-1:alpha2") or []
    return a[0] if a else ISO_NAVIC.get(p.get("id"))


def naplanuj(prah_b, jen, bez):
    """Seznam [(id, iso, url, bajtů)]; velké státy rozložené na regiony (rekurzivně)."""
    def index():
        with http(INDEX_URL) as r:
            return json.load(r)
    idx = s_opakovanim(index, "index Geofabriku")
    props = {f["properties"]["id"]: f["properties"] for f in idx["features"]}
    deti = {}
    for p in props.values():
        deti.setdefault(p.get("parent"), []).append(p)
    staty = sorted((p for p in deti.get("europe", []) if iso(p)), key=lambda p: p["id"])
    plan = []

    def pridej(p, kod):
        if p["id"] in VYNECHAT_REGIONY:
            log("  %-34s vynecháno (mimo evropskou pevninu)" % p["id"])
            return
        url = p["urls"]["pbf"]
        b = s_opakovanim(lambda: velikost(url), p["id"])
        sub = deti.get(p["id"], [])
        if b > prah_b and sub:
            log("  %-34s %6.2f GB > práh → %d regionů" % (p["id"], b / 1e9, len(sub)))
            for s in sorted(sub, key=lambda s: s["id"]):
                pridej(s, kod)
        else:
            if b > prah_b:
                log("  ⚠️ %s %.2f GB nad prahem, ale Geofabrik ho dál nedělí — stavím celý" % (p["id"], b / 1e9))
            plan.append((p["id"], kod, url, b))

    for p in staty:
        kod = iso(p)
        if jen and kod.lower() not in jen:
            continue
        if kod.lower() in bez:
            log("  %-34s vynecháno (--bez %s)" % (p["id"], kod))
            continue
        pridej(p, kod)
    return plan, deti


def s_opakovanim(f, co, pokusu=6, cekej=15):
    """Výpadek sítě (cloud 14. 11.: runner 20 s „Network is unreachable" → padl celý díl) → zkusit znovu.
    md5 / málo místa se neopakuje (RuntimeError)."""
    for k in range(1, pokusu + 1):
        try:
            return f()
        except RuntimeError:
            raise
        except Exception as e:          # noqa: BLE001 — URLError, timeout, reset spojení…
            if k == pokusu:
                raise
            log("  ↻ %s: %s — znovu za %d s (pokus %d/%d)" % (co, e, cekej, k + 1, pokusu))
            time.sleep(cekej)
            cekej = min(cekej * 2, 240)


def stahni(id_, url, b):
    cil = os.path.join(PBF, bezpecne(id_) + ".osm.pbf")
    if os.path.isfile(cil) and os.path.getsize(cil) == b:
        return cil
    volno = shutil.disk_usage(PRAC).free
    if volno < b * 1.2 + 5e9:
        raise RuntimeError("málo místa ve WSL: %.1f GB volno, potřeba %.1f GB" % (volno / 1e9, b / 1e9))
    with http(url + ".md5") as r:
        md5_ok = r.read().decode().split()[0]
    tmp = cil + ".part"
    h = hashlib.md5()
    # ⭐ 14. 11. 2026 (cloud: 2 díly visely hodiny): strop doby stažení — pomalé/zaseklé spojení
    #    skončí TimeoutError a `s_opakovanim` ho zkusí znovu (nové spojení).
    strop = 300 + b / 0.5e6
    t0 = time.time()
    with http(url) as r, open(tmp, "wb") as f:
        while True:
            if time.time() - t0 > strop:
                raise TimeoutError("stahování %s přes %.0f s (%.0f MB z %.0f)" % (id_, strop, f.tell() / 1e6, b / 1e6))
            k = r.read(1 << 20)
            if not k:
                break
            f.write(k)
            h.update(k)
    if h.hexdigest() != md5_ok:
        os.remove(tmp)
        raise RuntimeError("md5 nesedí u %s" % id_)
    os.replace(tmp, cil)
    return cil


def postav(id_, kod, pbf):
    cil = os.path.join(OUT, bezpecne(id_))
    tmp = cil + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    t0 = time.time()
    vystup = os.path.join(OUT, bezpecne(id_) + ".log")
    with open(vystup, "w", encoding="utf-8") as f:
        # ⭐ strop stavby jednoho packu (největší zdroj ~1 GB = ~10 min) — zaseklá stavba nesmí držet celý díl
        pr = subprocess.Popen(["/usr/bin/time", "-v", "python3", STAV, pbf, tmp, kod], stdout=f,
                              stderr=subprocess.STDOUT, start_new_session=True)
        try:
            e = pr.wait(timeout=STROP_STAVBY_S)
        except subprocess.TimeoutExpired:
            os.killpg(pr.pid, 9)
            pr.wait()
            raise RuntimeError("stavba %s přes %d s — zabita" % (id_, STROP_STAVBY_S))
    txt = open(vystup, encoding="utf-8", errors="replace").read()
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", txt)
    ram = int(m.group(1)) // 1024 if m else -1
    if e != 0 or not os.path.isfile(os.path.join(tmp, "hlavicka.json")):
        raise RuntimeError("stavba %s selhala (exit %d, RAM %d MB) — viz %s" % (id_, e, ram, vystup))
    shutil.rmtree(cil, ignore_errors=True)
    os.replace(tmp, cil)
    hl = json.load(open(os.path.join(cil, "hlavicka.json"), encoding="utf-8"))
    mb = sum(os.path.getsize(os.path.join(cil, x)) for x in os.listdir(cil)) / 1048576
    return hl, mb, round(time.time() - t0), ram


def rozdel(plan, k, n):
    """Díl k z n (1..n): hladově podle velikosti zdroje → díly trvají zhruba stejně. Deterministické."""
    zatez = [0] * n
    dily = [[] for _ in range(n)]
    for x in sorted(plan, key=lambda x: (-x[3], x[0])):
        i = min(range(n), key=lambda j: (zatez[j], j))
        zatez[i] += x[3]
        dily[i].append(x)
    return sorted(dily[k - 1], key=lambda x: x[0])


def zabal(id_, kod, zip_do, dil):
    """Pack → `<zip_do>/<id>.zip` + řádek manifestu (formát čte `Stahovac.kt` ve voze)."""
    import zipfile
    src = os.path.join(OUT, bezpecne(id_))
    hl = json.load(open(os.path.join(src, "hlavicka.json"), encoding="utf-8"))
    jmena = sorted(os.listdir(src))
    cil = os.path.join(zip_do, bezpecne(id_) + ".zip")
    with zipfile.ZipFile(cil + ".tmp", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for j in jmena:
            z.write(os.path.join(src, j), j)
    os.replace(cil + ".tmp", cil)
    h = hashlib.md5()
    with open(cil, "rb") as f:
        for k in iter(lambda: f.read(1 << 20), b""):
            h.update(k)
    b = hl["bunka"]
    radek = "\t".join(str(x) for x in (
        bezpecne(id_), kod, hl["lat0"], hl["lon0"], hl["lat0"] + hl["ny"] * b, hl["lon0"] + hl["nx"] * b,
        os.path.basename(cil), os.path.getsize(cil), h.hexdigest(), len(jmena), hl["n_seg"]))
    with open(os.path.join(zip_do, "manifest-%s.tsv" % dil), "a", encoding="utf-8", newline="\n") as f:
        f.write(radek + "\n")
    return os.path.getsize(cil)


def main():
    a = argparse.ArgumentParser()
    # 1,0 GB: ČR (0,95 GB zdroje) ve WSL potřebovala 5,1 GB RAM a WSL má ~7,6 GB (13. 11. 2026)
    a.add_argument("--prah-gb", type=float, default=1.0, help="zdroj nad tolik GB → stavět po regionech")
    a.add_argument("--jen", default="", help="jen tyto státy (ISO, čárkou)")
    a.add_argument("--bez", default=BEZ_VYCHOZI, help="vynechat státy (ISO, čárkou)")
    a.add_argument("--suchy", action="store_true", help="jen plán, nic nestahovat ani nestavět")
    a.add_argument("--plan-ven", default="", help="(cloud) uložit plán do JSON")
    a.add_argument("--plan", default="", help="(cloud) plán z JSON místo z indexu Geofabriku")
    a.add_argument("--dil", default="", help="(cloud) jen díl K/N plánu")
    a.add_argument("--zip-do", default="", help="(cloud) každý pack zabalit do této složky + manifest")
    a.add_argument("--uklid", action="store_true", help="(cloud) po zabalení smazat zdroj i rozbalený pack")
    v = a.parse_args()
    os.makedirs(PBF, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    jen = {x.strip().lower() for x in v.jen.split(",") if x.strip()}
    bez = {x.strip().lower() for x in v.bez.split(",") if x.strip()}

    log("=== EVROPA start (práh %.1f GB, jen=%s, bez=%s) ===" % (v.prah_gb, sorted(jen) or "vše", sorted(bez)))
    if v.plan:
        d = json.load(open(v.plan, encoding="utf-8"))
        plan, deti = [tuple(x) for x in d["plan"]], d["deti"]
    else:
        plan, deti = naplanuj(v.prah_gb * 1e9, jen, bez)
        deti = {k: [p["id"] for p in d] for k, d in deti.items() if k}
    if v.plan_ven:
        with open(v.plan_ven, "w", encoding="utf-8") as f:
            json.dump({"plan": plan, "deti": deti}, f, ensure_ascii=False)
    dil = "vse"
    if v.dil:
        k, n = (int(x) for x in v.dil.split("/"))
        plan, dil = rozdel(plan, k, n), str(k)
    if v.zip_do:
        os.makedirs(v.zip_do, exist_ok=True)
    zbyva = [x for x in plan if not os.path.isfile(os.path.join(OUT, bezpecne(x[0]), "hlavicka.json"))]
    log("plán: %d packů, zdroje %.1f GB; hotových %d, zbývá %d (%.1f GB)" % (
        len(plan), sum(x[3] for x in plan) / 1e9, len(plan) - len(zbyva), len(zbyva), sum(x[3] for x in zbyva) / 1e9))
    if v.suchy:
        for id_, kod, _, b in plan:
            print("%-40s %s %8.0f MB" % (id_, kod, b / 1e6))
        return

    if not os.path.isfile(SOUHRN):
        with open(SOUHRN, "w", encoding="utf-8") as f:
            f.write("id\tstat\tzdroj_MB\tpack_MB\tuseku\tretezcu\tzahozeno\tstavba_s\tRAM_MB\n")

    # ── stahování o krok napřed (jedno vlákno, popořadě) ──
    hotovo = [threading.Event() for _ in zbyva]
    cesty = [None] * len(zbyva)
    chyby = [None] * len(zbyva)

    def stahovac():
        for i, (id_, _, url, b) in enumerate(zbyva):
            if i > 1:
                hotovo[i - 2].wait()          # stahuje se stát i, zatímco se staví i−1 — nejvýš jeden napřed
            try:
                t = time.time()
                cesty[i] = s_opakovanim(lambda: stahni(id_, url, b), id_)
                log("staženo %-34s %7.0f MB za %.0f s" % (id_, b / 1e6, time.time() - t))
            except Exception as e:      # noqa: BLE001 — chyba jednoho státu nesmí zastavit ostatní
                chyby[i] = str(e)
            dl_hotovo[i].set()

    dl_hotovo = [threading.Event() for _ in zbyva]
    threading.Thread(target=stahovac, daemon=True).start()

    neprosly = []
    for i, (id_, kod, url, b) in enumerate(zbyva):
        dl_hotovo[i].wait()
        try:
            if chyby[i]:
                raise RuntimeError(chyby[i])
            log("stavím %s (%s, %.0f MB) [%d/%d]" % (id_, kod, b / 1e6, i + 1, len(zbyva)))
            hl, mb, s, ram = postav(id_, kod, cesty[i])
            zah = hl.get("retezce_zahozeno", 0)
            with open(SOUHRN, "a", encoding="utf-8") as f:
                f.write("%s\t%s\t%.0f\t%.1f\t%d\t%d\t%d\t%d\t%d\n" % (
                    id_, kod, b / 1e6, mb, hl["n_seg"], hl["n_retezcu"], zah, s, ram))
            log("  hotovo %s: %.1f MB, %d úseků, %d řetězců%s, %d s, RAM %d MB" % (
                id_, mb, hl["n_seg"], hl["n_retezcu"], (", ⛔ ZAHOZENO %d" % zah) if zah else "", s, ram))
            if zah and deti.get(id_):
                log("  ⛔ %s přetekl strop řetězců a dá se dělit → spusť znovu s nižším --prah-gb" % id_)
            if v.zip_do:
                if zah:
                    raise RuntimeError("přetekl strop řetězců — do vozu NE")
                zb = zabal(id_, kod, v.zip_do, dil)
                log("  zabaleno %s: %.1f MB" % (id_, zb / 1048576))
        except Exception as e:          # noqa: BLE001
            log("  ⛔ CHYBA %s: %s" % (id_, e))
            neprosly.append(id_)
        finally:
            if v.uklid:
                if cesty[i]:
                    try:
                        os.remove(cesty[i])
                    except OSError:
                        pass
                shutil.rmtree(os.path.join(OUT, bezpecne(id_)), ignore_errors=True)
            hotovo[i].set()

    log("=== EVROPA konec: %d OK, %d chyb%s ===" % (
        len(zbyva) - len(neprosly), len(neprosly), (" (" + ", ".join(neprosly) + ")") if neprosly else ""))
    if v.zip_do:
        # ⭐ jeden vadný stát nesmí shodit celý měsíc — rozhodne `publikuj.py` (strop chyb), vůz si nechá starý
        with open(os.path.join(v.zip_do, "chyby-%s.txt" % dil), "w", encoding="utf-8") as f:
            f.write("".join(x + "\n" for x in neprosly))
    return 0


if __name__ == "__main__":
    sys.exit(main())
