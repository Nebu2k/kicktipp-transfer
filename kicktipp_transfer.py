#!/usr/bin/env python3
"""
Kicktipp-Tipp-Übertragung
=========================

Kopiert alle abgegebenen Tipps (Spielergebnisse + Bonus-/Frage-Tipps) aus einer
Quell-Tipprunde in eine oder mehrere Ziel-Runden – auch über verschiedene
Kicktipp-Accounts hinweg.

Spiele werden über (Anstoßzeit, Heim, Gast) zugeordnet, Bonus-Fragen über den
Fragetext und die Antwort-Texte. IDs unterscheiden sich pro Runde, deshalb wird
nichts über interne IDs gematcht.

Konfiguration: Accounts, Quelle und Ziele stehen in config.toml
(Vorlage: config.example.toml) – nichts muss im Code geändert werden.

Aufruf:
    python3 kicktipp_transfer.py                 # Probelauf (zeigt nur, was passieren würde)
    python3 kicktipp_transfer.py --submit        # überträgt wirklich und verifiziert danach
    python3 kicktipp_transfer.py -c andere.toml  # andere Config-Datei verwenden
"""
import argparse
import re
import sys
import tomllib
import unicodedata

import requests
from bs4 import BeautifulSoup

BASE = "https://www.kicktipp.de"
DEFAULT_CONFIG = "config.toml"

FRAGE_RE = re.compile(r"fragetippForms\[\d+\]\.antwortIds\[\d+\]")
NICHT_GETIPPT = "-- Nicht getippt --"


def norm(s):
    """Vergleichbar machen: Unicode normalisieren, trimmen, casefold."""
    return unicodedata.normalize("NFC", (s or "").strip()).casefold()


# ---- Login / Sessions -------------------------------------------------------

def load_config(path):
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        sys.exit(f"FEHLER: {path} nicht gefunden. Lege sie nach Vorbild von "
                 f"config.example.toml an  (cp config.example.toml {path}).")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"FEHLER: {path} ist kein gültiges TOML: {e}")
    if not cfg.get("accounts"):
        sys.exit(f"FEHLER: In {path} fehlt mindestens ein [accounts.<NAME>]-Block.")
    if not cfg.get("source", {}).get("group"):
        sys.exit(f"FEHLER: In {path} fehlt der [source]-Block mit 'group'.")
    if not cfg.get("targets"):
        sys.exit(f"FEHLER: In {path} fehlt mindestens ein [[targets]]-Block.")
    return cfg


def new_session():
    s = requests.Session()
    s.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36")
    return s


def login(session, email, pw):
    session.get(f"{BASE}/info/profil/login")
    session.post(
        f"{BASE}/info/profil/loginaction",
        data={"kennung": email, "passwort": pw, "submitbutton": "Anmelden",
              "_charset_": "UTF-8"},
        headers={"Referer": f"{BASE}/info/profil/login"},
    )
    return "login" in session.cookies.get_dict()


def session_for(account, accounts, cache):
    """Liefert eine eingeloggte Session für ein Account-Kürzel (mit Caching)."""
    if account in cache:
        return cache[account]
    acc = accounts.get(account)
    if not acc or not acc.get("email") or not acc.get("password"):
        sys.exit(f"FEHLER: Account '{account}' fehlt oder ist unvollständig "
                 f"(email/password) in der Config.")
    s = new_session()
    if not login(s, acc["email"], acc["password"]):
        sys.exit(f"FEHLER: Login für Account '{account}' ({acc['email']}) fehlgeschlagen.")
    cache[account] = s
    return s


# ---- HTML-Helfer ------------------------------------------------------------

def get_form(session, group, params):
    r = session.get(f"{BASE}/{group}/tippabgabe", params=params)
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.find("form", id="tippabgabeForm")


def max_spieltag(session, group):
    """Höchsten spieltagIndex aus der Navigation lesen."""
    r = session.get(f"{BASE}/{group}/tippabgabe")
    idx = [int(m) for m in re.findall(r"spieltagIndex=(\d+)", r.text)]
    return max(idx) if idx else 1


