"""Front matter: identificadores, revista, heading, titulos, autores, afiliacoes, resumos, palavras-chave, datas, licenca."""
import re
from typing import List, Optional

from .leitura import Documento, Paragrafo, Linha, juntar_linhas
from .modelo import ArticleModel, Titulo, Autor, Afiliacao, Resumo
from .util import (RE_DOI, RE_ISSN, RE_ORCID, RE_EMAIL, RE_LATTES, RE_MARCADOR, SUPERSCRITOS, limpa_doi, orcid_valido,
                   issn_valido, detecta_idioma, parse_data, acha_pais, acha_uf, divide_nome, normaliza, marcador_normalizado)

RE_LABEL_RESUMO = re.compile(r"^(RESUMO|ABSTRACT|RESUMEN|RIASSUNTO|RÉSUMÉ|RESUME|ZUSAMMENFASSUNG|SUMMARY|SUMÁRIO EXECUTIVO)\s*[:.\-–]?\s*(.*)$", re.I)
RE_LABEL_KW = re.compile(r"(PALAVRAS[- ]CHAVES?|KEYWORDS|KEY[- ]WORDS|PALABRAS[- ]CLAVES?|PAROLE CHIAVE|MOTS[- ]CL[ÉE]S|SCHLÜSSELWÖRTER)\s*[:.\-–]?\s*", re.I)
IDIOMA_ROTULO = {"resumo": "pt", "abstract": "en", "resumen": "es", "riassunto": "it", "résumé": "fr", "resume": "fr", "zusammenfassung": "de", "summary": "en",
                 "palavras-chave": "pt", "palavras chave": "pt", "palavras-chaves": "pt", "keywords": "en", "key words": "en", "key-words": "en",
                 "palabras clave": "es", "palabras-clave": "es", "palabras claves": "es", "parole chiave": "it", "mots-clés": "fr", "mots clés": "fr", "schlüsselwörter": "de"}
RE_HEADING = re.compile(
    r"^\[?\s*(artigos?(\s+(inéditos|originais|original|de\s+revisão|científicos?))?|artículos?( originales?)?|original articles?|research articles?|"
    r"editorial(es)?|editoriais|resenhas?|book reviews?|reseñas?|dossi[êe]r?|dossier|dossiê temático|traduç(ão|ões)|translations?|entrevistas?|interviews?|"
    r"ensaios?|essays?|comunica(ção|ções)|notas? de pesquisa|relatos? de experiência|estudos? de caso|debates?|tema livre|seção livre|temas livres)\s*\]?$",
    re.I,
)
RE_HEADING_ROTULADO = re.compile(r"^(eixo tem[áa]tico|se[çc][ãa]o|section|secci[óo]n|área|tema)\s*[:\-–]\s*(.+)$", re.I)
KW_INSTITUICAO = re.compile(
    r"(Universi\w+|Faculdade|Faculty|Facultad|Instituto|Institute|Centro|Center|Centre|Escola|School|Funda[çc][ãa]o|Foundation|Programa|Departamento|"
    r"Department|Pontif[íi]cia|College|Defensoria|Minist[ée]rio|Tribunal|Hospital|Laborat[óo]rio|Academia|Conselho|Secretaria|Observat[óo]rio|Unidade|Rede)",
    re.I,
)
KW_NAO_NOME = re.compile(
    r"(universi|faculdade|faculty|facultad|professor|profesor|doutor|doctor|mestre|master|revista|journal|resumo|abstract|resumen|keywords|palavras|"
    r"editor|editora|copyright|issn|doi|recebido|aceito|artigo|article|programa|instituto|institute|escola|school|centro|center|departamento|department|"
    r"grupo|group|pesquisa|research|lattes|orcid|http|@|licen|creative|commons|tradu|translat|pós|pos-|graduad|bacharel|advogad|defensor|"
    r"submetido|aprovado|publicado|received|accepted|volume|número|vol\.|n\.|p\.|\d)",
    re.I,
)
TOKENS_PROIBIDOS = {
    "para", "sobre", "com", "sem", "the", "of", "and", "on", "in", "as", "a", "o", "os", "um", "uma", "no", "na", "nos", "nas", "por", "del", "las", "los",
    "en", "un", "una", "ao", "aos", "entre", "artes", "direito", "literatura", "research", "reflections", "análise", "analysis", "estudo", "study",
    "caso", "case", "teoria", "theory", "crítica", "critical", "pública", "público", "public", "regime", "democrático", "democracia", "democracy",
    "constituição", "constitution", "método", "method", "metodológicas", "brasil", "brazil", "contribuição", "contribution", "tensões", "possibilidades",
    "tempos", "crise", "instrumento", "defesa", "reformas", "judiciales", "burocracias", "cultura", "law", "literature", "visual", "visuais", "legal",
    "e", "y", "do", "da", "dos", "das", "de",
}
RE_NOME_TOKEN = re.compile(r"^[A-ZÀ-Ú][a-zà-ú'’\-]+\.?$|^[A-ZÀ-Ú]{2,}(?:-[A-ZÀ-Ú]+)?$|^[A-ZÀ-Ú]\.$")
PARTICULAS = {"de", "da", "do", "das", "dos", "e", "del", "della", "di", "van", "von", "der", "la", "le", "y", "dus", "du"}
RE_MARC_FIM = re.compile(r"[\s,]*(\d{1,2}|\*{1,4}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|†|‡|§)(?:[,;\s]*(\d{1,2}|\*{1,4}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|†|‡|§))*\s*$")
KW_BIO = re.compile(r"(doutor|doctor|mestre|master|professor|profesor|pesquisador|investigador|researcher|graduad|bacharel|advogad|defensor|docente|pós-doutor|pos-doutor|postdoc|post-doctoral|lattes|orcid|e-mail|email)", re.I)
RE_POSICAO_ATUAL = re.compile(
    r"(Professor[a]?|Profesor[a]?|Docente|Pesquisador[a]?|Investigador[a]?|Researcher|Doutorand[oa]|Mestrand[oa]|Defensor[a]?|Advogad[oa]|Procurador[a]?|Promotor[a]?|Juiz|Juíza|Analista|Coordenador[a]?|Diretor[a]?|Director|Fellow|Bolsista)"
    r"[^.;]*?(?:\b(?:na|no|da|do|de la|del|at the|of the|in the|at|of|pela|pelo|em|en|junto à|junto ao)\b|-|–)\s+((?:Universi\w+|Faculdade|Faculty|Facultad|Instituto|Institute|Centro|Center|Escola|School|Funda[çc][ãa]o|Programa|Departamento|Pontif[íi]cia|College|Defensoria|Minist[ée]rio|Tribunal|Academia)[^.;()]*)",
    re.I,
)
RE_DIVISAO_INST = re.compile(
    r"^((?:Programa|Departamento|Department|Faculdade|Faculty|Facultad|Escola|School|Centro|Center|Instituto|Institute|N[úu]cleo|Grupo|Laborat[óo]rio|Curso)[^.,;()]*?)"
    r"\s+(?:da|do|de|de la|del|of the|of|at)\s+((?:Universi\w+|Pontif[íi]cia|Faculdade|Facultad|Faculty|Instituto|Institute|Escola|School|Funda[çc][ãa]o|College)[^.,;()]*)$"
)
RE_QUALQUER_INST = re.compile(r"((?:Universi\w+|Faculdade|Faculty|Facultad|Instituto|Institute|Escola|School|Funda[çc][ãa]o|Pontif[íi]cia|College|Defensoria|Minist[ée]rio|Tribunal|Academia)[^.;()]*)")
RE_CIDADE_UF = re.compile(r"([A-ZÀ-Ú][\wÀ-ú]+(?:\s+(?:de|da|do|das|dos)?\s*[A-ZÀ-Ú][\wÀ-ú]+)*)\s*(?:[-–/(]|,)\s*\(?\s*([A-Z]{2})\s*\)?\s*(?:[-–,]\s*)?(?:Brasil|Brazil|BR)?")
RE_DATAS = [
    ("recebido", re.compile(r"\b(recebid[oa]|received|recibido|submetid[oa]|submiss[ãa]o|submission|submitted|enviado)\b\s*(?:em|on|el|:)?\s*", re.I)),
    ("revisado", re.compile(r"\b(revisad[oa]|revised|revisi[óo]n|editorial review[^:]*)\b\s*(?:em|on|:)?\s*", re.I)),
    ("aceito", re.compile(r"\b(aceit[oa]|accepted|aceptado|aprovad[oa]|approved|final editorial decision)\b\s*(?:em|on|el|:)?\s*", re.I)),
    ("publicado", re.compile(r"\b(publicad[oa]|published|publicado en)\b\s*(?:em|on|el|:)?\s*", re.I)),
]
RE_CC = re.compile(r"creative\s+commons[^.\n]{0,160}", re.I)


