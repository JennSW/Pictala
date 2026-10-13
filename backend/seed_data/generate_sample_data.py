"""Regenerates the synthetic eBird sample files in this folder.

Nothing here comes from a real person's eBird account: the locations are
invented, the checklist IDs are in a range eBird hasn't issued (S9000000xx),
and species/counts are drawn from fixed pools with a fixed random seed, so
re-running this reproduces the same files byte for byte.

Run from backend/:  python seed_data/generate_sample_data.py

Writes:
  sample_ebird_export.csv        -- "Download My Data" format (many checklists)
  S900000099_observations.csv    -- single-checklist "Download" format
"""
import csv
import random
from pathlib import Path

OUT = Path(__file__).parent
rng = random.Random(20260613)

HEADER = [
    "Submission ID", "Common Name", "Scientific Name", "Taxonomic Order", "Count",
    "State/Province", "County", "Location ID", "Location", "Latitude", "Longitude",
    "Date", "Time", "Protocol", "Duration (Min)", "All Obs Reported",
    "Distance Traveled (km)", "Area Covered (ha)", "Number of Observers",
    "Breeding Code", "Observation Details", "Checklist Comments", "ML Catalog Numbers",
]

# (common name, scientific name)
S = {
    "mallard": ("Mallard", "Anas platyrhynchos"),
    "cangoose": ("Canada Goose", "Branta canadensis"),
    "coot": ("American Coot", "Fulica americana"),
    "gbh": ("Great Blue Heron", "Ardea herodias"),
    "cormorant": ("Double-crested Cormorant", "Nannopterum auritum"),
    "pbgrebe": ("Pied-billed Grebe", "Podilymbus podiceps"),
    "bufflehead": ("Bufflehead", "Bucephala albeola"),
    "shoveler": ("Northern Shoveler", "Spatula clypeata"),
    "woodduck": ("Wood Duck", "Aix sponsa"),
    "ruddy": ("Ruddy Duck", "Oxyura jamaicensis"),
    "teal": ("Cinnamon Teal", "Spatula cyanoptera"),
    "kingfisher": ("Belted Kingfisher", "Megaceryle alcyon"),
    "rwbb": ("Red-winged Blackbird", "Agelaius phoeniceus"),
    "songsp": ("Song Sparrow", "Melospiza melodia"),
    "towhee": ("California Towhee", "Melozone crissalis"),
    "chickadee": ("Chestnut-backed Chickadee", "Poecile rufescens"),
    "bushtit": ("Bushtit", "Psaltriparus minimus"),
    "annas": ("Anna's Hummingbird", "Calypte anna"),
    "robin": ("American Robin", "Turdus migratorius"),
    "scrubjay": ("California Scrub-Jay", "Aphelocoma californica"),
    "flicker": ("Northern Flicker", "Colaptes auratus"),
    "rthawk": ("Red-tailed Hawk", "Buteo jamaicensis"),
    "osprey": ("Osprey", "Pandion haliaetus"),
    "gegret": ("Great Egret", "Ardea alba"),
    "segret": ("Snowy Egret", "Egretta thula"),
    "stilt": ("Black-necked Stilt", "Himantopus mexicanus"),
    "killdeer": ("Killdeer", "Charadrius vociferus"),
    "starling": ("European Starling", "Sturnus vulgaris"),
    "housefinch": ("House Finch", "Haemorhous mexicanus"),
    "goldfinch": ("American Goldfinch", "Spinus tristis"),
    "bswallow": ("Barn Swallow", "Hirundo rustica"),
    "phoebe": ("Black Phoebe", "Sayornis nigricans"),
    "marshwren": ("Marsh Wren", "Cistothorus palustris"),
    "yellowthroat": ("Common Yellowthroat", "Geothlypis trichas"),
    "ringbill": ("Ring-billed Gull", "Larus delawarensis"),
    "calgull": ("California Gull", "Larus californicus"),
    "dove": ("Mourning Dove", "Zenaida macroura"),
    "crow": ("American Crow", "Corvus brachyrhynchos"),
    "vulture": ("Turkey Vulture", "Cathartes aura"),
}

# name, location id, lat, lon, species pool (invented places)
PLACES = {
    "Heron Point Shoreline": ("L9000001", 37.7831, -122.2574,
        ["gbh", "gegret", "segret", "cormorant", "calgull", "ringbill", "killdeer", "mallard", "bufflehead", "osprey", "crow", "starling"]),
    "Alder Creek Boardwalk": ("L9000002", 37.8112, -122.2367,
        ["woodduck", "kingfisher", "marshwren", "yellowthroat", "rwbb", "songsp", "mallard", "gbh", "phoebe", "bushtit", "annas", "robin"]),
    "Millpond Marsh Overlook": ("L9000003", 37.7690, -122.2203,
        ["coot", "pbgrebe", "ruddy", "teal", "shoveler", "mallard", "cangoose", "rwbb", "marshwren", "bswallow", "gegret", "stilt"]),
    "Oak Hollow Meadow Trail": ("L9000004", 37.8260, -122.2711,
        ["towhee", "scrubjay", "flicker", "chickadee", "bushtit", "annas", "robin", "housefinch", "goldfinch", "songsp", "rthawk", "vulture", "dove"]),
    "Bayfront Slough Loop": ("L9000005", 37.7549, -122.2468,
        ["gegret", "segret", "stilt", "killdeer", "ringbill", "calgull", "mallard", "shoveler", "cormorant", "gbh", "osprey", "bswallow"]),
}

