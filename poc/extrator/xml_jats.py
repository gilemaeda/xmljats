"""Gerador de XML JATS / SciELO PS a partir do ArticleModel (dict vindo do model.json) + cadastro da revista.

Espelha a estrutura do XML oficial da SciELO (ver modelos/gabarito/rdp-*.xml): journal-meta, article-meta com
article-categories, title-group, contrib-group (contrib + aff), author-notes, pub-date, history, permissions,
abstract/trans-abstract, kwd-group, counts; body com sec/title/p e xref bibr; back com fn-group e ref-list
(mixed-citation + element-citation).

Nada e inventado: campo ausente vira aviso e, quando a SPS o exige, o XML sai marcado como rascunho (draft=True).
"""
import re
from typing import List, Optional, Tuple

from lxml import etree

from .util import normaliza, divide_nome, RE_CHAMADA_NOTA
from .citacao import campos_referencia

XLINK = "http://www.w3.org/1999/xlink"
MML = "http://www.w3.org/1998/Math/MathML"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NSMAP = {"xlink": XLINK, "mml": MML}

VERSOES = {
    "1.9": {"dtd": "1.1", "sps": "sps-1.9",
            "doctype": '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" "http://jats.nlm.nih.gov/publishing/1.1/JATS-journalpublishing1.dtd">'},
    "1.10": {"dtd": "1.3", "sps": "sps-1.10",
             "doctype": '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.3 20210610//EN" "https://jats.nlm.nih.gov/publishing/1.3/JATS-journalpublishing1-3.dtd">'},
}
ROTULO_RESUMO = {"pt": "Resumo", "en": "Abstract", "es": "Resumen", "fr": "Résumé", "it": "Riassunto", "de": "Zusammenfassung"}
ROTULO_KW = {"pt": "Palavras-chave:", "en": "Keywords:", "es": "Palabras clave:", "fr": "Mots-clés:", "it": "Parole chiave:", "de": "Schlüsselwörter:"}
LICENCA_P = {
    "by": {"pt": "Este é um artigo publicado em acesso aberto sob uma licença Creative Commons Atribuição 4.0 Internacional.",
           "en": "This is an open-access article distributed under the terms of the Creative Commons Attribution 4.0 International License.",
           "es": "Este es un artículo publicado en acceso abierto bajo una licencia Creative Commons Atribución 4.0 Internacional."},
    "by-nc": {"pt": "Este é um artigo publicado em acesso aberto sob uma licença Creative Commons Atribuição-NãoComercial 4.0 Internacional.",
              "en": "This is an open-access article distributed under the terms of the Creative Commons Attribution-NonCommercial 4.0 International License.",
              "es": "Este es un artículo publicado en acceso abierto bajo una licencia Creative Commons Atribución-NoComercial 4.0 Internacional."},
    "by-nc-sa": {"pt": "Este é um artigo publicado em acesso aberto sob uma licença Creative Commons Atribuição-NãoComercial-CompartilhaIgual 4.0 Internacional.",
                 "en": "This is an open-access article distributed under the terms of the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License.",
                 "es": "Este es un artículo publicado en acceso abierto bajo una licencia Creative Commons Atribución-NoComercial-CompartirIgual 4.0 Internacional."},
}
PAIS_NOME = {"BR": "Brasil", "AR": "Argentina", "PT": "Portugal", "US": "United States of America", "ES": "España", "MX": "México", "CO": "Colombia", "CL": "Chile", "UY": "Uruguay", "PE": "Perú", "IT": "Italia", "FR": "France", "DE": "Deutschland", "GB": "United Kingdom", "CA": "Canada"}


class Resultado:
    def __init__(self):
        self.avisos: List[str] = []
        self.bloqueantes: List[str] = []
        self.xml: Optional[bytes] = None
        self.nome_base: Optional[str] = None
        self.imagens: List[tuple] = []  # (arquivo de origem do extrator, nome SPS no pacote)
        self.campos_referencias: List[dict] = []  # campos do element-citation de cada referencia, na ordem, com confianca

    def aviso(self, m):
        self.avisos.append(m)

    def bloqueia(self, m):
        self.bloqueantes.append(m)


# ---------------------------------------------------------------- utilitarios