# ---------------------------------------------------------------- utilitarios de front

def _linhas_front(doc: Documento, i_sec: Optional[int]) -> List[Linha]:
    pars = doc.paragrafos[:i_sec] if i_sec is not None else [p for p in doc.paragrafos if p.pagina <= 2]
    out = []
    for p in pars:
        out.extend(p.linhas)
    return out


def _texto_em(linhas):
    return juntar_linhas([l.texto for l in linhas])


RE_CAB_REVISTA = re.compile(r"\b(v|vol|volume)\.?\s*\d|\bn\.?\s*\d|issn|\be\d{3,}\b|\bano\s+\d", re.I)


def _eh_journal_line(texto, doc: Documento):
    """Linha que repete a identificacao da revista (cabecalho com volume/numero/ISSN).
    Cabecalhos correntes com o titulo curto do artigo NAO contam (senao apagariam o proprio titulo)."""
    n = normaliza(texto)
    if len(n) < 8:
        return False
    for c in doc.cabecalhos:
        if not RE_CAB_REVISTA.search(c):
            continue
        nc = normaliza(re.split(r",?\s+(?:v|vol|volume|ano)\.?\s*\d.*$", c, flags=re.I)[0])
        if len(nc) >= 8 and (n in nc or nc in n):
            return True
    return False


def _strip_marcadores_nome(texto):
    t = re.sub(r"[¹²³⁰-⁹]+", " ", texto)
    t = RE_MARC_FIM.sub("", t)
    t = re.sub(r"^\s*(\*{1,4}|\d{1,2})\s+", "", t)
    return t.strip(" ,;.")


def _marcadores_de(ln: Linha):
    """Marcadores de autor: sobrescritos de fonte, digitos sobrescritos Unicode (¹²), ou asteriscos/digitos no fim da linha."""
    marcs = [marcador_normalizado(s) for s in ln.sups if s]
    for run in re.findall(r"[¹²³⁰-⁹]+", ln.texto):
        marcs.append("".join(SUPERSCRITOS[c] for c in run))
    if not marcs:
        m = RE_MARC_FIM.search(ln.texto)
        if m:
            for g in m.groups():
                if g:
                    marcs.append(marcador_normalizado(g))
    return list(dict.fromkeys(m for m in marcs if m))