def serialize_form(form):
    """Alle Felder des Formulars als Liste (name, value) – wie es ein Browser senden würde."""
    fields = []
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name:
            continue
        tag = el.name
        if tag == "input":
            itype = (el.get("type") or "text").lower()
            if itype in ("checkbox", "radio"):
                if el.has_attr("checked"):
                    fields.append((name, el.get("value", "on")))
            elif itype in ("submit", "button", "image", "file"):
                continue
            else:
                fields.append((name, el.get("value", "")))
        elif tag == "select":
            sel = el.find("option", selected=True) or el.find("option")
            fields.append((name, sel.get("value", "") if sel else ""))
        elif tag == "textarea":
            fields.append((name, el.get_text()))
    return fields


def post_form(session, group, form, overrides, idx, bonus=False):
    """Sendet das Formular mit angewandten Overrides (wie ein Browser-Submit)."""
    out, used = [], set()
    for name, val in serialize_form(form):
        if name in overrides:
            out.append((name, overrides[name]))
            used.add(name)
        else:
            out.append((name, val))
    for name, val in overrides.items():
        if name not in used:
            out.append((name, val))
    out.append(("submitbutton", ""))
    params = {"spieltagIndex": idx}
    if bonus:
        params["bonus"] = "true"
    session.post(f"{BASE}/{group}/tippabgabe", params=params, data=out,
                 headers={"Referer": f"{BASE}/{group}/tippabgabe"})


# ---- Spiel-Tipps ------------------------------------------------------------

def parse_games(form):
    """{(when,home,away): {...}} aus einem Spieltag-Formular."""
    games = {}
    for tr in form.find_all("tr"):
        hi = tr.find("input", attrs={"name": re.compile(r"spieltippForms\[\d+\]\.heimTipp")})
        if not hi:
            continue
        gi = tr.find("input", attrs={"name": re.compile(r"spieltippForms\[\d+\]\.gastTipp")})
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        key = (cells[0], norm(cells[1]), norm(cells[2]))
        games[key] = {
            "h": hi.get("value", ""), "a": gi.get("value", ""),
            "heim_name": hi["name"], "gast_name": gi["name"],
            "editable": not (hi.has_attr("disabled") or hi.has_attr("readonly")),
            "label": f"{cells[0]} {cells[1]} - {cells[2]}",
        }
    return games


def transfer_spieltag(src_sess, src_group, dst_sess, dst_group, idx, submit, log):
    src = get_form(src_sess, src_group, {"spieltagIndex": idx})
    dst = get_form(dst_sess, dst_group, {"spieltagIndex": idx})
    if not src or not dst:
        return 0, 0, 0
    src_games, dst_games = parse_games(src), parse_games(dst)

    overrides = {}
    planned = locked = unmatched = 0
    for key, sg in src_games.items():
        if sg["h"] == "" and sg["a"] == "":
            continue  # in der Quelle nicht getippt
        dg = dst_games.get(key)
        if not dg:
            unmatched += 1
            log(f"    ! kein Ziel-Spiel für {sg['label']}")
            continue
        if not dg["editable"]:
            locked += 1
            continue
        overrides[dg["heim_name"]] = sg["h"]
        overrides[dg["gast_name"]] = sg["a"]
        planned += 1
        log(f"    {dg['label']}: {sg['h']}:{sg['a']}")

    if planned and submit:
        post_form(dst_sess, dst_group, dst, overrides, idx)
    return planned, locked, unmatched


# ---- Bonus-/Frage-Tipps -----------------------------------------------------

