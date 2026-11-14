# Mapy TSR — měsíční mapové packy rychlostních limitů pro Evropu

Každý měsíc (2. den, GitHub Actions) se z extraktů [Geofabrik](https://download.geofabrik.de/)
postaví kompaktní packy silniční sítě s rychlostními limity po státech a regionech Evropy
a zveřejní se jako vydání (*Releases → Latest*):

- `manifest.tsv` — seznam packů (stát, obálka, velikost, md5),
- `<id>.zip` — jeden pack (binární úseky, křižovatky, obce, cedule obcí).

Stavba: `evropa.py` (plán, stažení, stavba po dílech) → `stav_pack.py` (jeden pack) → `publikuj.py`
(spojení manifestu + pojistky: chybějící packy, pokles počtu úseků o víc než 30 %).
Ruční spuštění: *Actions → Mapy TSR → Run workflow*.

## Licence dat

Mapová data © přispěvatelé [OpenStreetMap](https://www.openstreetmap.org/copyright),
dostupná pod licencí [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Packy v tomto repozitáři jsou odvozená databáze a šíří se pod toutéž licencí ODbL 1.0.

Výchozí limity států (v aplikaci, ne v packu) vycházejí z datasetu
[westnordost/osm-legal-default-speeds](https://github.com/westnordost/osm-legal-default-speeds) (CC BY-SA 2.0).