def _parece_nome(ln: Linha, doc: Documento):
    texto = ln.texto
    if len(texto) > 80 or KW_NAO_NOME.search(re.sub(r"[¹²³⁰-⁹*]+", "", texto)):
        return 0
    limpo = _strip_marcadores_nome(texto)
    if not limpo or "," in limpo and ";" not in limpo and " e " not in limpo:
        pass
    partes = re.split(r"\s*(?:;|\|| e | and | y |,)\s*", limpo)
    partes = [p for p in partes if p]
    if not partes or len(partes) > 6:
        return 0
    score = 0
    for p in partes:
        toks = p.split()
        if not (2 <= len(toks) <= 7):
            return 0
        for t in toks:
            tl = t.lower()
            if tl in PARTICULAS:
                continue
            if tl in TOKENS_PROIBIDOS:
                return 0
            if not RE_NOME_TOKEN.match(t):
                return 0
    tem_marcador = bool(ln.sups) or bool(RE_MARC_FIM.search(texto)) or bool(re.search(r"[¹²³⁰-⁹]", texto))
    if limpo.isupper() and not tem_marcador:
        return 0  # linha em caixa alta sem marcador: quase sempre e titulo, nao autor
    score += 1
    if tem_marcador:
        score += 2
    if ln.size < doc.corpo_size * 1.3:
        score += 1
    return score


def _sem_aspas_fechadas(textos):
    """Remove trechos entre aspas fechadas na mesma linha (citacoes dentro do titulo) e devolve tambem,
    por linha, se ela fecha uma aspa aberta antes (continua a anterior) e se deixa uma aspa aberta (prende a proxima)."""
    out, fecha_anterior, abre_proxima = [], [], []
    aberta = False
    for t in textos:
        s = t
        fecha = False
        if aberta:
            # fecha uma aspa aberta na linha anterior: o texto continua o titulo anterior; nao se apaga
            s = re.sub(r"^([^“\"]*)[”\"]", r"\1 ", s, count=1)
            fecha, aberta = True, False
        # so citacoes fechadas na mesma linha sao apagadas (ex.: titulo que cita um verso entre aspas)
        s = re.sub(r"[“\"][^”\"]*[”\"]", " ", s)
        abre = bool(re.search(r"[“\"][^”\"]*$", s))
        if abre:
            aberta = True
            s = s.replace("“", " ").replace('"', " ")
        out.append(s)
        fecha_anterior.append(fecha)
        abre_proxima.append(abre)
    return out, fecha_anterior, abre_proxima


def _divide_por_idioma(linhas):
    """Divide uma sequencia de linhas de mesmo estilo em titulos por idioma.
    So aceita uma divisao quando os dois lados, lidos inteiros, tem idiomas decididos e diferentes,
    e nunca divide no meio de uma aspa aberta."""
    textos = [l.texto for l in linhas]
    limpos, fecha_ant, abre_prox = _sem_aspas_fechadas(textos)
    if len(linhas) < 2:
        return [list(linhas)]
    langs = []
    for s in limpos:
        lang, conf = detecta_idioma(s.lower())
        langs.append(lang if (lang and conf >= 0.2) else None)
    # linhas presas por aspas herdam o idioma da vizinha a que estao presas
    for i in range(len(langs)):
        if langs[i] is None and fecha_ant[i] and i > 0:
            langs[i] = langs[i - 1]
    for i in range(len(langs) - 1):
        if langs[i + 1] is None and abre_prox[i]:
            langs[i + 1] = langs[i]
    decididas = [i for i, l in enumerate(langs) if l is not None]
    cortes = []
    for a, b in zip(decididas, decididas[1:]):
        if langs[a] == langs[b]:
            continue
        # entre a (idioma A) e b (idioma B) pode haver linhas indecisas: escolhe o corte que melhor separa os dois lados
        validos = []
        for c in range(a + 1, b + 1):
            if fecha_ant[c] or abre_prox[c - 1]:
                continue
            esq = " ".join(limpos[:c]).lower()
            dire = " ".join(limpos[c:]).lower()
            le, ce = detecta_idioma(esq)
            ld, cd = detecta_idioma(dire)
            if le != langs[a] or ld != langs[b]:
                continue
            validos.append((ce + cd, c))
        if not validos:
            continue
        melhor_score = max(s for s, _ in validos)
        empate = [c for s, c in validos if s >= melhor_score - 0.05]
        # desempate: linha indecisa que comeca com aspa abre titulo novo (fica a direita); senao ela fica com o titulo anterior
        com_aspa = [c for c in empate if textos[c].lstrip().startswith(("“", '"'))]
        cortes.append(min(com_aspa) if com_aspa else max(empate))
    partes, inicio = [], 0
    for c in cortes:
        partes.append(list(linhas[inicio:c]))
        inicio = c
    partes.append(list(linhas[inicio:]))
    return partes


def _divide_autores(texto):
    limpo = _strip_marcadores_nome(texto)
    return [p.strip() for p in re.split(r"\s*(?:;|\|| e | and | y )\s*", limpo) if p.strip()]


# ---------------------------------------------------------------- identificadores e revista