def _sub(parent, tag, text=None, **attrs):
    el = etree.SubElement(parent, tag)
    for k, v in attrs.items():
        if v is None:
            continue
        if k == "xml_lang":
            el.set(f"{{{XML_NS}}}lang", v)
        elif k == "xlink_href":
            el.set(f"{{{XLINK}}}href", v)
        else:
            el.set(k.replace("_", "-"), v)
    if text is not None:
        el.text = str(text)
    return el


def _data(parent, tag, iso, **attrs):
    """iso 'AAAA-MM-DD' -> <tag><day/><month/><year/>."""
    if not iso:
        return None
    el = _sub(parent, tag, **attrs)
    y, m, d = (iso.split("-") + [None, None])[:3]
    if d:
        _sub(el, "day", d)
    if m:
        _sub(el, "month", m)
    _sub(el, "year", y)
    return el


def escolhe_revista(model: dict, revistas: List[dict]) -> Optional[dict]:
    issns = set(model.get("issn") or [])
    for r in revistas:
        if issns & {r.get("issn_epub"), r.get("issn_ppub")}:
            return r
    doi = model.get("doi") or ""
    for r in revistas:
        if r.get("doi_prefixo") and doi.startswith(r["doi_prefixo"]):
            return r
    return None


def nome_base_sps(rev: Optional[dict], model: dict) -> Optional[str]:
    """ISSN-acronimo-volume-numero-(elocation|fpage) conforme regras de nomeacao SPS."""
    if not rev:
        return None
    issn = rev.get("issn_epub") or rev.get("issn_ppub")
    partes = [issn, rev["acronimo"]]
    if model.get("volume"):
        partes.append(model["volume"].zfill(2))
    if model.get("numero"):
        partes.append(model["numero"].zfill(2))
    if model.get("elocation"):
        partes.append(model["elocation"])
    elif model.get("fpage"):
        partes.append(model["fpage"].zfill(5))
    return "-".join(p for p in partes if p)


def _xref_bibr(p_el, texto: str, citacoes: List[dict], figuras: Optional[List[dict]] = None, notas_rid: Optional[dict] = None,
               sem_nota: Optional[list] = None, tabelas: Optional[List[dict]] = None, equacoes: Optional[List[dict]] = None):
    """Preenche <p> com texto e <xref> para referencias (bibr), figuras (fig) e notas de rodape (fn).
    As chamadas de nota chegam embutidas no texto como "[^3]" (ver leitura.texto_marcado); cada uma vira
    <xref ref-type="fn" rid="fnN"><sup>3</sup></xref>. Sem nota correspondente, sai so <sup>3</sup> e o rotulo vai para sem_nota."""
    marcas: List[Tuple[int, int, str, str]] = []
    for m in RE_CHAMADA_NOTA.finditer(texto):
        rotulo = m.group(1)
        fila = (notas_rid or {}).get(rotulo) or []
        if fila:
            marcas.append((m.start(), m.end(), fila.pop(0), "fn"))
        else:
            marcas.append((m.start(), m.end(), rotulo, "sup"))
            if sem_nota is not None:
                sem_nota.append(rotulo)
    for c in citacoes:
        if c.get("ref_index") is None:
            continue
        alvo = c["texto"]
        pos = texto.find(alvo)
        while pos >= 0:
            fim = pos + len(alvo)
            if not any(a < fim and pos < b for a, b, _, _ in marcas):
                marcas.append((pos, fim, f"B{c['ref_index'] + 1}", "bibr"))
                break
            pos = texto.find(alvo, fim)
    for f in figuras or []:
        if not f.get("numero") or not f.get("_rid"):
            continue
        for m in re.finditer(r"\b(Fig(?:ura|\.)|Figure)\s*" + re.escape(f["numero"]) + r"(?!\d)", texto):
            if not any(a < m.end() and m.start() < b for a, b, _, _ in marcas):
                marcas.append((m.start(), m.end(), f["_rid"], "fig"))
    for t in tabelas or []:
        if not t.get("numero") or not t.get("_rid"):
            continue
        for m in re.finditer(r"\b(Tabelas?|Tables?|Quadros?|Cuadros?)\.?\s*" + re.escape(t["numero"]) + r"(?!\d)", texto, re.I):
            if not any(a < m.end() and m.start() < b for a, b, _, _ in marcas):
                marcas.append((m.start(), m.end(), t["_rid"], "table"))
    for e in equacoes or []:
        if not e.get("numero") or not e.get("_rid"):
            continue
        for m in re.finditer(r"\b(equa[çc][ãa]o|equation|eq\.?|f[óo]rmula)\s*\(?" + re.escape(e["numero"]) + r"\)?(?!\d)", texto, re.I):
            if not any(a < m.end() and m.start() < b for a, b, _, _ in marcas):
                marcas.append((m.start(), m.end(), e["_rid"], "disp-formula"))
    marcas.sort()
    cursor, ultimo = 0, None
    for ini, fim, rid, tipo in marcas:
        trecho = texto[cursor:ini]
        if ultimo is None:
            p_el.text = (p_el.text or "") + trecho
        else:
            ultimo.tail = (ultimo.tail or "") + trecho
        if tipo == "fn":
            ultimo = _sub(p_el, "xref", ref_type="fn", rid=rid)
            _sub(ultimo, "sup", RE_CHAMADA_NOTA.match(texto[ini:fim]).group(1))
        elif tipo == "sup":
            ultimo = _sub(p_el, "sup", rid)
        else:
            ultimo = _sub(p_el, "xref", texto[ini:fim], ref_type=tipo, rid=rid)
        cursor = fim
    resto = texto[cursor:]
    if ultimo is None:
        p_el.text = (p_el.text or "") + resto
    else:
        ultimo.tail = (ultimo.tail or "") + resto


