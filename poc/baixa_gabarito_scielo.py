"""
Baixa o XML oficial (SciELO PS) de um artigo publicado na SciELO, a partir do DOI.
Serve de gabarito para comparar com o que o nosso pipeline gera.

Uso:  python poc/baixa_gabarito_scielo.py 10.1590/2179-8966/2026/92016 [outro DOI ...]
Saida: modelos/gabarito/<acronimo>-<pid>.xml
"""
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
RE_SCIELO_ART = re.compile(r"https?://www\.scielo\.br/j/([a-z0-9]+)/a/([A-Za-z0-9]+)")


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read()


def acha_artigo_scielo(doi):
    """Devolve (acronimo, pid) ou None."""
    try:
        final, _ = get("https://doi.org/" + doi)
        m = RE_SCIELO_ART.search(final)
        if m:
            return m.group(1), m.group(2)
    except Exception as e:  # noqa: BLE001
        print(f"  doi.org falhou: {e}")
    try:
        _, html = get("https://search.scielo.org/?q=" + urllib.parse.quote(doi) + "&lang=pt")
        m = RE_SCIELO_ART.search(html.decode("utf-8", "ignore"))
        if m:
            return m.group(1), m.group(2)
    except Exception as e:  # noqa: BLE001
        print(f"  busca SciELO falhou: {e}")
    return None


def resumo_xml(caminho):
    tree = ET.parse(caminho)
    root = tree.getroot()
    ns = {"xlink": "http://www.w3.org/1999/xlink"}
    def n(path):
        return len(root.findall(path, ns))
    def t(path):
        el = root.find(path, ns)
        return "".join(el.itertext()).strip() if el is not None else ""
    print(f"  raiz: article-type={root.get('article-type')} dtd-version={root.get('dtd-version')} specific-use={root.get('specific-use')} xml:lang={root.get('{http://www.w3.org/XML/1998/namespace}lang')}")
    print(f"  journal-id: {t('.//journal-meta/journal-id')} | abbrev: {t('.//abbrev-journal-title')} | issn: {[e.text for e in root.findall('.//journal-meta/issn')]}")
    print(f"  heading: {t('.//subj-group[@subj-group-type=\"heading\"]/subject')}")
    print(f"  título: {t('.//article-title')[:90]}")
    print(f"  autores: {n('.//contrib[@contrib-type=\"author\"]')} | aff: {n('.//article-meta/aff')} | orcid: {n('.//contrib-id[@contrib-id-type=\"orcid\"]')}")
    print(f"  datas: " + ", ".join(f"{d.get('date-type')}={t('.//history/date[@date-type=\"' + d.get('date-type') + '\"]/year')}" for d in root.findall('.//history/date')))
    print(f"  abstracts: {n('.//abstract')} + trans: {n('.//trans-abstract')} | kwd-group: {n('.//kwd-group')}")
    print(f"  seções (body/sec): {n('./body/sec')} | fn: {n('.//fn-group/fn')} | xref bibr: {n('.//xref[@ref-type=\"bibr\"]')} | ref: {n('.//ref-list/ref')} | fig: {n('.//fig')} | table-wrap: {n('.//table-wrap')}")


def main(dois):
    os.makedirs("modelos/gabarito", exist_ok=True)
    for doi in dois:
        print(f"\nDOI {doi}")
        hit = acha_artigo_scielo(doi)
        if not hit:
            print("  não encontrado na SciELO (ou DOI não resolve para lá).")
            continue
        acr, pid = hit
        print(f"  artigo SciELO: acrônimo={acr} pid={pid}")
        xml = None
        for tentativa, url in enumerate([f"https://www.scielo.br/j/{acr}/a/{pid}/?format=xml&lang=pt", f"https://www.scielo.br/j/{acr}/a/{pid}/?format=xml"] * 2):
            try:
                _, xml = get(url)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  tentativa {tentativa + 1} falhou ({url}): {e}")
                time.sleep(3)
        if xml is None:
            continue
        if b"<article" not in xml[:5000]:
            print(f"  resposta não parece XML JATS ({len(xml)} bytes). URL: {url}")
            continue
        out = f"modelos/gabarito/{acr}-{pid}.xml"
        with open(out, "wb") as f:
            f.write(xml)
        print(f"  salvo em {out} ({len(xml)} bytes)")
        try:
            resumo_xml(out)
        except Exception as e:  # noqa: BLE001
            print(f"  (não consegui resumir o XML: {e})")


if __name__ == "__main__":
    main(sys.argv[1:] or ["10.1590/2179-8966/2026/92016"])
