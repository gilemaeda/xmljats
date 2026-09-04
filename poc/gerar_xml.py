"""
model.json -> XML JATS/SciELO PS -> validacao packtools (DTD + Schematron SPS) -> comparacao com XML oficial (se houver).

Uso:  python poc/gerar_xml.py [--sps 1.9|1.10] "poc/saida/*.model.json"
Saidas: poc/saida/xml/<nome-base>.xml, poc/saida/xml/<nome>.validacao.md, poc/saida/xml/relatorio_xml.md
"""
import glob
import io
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extrator import xml_jats  # noqa: E402
from extrator.util import normaliza  # noqa: E402

XML_NS = "{http://www.w3.org/XML/1998/namespace}"


def _prepara_catalogo():
    """libxml2 resolve o DOCTYPE pelo catalogo XML do packtools, mas so se XML_CATALOG_FILES estiver no ambiente."""
    try:
        from packtools import catalogs
        cat = getattr(catalogs, "XML_CATALOG", None)
        if cat and not os.environ.get("XML_CATALOG_FILES"):
            os.environ["XML_CATALOG_FILES"] = cat
    except Exception:  # noqa: BLE001
        pass


def _dtd_local(caminho_xml):
    """Fallback: valida com o DTD empacotado no packtools, escolhido pela versao no DOCTYPE."""
    from lxml import etree
    import packtools
    base = os.path.dirname(packtools.__file__)
    doc = etree.parse(caminho_xml)
    doctype = doc.docinfo.doctype or ""
    dtd_path = os.path.join(base, "catalogs", "jats-publishing-dtd-1.3", "JATS-journalpublishing1-3.dtd") if "v1.3" in doctype else os.path.join(base, "catalogs", "jats-publishing-dtd-1.1", "JATS-journalpublishing1.dtd")
    dtd = etree.DTD(dtd_path)
    ok = dtd.validate(doc.getroot())
    return ok, [f"DTD (local {os.path.basename(dtd_path)}): {e.message} (linha {e.line})" for e in dtd.error_log]


def valida_packtools(caminho):
    """Devolve (dtd_ok, sps_ok, erros[str], detalhe)."""
    _prepara_catalogo()
    try:
        from packtools import XMLValidator
    except Exception as e:  # noqa: BLE001
        return None, None, [], f"packtools indisponível: {e}"
    try:
        xv = XMLValidator.parse(caminho)
    except Exception as e:  # noqa: BLE001
        return None, None, [], f"XMLValidator.parse falhou: {e}"
    erros = []
    dtd_ok = sps_ok = None
    try:
        dtd_ok, dtd_err = xv.validate()
        erros += [f"DTD: {getattr(e, 'message', e)} (linha {getattr(e, 'line', '?')})" for e in dtd_err]
    except Exception as e:  # noqa: BLE001
        try:
            dtd_ok, dtd_err = _dtd_local(caminho)
            erros += dtd_err
        except Exception as e2:  # noqa: BLE001
            erros.append(f"validate() falhou: {e}; DTD local também falhou: {e2}")
    try:
        sps_ok, sps_err = xv.validate_style()
        erros += [f"SPS [{getattr(e, 'label', '')}]: {getattr(e, 'message', e)} (linha {getattr(e, 'line', '?')})" for e in sps_err]
    except Exception as e:  # noqa: BLE001
        erros.append(f"validate_style() falhou: {e}")
    return dtd_ok, sps_ok, erros, f"packtools sps_version={getattr(xv, 'sps_version', '?')}"


