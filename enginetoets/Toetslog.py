"""Het toetslog van een branch als pagina: de toetsen genummerd op een rij, met de rapporten eronder.

Gebruik:
    python Toetslog.py --log <toetslog.csv> --uit <toetslog.html> [--titel ...] [--ondertitel ...]
    python Toetslog.py --log <toetslog.csv> --baseline <tag> --commit <sha> --datum <jjjj-mm-dd> [--samenvatting ...]

Toetsrapport.py schrijft per toets een regel in het log (--log) en een html-versie van zijn rapport
(--html); Baseline.ps1 schrijft een regel wanneer een commit baseline wordt (--baseline). Dit script
zet het log en alle rapporten die nog op schijf staan in een pagina die zonder server opent, op elke
machine, en die als artifact te publiceren is. Het rapport is markdown in een vaste, kleine vorm
(koppen, tabellen, opsommingen, ingesprongen regels) en md_naar_html kent precies die vorm; het is
geen algemene markdown-vertaler.

Het log is een csv met puntkomma's: nr, tijd, van, van_datum, naar, naar_datum, commits, samenvatting,
oordeel, tifs_anders, tifs_totaal, checks_anders, checks_totaal, rapport. Een regel per toets of
baseline, genummerd in volgorde, de nieuwste onderaan. Een log hoort bij een branch; vergelijk nooit
over branches heen.
"""

import argparse
import csv
import html
import re
import sys
from datetime import datetime
from pathlib import Path

LOGKOLOMMEN = ["nr", "tijd", "van", "van_datum", "naar", "naar_datum", "commits", "samenvatting", "oordeel",
               "tifs_anders", "tifs_totaal", "checks_anders", "checks_totaal", "rapport"]


def lees_log(pad):
    if not Path(pad).is_file():
        return []
    with open(pad, newline="", encoding="utf8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def schrijf_logregel(pad, van, van_datum, naar, naar_datum, commits, samenvatting, oordeel,
                     tifs_anders="", tifs_totaal="", checks_anders="", checks_totaal="", rapport=""):
    rijen = lees_log(pad)
    nr = len(rijen) + 1
    nieuw = not Path(pad).is_file()
    Path(pad).parent.mkdir(parents=True, exist_ok=True)
    with open(pad, "a", newline="", encoding="utf8") as f:
        w = csv.writer(f, delimiter=";")
        if nieuw:
            w.writerow(LOGKOLOMMEN)
        w.writerow([nr, datetime.now().strftime("%Y-%m-%d %H:%M"), van, van_datum, naar, naar_datum, commits,
                    (samenvatting or "").replace("\n", " ").strip(), oordeel, tifs_anders, tifs_totaal, checks_anders, checks_totaal, rapport])
    return nr


def oordeel_klasse(oordeel):
    o = (oordeel or "").upper()
    if o.startswith("IDENTIEK"):
        return "ok"
    if o.startswith("STAND GELIJK"):
        return "meet"
    if o.startswith("VERSCHILT"):
        return "warn"
    if o.startswith("BASELINE"):
        return "base"
    if o.startswith("GEEN OORDEEL"):
        return "muted"
    return "bad"


def inline(tekst):
    t = html.escape(tekst)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


GETAL = re.compile(r"^[-+]?[\d.,]+(\s?(procent|ha|GB|min|%|[a-z]+))?(\s\([^)]*\))?$")
GETALWOORD = {"", "gelijk", "anders", "n.v.t.", "leeg"}


def kolomklassen(body):
    """Per kolom: num als elke gevulde cel een getal is (of gelijk, anders, n.v.t.), anders tekst. Zo
    staat een hele kolom rechts of links en niet cel voor cel wisselend."""
    if not body:
        return []
    n = max(len(r) for r in body)
    klassen = []
    for i in range(n):
        cellen = [r[i] for r in body if i < len(r)]
        getallen = [c for c in cellen if GETAL.match(c) and c not in GETALWOORD]
        rest = [c for c in cellen if not GETAL.match(c) and c not in GETALWOORD]
        klassen.append("num" if getallen and not rest else "")
    return klassen