# (submission, place, date, time, protocol, minutes, km, observers, comment)
CHECKLISTS = [
    ("S900000001", "Alder Creek Boardwalk", "02 Jun 2026", "07:15 AM", "eBird - Traveling Count", 95, 2.1, 1, "Overcast, light breeze."),
    ("S900000002", "Heron Point Shoreline", "06 Jun 2026", "06:50 AM", "eBird - Traveling Count", 120, 3.4, 1, ""),
    ("S900000003", "Millpond Marsh Overlook", "13 Jun 2026", "08:05 AM", "eBird - Stationary Count", 45, 0, 1, "Scope on the far shore, calm water."),
    ("S900000004", "Oak Hollow Meadow Trail", "20 Jun 2026", "07:40 AM", "eBird - Traveling Count", 110, 2.8, 2, ""),
    ("S900000005", "Bayfront Slough Loop", "27 Jun 2026", "09:20 AM", "eBird - Traveling Count", 85, 2.2, 1, "Tide going out."),
    ("S900000006", "Alder Creek Boardwalk", "11 Jul 2026", "07:30 AM", "eBird - Traveling Count", 100, 2.0, 1, ""),
    ("S900000007", "Heron Point Shoreline", "18 Jul 2026", "06:45 AM", "eBird - Traveling Count", 135, 3.8, 3, "Group outing with the local club."),
    ("S900000008", "Millpond Marsh Overlook", "25 Jul 2026", "08:10 AM", "eBird - Stationary Count", 60, 0, 1, ""),
    ("S900000009", "Oak Hollow Meadow Trail", "08 Aug 2026", "07:25 AM", "eBird - Traveling Count", 90, 2.5, 1, "Fog until about 9."),
    ("S900000010", "Bayfront Slough Loop", "15 Aug 2026", "08:50 AM", "eBird - Traveling Count", 75, 1.9, 1, ""),
    ("S900000011", "Alder Creek Boardwalk", "22 Aug 2026", "07:05 AM", "eBird - Traveling Count", 105, 2.3, 1, ""),
    ("S900000012", "Heron Point Shoreline", "29 Aug 2026", "07:55 AM", "eBird - Traveling Count", 115, 3.1, 1, "Lots of shorebirds on the mudflat."),
    ("S900000013", "Millpond Marsh Overlook", "05 Sep 2026", "08:15 AM", "eBird - Stationary Count", 50, 0, 1, ""),
    ("S900000014", "Oak Hollow Meadow Trail", "12 Sep 2026", "07:35 AM", "eBird - Traveling Count", 95, 2.6, 1, ""),
]
DETAILS = {"flicker": "Calling from the oak", "annas": "Male displaying", "songsp": "Singing male", "gbh": "Hunting in the shallows"}


def count_for():
    return str(rng.choice([1, 1, 2, 2, 3, 4, 6, 8, 12, 20, 35]))


def write_history():
    rows = []
    for sub, place, date, time, protocol, minutes, km, observers, comment in CHECKLISTS:
        loc_id, lat, lon, pool = PLACES[place]
        n = rng.randint(7, min(13, len(pool)))
        for key in rng.sample(pool, n):
            common, sci = S[key]
            cnt = "X" if rng.random() < 0.08 else count_for()
            rows.append([
                sub, common, sci, "", cnt, "US-CA", "Alameda", loc_id, place,
                f"{lat:.7f}", f"{lon:.7f}", date, time, protocol, minutes, 1,
                km if km else "", "", observers, "", DETAILS.get(key, "") if rng.random() < 0.5 else "",
                comment, "",
            ])
    with open(OUT / "sample_ebird_export.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return len(rows)


def write_single():
    place = "Alder Creek Boardwalk"
    pool = PLACES[place][3]
    keys = rng.sample(pool, 7)
    header = ["Species", "Count", "Location", "Observation Type", "Observation Date",
              "Start Time", "Duration", "Distance", "Area", "Party Size",
              "Complete Checklist", "# of species", "Details"]
    with open(OUT / "S900000099_observations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for key in keys:
            w.writerow([S[key][0], count_for(), place, "Traveling", "Aug 7, 2026", "07:20 AM",
                        "1 hour(s), 20 minute(s)", "1.4 mile(s)", "", 1, "Yes", len(keys), ""])
    return len(keys)


if __name__ == "__main__":
    print("history rows:", write_history(), "| single-checklist rows:", write_single())