def extrai_identificadores(doc: Documento, model: ArticleModel, linhas_front: List[Linha]):
    p1 = [l for l in doc.linhas if l.pagina == 1]
    fontes = [("cabeçalho", c) for c in doc.cabecalhos] + [("página 1", l.texto) for l in p1] + [("front", l.texto) for l in linhas_front]
    texto_p1 = juntar_linhas([l.texto for l in p1])
    dois = []
    for origem, t in fontes:
        for m in RE_DOI.finditer(t):
            d = limpa_doi(m.group(0))
            if d not in dois:
                dois.append((d, origem))
    if not dois:
        for m in RE_DOI.finditer(texto_p1):
            dois.append((limpa_doi(m.group(0)), "página 1 (texto junto)"))
    if dois:
        # prefere DOI que aparece em cabeçalho repetido; senão o primeiro da página 1
        pref = next((d for d, o in dois if o == "cabeçalho"), dois[0][0])
        model.doi = pref
        model.marca("doi", "lido (" + next(o for d, o in dois if d == pref) + ")")
        model.outros_dois = [d for d, _ in dois if d != pref][:6]
    issns = []
    for _, t in fontes:
        for m in RE_ISSN.finditer(t):
            v = m.group(1).upper()
            if not RE_ORCID.search(t[max(0, m.start() - 6): m.end() + 6]) and v not in issns:
                issns.append(v)
    model.issn = [i for i in issns if issn_valido(i)] or issns[:2]
    if model.issn:
        model.marca("issn", "lido")
    # volume, numero, ano, elocation, paginas: cabeçalhos primeiro, depois página 1
    for origem, t in [("cabeçalho", c) for c in doc.cabecalhos] + [("página 1", l.texto) for l in p1]:
        m = re.search(r"\b(?:v|vol|volume)\.?\s*(\d+)", t, re.I)
        if m and not model.volume:
            model.volume = m.group(1); model.marca("volume", f"lido ({origem})")
        m = re.search(r"\b(?:n|no|núm|num|número|number|issue)\.?\s*(\d+)", t, re.I)
        if m and not model.numero:
            model.numero = m.group(1); model.marca("numero", f"lido ({origem})")
        m = re.search(r"\bano\s+(\d+)\b", t, re.I)
        if m and not model.volume:
            model.volume = m.group(1); model.marca("volume", f"lido ({origem}, 'ano')")
        m = re.search(r"\b(e\d{3,6})\b", t)
        if m and not model.elocation:
            model.elocation = m.group(1); model.marca("elocation", f"lido ({origem})")
        m = re.search(r"\bp\.?\s*(\d{1,4})\s*[-–]\s*(\d{1,4})", t)
        if m and not model.fpage:
            model.fpage, model.lpage = m.group(1), m.group(2); model.marca("paginas", f"lido ({origem})")
        m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", t)
        if m and not model.ano:
            model.ano = m.group(1); model.marca("ano", f"lido ({origem})")
    # titulo da revista: prefixo do cabeçalho antes de ", v." ou "Vol."
    for c in doc.cabecalhos:
        c_limpo = re.sub(r"^\s*\d+\s*[•|·]\s*", "", c)
        m = re.match(r"^(.*?)[,\s]+(?:v\.|vol\.|volume|ano)\s*\d", c_limpo, re.I)
        if m and len(m.group(1)) > 6 and not re.search(r"\|", m.group(1)):
            model.revista_titulo = m.group(1).strip(" ,.")
            model.marca("revista_titulo", "lido (cabeçalho; pode ser título abreviado)")
            break
    if not model.revista_titulo:
        for l in p1:
            if l.bold and re.search(r"revista|journal|review", l.texto, re.I) and len(l.texto) < 120:
                model.revista_titulo = l.texto.strip(); model.marca("revista_titulo", "lido (página 1)")
                break


def extrai_heading(doc: Documento, model: ArticleModel, linhas_front: List[Linha]):
    candidatos = [l.texto for l in linhas_front] + doc.cabecalhos + [l.texto for l in doc.linhas if l.zona == "lateral"] + [l.texto for l in doc.linhas if l.pagina == 1]
    for t in candidatos:
        t2 = t.strip()
        m = RE_HEADING_ROTULADO.match(t2)
        if m and len(m.group(2)) <= 60:
            model.heading = m.group(2).strip(" .")
            model.marca("heading", f"lido ('{m.group(1)}:')")
            return
    for t in candidatos:
        t2 = t.strip()
        if RE_HEADING.match(t2) and len(t2) < 60:
            model.heading = t2.strip("[] ")
            model.marca("heading", "lido (rótulo de seção)")
            return
    for t in candidatos:
        m = re.match(r"^(Dossi[êe]r?|Dossier)\s*[-–:]\s*(.+)$", t.strip(), re.I)
        if m:
            model.heading = m.group(1) + ": " + m.group(2).strip()
            model.marca("heading", "lido (cabeçalho de dossiê)")
            return


# ---------------------------------------------------------------- titulos e autores

