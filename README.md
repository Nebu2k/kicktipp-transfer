# kicktipp-transfer

Kopiert alle abgegebenen Tipps von einer [Kicktipp](https://www.kicktipp.de)-Tipprunde
in eine oder mehrere andere – auch über **verschiedene Accounts** hinweg. Praktisch,
wenn man in mehreren Runden (z.B. Arbeit und Freunde) mitspielt und nicht alles
mehrfach eintippen will. Kicktipp selbst bietet dafür keine Funktion.

Übertragen werden:

- **Spielergebnis-Tipps** aller Spieltage
- **Bonus-/Frage-Tipps** (Gruppensieger, Halbfinalisten, Weltmeister, Torschützenkönig …)

Spiele werden über **Anstoßzeit + Heim-/Gastmannschaft** zugeordnet, Bonusfragen über
**Fragetext + Antworttext** – nicht über interne IDs, da diese sich pro Runde unterscheiden.
Nach der Übertragung wird automatisch verifiziert, dass im Ziel exakt dieselben Tipps stehen.
Bereits gestartete (gesperrte) Spiele werden übersprungen.

## Nutzung

1. Abhängigkeiten installieren:

   ```bash
   pip install requests beautifulsoup4
   ```

2. Config anlegen und ausfüllen (Accounts, Quelle, Ziele – kein Eingriff in den Code nötig):

   ```bash
   cp config.example.toml config.toml
   # config.toml im Editor öffnen und ausfüllen
   ```

   ```toml
   [accounts.A]                     # frei wählbares Kürzel pro Login
   email = "account-a@example.com"
   password = "geheim"

   [accounts.B]                     # nur nötig, wenn ein Ziel unter anderem Login liegt
   email = "account-b@example.com"
   password = "geheim"

   [source]                         # Runde mit den vorhandenen Tipps
   account = "A"
   group = "meine-quell-runde"      # Pfadteil der URL: kicktipp.de/<group>/

   [[targets]]                      # beliebig viele Ziele
   account = "A"
   group = "ziel-runde-1"

   [[targets]]
   account = "B"
   group = "ziel-runde-2"
   ```

   Liegen alle Runden unter demselben Login, genügt ein einziger Account.

3. Erst ein **Probelauf** (ändert nichts, zeigt nur die geplante Zuordnung):

   ```bash
   python3 kicktipp_transfer.py
   ```

4. Wenn alles passt, **wirklich übertragen**:

   ```bash
   python3 kicktipp_transfer.py --submit
   ```

   Mit `-c andere.toml` lässt sich eine andere Config-Datei wählen.

## Hinweise

- `config.toml` enthält deine Passwörter und Rundennamen und ist per `.gitignore`
  ausgeschlossen – nicht committen.
- Inoffizielles Tool, nutzt die normalen Web-Formulare von Kicktipp. Keine Garantie,
  dass es nach Änderungen an der Seite weiter funktioniert.
- Nur für eigene Accounts/Runden gedacht.

## Unterstützen

Das Tool ist kostenlos und ein Hobby-Projekt. Wenn es dir Tipp-Arbeit erspart hat,
freue ich mich über einen Kaffee: [paypal.me/nebu2k](https://paypal.me/nebu2k) ☕
Kein Muss – ein ⭐ auf GitHub hilft auch.