def md_naar_html(md, zonder_h1=False):
    """De vaste rapportvorm naar html: koppen, tabellen, opsommingen, ingesprongen regels, alinea's.
    Onder de kop Verder kijken wordt elke ### een inklapbaar blok."""
    uit, regels, i = [], md.splitlines(), 0
    alinea = []
    inklap = False
    open_blok = False

    def sluit_alinea():
        if alinea:
            uit.append("<p>" + " ".join(inline(r) for r in alinea) + "</p>")
            alinea.clear()

    def sluit_blok():
        nonlocal open_blok
        if open_blok:
            uit.append("</details>")
            open_blok = False

    while i < len(regels):
        r = regels[i]
        if not r.strip():
            sluit_alinea()
            i += 1
            continue
        m = re.match(r"^(#{1,3}) (.*)", r)
        if m:
            sluit_alinea()
            n = len(m.group(1))
            tekst = inline(m.group(2))
            if n == 1:
                if not zonder_h1:
                    uit.append(f"<h1>{tekst}</h1>")
            elif n == 2:
                sluit_blok()
                inklap = m.group(2).strip().lower().startswith("verder kijken")
                uit.append(f"<h2>{tekst}</h2>")
            elif inklap:
                sluit_blok()
                uit.append(f"<details><summary>{tekst}</summary>")
                open_blok = True
            else:
                uit.append(f"<h3>{tekst}</h3>")
            i += 1
            continue
        if r.startswith("|"):
            sluit_alinea()
            rijen = []
            while i < len(regels) and regels[i].startswith("|"):
                cellen = [c.strip() for c in regels[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"-+", c) for c in cellen):
                    rijen.append(cellen)
                i += 1
            if rijen:
                kop, body = rijen[0], rijen[1:]
                klassen = kolomklassen(body)
                uit.append('<div class="tabel"><table><thead><tr>'
                           + "".join(f'<th{" class=\"num\"" if k == "num" else ""}>{inline(c)}</th>' for c, k in zip(kop, klassen + [""] * len(kop)))
                           + "</tr></thead><tbody>")
                for rij in body:
                    cellen = []
                    for j, c in enumerate(rij):
                        k = [klassen[j]] if j < len(klassen) and klassen[j] else []
                        if c.lower() == "anders" or c.lower().startswith("anders ") or "(andere klasse)" in c:
                            k.append("warn")
                        elif c.lower() == "gelijk":
                            k.append("ok")
                        cellen.append(f'<td{" class=\"" + " ".join(k) + "\"" if k else ""}>{inline(c)}</td>')
                    uit.append("<tr>" + "".join(cellen) + "</tr>")
                uit.append("</tbody></table></div>")
            continue
        if r.startswith("- "):
            sluit_alinea()
            uit.append("<ul>")
            while i < len(regels) and regels[i].startswith("- "):
                uit.append(f"<li>{inline(regels[i][2:])}</li>")
                i += 1
            uit.append("</ul>")
            continue
        if r.startswith("  "):
            sluit_alinea()
            blok = []
            while i < len(regels) and regels[i].startswith("  "):
                blok.append(html.escape(regels[i].strip()))
                i += 1
            uit.append("<pre>" + "\n".join(blok) + "</pre>")
            continue
        alinea.append(r)
        i += 1
    sluit_alinea()
    sluit_blok()
    return "\n".join(uit)