def parse_bonus(form):
    """[{'q':frage, 'selects':[{'name','chosen','options':{normtext:value}}]}]"""
    questions = []
    for tr in form.find_all("tr"):
        sels = tr.find_all("select", attrs={"name": FRAGE_RE})
        if not sels:
            continue
        qtext = ""
        for td in tr.find_all("td"):
            cls = td.get("class") or []
            if "kicktipp-time" in cls or "kicktipp-tippabgabe" in cls:
                continue
            qtext = td.get_text(" ", strip=True)
            break
        select_info = []
        for sel in sels:
            options, chosen = {}, ""
            for o in sel.find_all("option"):
                txt, val = o.get_text(strip=True), o.get("value", "")
                if val not in ("-1", "", "0"):
                    options[norm(txt)] = val
                if o.has_attr("selected"):
                    chosen = txt
            select_info.append({"name": sel["name"], "chosen": chosen, "options": options})
        questions.append({"q": qtext, "selects": select_info})
    return questions


def transfer_bonus(src_sess, src_group, dst_sess, dst_group, submit, log):
    src = get_form(src_sess, src_group, {"bonus": "true", "spieltagIndex": 1})
    dst = get_form(dst_sess, dst_group, {"bonus": "true", "spieltagIndex": 1})
    if not src or not dst:
        return 0, 0
    by_text = {norm(q["q"]): q for q in parse_bonus(dst)}

    overrides = {}
    planned = problems = 0
    for sq in parse_bonus(src):
        chosen = [s["chosen"] for s in sq["selects"]
                  if s["chosen"] and norm(s["chosen"]) != norm(NICHT_GETIPPT)]
        if not chosen:
            continue
        dq = by_text.get(norm(sq["q"]))
        if not dq:
            problems += 1
            log(f"    ! keine Zielfrage für: {sq['q'][:60]}")
            continue
        free = list(dq["selects"])  # Antworten der Reihe nach freien Dropdowns zuweisen
        for ans in chosen:
            for i, dsel in enumerate(free):
                val = dsel["options"].get(norm(ans))
                if val is not None:
                    overrides[dsel["name"]] = val
                    free.pop(i)
                    planned += 1
                    log(f"    {sq['q'][:45]} -> {ans}")
                    break
            else:
                problems += 1
                log(f"    ! Antwort '{ans}' nicht in Zielfrage '{sq['q'][:40]}'")

    if planned and submit:
        post_form(dst_sess, dst_group, dst, overrides, 1, bonus=True)
    return planned, problems


# ---- Verifikation -----------------------------------------------------------

def verify(src_sess, src_group, dst_sess, dst_group, maxst):
    """Vergleicht nach der Übertragung Quelle und Ziel; gibt Anzahl Abweichungen zurück."""
    diffs = n_games = n_bonus = 0
    for idx in range(1, maxst + 1):
        s = get_form(src_sess, src_group, {"spieltagIndex": idx})
        d = get_form(dst_sess, dst_group, {"spieltagIndex": idx})
        if not s or not d:
            continue
        sg, dg = parse_games(s), parse_games(d)
        for key, g in sg.items():
            if g["h"] == "" and g["a"] == "":
                continue
            t = dg.get(key)
            n_games += 1
            if not t or (t["h"], t["a"]) != (g["h"], g["a"]):
                diffs += 1
                print(f"  ABWEICHUNG Spiel {g['label']}: Quelle {g['h']}:{g['a']} "
                      f"Ziel {t['h'] if t else '-'}:{t['a'] if t else '-'}")
    s = get_form(src_sess, src_group, {"bonus": "true", "spieltagIndex": 1})
    d = get_form(dst_sess, dst_group, {"bonus": "true", "spieltagIndex": 1})
    if s and d:
        sq = {norm(q["q"]): q for q in parse_bonus(s)}
        dq = {norm(q["q"]): q for q in parse_bonus(d)}
        for k, q in sq.items():
            src_ans = sorted(norm(x["chosen"]) for x in q["selects"]
                             if x["chosen"] and norm(x["chosen"]) != norm(NICHT_GETIPPT))
            if not src_ans:
                continue
            n_bonus += 1
            t = dq.get(k)
            dst_ans = sorted(norm(x["chosen"]) for x in t["selects"]
                             if x["chosen"] and norm(x["chosen"]) != norm(NICHT_GETIPPT)) if t else []
            if src_ans != dst_ans:
                diffs += 1
                print(f"  ABWEICHUNG Bonus '{q['q'][:45]}': Quelle {src_ans} Ziel {dst_ans}")
    print(f"  Verifiziert: {n_games} Spiel-Tipps + {n_bonus} Bonus-Fragen, {diffs} Abweichung(en).")
    return diffs