def _txt(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def compara_com_oficial(gerado, oficial):
    """Compara campos-chave de dois XML JATS. Devolve lista de (campo, ok, esperado, obtido)."""
    from lxml import etree
    g = etree.parse(gerado).getroot()
    o = etree.parse(oficial).getroot()
    out = []

    def cmp(nome, fg, fo, norm=lambda x: x):
        vg, vo = fg(g), fo(o)
        out.append((nome, norm(vg) == norm(vo), vo, vg))

    cmp("article-type", lambda r: r.get("article-type"), lambda r: r.get("article-type"))
    cmp("xml:lang", lambda r: r.get(XML_NS + "lang"), lambda r: r.get(XML_NS + "lang"))
    cmp("journal-id", lambda r: _txt(r.find(".//journal-id")), lambda r: _txt(r.find(".//journal-id")))
    cmp("abbrev-journal-title", lambda r: _txt(r.find(".//abbrev-journal-title")), lambda r: _txt(r.find(".//abbrev-journal-title")))
    cmp("DOI", lambda r: _txt(r.find(".//article-id[@pub-id-type='doi']")), lambda r: _txt(r.find(".//article-id[@pub-id-type='doi']")))
    cmp("heading", lambda r: _txt(r.find(".//subj-group[@subj-group-type='heading']/subject")), lambda r: _txt(r.find(".//subj-group[@subj-group-type='heading']/subject")), normaliza)
    cmp("article-title", lambda r: _txt(r.find(".//article-title")), lambda r: _txt(r.find(".//title-group/article-title")), normaliza)
    cmp("trans-title (idiomas)", lambda r: sorted(t.get(XML_NS + "lang") for t in r.findall(".//trans-title-group")), lambda r: sorted(t.get(XML_NS + "lang") for t in r.findall(".//trans-title-group")))
    cmp("autores (surname)", lambda r: [_txt(x) for x in r.findall(".//contrib[@contrib-type='author']/name/surname")], lambda r: [_txt(x) for x in r.findall(".//contrib[@contrib-type='author']/name/surname")], lambda v: [normaliza(x) for x in v])
    cmp("ORCID", lambda r: [_txt(x) for x in r.findall(".//contrib-id[@contrib-id-type='orcid']")], lambda r: [_txt(x) for x in r.findall(".//contrib-id[@contrib-id-type='orcid']")])
    cmp("aff orgname", lambda r: [_txt(x) for x in r.findall(".//aff/institution[@content-type='orgname']")], lambda r: [_txt(x) for x in r.findall(".//aff/institution[@content-type='orgname']")], lambda v: [normaliza(x) for x in v])
    cmp("aff país", lambda r: [x.get("country") for x in r.findall(".//aff/country")], lambda r: [x.get("country") for x in r.findall(".//aff/country")])
    cmp("volume/issue/elocation", lambda r: (_txt(r.find(".//volume")), _txt(r.find(".//issue")), _txt(r.find(".//elocation-id"))), lambda r: (_txt(r.find(".//volume")), _txt(r.find(".//issue")), _txt(r.find(".//elocation-id"))))
    def hist(r):
        return {d.get("date-type"): "-".join(_txt(d.find(t)) for t in ("year", "month", "day") if d.find(t) is not None) for d in r.findall(".//history/date")}
    cmp("history", hist, hist)
    def lic(r):
        el = r.find(".//license")
        return el.get("{http://www.w3.org/1999/xlink}href") if el is not None else None
    cmp("license", lic, lic)
    def resumos(r):
        return {"abstract": len(_txt(r.find(".//abstract/p")).split())} | {("trans-" + t.get(XML_NS + "lang")): len(_txt(t.find("p")).split()) for t in r.findall(".//trans-abstract")}
    rg, ro = resumos(g), resumos(o)
    out.append(("resumos (palavras, ±10%)", set(rg) == set(ro) and all(abs(rg[k] - ro[k]) <= 0.1 * max(ro[k], 1) for k in ro), ro, rg))
    def kwds(r):
        return {k.get(XML_NS + "lang"): len(k.findall("kwd")) for k in r.findall(".//kwd-group")}
    cmp("kwd-group (n por idioma)", kwds, kwds)
    cmp("seções do corpo", lambda r: [_txt(s.find("title")) for s in r.findall("./body/sec")], lambda r: [_txt(s.find("title")) for s in r.findall("./body/sec")], lambda v: [normaliza(x) for x in v])
    cmp("subseções", lambda r: len(r.findall("./body/sec/sec")), lambda r: len(r.findall("./body/sec/sec")))
    cmp("xref bibr (n)", lambda r: len(r.findall(".//xref[@ref-type='bibr']")), lambda r: len(r.findall(".//xref[@ref-type='bibr']")))
    cmp("fn no back (n)", lambda r: len(r.findall("./back/fn-group/fn")), lambda r: len(r.findall("./back/fn-group/fn")))
    cmp("refs (n)", lambda r: len(r.findall(".//ref-list/ref")), lambda r: len(r.findall(".//ref-list/ref")))
    cmp("refs publication-type", lambda r: [e.get("publication-type") for e in r.findall(".//element-citation")], lambda r: [e.get("publication-type") for e in r.findall(".//element-citation")])
    cmp("refs year", lambda r: [_txt(e.find("year")) for e in r.findall(".//element-citation")], lambda r: [_txt(e.find("year")) for e in r.findall(".//element-citation")])
    return out


def main(args):
    versao = "1.9"
    if "--sps" in args:
        i = args.index("--sps")
        versao = args[i + 1]
        args = args[:i] + args[i + 2:]
    paths = []
    for a in args or ["poc/saida/*.model.json"]:
        paths.extend(glob.glob(a))
    os.makedirs("poc/saida/xml", exist_ok=True)
    with io.open("modelos/revistas.json", encoding="utf-8") as f:
        revistas = json.load(f)["revistas"]
    oficiais = {os.path.basename(p): p for p in glob.glob("modelos/gabarito/*.xml")}
    relatorio = ["# Geração de XML e validação packtools", "", f"SPS {versao}", "", "| Arquivo | Nome-base SPS | Bloqueantes | Avisos | DTD | SPS (Schematron) | Erros packtools |", "|---|---|---|---|---|---|---|"]
    for p in paths:
        nome = os.path.basename(p).replace(".model.json", "")
        with io.open(p, encoding="utf-8") as f:
            model = json.load(f)
        rev = xml_jats.escolhe_revista(model, revistas)
        try:
            res = xml_jats.gera_xml(model, rev, versao=versao)
        except Exception:  # noqa: BLE001
            print(f"### {nome}: ERRO no gerador\n{traceback.format_exc()}")
            continue
        base = res.nome_base or nome
        xml_path = f"poc/saida/xml/{base}.xml"
        with open(xml_path, "wb") as f:
            f.write(res.xml)
        dtd_ok, sps_ok, erros, detalhe = valida_packtools(xml_path)
        linhas = [f"# {nome}", "", f"- XML: `{xml_path}` ({len(res.xml)} bytes) · revista: {rev['acronimo'] if rev else 'NÃO CADASTRADA'} · {detalhe}",
                  f"- DTD: {dtd_ok} · Schematron SPS: {sps_ok} · erros packtools: {len(erros)}", "", "## Bloqueantes (regras nossas)"] + [f"- {b}" for b in res.bloqueantes] + ["", "## Avisos"] + [f"- {a}" for a in res.avisos] + ["", "## Erros do packtools"] + [f"- {e}" for e in erros[:80]]
        # comparacao com XML oficial (por acrônimo no nome do arquivo)
        oficial = next((v for k, v in oficiais.items() if rev and k.startswith(rev["acronimo"] + "-")), None)
        if oficial:
            try:
                comp = compara_com_oficial(xml_path, oficial)
                linhas += ["", f"## Comparação com o XML oficial ({os.path.basename(oficial)})", "", "| Campo | Igual? | Oficial | Gerado |", "|---|---|---|---|"]
                for campo, ok, vo, vg in comp:
                    linhas.append(f"| {campo} | {'sim' if ok else 'NÃO'} | {str(vo)[:90]} | {str(vg)[:90]} |")
                print(f"    comparação com oficial: {sum(1 for _, ok, _, _ in comp if ok)} de {len(comp)} campos iguais")
            except Exception:  # noqa: BLE001
                linhas += ["", "## Comparação com o XML oficial: ERRO", traceback.format_exc()]
        with io.open(f"poc/saida/xml/{nome}.validacao.md", "w", encoding="utf-8") as f:
            f.write("\n".join(linhas))
        print(f"ok  {nome} -> {base}.xml · bloqueantes {len(res.bloqueantes)} · avisos {len(res.avisos)} · DTD {dtd_ok} · SPS {sps_ok} · erros packtools {len(erros)}")
        relatorio.append(f"| {nome} | {base} | {len(res.bloqueantes)} | {len(res.avisos)} | {dtd_ok} | {sps_ok} | {len(erros)} |")
    with io.open("poc/saida/xml/relatorio_xml.md", "w", encoding="utf-8") as f:
        f.write("\n".join(relatorio) + "\n")
    print("\n" + "\n".join(relatorio[4:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
