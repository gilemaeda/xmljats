"""
Campos do element-citation a partir do texto de uma referencia (ABNT ou APA).

Entrada: texto da referencia, tipo (journal | book | thesis | confproc | legal-doc | report | newspaper | webpage | other),
autores ja detectados (lista de strings "SOBRENOME, Nomes" ou "Sobrenome, I."). Saida: dict com as chaves usadas no XML:
  autores        [(sobrenome, nomes)]           person-group author
  editores       [(sobrenome, nomes)]           person-group editor (ABNT "In: FULANO (org.)")
  article-title | chapter-title | source | volume | issue | fpage | lpage | year | edition | publisher-loc | publisher-name
  ext-link | doi | date-in-citation (data de acesso)
  confianca      'alta' | 'media' | 'baixa'     quanto o parser reconheceu da estrutura

Nada e inventado: campo nao reconhecido nao sai. mixed-citation continua levando o texto integral.
"""
import re
from typing import Dict, List, Optional, Tuple

from .util import RE_DOI, RE_URL, limpa_doi, divide_nome, cabecalho_autores

RE_ANO = re.compile(r"(?<![\d./-])(1[6-9]\d{2}|20[0-4]\d)([a-z])?(?![\d/])")
RE_ANO_PAREN = re.compile(r"\((\d{4}[a-z]?)\)")
RE_ACESSO = re.compile(r"\b(Acesso em|Acessado em|Accessed(?: on)?|Retrieved(?: on)?|Consultado(?: el| em)?|Recuperado (?:em|el))\b[:\s]*\[?(.+?)\]?\.?\s*$", re.I)
RE_DISPONIVEL = re.compile(r"\b(Dispon[íi]vel em|Available at|Available from|Disponible en|Recuperado de|Retrieved from)\b[:\s]*", re.I)
RE_VOL = re.compile(r"\b(?:v|vol|volume)\.?\s*(\d+[A-Za-z]?)", re.I)
RE_NUM = re.compile(r"\b(?:n|no|núm|num|number|issue)[.º°]?\s*(\d+(?:[-–/]\d+)?)", re.I)
RE_VOL_NUM_APA = re.compile(r"\b(\d{1,4})\s*\((\d{1,4}(?:[-–/]\d+)?)\)")
RE_PAG = re.compile(r"\b(?:pp?|p[áa]g(?:s|inas)?)\.?\s*(\d+)\s*[-–]\s*(\d+)", re.I)
RE_PAG_UMA = re.compile(r"\b(?:pp?|p[áa]g(?:s|inas)?)\.?\s*(\d+)(?![\d\-–])", re.I)
RE_PAG_APA = re.compile(r",\s*(\d+)\s*[-–]\s*(\d+)\s*\.?(?:\s|$)")
RE_EDICAO = re.compile(r"\b(\d{1,2})\s*[ªa.º°]{0,2}\s*(?:ed|edi[çc][ãa]o|edici[óo]n|edition)\b\.?(?:\s*(?:rev|ampl|atual)\w*\.?)*", re.I)
RE_LOCAL_EDITORA = re.compile(r"(?:^|[.,;]\s*)(?:\[?S\.?\s*l\.?\]?|[A-ZÀ-Ú][\w'’.\-]*(?:\s+(?:de|do|da|dos|das|del|de la|of|the|e|y|and|-)?\s*[A-ZÀ-Ú][\w'’.\-]*)*)\s*:\s*[^:,;.]{2,80}?,\s*(?=\d{4}\b|\[?\d{4}\]?\b|s\.?\s*d\.?\b|\d{1,2}\s+\w+\.?\s+\d{4})")
RE_IN = re.compile(r"\bIn:\s*", re.I)
RE_ORG = re.compile(r"\s*\((?:orgs?|eds?|coords?|dir|comps?|editors?|organizadores?|coordinadores?|Hg|Hrsg)\.?\)\.?", re.I)
RE_TRAD = re.compile(r"(?:\b(?:Tradu[çc][ãa]o|Traducci[óo]n)(?:\s+de|:)?|\bTrad\.|\bTranslated by|\bcom a colabora[çc][ãa]o de)\s*[^.;]+?(?=\.\s|;|,\s*\d|,\s*[A-ZÀ-Ú][^:;,.]{1,40}:|\.?\s*$)", re.I)
RE_COLCHETE_TRAD = re.compile(r"\s*\[[^\]]*tradu[^\]]*\]", re.I)
RE_THESIS = re.compile(r"\b(Tese|Disserta[çc][ãa]o|Monografia|Trabalho de Conclus[ãa]o de Curso|TCC|Doctoral dissertation|PhD thesis|Master.?s thesis|Tesis)\b\s*\(([^)]+)\)?", re.I)
RE_UNIVERSIDADE = re.compile(r"\b((?:Universidade|Universidad|University|Universit[àé]|Pontif[íi]cia|Faculdade|Instituto|Escola|Fundação|Centro Universitário)[^,.;]*)", re.I)
RE_SD = re.compile(r"\[?\bs\.?\s*d\.?\]?", re.I)
RE_TRACO = re.compile(r"^[_\-–—]{3,}\.?\s*")