def extrai_titulos_e_autores(doc: Documento, model: ArticleModel, linhas_front: List[Linha]):
    corpo = doc.corpo_size
    # 1. localizar inicio dos resumos
    i_resumo = next((i for i, l in enumerate(linhas_front) if RE_LABEL_RESUMO.match(l.texto) or RE_LABEL_KW.match(l.texto)), len(linhas_front))
    # 2. primeiro candidato a titulo (linha em destaque, tamanho >= 0.9 do corpo); autores so valem depois dele
    def _cand_titulo(l):
        t = l.texto.strip()
        if len(t) <= 3 or l.size < corpo * 0.9 or _eh_journal_line(t, doc) or RE_HEADING.match(t) or RE_HEADING_ROTULADO.match(t):
            return False
        if RE_LABEL_RESUMO.match(t) or RE_LABEL_KW.match(t):
            return False
        if RE_DOI.search(t) or RE_ISSN.search(t) or RE_EMAIL.search(t) or re.search(r"©|issn|doi|recebid|aceit|submetid|aprovad|licen[çc]a|creative", t, re.I):
            return False
        if len(t.split()) < 2 and l.size < corpo * 1.3:
            return False  # palavra solta em negrito (Editorial, Autor, Abstract) nao e titulo
        if re.search(r"^\d+\s+\S+\.\s+\d+\s+\S+", t):
            return False  # sumario "1 Introdução. 2 ..."
        return l.bold or l.italic or l.size >= corpo * 1.15
    i_tit0 = next((i for i, l in enumerate(linhas_front[:i_resumo]) if _cand_titulo(l)), 0)
    # 3. autores: linhas com cara de nome depois do primeiro titulo e antes do resumo
    scores = [(_parece_nome(l, doc) if i_tit0 < i < i_resumo else 0) for i, l in enumerate(linhas_front)]
    idx_autores = [i for i, s in enumerate(scores) if s >= 2]
    if not idx_autores:
        idx_autores = [i for i, s in enumerate(scores) if s >= 1]
    # autores contiguos: a partir do primeiro, aceita novos nomes ate o resumo, desde que a distancia nao passe de 6 linhas
    autores_idx = []
    for i in idx_autores:
        if not autores_idx or i - autores_idx[-1] <= 6:
            autores_idx.append(i)
        else:
            break
    i_aut0 = autores_idx[0] if autores_idx else i_resumo
    # 3. titulos: linhas antes do primeiro autor, com destaque
    cand = [l for l in linhas_front[:i_aut0] if _cand_titulo(l)]
    # agrupa por estilo (tamanho com tolerancia de 0,7 pt, negrito, italico) e quebra por idioma
    grupos: List[List[Linha]] = []
    for l in cand:
        if grupos and abs(l.size - grupos[-1][-1].size) <= 0.7 and l.bold == grupos[-1][-1].bold and l.italic == grupos[-1][-1].italic:
            grupos[-1].append(l)
        else:
            grupos.append([l])
    titulos: List[List[Linha]] = []
    for g in grupos:
        for parte in _divide_por_idioma(g):
            titulos.append(parte)
    for k, g in enumerate(titulos):
        texto = _texto_em(g).strip()
        # tira aspas externas so quando o titulo inteiro esta entre um unico par de aspas (traducao entre aspas)
        n_abre, n_fecha, n_retas = texto.count("“"), texto.count("”"), texto.count('"')
        par_unico = (texto[:1] == "“" and texto[-1:] == "”" and n_abre == 1 and n_fecha == 1) or (texto[:1] == '"' and texto[-1:] == '"' and n_retas == 2)
        if par_unico:
            texto = texto[1:-1].strip()
        texto = re.sub(r"[¹²³⁰-⁹]+$", "", texto).strip()
        # nota no titulo (sobrescrito): registra
        for l in g:
            if l.sup_fim or l.sups:
                model.marca("titulo_nota", f"sobrescrito {l.sups} no título")
        # idioma do titulo sem as citacoes entre aspas (um verso citado nao define o idioma do titulo)
        limpos, _, _ = _sem_aspas_fechadas([l.texto for l in g])
        lang, _ = detecta_idioma(" ".join(limpos).lower())
        if not lang:
            lang, _ = detecta_idioma(texto.lower())
        model.titulos.append(Titulo(texto=texto, idioma=lang, tipo="article-title" if k == 0 else "trans-title", pagina=g[0].pagina))
    if model.titulos:
        model.marca("titulos", "lido (linhas em destaque antes dos autores; idioma por detecção)")
    else:
        model.aviso("Título não identificado (nenhuma linha em destaque antes dos autores).")
    # 4. autores (as linhas de ORCID/afiliacao de cada um sao escolhidas por posicao na pagina, nao por ordem de leitura,
    #    porque uma linha de ORCID em fonte menor pode ficar um pouco acima da linha do nome)
    autores_linhas = [linhas_front[i] for i in autores_idx]
    apoio = _linhas_de_apoio(linhas_front, autores_idx, i_tit0, i_resumo)
    atribuidas = _atribui_apoio(apoio, autores_linhas)
    for k, i in enumerate(autores_idx):
        l = linhas_front[i]
        marcs = _marcadores_de(l)
        estrut = atribuidas.get(k, [])
        for nome in _divide_autores(l.texto):
            sobrenome, nomes = divide_nome(nome)
            a = Autor(nome_completo=nome, sobrenome=sobrenome, nomes=nomes, marcadores=marcs)
            _completa_autor(doc, model, a, estrut)
            model.autores.append(a)
    if model.autores:
        model.marca("autores", "lido (linhas com cara de nome entre título e resumo; marcadores ligam a notas)")
    else:
        model.aviso("Nenhum autor identificado.")
    _liga_notas_biograficas(doc, model)
    _orcids_soltos(doc, model)
    _emails_laterais(doc, model)


RE_APOIO_ID = re.compile(r"orcid|lattes|@|https?://", re.I)


def _linhas_de_apoio(linhas_front: List[Linha], autores_idx, i_tit0: int, i_resumo: int):
    """Linhas entre o titulo e o resumo que nao sao nomes: identificadores (ORCID, Lattes, e-mail) ou afiliacoes."""
    out = []
    aut = set(autores_idx)
    for j in range(i_tit0 + 1, i_resumo):
        if j in aut:
            continue
        l = linhas_front[j]
        t = l.texto.strip()
        if not t or re.search(r"^\d+\s+\S+\.\s+\d+\s+\S+", t):
            continue
        if RE_APOIO_ID.search(t):
            out.append(("id", l))
        elif KW_INSTITUICAO.search(t) or re.match(r"^[¹²³⁰-⁹\d*]+\s", t):
            out.append(("aff", l))
    return out


def _atribui_apoio(apoio, autores_linhas: List[Linha]):
    """Cada linha de apoio vai para o autor mais proximo na vertical. A direcao (nome acima ou nome abaixo da linha)
    e decidida por tipo de linha para o documento inteiro: ha revistas que poem o ORCID acima do nome."""
    res = {}
    for tipo in ("id", "aff"):
        linhas = [l for tp, l in apoio if tp == tipo]
        if not linhas:
            continue

        def escolhe(direcao):
            total, escolhas = 0.0, []
            for l in linhas:
                cands = [(k, a) for k, a in enumerate(autores_linhas)
                         if a.pagina == l.pagina and ((a.y0 <= l.y0 + 1) if direcao == "acima" else (a.y0 > l.y0 + 1))]
                if not cands:
                    total += 1000
                    escolhas.append(None)
                    continue
                k, a = min(cands, key=lambda ka: abs(l.y0 - ka[1].y0))
                total += abs(l.y0 - a.y0)
                escolhas.append(k)
            return total, escolhas

        t_acima, e_acima = escolhe("acima")
        t_abaixo, e_abaixo = escolhe("abaixo")
        escolhas = e_acima if t_acima <= t_abaixo else e_abaixo
        for l, k in zip(linhas, escolhas):
            if k is not None:
                res.setdefault(k, []).append(l)
    for k in res:
        res[k].sort(key=lambda l: (l.pagina, l.y0, l.x0))
    return res


