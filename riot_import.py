#!/usr/bin/env python3
"""
Récupère tes dernières parties League of Legends via l'API Riot et écrit
`nouvelles_parties.json`, à importer dans l'application de suivi.

Utilisation :
    python riot_import.py                    # une seule passe
    python riot_import.py --surveiller 10    # revérifie toutes les 10 minutes

Aucune installation nécessaire (Python 3.8+ suffit).
Chaque partie déjà exportée est mémorisée dans `deja_importees.json`,
donc seules les nouvelles parties sont ajoutées à chaque passage.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============ À MODIFIER ============
# Ta clé : developer.riotgames.com (une clé de développement expire toutes les 24 h).
# Le mieux est de la mettre dans la variable d'environnement RIOT_API_KEY.
API_KEY = os.environ.get("RIOT_API_KEY", "RGAPI-ac006fcd-5324-4852-8c77-ec0abc7d45a6")
GAME_NAME = "KC NEXT ADKING"     # ton Riot ID sans le #, ex. "Faker"
TAG_LINE = "CLSTE"            # ce qui suit le #, ex. "EUW"
REGION = "europe"           # europe (EUW, EUNE, TR, RU) | americas (NA, BR, LAN, LAS) | asia (KR, JP) | sea (OCE, SG...)
QUEUE = 420                 # 420 classée solo/duo, 440 flex, 400 normale draft, None = toutes les files
NB_PARTIES = 20             # nombre de parties récentes à examiner à chaque passage
XP_EN_ECART = True         # False : EXP@15 = XP total à 15 min ; True : écart d'XP avec ton adversaire direct
# ====================================

BASE = f"https://{REGION}.api.riotgames.com"
FICHIER_VUES = "deja_importees.json"
SORTIE = "nouvelles_parties.json"


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for _ in range(6):
        req = urllib.request.Request(url, headers={"X-Riot-Token": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:  # limite de requêtes atteinte : on patiente
                time.sleep(int(e.headers.get("Retry-After", "5")) + 1)
                continue
            if e.code in (401, 403):
                sys.exit("Clé refusée (401/403) : elle est peut-être expirée ou mal copiée. "
                         "Génère-en une nouvelle sur developer.riotgames.com.")
            if e.code == 404:
                return None
            raise
        except urllib.error.URLError as e:
            print("Problème réseau :", e.reason)
            time.sleep(3)
    return None


def stats_partie(match_id, puuid):
    m = get(f"{BASE}/lol/match/v5/matches/{match_id}")
    if not m:
        return None
    info = m["info"]
    duree = info["gameDuration"]
    if "gameEndTimestamp" not in info:  # anciennes parties : durée en millisecondes
        duree /= 1000
    if duree < 300:  # remake
        return None
    minutes = duree / 60

    moi = next((p for p in info["participants"] if p["puuid"] == puuid), None)
    if not moi:
        return None
    equipe = [p for p in info["participants"] if p["teamId"] == moi["teamId"]]
    kills_equipe = sum(p["kills"] for p in equipe) or 1
    cs = moi["totalMinionsKilled"] + moi["neutralMinionsKilled"]

    vals = {
        "KDA": round((moi["kills"] + moi["assists"]) / max(1, moi["deaths"]), 2),
        "CS/min": round(cs / minutes, 2),
        "KP%": round(100 * (moi["kills"] + moi["assists"]) / kills_equipe, 1),
        "G/m": round(moi["goldEarned"] / minutes, 1),
        "DMG/m": round(moi["totalDamageDealtToChampions"] / minutes, 1),
        "VS/m": round(moi["visionScore"] / minutes, 2),
        "GD@15": None,
        "EXP@15": None,
        "CS@15": None,
    }

    # Stats à 15 minutes : elles viennent de la timeline de la partie
    tl = get(f"{BASE}/lol/match/v5/matches/{match_id}/timeline")
    if tl and len(tl["info"]["frames"]) > 15:
        f = tl["info"]["frames"][15]["participantFrames"]
        a = f[str(moi["participantId"])]
        vals["CS@15"] = a["minionsKilled"] + a["jungleMinionsKilled"]
        pos = moi.get("teamPosition")
        adv = next((p for p in info["participants"]
                    if p["teamId"] != moi["teamId"] and pos and p.get("teamPosition") == pos), None)
        b = f.get(str(adv["participantId"])) if adv else None
        if b:
            vals["GD@15"] = a["totalGold"] - b["totalGold"]
        if XP_EN_ECART:
            vals["EXP@15"] = a["xp"] - b["xp"] if b else None
        else:
            vals["EXP@15"] = a["xp"]

    pos = (moi.get("teamPosition") or "").lower()
    note = f"{moi['championName']} {pos}, {'victoire' if moi['win'] else 'défaite'}".replace("  ", " ")
    return {
        "mid": match_id,
        "date": datetime.fromtimestamp(info["gameCreation"] / 1000, tz=timezone.utc).isoformat(),
        "vals": vals,
        "note": note,
    }


def une_passe(puuid):
    vus = set()
    if os.path.exists(FICHIER_VUES):
        with open(FICHIER_VUES, encoding="utf-8") as f:
            vus = set(json.load(f))

    params = {"start": 0, "count": NB_PARTIES}
    if QUEUE:
        params["queue"] = QUEUE
    ids = get(f"{BASE}/lol/match/v5/matches/by-puuid/{puuid}/ids", params) or []
    nouveaux = [i for i in ids if i not in vus]

    parties = []
    for mid in reversed(nouveaux):  # du plus ancien au plus récent
        p = stats_partie(mid, puuid)
        if p:
            parties.append(p)
        vus.add(mid)

    if parties:
        ancien = []
        if os.path.exists(SORTIE):
            with open(SORTIE, encoding="utf-8") as f:
                ancien = json.load(f)
        with open(SORTIE, "w", encoding="utf-8") as f:
            json.dump(ancien + parties, f, ensure_ascii=False, indent=1)
    with open(FICHIER_VUES, "w", encoding="utf-8") as f:
        json.dump(sorted(vus), f)

    if parties:
        print(f"{len(parties)} nouvelle(s) partie(s) ajoutée(s) à {SORTIE}. Importe ce fichier dans l'application.")
    else:
        print("Aucune nouvelle partie.")


def main():
    if API_KEY.startswith("COLLE") or GAME_NAME == "TonPseudo":
        sys.exit("Ouvre le script et renseigne API_KEY, GAME_NAME et TAG_LINE tout en haut.")
    compte = get(f"{BASE}/riot/account/v1/accounts/by-riot-id/"
                 f"{urllib.parse.quote(GAME_NAME)}/{urllib.parse.quote(TAG_LINE)}")
    if not compte:
        sys.exit("Compte introuvable : vérifie GAME_NAME, TAG_LINE et REGION.")
    puuid = compte["puuid"]

    if len(sys.argv) >= 3 and sys.argv[1] == "--surveiller":
        minutes = max(2, int(sys.argv[2]))
        print(f"Surveillance toutes les {minutes} minutes (Ctrl+C pour arrêter).")
        while True:
            une_passe(puuid)
            time.sleep(minutes * 60)
    else:
        une_passe(puuid)


if __name__ == "__main__":
    main()