# ---- Main -------------------------------------------------------------------

def run_target(src_sess, src_group, dst_sess, target, maxst, submit):
    dst_group = target["group"]
    print(f"\n=== Ziel: {dst_group}  (Account {target['account']}) ===")
    total_games = 0
    for idx in range(1, maxst + 1):
        planned, locked, unmatched = transfer_spieltag(
            src_sess, src_group, dst_sess, dst_group, idx, submit, print)
        total_games += planned
        if planned or locked or unmatched:
            extra = []
            if locked:
                extra.append(f"{locked} gesperrt")
            if unmatched:
                extra.append(f"{unmatched} ohne Zuordnung")
            suffix = f"  ({', '.join(extra)})" if extra else ""
            print(f"  Spieltag {idx}: {planned} Spiel-Tipps{suffix}")
    bonus_planned, bonus_problems = transfer_bonus(
        src_sess, src_group, dst_sess, dst_group, submit, print)
    print(f"  Bonus: {bonus_planned} Frage-Tipps"
          + (f"  ({bonus_problems} Problem(e))" if bonus_problems else ""))
    print(f"  Summe: {total_games} Spiel-Tipps + {bonus_planned} Bonus-Tipps.")

    diffs = None
    if submit:
        diffs = verify(src_sess, src_group, dst_sess, dst_group, maxst)
    return total_games, bonus_planned, diffs


def main():
    ap = argparse.ArgumentParser(
        description="Kicktipp-Tipps aus einer Runde in eine/mehrere andere übertragen.")
    ap.add_argument("--submit", action="store_true",
                    help="Tipps wirklich übertragen (sonst nur Probelauf).")
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG,
                    help=f"Pfad zur Config-Datei (Standard: {DEFAULT_CONFIG}).")
    args = ap.parse_args()

    cfg = load_config(args.config)
    accounts = cfg["accounts"]
    source = cfg["source"]
    targets = cfg["targets"]

    sessions = {}
    src_sess = session_for(source["account"], accounts, sessions)
    maxst = max_spieltag(src_sess, source["group"])

    mode = "ÜBERTRAGUNG" if args.submit else "PROBELAUF (nichts wird gesendet – mit --submit ausführen)"
    print(f"Quelle: {source['group']} (Account {source['account']}, bis Spieltag {maxst})")
    print(f"Ziele:  {', '.join(t['group'] for t in targets)}")
    print(f"Modus:  {mode}")

    results = []
    for target in targets:
        dst_sess = session_for(target["account"], accounts, sessions)
        results.append((target,
                        run_target(src_sess, source["group"], dst_sess, target, maxst, args.submit)))

    print("\n--- Zusammenfassung ---")
    any_diff = False
    for target, (g, b, diffs) in results:
        status = ""
        if diffs is not None:
            status = "  ✓ verifiziert" if diffs == 0 else f"  ⚠ {diffs} Abweichung(en)"
            any_diff = any_diff or diffs != 0
        print(f"  {target['group']}: {g} Spiel-Tipps + {b} Bonus-Tipps{status}")

    if not args.submit:
        print("\nProbelauf ok. Zum echten Übertragen:  python3 kicktipp_transfer.py --submit")
    elif any_diff:
        print("\n⚠ Es gibt Abweichungen (siehe oben). Bitte prüfen.")
        sys.exit(1)
    else:
        print("\n✓ Fertig – alle Tipps wurden in alle Ziele korrekt übertragen.")


if __name__ == "__main__":
    main()