def _completa_autor(doc: Documento, model: ArticleModel, a: Autor, estrut: List[Linha]):
    texto = _texto_em(estrut)
    if not texto:
        return
    m = RE_ORCID.search(texto)
    if m:
        a.orcid = m.group(1).upper(); a.orcid_valido = orcid_valido(a.orcid)
    m = RE_EMAIL.search(texto)
    if m:
        a.email = m.group(0).rstrip(".")
    m = RE_LATTES.search(texto)
    if m:
        a.lattes = "http://" + m.group(0)
    # afiliacao estruturada: linha(s) com instituicao e sem cara de biografia
    for l in estrut:
        t = re.sub(r"^[¹²³⁰-⁹\d*\s]+", "", l.texto).strip()
        t = re.split(r"\b(E-?mail|Email|ORCID|Orcid|Lattes)\b", t)[0].strip(" .;")
        if KW_INSTITUICAO.search(t) and not re.search(r"\b(pel[oa]|Doutor|Mestre|Professor|Pós|Post-doctoral|researcher at)\b", t, re.I) and len(t) < 220:
            _nova_afiliacao(model, a, t, origem="linha estruturada sob o autor", confianca="alta")
            return
    for l in estrut:
        t = l.texto.strip()
        if KW_INSTITUICAO.search(t) and len(t) < 260:
            _nova_afiliacao(model, a, t, origem="linha sob o autor (prosa)", confianca="média")
            return


def _nova_afiliacao(model: ArticleModel, a: Autor, texto: str, origem: str, confianca: str):
    # reaproveita afiliacao identica
    for aff in model.afiliacoes:
        if normaliza(aff.texto_original) == normaliza(texto):
            if aff.id not in a.aff_ids:
                a.aff_ids.append(aff.id)
            return aff
    aff = Afiliacao(id=f"aff{len(model.afiliacoes) + 1}", texto_original=texto, origem=origem, confianca=confianca)
    _parse_afiliacao(aff)
    model.afiliacoes.append(aff)
    a.aff_ids.append(aff.id)
    return aff


def _parse_afiliacao(aff: Afiliacao):
    t = aff.texto_original
    pais_nome, iso = acha_pais(t)
    aff.pais_iso = iso
    if pais_nome:
        m = re.search(re.escape(pais_nome), normaliza(t))
        aff.pais = pais_nome.title() if pais_nome not in ("br", "pt", "eua", "usa") else {"br": "Brasil", "pt": "Portugal", "eua": "EUA", "usa": "USA"}[pais_nome]
    segs = [s.strip(" .") for s in re.split(r",", t) if s.strip(" .")]
    if aff.origem.startswith("linha estruturada") and len(segs) >= 2:
        aff.instituicao = segs[0]
        if len(segs) >= 3:
            aff.cidade = segs[1]
            meio = segs[2:-1] if iso else segs[2:]
            if meio:
                aff.estado = meio[0]
        elif len(segs) == 2 and not iso:
            aff.cidade = segs[1]
        if iso and len(segs) == 3 and not aff.estado:
            pass
    else:
        m = RE_POSICAO_ATUAL.search(t)
        inst = None
        if m:
            inst = m.group(2).strip()
        else:
            m2 = RE_QUALQUER_INST.search(t)
            if m2:
                inst = m2.group(1).strip()
        if inst:
            # corta na primeira virgula ou num "e/and/y" seguido de palavra minuscula ("..., e professor associado da ...")
            inst = re.split(r",\s|\s(?:e|and|y)\s(?=[a-zà-ú])", inst)[0].strip(" -–")
            m3 = RE_DIVISAO_INST.match(inst)
            if m3:
                aff.divisao, aff.instituicao = m3.group(1).strip(), m3.group(2).strip()
            else:
                aff.instituicao = inst
        uf = acha_uf(t)
        if uf:
            aff.estado = uf
            mc = re.search(r"([A-ZÀ-Ú][\wÀ-ú]+(?:\s+(?:de|da|do|das|dos)?\s*[A-ZÀ-Ú][\wÀ-ú]+){0,3})\s*(?:[-–/(]|,)\s*\(?\s*" + uf + r"\b", t)
            if mc:
                aff.cidade = mc.group(1).strip()
        if not aff.cidade and pais_nome:
            mc = re.search(r"([A-ZÀ-Ú][\wÀ-ú]+(?:\s+[A-ZÀ-Ú][\wÀ-ú]+){0,2})\s*[,(-]\s*[^,]*?" + re.escape(pais_nome), sem_acento_keep(t), re.I)
            if mc:
                aff.cidade = mc.group(1)
    if aff.instituicao:
        aff.instituicao = aff.instituicao.strip(" .,;:-–")


def sem_acento_keep(t):
    return t


