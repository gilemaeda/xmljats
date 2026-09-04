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

from .util import normaliza, divide_nome

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


def _xref_bibr(p_el, texto: str, citacoes: List[dict]):
    """Preenche <p> com texto e <xref ref-type="bibr"> nas citacoes ligadas a referencias."""
    marcas: List[Tuple[int, int, str]] = []
    for c in citacoes:
        if c.get("ref_index") is None:
            continue
        alvo = c["texto"]
        pos = texto.find(alvo)
        while pos >= 0:
            fim = pos + len(alvo)
            if not any(a < fim and pos < b for a, b, _ in marcas):
                marcas.append((pos, fim, f"B{c['ref_index'] + 1}"))
                break
            pos = texto.find(alvo, fim)
    marcas.sort()
    cursor, ultimo = 0, None
    for ini, fim, rid in marcas:
        trecho = texto[cursor:ini]
        if ultimo is None:
            p_el.text = (p_el.text or "") + trecho
        else:
            ultimo.tail = (ultimo.tail or "") + trecho
        ultimo = _sub(p_el, "xref", texto[ini:fim], ref_type="bibr", rid=rid)
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


def _pessoas(autores: List[str]):
    out = []
    for a in autores:
        if a.startswith("("):
            continue
        if "," in a:
            sob, nomes = a.split(",", 1)
        else:
            sob, nomes = divide_nome(a)
        out.append((sob.strip(" ."), nomes.strip(" .")))
    return out


def _campos_referencia(r: dict):
    """Heuristica minima para element-citation: fonte/titulo a partir do texto ABNT ou APA."""
    t = r["texto"]
    campos = {}
    m = re.search(r"\((\d{4}[a-z]?)\)\.?\s*(.+)$", t)
    if r.get("tipo") in ("journal",):
        mj = re.search(r"\.\s+([^.]+?)\s*,\s*(?:\[s\.?\s*l\.?\]\s*,\s*)?(?:v|vol)\.?\s*(\d+)", t, re.I)
        if mj:
            campos["source"] = mj.group(1).strip()
            campos["volume"] = mj.group(2)
        mn = re.search(r"\bn\.?\s*(\d+)", t)
        if mn:
            campos["issue"] = mn.group(1)
        mp = re.search(r"\bp\.?\s*(\d+)\s*[-–]\s*(\d+)", t)
        if mp:
            campos["fpage"], campos["lpage"] = mp.group(1), mp.group(2)
        ma = re.search(r"^[^.]+\.\s+(?:[A-Z]\.\s+)*([^.]{10,}?)\.\s", t)
        if ma:
            campos["article-title"] = ma.group(1).strip()
    else:
        if m:  # APA: Sobrenome, I. (ano). Titulo. Local. Editora
            partes = [p.strip() for p in m.group(2).split(". ") if p.strip()]
            if partes:
                campos["source"] = partes[0].rstrip(".")
        else:  # ABNT: AUTORES. Titulo. Local: Editora, ano.
            mt = re.search(r"^[^.]+\.\s+(?:[A-Z]\.\s+)*([^.]{4,}?)\.\s", t)
            if mt:
                campos["source"] = mt.group(1).strip()
            ml = re.search(r"\.\s+([A-ZÀ-Ú][^:.,;]{2,40}):\s*([^,;.]{2,60}),\s*\d{4}", t)
            if ml:
                campos["publisher-loc"], campos["publisher-name"] = ml.group(1).strip(), ml.group(2).strip()
    return campos


# ---------------------------------------------------------------- gerador