STIJL = """
<style>
/* Een kolom op volle breedte (max 76rem); tekst en tabellen even breed, tabellen met eigen zijwaartse scroll. */
:root {
  --bg: #f5f6f8; --fg: #1c2330; --muted: #5b6577; --line: #d6dbe3; --panel: #ffffff;
  --accent: #1e5a86; --ok: #2b7a4b; --meet: #3b6ea8; --warn: #a86400; --bad: #b3261e; --base: #5b6577;
  --font-body: 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', ui-monospace, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #131920; --fg: #e4e9f0; --muted: #98a3b3; --line: #2a3441; --panel: #1a222c;
    --accent: #7db4dd; --ok: #6cc48c; --meet: #8db6e6; --warn: #e2a74f; --bad: #ef8079; --base: #98a3b3; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #131920; --fg: #e4e9f0; --muted: #98a3b3; --line: #2a3441; --panel: #1a222c;
  --accent: #7db4dd; --ok: #6cc48c; --meet: #8db6e6; --warn: #e2a74f; --bad: #ef8079; --base: #98a3b3; color-scheme: dark;
}
body { background: var(--bg); color: var(--fg); font-family: var(--font-body); font-size: 15px; line-height: 1.5;
       padding-inline: 16px; padding-block: 24px 48px; }
main { max-width: 76rem; margin-inline: auto; display: grid; gap: 28px; }
header h1 { font-size: 1.6rem; margin: 0 0 4px; text-wrap: balance; }
header p { margin: 0; color: var(--muted); }
h1 { font-size: 1.3rem; margin: 0; } h2 { font-size: 1.1rem; margin: 20px 0 8px; } h3 { font-size: 1rem; margin: 14px 0 4px; color: var(--muted); }
p { margin: 0 0 8px; }
code, pre, .num, .sha { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
code { font-size: 0.92em; }
pre { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 8px 12px; overflow-x: auto; font-size: 0.86em; margin: 0 0 10px; white-space: pre-wrap; }
.tabel { overflow-x: auto; margin: 0 0 12px; }
table { border-collapse: collapse; width: 100%; font-size: 0.92em; }
th, td { text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.04em; }
th.num, td.num { text-align: right; white-space: nowrap; }
td.warn { color: var(--warn); font-weight: 600; } td.ok { color: var(--ok); }
ul { margin: 0 0 8px; padding-left: 20px; }
li { margin: 0 0 3px; }
.pil { display: inline-block; padding: 2px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8em; letter-spacing: 0.04em;
       border: 1.5px solid currentColor; white-space: nowrap; }
.ok { color: var(--ok); } .meet { color: var(--meet); } .warn { color: var(--warn); } .bad { color: var(--bad); } .base { color: var(--base); } .muted { color: var(--muted); }
.log td.tijd { white-space: nowrap; color: var(--muted); }
.log .sha { white-space: nowrap; }
.log .datum { color: var(--muted); font-size: 0.9em; white-space: nowrap; }
.log td.wat { min-width: 18rem; }
details { border: 1px solid var(--line); border-radius: 4px; padding: 6px 12px; margin: 0 0 8px; }
details[open] { padding-bottom: 10px; }
summary { cursor: pointer; font-weight: 600; padding: 4px 0; }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
section.rapport { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 16px 20px; }
details.rapport { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 0 20px 16px; margin-bottom: 12px; }
details.rapport > summary { cursor: pointer; padding: 12px 0; font-weight: 600; }
details.rapport > summary .pil { margin-left: 6px; }
details.rapport > summary .wat { font-weight: 400; color: var(--muted); }
.uitleg { color: var(--muted); font-size: 0.92em; }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 480px) { body { font-size: 14px; } th, td { padding: 4px 6px; } }
</style>
"""

FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;600&display=swap">'


def pagina(titel, body):
    return f"<title>{html.escape(titel)}</title>\n{FONTS}\n{STIJL}\n<main>\n{body}\n</main>\n"


def rapportpagina(md, titel):
    return pagina(titel, '<section class="rapport">' + md_naar_html(md) + "</section>")