def _limpa(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip(" .,;:")


def _pessoas(autores: List[str]) -> List[Tuple[str, str]]:
    out = []
    for a in autores:
        a = _limpa(a)
        if not a or a.startswith("("):
            continue
        a = RE_ORG.sub("", a)
        a = re.sub(r",?\s*\d{4}\s*[-–]\s*\d{4}$", "", a)  # "KELSEN, Hans, 1881-1973"
        if "," in a:
            sob, nomes = a.split(",", 1)
        elif a.isupper() or len(a.split()) >= 3:
            sob, nomes = a, None  # autor institucional ("BRASIL", "ORGANIZAÇÃO DAS NAÇÕES UNIDAS") -> <collab>
        else:
            sob, nomes = divide_nome(a)
        sob = sob.strip(" .")
        nomes = nomes.strip(" .") if nomes is not None else None
        if sob:
            out.append((sob, nomes))
    return out


def _tira_autores(t: str, autores: List[str]) -> str:
    """Remove o bloco de autores do inicio do texto."""
    t = RE_TRACO.sub("", t)
    if not autores:
        return t
    ultimo = _limpa(autores[-1])
    chave = ultimo.split(",")[0].strip()
    if t.find(chave) < 0:
        return t
    if re.match(r"^[A-ZÀ-Ú]{2,}", t):  # ABNT: mesmo criterio do extrator de referencias
        cab = cabecalho_autores(t)
        return t[len(cab):].lstrip(" .")
    m = RE_ANO_PAREN.search(t)  # APA: autores vao ate o "(ano)"
    if m:
        return t[m.start():]
    pos = t.find(chave) + len(chave)
    mp = re.compile(r"\.\s+(?=[A-ZÀ-Ú0-9“\"'(\[])").search(t, pos)
    return t[mp.end():] if mp else t[pos:]


def _ano(t: str) -> Optional[str]:
    m = RE_ANO_PAREN.search(t)
    if m:
        return m.group(1)
    sem_acesso = RE_ACESSO.sub("", t)
    anos = RE_ANO.findall(sem_acesso)
    if anos:
        a, suf = anos[-1]
        return a + (suf or "")
    return None


def _split_pontos(t: str) -> List[str]:
    """Divide em segmentos por '. ' ignorando pontos de abreviaturas comuns (v., n., p., ed., org., et al., iniciais)."""
    prot = re.sub(r"\bBs\.\s*As\.", "Bs\u0001 As\u0001", t)  # Buenos Aires
    prot = re.sub(r"\b(v|vol|n|no|p|pp|ed|org|orgs|coord|trad|et al|cf|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez|Jr|St|Dr|Prof|Ed|Eds|Vol|No|s|l)\.", lambda m: m.group(1) + "\u0001", prot, flags=re.I)
    prot = re.sub(r"\b([A-ZÀ-Ú])\.(?=\s*[A-ZÀ-Ú])", "\\1\u0001", prot)  # iniciais
    partes = [p.replace("\u0001", ".").strip() for p in re.split(r"[.?!]\s+(?=[^a-z])", prot)]
    return [p for p in partes if p]


def campos_referencia(texto: str, tipo: str, autores: List[str]) -> Dict:
    t = re.sub(r"\s+", " ", texto or "").strip()
    out: Dict = {"autores": _pessoas(autores), "editores": [], "confianca": "baixa"}
    ano = _ano(t)
    if ano:
        out["year"] = ano
    md = RE_DOI.search(t)
    if md:
        out["doi"] = limpa_doi(md.group(0))
    mu = RE_URL.search(t)
    if mu:
        url = mu.group(0).rstrip(".,;)")
        if not (md and md.group(0) in url and "doi.org" in url):
            out["ext-link"] = url
    ma = RE_ACESSO.search(t)
    if ma and (out.get("ext-link") or out.get("doi")):
        out["date-in-citation"] = _limpa(ma.group(2))
    elif ma:
        # "Disponivel em: . Acesso em: 18 dez. 2024" — a propria referencia ficou sem o endereco.
        # Data de acesso sozinha nao diz nada e a SciELO cobra o ext-link junto, entao ela nao sai.
        out["_acesso_sem_link"] = _limpa(ma.group(2))
    # "GEWIRTZ, Paul; BROOKS, P. (eds.). Law's stories..." — quem abre a referencia sao os organizadores
    # da obra, nao os autores. Sem isso os dois saem como author, que e o que a SciELO le errado.
    cabecalho = cabecalho_autores(t)
    # o "(eds.)" costuma cair logo DEPOIS do bloco de nomes ("BROOKS, P. (eds.)."), entao a janela
    # olha um pouco alem do cabecalho. "In: FULANO (org.)" e outro caso, tratado no capitulo de livro.
    janela = t[: len(cabecalho) + 30]
    if RE_ORG.search(janela) and not re.search("In:", janela):
        out["editores"] = out["autores"]
        out["autores"] = []
    apa = bool(RE_ANO_PAREN.search(t)) and not re.match(r"^[A-ZÀ-Ú]{2,}", t)
    corpo = _tira_autores(t, autores)
    corpo = RE_DISPONIVEL.split(corpo)[0]
    corpo = RE_ACESSO.sub("", corpo)
    corpo = RE_DOI.sub("", corpo)
    corpo = RE_URL.sub("", corpo).strip()
    if apa:
        _apa(corpo, tipo, out)
    else:
        _abnt(corpo, tipo, out)
    for k in list(out):
        if out[k] in ("", None, []) and k not in ("autores", "editores"):
            del out[k]
    return out


_LOC = r"(\[?S\.?\s*l\.?\]?|[A-ZÀ-Ú][^:;,.()\[\]]{1,40}?(?:,\s*[A-Z]{2})?)"
_ED = r"([A-ZÀ-Ú0-9\[][^:;()]{1,80}?)"
# o par "Local: Editora" termina em ", ano", ", s.d.", "; Outro Local:" (editora dupla) ou no fim do texto
_FIM = r"(?=\s*,\s*(?:\[?\d{4}|\[?s\.?\s*d)|\s*;\s*[A-ZÀ-Ú][^:;,.()\[\]]{1,40}?\s*:|\s*\.?\s*$)"
# precedido por inicio, ". ", "; " ou "- ": normal; precedido por ", ": tambem vale (ABNT com virgula antes do local),
# mas a editora precisa comecar em maiuscula, o que evita "Titulo: subtitulo, ..." virar local/editora
RE_LOC_ED_FORTE = re.compile(r"(?:^|[.;]\s+|[-–]\s+)" + _LOC + r"\s*:\s*" + _ED + _FIM)
RE_LOC_ED_FRACO = re.compile(r",\s+" + _LOC + r"\s*:\s*" + _ED + _FIM)


def _local_editora(seg: str, out: Dict):
    """'Local: Editora, ano' (pode repetir: 'Salvador: EDUFBA; São Paulo: Editora UNESP, 2007')."""
    achou = False
    pares = {}
    for rx in (RE_LOC_ED_FORTE, RE_LOC_ED_FRACO):
        for m in rx.finditer(seg):
            loc, ed = _limpa(m.group(1)), _limpa(m.group(2))
            if re.search(r"\b(Tese|Disserta|Tradu|Trad|ed|In)\b", loc, re.I) or len(ed) < 2:
                continue
            pares.setdefault(m.start(1), (loc, ed))
    for pos in sorted(pares):  # na ordem em que aparecem no texto
        loc, ed = pares[pos]
        out.setdefault("publisher-loc", []).append(loc)
        out.setdefault("publisher-name", []).append(ed)
        achou = True
    return achou


def _corta_local(titulo: str) -> str:
    """'Titulo, Local: Editora, ano' -> 'Titulo' (virgula no lugar do ponto antes do local)."""
    m = RE_LOC_ED_FRACO.search(titulo)
    return titulo[: m.start()] if m else titulo


def _abnt(corpo: str, tipo: str, out: Dict):
    t = corpo
    # edicao e traducao saem para nao poluir titulo/editora
    me = RE_EDICAO.search(t)
    if me:
        out["edition"] = me.group(1)
        t = t[: me.start()] + " " + t[me.end():]
    t = RE_COLCHETE_TRAD.sub("", t)
    t = RE_TRAD.sub("", t)
    t = re.sub(r"\s*,\s*,", ",", re.sub(r"\.\s*\.", ".", t))  # sobras da remocao: ". ." e ", ,"
    t = re.sub(r"\s+", " ", t).strip()
    if tipo in ("newspaper", "webpage") and not RE_IN.search(t):
        segs = _split_pontos(t)
        if segs:
            out["article-title"] = _limpa(segs[0])
            if len(segs) > 1:  # "Valor Econômico, São Paulo, 13 out. 2022" -> a fonte vai ate a primeira virgula
                out["source"] = _limpa(segs[1].split(",")[0])
        out["confianca"] = "alta" if out.get("source") else "media"
        return
    if tipo == "journal":
        mv, mn, mp = RE_VOL.search(t), RE_NUM.search(t), RE_PAG.search(t)
        if mv:
            out["volume"] = mv.group(1)
        if mn:
            out["issue"] = mn.group(1)
        if mp:
            out["fpage"], out["lpage"] = mp.group(1), mp.group(2)
        elif RE_PAG_UMA.search(t):
            out["fpage"] = RE_PAG_UMA.search(t).group(1)
        segs = _split_pontos(t)
        if segs:
            out["article-title"] = _limpa(segs[0])
            # a fonte e o segmento seguinte, ate a primeira virgula que antecede local/v./n./ano
            if len(segs) > 1:
                fonte = re.split(r",\s*(?=(?:v|vol|n|no|p|ano|t|tomo|\[?S\.?\s*l|\d{4}|[A-ZÀ-Ú][\wà-ú]+,\s*(?:v|n|p|ano)\b)[.\s]|$)", segs[1], maxsplit=1)[0]
                fonte = re.sub(r",\s*[^,]*$", "", fonte) if re.search(r",\s*(?:v|n|p|ano)\b", fonte) else fonte
                out["source"] = _limpa(fonte)
        out["confianca"] = "alta" if (out.get("source") and out.get("volume")) else "media"
        return
    if tipo == "thesis":
        mt = RE_THESIS.search(t)
        segs = _split_pontos(t)
        if segs:
            out["source"] = _limpa(segs[0])
        if mt:
            out["comment"] = _limpa(mt.group(0).rstrip(")") + ")") if "(" in mt.group(0) else _limpa(mt.group(0))
            resto = t[mt.end():]
            mu = RE_UNIVERSIDADE.search(resto)
            if mu:
                out["publisher-name"] = [_limpa(mu.group(1))]
                ml = re.search(r",\s*([A-ZÀ-Ú][^,.\d]{2,40}?),\s*\d{4}", resto[mu.end() - 1:] if mu else resto)
                if ml:
                    out["publisher-loc"] = [_limpa(ml.group(1))]
        out["confianca"] = "alta" if mt and out.get("publisher-name") else "media"
        return
    if tipo == "legal-doc":
        segs = _split_pontos(t)
        if segs:
            out["source"] = _limpa(segs[0])
        out["confianca"] = "media"
        return
    # livro, capitulo, anais, relatorio, pagina web, outro
    mi = RE_IN.search(t)
    if mi:
        out["chapter-title"] = _limpa(_split_pontos(t[: mi.start()])[0]) if _split_pontos(t[: mi.start()]) else None
        resto = t[mi.end():]
        # organizadores: "NÓVOA, Jorge (org.)" ou "SILVA, A.; SOUZA, B. (orgs.)" ate o primeiro ". " apos "(org.)"
        morg = RE_ORG.search(resto)
        if morg:
            bloco = resto[: morg.start()]
            out["editores"] = _pessoas(re.split(r";\s*|\s+(?:e|and|y|&)\s+(?=[A-ZÀ-Ú])", bloco))
            resto = resto[morg.end():].strip()
        else:
            # sem "(org.)": autores do livro em CAIXA ALTA ate o primeiro ". "
            mb = re.match(r"^((?:[A-ZÀ-Ú][A-ZÀ-Ú'’\-]+(?: [A-ZÀ-Ú][A-ZÀ-Ú'’\-]+)*,\s*[^;.]+?(?:;\s*)?)+)\.\s+", resto)
            if mb:
                out["editores"] = _pessoas(re.split(r";\s*", mb.group(1)))
                resto = resto[mb.end():]
        segs = _split_pontos(resto)
        if segs:
            out["source"] = _limpa(segs[0])
        mp = RE_PAG.search(resto)
        if mp:
            out["fpage"], out["lpage"] = mp.group(1), mp.group(2)
        mv = RE_VOL.search(resto)
        if mv:
            out["volume"] = mv.group(1)
        _local_editora(resto, out)
        out["confianca"] = "alta" if out.get("source") and out.get("publisher-name") else "media"
        return
    segs = _split_pontos(t)
    if segs:
        out["source"] = _limpa(_corta_local(segs[0]))
    _local_editora(t, out)
    if tipo == "confproc":
        mv = RE_VOL.search(t)
        if mv:
            out["volume"] = mv.group(1)
        mp = RE_PAG.search(t)
        if mp:
            out["fpage"], out["lpage"] = mp.group(1), mp.group(2)
    out["confianca"] = "alta" if out.get("source") and (out.get("publisher-name") or tipo in ("webpage", "report", "newspaper")) else "media"


def _apa(corpo: str, tipo: str, out: Dict):
    """APA: Sobrenome, I. (ano). Título. Fonte, vol(num), pp-pp. / (ano). Título do livro. Editora."""
    t = corpo
    m = RE_ANO_PAREN.search(t)
    if m:
        t = t[m.end():].lstrip(". ")
    segs = _split_pontos(t)
    if not segs:
        return
    if tipo == "journal":
        out["article-title"] = _limpa(segs[0])
        resto = " ".join(segs[1:])
        mvn = RE_VOL_NUM_APA.search(resto)
        if mvn:
            out["volume"], out["issue"] = mvn.group(1), mvn.group(2)
            out["source"] = _limpa(resto[: mvn.start()].rstrip(", "))
        else:
            mv = re.search(r",\s*(\d{1,4})\s*,", resto)
            if mv:
                out["volume"] = mv.group(1)
                out["source"] = _limpa(resto[: mv.start()])
            else:
                out["source"] = _limpa(resto.split(",")[0])
        mp = RE_PAG_APA.search(resto) or RE_PAG.search(resto)
        if mp:
            out["fpage"], out["lpage"] = mp.group(1), mp.group(2)
        out["confianca"] = "alta" if out.get("source") and out.get("volume") else "media"
        return
    mi = RE_IN.search(t)
    if mi:
        out["chapter-title"] = _limpa(segs[0])
        resto = t[mi.end():]
        mo = RE_ORG.search(resto)
        if mo:
            out["editores"] = _pessoas(re.split(r",\s*(?=[A-ZÀ-Ú][a-z])|\s+(?:&|and|e|y)\s+", resto[: mo.start()]))
            resto = resto[mo.end():]
        mp = RE_PAG.search(resto)
        if mp:
            out["fpage"], out["lpage"] = mp.group(1), mp.group(2)
            resto = resto[: mp.start()]
        segs2 = _split_pontos(resto.strip(" ,("))
        if segs2:
            out["source"] = _limpa(segs2[0])
            if len(segs2) > 1:
                out["publisher-name"] = [_limpa(segs2[-1])]
    else:
        out["source"] = _limpa(segs[0])
        if len(segs) > 1 and tipo in ("book", "report", "other"):
            resto = [_limpa(x) for x in segs[1:] if _limpa(x) and not RE_URL.search(x)]
            if resto and len(resto[0]) < 80:
                mle = re.match(r"^([^:]{2,40}):\s*(.+)$", resto[0])
                mab = re.match(r"^(Bs\. As\.|S\.\s*l\.|N\.\s*Y\.|D\.\s*F\.)\s+(.+)$", resto[0])
                if mab:  # "Bs. As. Siglo XXI"
                    out["publisher-loc"], out["publisher-name"] = [_limpa(mab.group(1))], [_limpa(mab.group(2))]
                elif mle:  # "Local: Editora"
                    out["publisher-loc"], out["publisher-name"] = [_limpa(mle.group(1))], [_limpa(mle.group(2))]
                elif len(resto) > 1 and len(resto[0].split()) <= 3 and not re.search(r"\d", resto[0]):  # "Barcelona. Anagrama"
                    out["publisher-loc"], out["publisher-name"] = [resto[0]], [resto[1]]
                else:
                    out["publisher-name"] = [resto[0]]
    out["confianca"] = "alta" if out.get("source") and (out.get("publisher-name") or tipo not in ("book",)) else "media"