def _tipo_declaracao(titulo: str) -> Optional[str]:
    t = normaliza(titulo)
    if re.search(r"conflito|conflict|interesse", t):
        return "coi-statement"
    if re.search(r"financ|funding|apoio", t):
        return "financial-disclosure"
    if re.search(r"disponibilidade de dados|data availability|dados", t):
        return "data-availability"
    if re.search(r"editor", t):
        return "edited-by"
    if re.search(r"inteligencia artificial|artificial intelligence|\bia\b|\bai\b|originalidade|originality|autoria|authorship|coautoria|contribui", t):
        return "other"
    return None



# ---------------------------------------------------------------- gerador

def gera_xml(model: dict, rev: Optional[dict], versao: str = "1.9", rascunho_ok: bool = True) -> Resultado:
    res = Resultado()
    v = VERSOES[versao]
    lang = model.get("idioma") or "pt"
    res.nome_base = nome_base_sps(rev, model) or "artigo"
    # figuras com imagem: numeracao SPS <base>-gfNN e id f<N>
    figs_xml = []
    for f in model.get("figuras", []):
        if f["tipo"] == "fig" and f.get("arquivo"):
            f = dict(f)
            f["_rid"] = f"f{len(figs_xml) + 1}"
            f["_href"] = f"{res.nome_base}-gf{len(figs_xml) + 1:02d}.tif"
            figs_xml.append(f)
            res.imagens.append((f["arquivo"], f["_href"]))
    art = etree.Element("article", nsmap=NSMAP)
    art.set("article-type", model.get("tipo_artigo") or "research-article")
    art.set("dtd-version", v["dtd"])
    art.set("specific-use", v["sps"])
    art.set(f"{{{XML_NS}}}lang", lang)
    front = _sub(art, "front")

    # ---- journal-meta
    jm = _sub(front, "journal-meta")
    if rev:
        _sub(jm, "journal-id", rev["acronimo"], journal_id_type="publisher-id")
        jtg = _sub(jm, "journal-title-group")
        _sub(jtg, "journal-title", rev["titulo"])
        _sub(jtg, "abbrev-journal-title", rev["abrev"], abbrev_type="publisher")
        if rev.get("issn_epub"):
            _sub(jm, "issn", rev["issn_epub"], pub_type="epub")
        if rev.get("issn_ppub"):
            _sub(jm, "issn", rev["issn_ppub"], pub_type="ppub")
        _sub(_sub(jm, "publisher"), "publisher-name", rev["editora"])
        if "confirmar" in (rev.get("_fonte") or ""):
            res.aviso(f"Cadastro da revista '{rev['acronimo']}' tem campos por confirmar: {rev['_fonte']}")
    else:
        res.bloqueia("Revista não cadastrada: sem acrônimo, título abreviado e editora (J01, J03, J05).")
        _sub(jm, "journal-title-group")

    # ---- article-meta
    am = _sub(front, "article-meta")
    if model.get("elocation"):
        _sub(am, "article-id", model["elocation"], pub_id_type="publisher-id")
    if model.get("doi"):
        _sub(am, "article-id", model["doi"], pub_id_type="doi")
    else:
        res.bloqueia("DOI ausente (A01).")
    order = model.get("order")
    if not order and model.get("elocation"):
        digs = re.sub(r"\D", "", model["elocation"])[-5:]
        order = digs.zfill(5) if digs else None
        res.aviso(f"Order (article-id other) derivado do elocation-id: {order}. Confirmar com o sumário do número (A02).")
    if order:
        _sub(am, "article-id", order, pub_id_type="other")
    else:
        res.bloqueia("Order (article-id pub-id-type='other', 5 dígitos) ausente (A02).")
    heading = model.get("heading") or (rev or {}).get("secao_padrao")
    if heading:
        _sub(_sub(_sub(am, "article-categories"), "subj-group", subj_group_type="heading"), "subject", heading)
        if not model.get("heading"):
            res.aviso(f"Seção (heading) '{heading}' veio do cadastro da revista; confirmar (A04).")
    else:
        res.bloqueia("Seção da revista (heading) ausente (A04).")
    tg = _sub(am, "title-group")
    principal = next((t for t in model.get("titulos", []) if t["tipo"] == "article-title"), None)
    if principal:
        _sub(tg, "article-title", principal["texto"])
    else:
        res.bloqueia("Título ausente (A05).")
    for t in model.get("titulos", []):
        if t["tipo"] == "trans-title" and t.get("idioma"):
            _sub(_sub(tg, "trans-title-group", xml_lang=t["idioma"]), "trans-title", t["texto"])
        elif t["tipo"] == "trans-title":
            res.aviso(f"Título traduzido sem idioma detectado, omitido: '{t['texto'][:50]}…'")

    # ---- contribs e affs
    cg = _sub(am, "contrib-group") if model.get("autores") else None
    autores = model.get("autores", [])
    if not autores:
        res.bloqueia("Nenhum autor (C01).")
    affs = {a["id"]: a for a in model.get("afiliacoes", [])}
    corresp = next((a for a in autores if a.get("email")), None)
    notas = model.get("notas", [])
    for i, a in enumerate(autores, start=1):
        c = _sub(cg, "contrib", contrib_type="author")
        if a.get("orcid"):
            _sub(c, "contrib-id", a["orcid"], contrib_id_type="orcid")
            if a.get("orcid_valido") is False:
                res.bloqueia(f"ORCID inválido para {a['nome_completo']} (C02).")
        else:
            res.bloqueia(f"ORCID ausente para {a['nome_completo']} (C02).")
        nome = _sub(c, "name")
        _sub(nome, "surname", a["sobrenome"])
        if a.get("nomes"):
            _sub(nome, "given-names", a["nomes"])
        for k, aid in enumerate(a.get("aff_ids", [])):
            x = _sub(c, "xref", ref_type="aff", rid=aid)
            _sub(x, "sup", str(list(affs).index(aid) + 1) if aid in affs else str(k + 1))
        if not a.get("aff_ids"):
            res.bloqueia(f"Autor {a['nome_completo']} sem afiliação (C03).")
        if corresp is a:
            _sub(c, "xref", "*", ref_type="corresp", rid="c1")
        bio = next((n for n in notas if n.get("ligada_a") == f"autor:{i}"), None)
        if bio:
            _sub(_sub(c, "bio"), "p", bio["texto"])
    for k, (aid, af) in enumerate(affs.items(), start=1):
        el = _sub(cg, "aff", id=aid)
        _sub(el, "label", str(k))
        _sub(el, "institution", af["texto_original"], content_type="original")
        if af.get("instituicao"):
            _sub(el, "institution", af["instituicao"], content_type="orgname")
        else:
            res.bloqueia(f"Afiliação {aid} sem instituição (C05).")
        if af.get("divisao"):
            _sub(el, "institution", af["divisao"], content_type="orgdiv1")
        if af.get("cidade") or af.get("estado"):
            al = _sub(el, "addr-line")
            if af.get("cidade"):
                _sub(al, "city", af["cidade"])
            if af.get("estado"):
                _sub(al, "state", af["estado"])
        if af.get("pais_iso"):
            _sub(el, "country", af.get("pais") or PAIS_NOME.get(af["pais_iso"], af["pais_iso"]), country=af["pais_iso"])
        else:
            res.bloqueia(f"Afiliação {aid} sem país (C05).")
        if af.get("confianca") == "baixa":
            res.aviso(f"Afiliação {aid} extraída de prosa por heurística; confirmar campos (origem: {af.get('origem')}).")

    # ---- author-notes
    an = _sub(am, "author-notes")
    if corresp:
        co = _sub(an, "corresp", id="c1")
        _sub(co, "label", "Correspondência")
        co[-1].tail = f": {corresp['nome_completo']} "
        _sub(co, "email", corresp["email"])
    else:
        res.bloqueia("Nenhum e-mail de autor correspondente (C07).")
    for n in notas:
        if n.get("ligada_a") == "titulo":
            fn = _sub(an, "fn", fn_type="other", id=n["id"])  # nota do titulo (financiamento, origem do texto): 'other' e aceito em todas as versoes
            _sub(fn, "label", n["rotulo"])
            _sub(fn, "p", n["texto"])
    # declaracoes do back matter (conflito de interesses, financiamento, dados, editores, IA) viram fn tipadas
    for b in model.get("back_matter", []):
        tipo = _tipo_declaracao(b.get("titulo", ""))
        if tipo and versao == "1.9":
            # JATS 1.1 / SPS 1.9 so aceitam a lista fechada de fn-type: coi-statement e data-availability nao existem nela
            tipo = {"coi-statement": "conflict", "data-availability": "other"}.get(tipo, tipo)
        if tipo and b.get("texto"):
            fn = _sub(an, "fn", fn_type=tipo, id=f"fn{len(an) + 1}d")
            _sub(fn, "label", b["titulo"].rstrip(":"))
            _sub(fn, "p", b["texto"])
    if len(an) == 0:
        am.remove(an)

    # ---- datas de publicacao, volume, numero, elocation
    datas = model.get("datas") or {}
    ano = model.get("ano")
    if datas.get("publicado") and len(datas["publicado"]) == 10:
        _data(am, "pub-date", datas["publicado"], date_type="pub", publication_format="electronic")
    elif ano:
        _data(am, "pub-date", ano, date_type="pub", publication_format="electronic")
        res.bloqueia(f"Data de publicação completa (dia e mês) não consta no PDF; só o ano {ano}. A SPS exige dia/mês; buscar no OJS (A09).")
    else:
        res.bloqueia("Data de publicação ausente (A09).")
    if ano:
        _data(am, "pub-date", ano, date_type="collection", publication_format="electronic")
    if model.get("volume"):
        _sub(am, "volume", model["volume"])
    else:
        res.bloqueia("Volume ausente (A08).")
    if model.get("numero"):
        _sub(am, "issue", model["numero"].lstrip("0") or model["numero"])
    if model.get("elocation"):
        _sub(am, "elocation-id", model["elocation"])
    elif model.get("fpage"):
        _sub(am, "fpage", model["fpage"])
        if model.get("lpage"):
            _sub(am, "lpage", model["lpage"])
    else:
        res.bloqueia("Nem elocation-id nem páginas (A08).")

    # ---- history
    if datas.get("recebido") or datas.get("aceito") or datas.get("revisado"):
        h = _sub(am, "history")
        _data(h, "date", datas.get("recebido"), date_type="received")
        _data(h, "date", datas.get("revisado"), date_type="rev-recd")
        _data(h, "date", datas.get("aceito"), date_type="accepted")
    if art.get("article-type") == "research-article" and not (datas.get("recebido") and datas.get("aceito")):
        res.bloqueia("Datas de recebimento e aceite ausentes para research-article (H01).")

    # ---- permissions
    perm = _sub(am, "permissions")
    if ano:
        _sub(perm, "copyright-year", ano)
    lic_url = model.get("licenca_url") or (rev or {}).get("licenca_url")
    lic = (model.get("licenca") or "").lower()
    chave = "by-nc-sa" if "sa" in lic else ("by-nc" if "nc" in lic else "by")
    if not lic_url and lic:
        lic_url = f"https://creativecommons.org/licenses/{chave}/4.0/"
    if lic_url:
        le = _sub(perm, "license", license_type="open-access", xlink_href=lic_url, xml_lang=lang)
        _sub(le, "license-p", LICENCA_P.get(chave, LICENCA_P["by"]).get(lang, LICENCA_P["by"]["en"]))
        if not model.get("licenca"):
            res.aviso("Licença não lida do PDF; usada a do cadastro da revista (L01).")
    else:
        res.bloqueia("Licença ausente (L01).")

    # ---- resumos e palavras-chave
    resumos = model.get("resumos", [])
    principal_r = next((r for r in resumos if r.get("idioma") == lang), resumos[0] if resumos else None)
    if principal_r:
        ab = _sub(am, "abstract")
        _sub(ab, "title", ROTULO_RESUMO.get(lang, principal_r["rotulo"].title()))
        _sub(ab, "p", principal_r["texto"])
    elif art.get("article-type") in ("research-article", "review-article"):
        res.bloqueia("Resumo no idioma do artigo ausente (A12).")
    for r in resumos:
        if r is principal_r or not r.get("idioma"):
            continue
        ta = _sub(am, "trans-abstract", xml_lang=r["idioma"])
        _sub(ta, "title", ROTULO_RESUMO.get(r["idioma"], r["rotulo"].title()))
        _sub(ta, "p", r["texto"])
    for r in resumos:
        if not r.get("idioma"):
            continue
        if r.get("palavras_chave"):
            kg = _sub(am, "kwd-group", xml_lang=r["idioma"])
            _sub(kg, "title", ROTULO_KW.get(r["idioma"], (r.get("rotulo_palavras") or "Keywords") + ":"))
            for k in r["palavras_chave"]:
                _sub(kg, "kwd", k)
        else:
            res.bloqueia(f"Resumo em '{r['idioma']}' sem palavras-chave (A13).")

    # ---- tabelas e equacoes que vao para o XML
    tabs_xml = []
    for t in model.get("tabelas", []):
        if not t.get("celulas"):
            continue  # legenda sem grade reconhecida: fica no aviso T01, nao entra no XML
        t = dict(t)
        t["_rid"] = f"t{len(tabs_xml) + 1}"
        if t.get("qualidade") == "baixa" and t.get("arquivo"):
            t["_href"] = f"{res.nome_base}-gt{len(tabs_xml) + 1:02d}.tif"
            res.imagens.append((t["arquivo"], t["_href"]))
        tabs_xml.append(t)
    eqs_xml = []
    for e in model.get("equacoes", []):
        if not e.get("arquivo"):
            continue  # sem recorte nao ha o que emitir
        e = dict(e)
        e["_rid"] = f"e{len(eqs_xml) + 1:02d}"
        e["_href"] = f"{res.nome_base}-e{len(eqs_xml) + 1:02d}.tif"
        res.imagens.append((e["arquivo"], e["_href"]))
        eqs_xml.append(e)

    # ---- counts
    figs = [f for f in model.get("figuras", []) if f["tipo"] == "fig"]
    counts = _sub(am, "counts")
    # os contadores refletem o que EXISTE no XML
    _sub(counts, "fig-count", count=str(len(figs_xml)))
    _sub(counts, "table-count", count=str(len(tabs_xml)))
    _sub(counts, "equation-count", count=str(len(eqs_xml)))
    _sub(counts, "ref-count", count=str(len(model.get("referencias", []))))
    if model.get("fpage") and model.get("lpage"):
        _sub(counts, "page-count", count=str(int(model["lpage"]) - int(model["fpage"]) + 1))

    # ---- body
    body = _sub(art, "body")
    citacoes = model.get("citacoes", [])
    pilha = []  # (nivel, elemento)
    # notas de rodape do corpo (as ligadas a autor/titulo ja sairam em author-notes): rotulo -> fila de ids, na ordem
    fns = [n for n in notas if not (n.get("ligada_a") or "").startswith("autor") and n.get("ligada_a") != "titulo"]
    notas_rid: dict = {}
    for n in fns:
        notas_rid.setdefault(str(n.get("rotulo") or ""), []).append(n["id"])
    chamadas_sem_nota: list = []

    def _emite_tabela(pai_el, t):
        tw = _sub(pai_el, "table-wrap", id=t["_rid"])
        if t.get("rotulo"):
            _sub(tw, "label", t["rotulo"])
        if t.get("legenda"):
            _sub(_sub(tw, "caption"), "title", t["legenda"])
        if t.get("_href"):  # grade incerta: a tabela vai como imagem, para nao entregar coluna trocada
            _sub(tw, "graphic", xlink_href=t["_href"])
            if t.get("fonte"):
                _sub(_sub(tw, "table-wrap-foot"), "p", "Fonte: " + t["fonte"])
            return
        tab = _sub(tw, "table")
        celulas = t.get("celulas") or []
        n_cab = min(int(t.get("linhas_cabecalho") or 0), max(len(celulas) - 1, 0))
        n_col = int(t.get("colunas") or (max((len(l) for l in celulas), default=1)))
        if n_cab:
            thead = _sub(tab, "thead")
            for linha in celulas[:n_cab]:
                tr = _sub(thead, "tr")
                for k in range(n_col):
                    _sub(tr, "th", (linha[k] if k < len(linha) else "") or "")
        tbody = _sub(tab, "tbody")
        for linha in celulas[n_cab:]:
            tr = _sub(tbody, "tr")
            for k in range(n_col):
                _sub(tr, "td", (linha[k] if k < len(linha) else "") or "")
        if t.get("fonte"):
            _sub(_sub(tw, "table-wrap-foot"), "p", "Fonte: " + t["fonte"])

    def _emite_equacao(pai_el, e):
        df = _sub(pai_el, "disp-formula", id=e["_rid"])
        if e.get("rotulo"):
            _sub(df, "label", e["rotulo"])
        _sub(df, "graphic", xlink_href=e["_href"])

    def _emite_fig(pai_el, f):
        fig = _sub(pai_el, "fig", id=f["_rid"])
        _sub(fig, "label", f["rotulo"])
        if f.get("legenda"):
            _sub(_sub(fig, "caption"), "title", f["legenda"])
        if f.get("fonte"):
            _sub(fig, "attrib", "Fonte: " + f["fonte"])
        _sub(fig, "graphic", xlink_href=f["_href"])

    for si, s in enumerate(model.get("secoes", [])):
        nivel = s.get("nivel") or 1
        while pilha and pilha[-1][0] >= nivel:
            pilha.pop()
        pai = pilha[-1][1] if pilha else body
        sec = _sub(pai, "sec", sec_type=s.get("sec_type"))
        titulo = s.get("titulo_completo") or (f"{s['numero']} {s['titulo']}" if s.get("numero") else s["titulo"])
        _sub(sec, "title", titulo)
        figs_secao = [f for f in figs_xml if f.get("secao_indice") == si]
        tabs_secao = [t for t in tabs_xml if t.get("secao_indice") == si]
        eqs_secao = [e for e in eqs_xml if e.get("secao_indice") == si]
        pars = s.get("paragrafos", [])
        for k, par in enumerate(pars):
            for f in figs_secao:
                if (f.get("pos_paragrafo") or 0) == k:
                    _emite_fig(sec, f)
            for t in tabs_secao:
                if (t.get("pos_paragrafo") or 0) == k:
                    _emite_tabela(sec, t)
            for e in eqs_secao:
                if (e.get("pos_paragrafo") or 0) == k:
                    _emite_equacao(sec, e)
            _xref_bibr(_sub(sec, "p"), par, citacoes, figs_xml, notas_rid, chamadas_sem_nota, tabs_xml, eqs_xml)
        for f in figs_secao:
            if (f.get("pos_paragrafo") or 0) >= len(pars):
                _emite_fig(sec, f)
        for t in tabs_secao:
            if (t.get("pos_paragrafo") or 0) >= len(pars):
                _emite_tabela(sec, t)
        for e in eqs_secao:
            if (e.get("pos_paragrafo") or 0) >= len(pars):
                _emite_equacao(sec, e)
        pilha.append((nivel, sec))
    if not model.get("secoes"):
        res.bloqueia("Corpo do texto sem seções (S01).")
    sem_imagem = [f["rotulo"] for f in figs if not f.get("arquivo")]
    if sem_imagem:
        res.aviso(f"Figura(s) sem imagem no PDF, omitidas do XML: {', '.join(sem_imagem)} (F01).")
    for f in figs_xml:
        if not f.get("chamada_no_texto"):
            res.aviso(f"{f['rotulo']} não é citada no texto (F01).")

    for t in tabs_xml:
        if not t.get("chamada_no_texto"):
            res.aviso(f"{t.get('rotulo') or 'Tabela sem rótulo'} não é citada no texto (T01).")
    sem_grade = [t.get("rotulo") for t in model.get("tabelas", []) if not t.get("celulas")]
    if sem_grade:
        res.aviso(f"Tabela(s) com legenda mas sem grade reconhecida no PDF, fora do XML: {', '.join(x or '?' for x in sem_grade)} (T01).")
    if eqs_xml:
        res.aviso(f"{len(eqs_xml)} equação(ões) em <disp-formula> como imagem: o PDF não guarda MathML. "
                  f"Para MathML é preciso o DOCX ou o LaTeX original (E01).")
        numeros = [int(e["numero"]) for e in eqs_xml if (e.get("numero") or "").isdigit()]
        if numeros:
            faltando = sorted(set(range(min(numeros), max(numeros) + 1)) - set(numeros))
            if faltando:
                res.aviso(f"Numeração de equações com saltos: {', '.join(str(n) for n in faltando)} não saiu separada; "
                          f"confira se ficou dentro do recorte de outra equação (E01).")
    if chamadas_sem_nota:
        res.aviso(f"Chamada(s) de nota no texto sem nota de rodapé correspondente (ficaram como sobrescrito): {', '.join(sorted(set(chamadas_sem_nota), key=lambda x: (len(x), x)))} (N01).")

    # ---- back
    back = _sub(art, "back")
    if fns:
        fg = _sub(back, "fn-group")
        for n in fns:
            fn = _sub(fg, "fn", fn_type=n.get("tipo") or "other", id=n["id"])
            _sub(fn, "label", n["rotulo"])
            _sub(fn, "p", n["texto"])
            if notas_rid.get(str(n.get("rotulo") or "")) and n["id"] in notas_rid[str(n.get("rotulo") or "")]:
                res.aviso(f"Nota {n['id']} (rótulo {n['rotulo']}) sem chamada no texto do corpo; fica no fn-group sem xref (N01).")
    refs = model.get("referencias", [])
    if refs:
        rl = _sub(back, "ref-list")
        _sub(rl, "title", "Referências" if lang == "pt" else ("Referencias" if lang == "es" else "References"))
        conf = {"alta": 0, "media": 0, "baixa": 0}
        for k, r in enumerate(refs, start=1):
            ref = _sub(rl, "ref", id=f"B{k}")
            _sub(ref, "mixed-citation", r["texto"])
            tipo_ref = r.get("tipo") or "other"
            ec = _sub(ref, "element-citation", publication_type=tipo_ref)
            campos = campos_referencia(r["texto"], tipo_ref, r.get("autores", []))
            res.campos_referencias.append(campos)
            conf[campos.get("confianca", "baixa")] += 1
            for grupo, tipo_pg in (("autores", "author"), ("editores", "editor")):
                if campos.get(grupo):
                    pg = _sub(ec, "person-group", person_group_type=tipo_pg)
                    for sob, nomes in campos[grupo]:
                        if nomes is None:  # autor institucional
                            _sub(pg, "collab", sob)
                            continue
                        nm = _sub(pg, "name")
                        _sub(nm, "surname", sob)
                        if nomes:
                            _sub(nm, "given-names", nomes)
            for tag in ("article-title", "chapter-title", "source", "edition"):
                if campos.get(tag):
                    _sub(ec, tag, campos[tag])
            for loc, nome in zip(campos.get("publisher-loc") or [], campos.get("publisher-name") or []):
                _sub(ec, "publisher-loc", loc)
                _sub(ec, "publisher-name", nome)
            for tag in ("volume", "issue", "fpage", "lpage"):
                if campos.get(tag):
                    _sub(ec, tag, campos[tag])
            ano_ref = campos.get("year") or r.get("ano")
            if ano_ref:
                _sub(ec, "year", ano_ref)
            if campos.get("comment"):
                _sub(ec, "comment", campos["comment"])
            doi_ref = campos.get("doi") or r.get("doi")
            if doi_ref:
                _sub(ec, "pub-id", doi_ref, pub_id_type="doi")
            url_ref = campos.get("ext-link") or (r.get("url") if not doi_ref else None)
            if url_ref:
                _sub(ec, "ext-link", url_ref, ext_link_type="uri", xlink_href=url_ref)
            if campos.get("date-in-citation"):
                _sub(ec, "date-in-citation", campos["date-in-citation"], content_type="access-date")
        if conf["media"] or conf["baixa"]:
            res.aviso(f"element-citation: {conf['alta']} de {len(refs)} referências com estrutura reconhecida por inteiro; "
                      f"{conf['media'] + conf['baixa']} com campos parciais, conferir na lista de referências (R02).")
    else:
        res.bloqueia("Lista de referências vazia (R01).")

    if res.bloqueantes and not rascunho_ok:
        return res
    corpo = etree.tostring(art, pretty_print=True, encoding="unicode")
    res.xml = ('<?xml version="1.0" encoding="UTF-8"?>\n' + v["doctype"] + "\n" + corpo).encode("utf-8")
    return res