def _liga_notas_biograficas(doc: Documento, model: ArticleModel):
    """Marcador do autor -> nota de rodape (p.1-2) com o mesmo rotulo; extrai bio, ORCID, e-mail, afiliacao."""
    notas = [n for n in doc.notas if n.pagina <= 2]
    def rotulo_de(n: Paragrafo):
        l0 = n.linhas[0]
        if l0.sup_inicio:
            return marcador_normalizado(l0.sup_inicio)
        m = RE_MARCADOR.match(n.texto)
        return marcador_normalizado(m.group(1)) if m else ""
    def texto_sem_rotulo(n: Paragrafo):
        t = n.texto
        if n.linhas[0].sup_inicio:
            return t
        return RE_MARCADOR.sub("", t, count=1).strip()
    for a in model.autores:
        bios = []
        for n in notas:
            r = rotulo_de(n)
            if r and r in a.marcadores:
                bios.append(n)
        if not bios and len(model.autores) == 1:
            bios = [n for n in notas if KW_BIO.search(n.texto)][:1]
        for n in bios:
            t = texto_sem_rotulo(n)
            if not KW_BIO.search(t) and not KW_INSTITUICAO.search(t):
                continue
            a.bio = t if not a.bio else a.bio + " " + t
            if not a.orcid:
                m = RE_ORCID.search(t)
                if m:
                    a.orcid = m.group(1).upper(); a.orcid_valido = orcid_valido(a.orcid)
            if not a.email:
                m = RE_EMAIL.search(t)
                if m:
                    a.email = m.group(0).rstrip(".")
            if not a.lattes:
                m = RE_LATTES.search(t)
                if m:
                    a.lattes = "http://" + m.group(0)
            if not a.aff_ids:
                _nova_afiliacao(model, a, t, origem="nota biográfica (heurística; confirmar)", confianca="baixa")
            for nt in model.notas:
                pass
    # autor sem afiliacao e sem marcador, com uma unica nota bio disponivel
    if len(model.autores) > 1:
        sem = [a for a in model.autores if not a.aff_ids]
        for a in sem:
            model.aviso(f"Autor '{a.nome_completo}' sem afiliação identificada.")


def _orcids_soltos(doc: Documento, model: ArticleModel):
    # 1. autor ainda sem ORCID: procura em notas (qualquer pagina) que citem o sobrenome
    for a in model.autores:
        if a.orcid:
            continue
        for n in doc.notas:
            if normaliza(a.sobrenome) in normaliza(n.texto):
                m = RE_ORCID.search(n.texto)
                if m:
                    a.orcid = m.group(1).upper(); a.orcid_valido = orcid_valido(a.orcid)
                    model.marca(f"orcid:{a.sobrenome}", "lido (nota que cita o sobrenome)")
                    break
    # 2. ORCIDs que sobraram (editores no cabecalho, quadro lateral etc.) ficam listados, nunca atribuidos
    usados = {a.orcid for a in model.autores if a.orcid}
    for l in doc.linhas:
        if l.pagina > 3 and l.zona not in ("lateral", "margem"):
            continue
        for m in RE_ORCID.finditer(l.texto):
            o = m.group(1).upper()
            if o not in usados:
                model.orcids_nao_atribuidos.append({"orcid": o, "pagina": l.pagina, "zona": l.zona, "contexto": l.texto[:120]})
                usados.add(o)
    for a in model.autores:
        if not a.orcid:
            model.aviso(f"ORCID não encontrado para '{a.nome_completo}'.")
        elif a.orcid_valido is False:
            model.aviso(f"ORCID de '{a.nome_completo}' com dígito verificador inválido: {a.orcid}.")


def _emails_laterais(doc: Documento, model: ArticleModel):
    """Quadro lateral (Pensar): 'Autor' / nome / e-mail / contribuicao."""
    linhas = [l for l in doc.linhas if l.zona == "lateral"]
    if not linhas:
        return
    norm = [normaliza(l.texto) for l in linhas]
    for a in model.autores:
        if a.email:
            continue
        alvo = normaliza(a.nome_completo)
        for i, n in enumerate(norm):
            if alvo and alvo in n:
                for x in linhas[i: i + 5]:
                    m = RE_EMAIL.search(x.texto)
                    if m:
                        a.email = m.group(0).rstrip(".")
                        model.marca(f"email:{a.sobrenome}", "lido (quadro lateral)")
                        break
                break
    # editores no quadro lateral: bloco 'Editor(es)...' seguido de nomes
    em_bloco = False
    for l in linhas:
        t = l.texto.strip()
        if re.match(r"^editor", t, re.I):
            em_bloco = True
            continue
        if re.match(r"^(autor|como citar|declara|hist[óo]rico|eixo)", t, re.I):
            em_bloco = False
        if not em_bloco:
            continue
        if re.fullmatch(r"[A-ZÀ-Ú][a-zà-ú'’\-]+(?:\s+(?:de|da|do|dos|das|e)?\s*[A-ZÀ-Ú][a-zà-ú'’\-]+){1,5}", t) and not KW_INSTITUICAO.search(t):
            if t not in [e.nome_completo for e in model.editores]:
                s, n = divide_nome(t)
                model.editores.append(Autor(nome_completo=t, sobrenome=s, nomes=n, papel="editor"))


# ---------------------------------------------------------------- resumos