def logpagina(rijen, titel, ondertitel):
    def commit(r, sleutel):
        sha = html.escape(r.get(sleutel) or "")
        datum = html.escape(r.get(sleutel + "_datum") or "")
        if not sha:
            return ""
        return f'<span class="sha">{sha}</span>' + (f' <span class="datum">{datum}</span>' if datum else "")

    def pil(oordeel):
        k = oordeel_klasse(oordeel)
        return f'<span class="pil {k}">{html.escape((oordeel or "").split(":")[0])}</span>'

    def rest(oordeel):
        return html.escape((oordeel or "").split(":", 1)[-1].strip()) if ":" in (oordeel or "") else ""

    delen = [f"<header><h1>{html.escape(titel)}</h1><p>{html.escape(ondertitel)}</p></header>"]
    delen.append("<section>")
    if not rijen:
        delen.append('<p class="uitleg">Nog geen toets gedraaid. Een toets start met pwsh batch\\Toets.ps1 en zet hier een regel bij.</p>')
    else:
        delen.append('<div class="tabel log"><table><thead><tr><th class="num">nr</th><th>wanneer</th><th>van</th><th>naar</th>'
                     '<th class="num">commits</th><th>wat zit ertussen</th><th>oordeel</th><th class="num">standtifs anders</th>'
                     '<th class="num">controlewaarden anders</th></tr></thead><tbody>')
        for r in reversed(rijen):
            k = oordeel_klasse(r.get("oordeel"))
            is_base = k == "base"
            delen.append("<tr>"
                         f"<td class=\"num\">{html.escape(r.get('nr') or '')}</td>"
                         f"<td class=\"tijd\">{html.escape(r.get('tijd') or '')}</td>"
                         f"<td>{commit(r, 'van')}</td>"
                         f"<td>{commit(r, 'naar')}</td>"
                         f"<td class=\"num\">{html.escape(r.get('commits') or '')}</td>"
                         f"<td class=\"wat\">{html.escape(r.get('samenvatting') or '')}</td>"
                         f"<td class=\"{k}\">{pil(r.get('oordeel') or '')}</td>"
                         f"<td class=\"num\">{'' if is_base else html.escape(r.get('tifs_anders') or '') + ' van ' + html.escape(r.get('tifs_totaal') or '')}</td>"
                         f"<td class=\"num\">{'' if is_base else html.escape(r.get('checks_anders') or '') + ' van ' + html.escape(r.get('checks_totaal') or '')}</td>"
                         "</tr>")
        delen.append("</tbody></table></div>")
    delen.append('<p class="uitleg">Elke toets rekent een commit door onder het profiel van de baseline (alle instellingen zoals bij de laatste '
                 "productierun) en het testprofiel, en legt de standtifs en de controlewaarden naast die van de kant ervoor. Onder dat profiel is de "
                 "allocatie deterministisch, dus elk verschil is een verschil in de rekenwijze of de invoer. IDENTIEK: stand en controlewaarden gelijk. "
                 "STAND GELIJK: de allocatie is gelijk, alleen een meting is anders. VERSCHILT: de stand is anders.</p></section>")
    # Elk rapport dat nog op schijf staat komt mee, het nieuwste opengeklapt: zo is de pagina het hele log en niet alleen de laatste toets.
    rapporten = []
    for r in reversed(rijen):
        pad = r.get("rapport") or ""
        if pad and Path(pad).is_file():
            rapporten.append((r, Path(pad).read_text(encoding="utf8")))
    if rapporten:
        delen.append('<section class="rapporten"><h2>Rapporten</h2>')
        for i, (r, md) in enumerate(rapporten):
            kop = (f"Toets {html.escape(r.get('nr') or '')}: van {commit(r, 'van')} naar {commit(r, 'naar')} {pil(r.get('oordeel') or '')}"
                   + (f' <span class="wat">{rest(r.get("oordeel"))}</span>' if rest(r.get("oordeel")) else ""))
            delen.append('<details class="rapport"' + (" open" if i == 0 else "") + "><summary>" + kop + "</summary>"
                         + md_naar_html(md, zonder_h1=True) + "</details>")
        delen.append("</section>")
    return pagina(titel, "\n".join(delen))


def main():
    p = argparse.ArgumentParser(description="Het toetslog van een branch als pagina, of een baselineregel in het log.")
    p.add_argument("--log", required=True)
    p.add_argument("--uit")
    p.add_argument("--titel", default="Enginetoets")
    p.add_argument("--ondertitel", default="Groepen commits van een branch, doorgerekend onder het profiel van de baseline en naast elkaar gelegd")
    p.add_argument("--baseline", help="schrijf een regel BASELINE voor deze tag in plaats van een pagina")
    p.add_argument("--commit")
    p.add_argument("--datum")
    p.add_argument("--samenvatting", default="")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf8", errors="replace")
    if a.baseline:
        nr = schrijf_logregel(a.log, "", "", a.commit or "", a.datum or "", "", a.samenvatting, f"BASELINE: {a.baseline}")
        print(f"log: regel {nr}, {a.baseline} op {a.commit}")
        return
    if not a.uit:
        raise SystemExit("geef --uit voor de pagina, of --baseline voor een logregel")
    rijen = lees_log(a.log)
    Path(a.uit).write_text(logpagina(rijen, a.titel, a.ondertitel), encoding="utf8")
    print(f"logpagina: {a.uit} ({len(rijen)} regels)")


if __name__ == "__main__":
    sys.exit(main())
