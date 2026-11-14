#!/usr/bin/env python3
"""
☁️ PUBLIKACE měsíčních map (14. 11. 2026) — poslední krok `.github/workflows/mapy.yml`.

Spojí díly manifestu z `evropa.py --zip-do` do jednoho `manifest.tsv`, který si stahuje TSR ve voze
(`Stahovac.kt`). Formát (TAB, LF, UTF-8):

    #tsr-mapy  1  <tag vydání>  <datum YYYYMMDD>  <počet packů>
    <id> <stát> <lat0> <lon0> <lat1> <lon1> <zip> <bajtů> <md5 zipu> <souborů> <úseků>     (stupně × 1e7)

POJISTKY (falešné ZVÝŠENÍ limitu je jediná opravdu nebezpečná chyba — vadná mapa do vozu nesmí):
  • chybí víc než --max-chyb packů z plánu → publikace SELŽE, vozy si nechají minulý měsíc
  • pack má o víc než 30 % méně úseků než minulý měsíc (--predchozi) → do manifestu NEJDE
    (vůz si nechá svůj starý; nejspíš rozbitý extrakt na Geofabriku)

    python3 publikuj.py --dily dist --plan plan.json --tag mapy-20261202 --datum 20261202 \
        [--predchozi stary-manifest.tsv] --ven manifest.tsv --poznamky notes.md
"""
import argparse
import glob
import json
import os
import sys

POKLES_MAX = 0.30


def nacti_manifest(cesta):
    out = {}
    if not cesta or not os.path.isfile(cesta):
        return out
    for r in open(cesta, encoding="utf-8"):
        r = r.rstrip("\n")
        if not r or r.startswith("#"):
            continue
        p = r.split("\t")
        out[p[0]] = p
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--dily", required=True)
    a.add_argument("--plan", required=True)
    a.add_argument("--tag", required=True)
    a.add_argument("--datum", required=True)
    a.add_argument("--predchozi", default="")
    a.add_argument("--max-chyb", type=int, default=10)
    a.add_argument("--ven", required=True)
    a.add_argument("--poznamky", default="")
    v = a.parse_args()

    plan = [x[0].replace("/", "__") for x in json.load(open(v.plan, encoding="utf-8"))["plan"]]
    radky = {}
    for f in sorted(glob.glob(os.path.join(v.dily, "**", "manifest-*.tsv"), recursive=True)):
        for r in open(f, encoding="utf-8"):
            r = r.rstrip("\n")
            if r:
                p = r.split("\t")
                if len(p) != 11:
                    sys.exit("vadný řádek v %s: %r" % (f, r))
                radky[p[0]] = p
    chyby = []
    for f in sorted(glob.glob(os.path.join(v.dily, "**", "chyby-*.txt"), recursive=True)):
        chyby += [x.strip() for x in open(f, encoding="utf-8") if x.strip()]

    stare = nacti_manifest(v.predchozi)
    vyrazene = []
    for i, p in list(radky.items()):
        s = stare.get(i)
        if s and int(s[10]) > 0 and int(p[10]) < int(s[10]) * (1 - POKLES_MAX):
            vyrazene.append("%s: úseků %s → %s" % (i, s[10], p[10]))
            del radky[i]

    chybi = [i for i in plan if i not in radky]
    print("packů v plánu %d, hotových %d, chybí %d, vyřazeno poklesem %d" % (
        len(plan), len(radky), len(chybi), len(vyrazene)))
    for x in vyrazene:
        print("  ⛔ vyřazeno", x)
    for x in chybi:
        print("  ⚠️ chybí", x)
    if len(chybi) > v.max_chyb:
        sys.exit("⛔ chybí %d packů (strop %d) — NEPUBLIKUJI, vozy zůstanou na minulém měsíci" % (len(chybi), v.max_chyb))

    with open(v.ven, "w", encoding="utf-8", newline="\n") as f:
        f.write("#tsr-mapy\t1\t%s\t%s\t%d\n" % (v.tag, v.datum, len(radky)))
        for i in sorted(radky):
            f.write("\t".join(radky[i]) + "\n")

    if v.poznamky:
        mb = sum(int(p[7]) for p in radky.values()) / 1048576
        with open(v.poznamky, "w", encoding="utf-8") as f:
            f.write("Mapy TSR %s — %d packů, %.0f MB (data © OpenStreetMap contributors, ODbL 1.0).\n\n" % (
                v.datum, len(radky), mb))
            if chybi:
                f.write("Chybí (vozy si nechají minulou verzi): %s\n\n" % ", ".join(chybi))
            if vyrazene:
                f.write("Vyřazeno kvůli poklesu úseků: %s\n\n" % "; ".join(vyrazene))
            # chyby-*.txt hlásí i státy, které pak dohnal job dohanka — vypsat jen počet dohnaných
            dohnano = sorted(set(chyby) & set(radky))
            if dohnano:
                f.write("Dohnáno na druhý pokus (výpadek sítě runneru): %d packů.\n" % len(dohnano))
    return 0


if __name__ == "__main__":
    sys.exit(main())