def extrai_resumos(doc: Documento, model: ArticleModel, linhas_front: List[Linha]):
    blocos = []  # (rotulo, [linhas])
    atual = None
    for l in linhas_front:
        m = RE_LABEL_RESUMO.match(l.texto)
        if m and (l.bold or l.texto.isupper() or l.texto.strip().endswith(":") or len(m.group(2)) > 0 or len(l.texto) < 25):
            atual = [m.group(1), []]
            blocos.append(atual)
            resto = m.group(2).strip()
            if resto:
                atual[1].append(resto)
            continue
        if atual is not None:
            atual[1].append(l.texto)
    for rotulo, linhas in blocos:
        kws, rot_kw = [], None
        i_kw = next((i for i, ln in enumerate(linhas) if RE_LABEL_KW.search(ln)), None)
        if i_kw is None:
            texto = juntar_linhas(linhas)
        else:
            m = RE_LABEL_KW.search(linhas[i_kw])
            rot_kw = m.group(1)
            antes = linhas[:i_kw] + ([linhas[i_kw][: m.start()]] if linhas[i_kw][: m.start()].strip() else [])
            # as palavras-chave vao do rotulo ate o fim da primeira linha terminada em ponto (ou ate o fim do bloco)
            kw_linhas = [linhas[i_kw][m.end():]]
            j = i_kw + 1
            while not kw_linhas[-1].rstrip().endswith(".") and j < len(linhas):
                kw_linhas.append(linhas[j])
                j += 1
            depois = linhas[j:]
            trecho_kw = juntar_linhas(kw_linhas)
            sep = ";" if ";" in trecho_kw else ","
            kws = [k.strip(" .") for k in trecho_kw.split(sep) if k.strip(" .")]
            texto = juntar_linhas(antes + depois)
            if depois:
                model.aviso(f"Palavras-chave ('{rot_kw}') aparecem no meio do resumo; texto após elas foi mantido no resumo. Confirme.")
        lang_rot = IDIOMA_ROTULO.get(rotulo.lower())
        lang_det, conf = detecta_idioma(texto)
        idioma = lang_det if (lang_det and conf >= 0.15 and lang_det != lang_rot) else (lang_rot or lang_det)
        if lang_det and lang_rot and lang_det != lang_rot and conf >= 0.15:
            model.aviso(f"Resumo rotulado '{rotulo}' parece estar em '{lang_det}'. Idioma atribuído: {idioma}.")
        model.resumos.append(Resumo(idioma=idioma, rotulo=rotulo, texto=texto, palavras_chave=kws, rotulo_palavras=rot_kw))
    if model.resumos:
        model.marca("resumos", "lido (rótulos RESUMO/ABSTRACT/RESUMEN; palavras-chave por rótulo)")
    # idioma do documento
    corpo_txt = " ".join(p.texto for p in doc.paragrafos if p.pagina >= 2 and abs(p.size - doc.corpo_size) < 0.7)[:6000]
    lang, conf = detecta_idioma(corpo_txt)
    model.idioma = lang or (model.resumos[0].idioma if model.resumos else None)
    model.marca("idioma", f"detectado no corpo (confiança {conf})")
    for t in model.titulos:
        if t.tipo == "article-title" and not t.idioma:
            t.idioma = model.idioma
        if t.tipo == "article-title" and t.idioma and model.idioma and t.idioma != model.idioma:
            # o primeiro titulo em destaque nao esta no idioma do texto: procura um que esteja
            alvo = next((x for x in model.titulos if x.idioma == model.idioma), None)
            if alvo:
                model.aviso(f"Título em destaque ('{t.idioma}') não está no idioma do texto ('{model.idioma}'); article-title reatribuído.")
                t.tipo, alvo.tipo = "trans-title", "article-title"
                model.titulos.sort(key=lambda x: 0 if x.tipo == "article-title" else 1)
            break
    # ligacao resumo <-> titulo traduzido faltando
    idiomas_titulo = {t.idioma for t in model.titulos}
    for r in model.resumos:
        if r.idioma and r.idioma not in idiomas_titulo:
            model.aviso(f"Há resumo em '{r.idioma}' sem título nesse idioma (A06).")


# ---------------------------------------------------------------- datas e licenca

def extrai_datas_e_licenca(doc: Documento, model: ArticleModel):
    # datas editoriais ficam nas primeiras paginas, nas margens/quadros ou nas ultimas paginas; nunca no meio do corpo
    linhas = sorted(
        [l for l in doc.linhas if l.pagina <= 2 or l.pagina >= doc.paginas - 1 or l.zona in ("lateral", "margem")],
        key=lambda l: (l.pagina, l.y0),
    )
    achados = {}
    for k, l in enumerate(linhas):
        t = l.texto
        if re.search(r"acesso em|dispon[íi]vel em|retrieved|available at|publicad[oa] (no|na|em|pel)", t, re.I):
            continue
        for campo, rx in RE_DATAS:
            for m in rx.finditer(t):
                resto = t[m.end():]
                d = parse_data(resto[:40])
                if not d and k + 1 < len(linhas):
                    d = parse_data(linhas[k + 1].texto[:40])
                if d and campo not in achados:
                    achados[campo] = (d, f"p.{l.pagina} {l.zona}: '{t[:60]}'")
    # frase 'recebido em X e aceito em Y' na mesma linha ja e coberta pelo finditer (aceito casa depois)
    for campo, (d, origem) in achados.items():
        setattr(model.datas, campo, d)
    if achados:
        model.datas.origem = "; ".join(f"{c}: {o}" for c, (_, o) in achados.items())
        model.marca("datas", "lido (padrões recebido/aceito/submetido/aprovado; nunca inferido)")
    else:
        model.aviso("Datas de recebimento/aceite não encontradas no PDF (H01: bloqueante; buscar no OJS).")
    if model.datas.recebido and model.datas.aceito and model.datas.aceito < model.datas.recebido:
        model.aviso(f"Data de aceite ({model.datas.aceito}) anterior ao recebimento ({model.datas.recebido}) (H02).")
    texto = " ".join(l.texto for l in doc.linhas)
    m = RE_CC.search(texto)
    if m:
        trecho = m.group(0)
        tipo = "CC BY"
        if re.search(r"n[ãa]o[- ]comercial|noncommercial|non-commercial", trecho, re.I):
            tipo += "-NC"
        if re.search(r"compartilha|sharealike|share alike|compartir igual", trecho, re.I):
            tipo += "-SA"
        if re.search(r"sem deriva|noderiv|no derivatives|sin obra derivada", trecho, re.I):
            tipo += "-ND"
        mv = re.search(r"\b([2-4]\.\d)\b", trecho)
        model.licenca = tipo + (" " + mv.group(1) if mv else "")
        mu = re.search(r"https?://creativecommons\.org/licenses/[a-z\-]+/\d\.\d/?", texto, re.I)
        model.licenca_url = mu.group(0) if mu else None
        model.marca("licenca", "lido (texto 'Creative Commons' no PDF)")
    else:
        model.aviso("Licença não encontrada no PDF (L01).")