def gera_xml(model: dict, rev: Optional[dict], versao: str = "1.9", rascunho_ok: bool = True) -> Resultado:
    res = Resultado()
    v = VERSOES[versao]
    lang = model.get("idioma") or "pt"
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
    cg = _sub(am, "contrib-group")
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

    # ---- counts
    figs = [f for f in model.get("figuras", []) if f["tipo"] == "fig"]
    tabs = [f for f in model.get("figuras", []) if f["tipo"] == "table"]
    counts = _sub(am, "counts")
    # os contadores refletem o que EXISTE no XML; figuras/tabelas ainda nao sao emitidas (ver aviso F01)
    _sub(counts, "fig-count", count="0")
    _sub(counts, "table-count", count="0")
    _sub(counts, "equation-count", count="0")
    _sub(counts, "ref-count", count=str(len(model.get("referencias", []))))
    if model.get("fpage") and model.get("lpage"):
        _sub(counts, "page-count", count=str(int(model["lpage"]) - int(model["fpage"]) + 1))

    # ---- body
    body = _sub(art, "body")
    citacoes = model.get("citacoes", [])
    pilha = []  # (nivel, elemento)
    for s in model.get("secoes", []):
        nivel = s.get("nivel") or 1
        while pilha and pilha[-1][0] >= nivel:
            pilha.pop()
        pai = pilha[-1][1] if pilha else body
        sec = _sub(pai, "sec", sec_type=s.get("sec_type"))
        titulo = s.get("titulo_completo") or (f"{s['numero']} {s['titulo']}" if s.get("numero") else s["titulo"])
        _sub(sec, "title", titulo)
        for par in s.get("paragrafos", []):
            _xref_bibr(_sub(sec, "p"), par, citacoes)
        pilha.append((nivel, sec))
    if not model.get("secoes"):
        res.bloqueia("Corpo do texto sem seções (S01).")
    if figs:
        res.aviso(f"{len(figs)} figura(s) com legenda, mas imagens ainda não são extraídas: fig/graphic não gerados (F01).")

    # ---- back
    back = _sub(art, "back")
    fns = [n for n in notas if not (n.get("ligada_a") or "").startswith("autor") and n.get("ligada_a") != "titulo"]
    if fns:
        fg = _sub(back, "fn-group")
        for n in fns:
            fn = _sub(fg, "fn", fn_type=n.get("tipo") or "other", id=n["id"])
            _sub(fn, "label", n["rotulo"])
            _sub(fn, "p", n["texto"])
            if not n.get("chamada_no_texto"):
                res.aviso(f"Nota {n['id']} (rótulo {n['rotulo']}) sem chamada detectada no texto (N01).")
    refs = model.get("referencias", [])
    if refs:
        rl = _sub(back, "ref-list")
        _sub(rl, "title", "Referências" if lang == "pt" else ("Referencias" if lang == "es" else "References"))
        for k, r in enumerate(refs, start=1):
            ref = _sub(rl, "ref", id=f"B{k}")
            _sub(ref, "mixed-citation", r["texto"])
            ec = _sub(ref, "element-citation", publication_type=r.get("tipo") or "other")
            pessoas = _pessoas(r.get("autores", []))
            if pessoas:
                pg = _sub(ec, "person-group", person_group_type="author")
                for sob, nomes in pessoas:
                    nm = _sub(pg, "name")
                    _sub(nm, "surname", sob)
                    if nomes:
                        _sub(nm, "given-names", nomes)
            campos = _campos_referencia(r)
            for tag in ("article-title", "chapter-title", "source", "publisher-loc", "publisher-name", "volume", "issue", "fpage", "lpage"):
                if campos.get(tag):
                    _sub(ec, tag, campos[tag])
            if r.get("ano"):
                _sub(ec, "year", r["ano"])
            if r.get("doi"):
                _sub(ec, "pub-id", r["doi"], pub_id_type="doi")
            if r.get("url"):
                _sub(ec, "ext-link", r["url"], ext_link_type="uri", xlink_href=r["url"])
        res.aviso("element-citation preenchido por heurística (autores, ano, fonte, DOI/URL); os demais campos exigem revisão (R02).")
    else:
        res.bloqueia("Lista de referências vazia (R01).")

    if res.bloqueantes and not rascunho_ok:
        return res
    res.nome_base = nome_base_sps(rev, model)
    corpo = etree.tostring(art, pretty_print=True, encoding="unicode")
    res.xml = ('<?xml version="1.0" encoding="UTF-8"?>\n' + v["doctype"] + "\n" + corpo).encode("utf-8")
    return res
