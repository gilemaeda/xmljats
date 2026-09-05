"""Lista de referencias: localizacao, agrupamento de linhas em entradas, estilo (ABNT/APA), tipo e ligacao com citacoes."""
import re
from collections import Counter
from typing import Optional, Tuple

from .leitura import Documento, juntar_linhas
from .modelo import ArticleModel, Referencia
from .util import RE_DOI, RE_URL, limpa_doi, normaliza, cabecalho_autores
from .corpo import KW_BACK

RE_HEAD_REF = re.compile(r"^(refer[êe]ncias?(\s+bibliogr[áa]ficas?)?|references|bibliografia|bibliography|referencias(\s+bibliogr[áa]ficas)?|obras citadas|fontes|works cited|literatura citada)\s*[:.]?$", re.I)
RE_ABNT = re.compile(r"^[A-ZÀ-Ú][A-ZÀ-Ú'’\-]+(?: [A-ZÀ-Ú][A-ZÀ-Ú'’\-]+)*\s*[,.:]\s")
RE_ABNT_ENT = re.compile(r"^[A-ZÀ-Ú]{3,}(?: [A-ZÀ-Ú]{2,})*\s+[a-zà-ú]")  # ACAO da Defensoria / ORGANIZACAO das Nacoes
RE_APA = re.compile(r"^[A-ZÀ-Ú][a-zà-ú'’\-]+(?:,?\s+[A-ZÀ-Ú]\.)+|^[A-ZÀ-Ú][a-zà-ú'’\-]+,\s+[A-ZÀ-Ú][a-zà-ú'’\-]+.{0,80}\(\d{4}[a-z]?\)")
# Rodape que a revista imprime depois das referencias e que o layout gruda na ultima entrada:
# "Idioma original: Portugues Recebido: 23/12/24 Aceito: 05/01/25". Nao e parte da referencia.
RE_RODAPE_ARTIGO = re.compile(
    r"\s*(?:(?:Idioma original|Original language|Idioma de publica[^:]{0,12}|Recebido(?: em)?|Received|"
    r"Recibido|Aceito(?: em)?|Accepted|Aceptado|Aprovado(?: em)?|Submetido(?: em)?|Submitted|Submission|"
    r"Data de submiss[^:]{0,8}|Como citar|How to cite|C[oó]mo citar|Editor(?:es)? respons[^:]{0,10})\s*:|"
    r"Esta obra est[aá] licenciada|This work is licensed).*$", re.I | re.S)
RE_TRACO = re.compile(r"^_{3,}")
RE_ANO_PAREN = re.compile(r"\((\d{4}[a-z]?)\)")
RE_ANO = re.compile(r"(?<![\d./-])(1[6-9]\d{2}|20[0-4]\d)[a-z]?(?![\d/])")
RE_ACESSO = re.compile(r"(Acesso em|Acessado em|Retrieved|Accessed|Consultado|Recuperado)\b.*$", re.I)
# autor institucional/legal em CAIXA ALTA no inicio, seguido de ponto ou espaco (nunca de virgula: "CÂMARA, Antônio" e pessoa)
LEGAL_CAPS = re.compile(r"^(BRASIL|ARGENTINA|PORTUGAL|ESPANHA|CHILE|URUGUAI|COL[ÔO]MBIA|M[ÉE]XICO|UNI[ÃA]O EUROPEIA|EUROPEAN UNION|UNITED STATES|UNITED NATIONS|ONU|OEA|SUPREMO|SUPERIOR|TRIBUNAL|C[ÂA]MARA|SENADO|CONSELHO|MINIST[ÉE]RIO|ORGANIZA[ÇC][ÃA]O DAS NA[ÇC][ÕO]ES|CONSTITUI[ÇC][ÃA]O|STF|STJ|TSE|CNJ|CORTE)\b(?!\s*,)")
LEGAL_TERMOS = re.compile(r"\b(Lei\s+n|Lei\s+Complementar|Decreto(-Lei)?\s+n|Habeas\s+corpus|Recurso\s+(Extraordin|Especial)|S[úu]mula|ADI\s+\d|ADPF\s+\d|Medida\s+Provis[óo]ria|Resolu[çc][ãa]o\s+n|Portaria\s+n|Emenda\s+Constitucional)", re.I)


class _Legal:
    """LEGAL.match(t): entrada de documento legal (pais/tribunal em CAIXA ALTA no inicio, ou termo legal no texto)."""

    @staticmethod
    def match(t):
        return LEGAL_CAPS.match(t) or LEGAL_TERMOS.search(t)


LEGAL = _Legal
THESIS = re.compile(r"\b(Tese|Disserta[çc][ãa]o|Monografia|Trabalho de Conclus[ãa]o|Doctoral dissertation|PhD thesis|Master.?s thesis|Tesis)\b", re.I)
CONF = re.compile(r"\b(Anais|Proceedings|Congresso|Congress|Conference|Encontro|Simp[óo]sio|Symposium|Semin[áa]rio|Colóquio|Jornada)\b", re.I)
REPORT = re.compile(r"\b(Relat[óo]rio|Report|Working Paper|Issue Brief|Nota t[ée]cnica|Policy brief|White paper|Documento de trabalho)\b", re.I)
JOURNAL = re.compile(r"\b(v|vol)\.\s*\d+|\bn\.\s*\d+|\b\d+\s*\(\d+\)|\b(Revista|Journal|Review|Cadernos|Anu[áa]rio|Boletim|Quarterly|Annals|Archives|Bulletin|Studies|Law Review)\b", re.I)
NEWS = re.compile(r"\b(Folha de S|Folha de São Paulo|Estad[ãa]o|O Globo|G1|Globo\.com|Valor Econ[ôo]mico|Conjur|Consultor Jur[íi]dico|Nexo|BBC|El Pa[íi]s|New York Times|The Guardian|Tech Policy Press|The Conversation|Lawfare|Migalhas|UOL|Jota|Correio Braziliense|Ag[êe]ncia Brasil|CNN|Reuters|Washington Post|Le Monde|Portal)\b", re.I)
WEB = re.compile(r"(Dispon[íi]vel em|Available at|Acesso em|Retrieved|Recuperado de|Consultado)", re.I)
RE_DIA_MES = re.compile(r"\b\d{1,2}\s+[a-zç]{3,9}\.?\s+\d{4}\b", re.I)


def indice_referencias(doc: Documento, i_sec: Optional[int]) -> Optional[int]:
    inicio = i_sec or 0
    achado = None
    for i, p in enumerate(doc.paragrafos):
        if i < inicio:
            continue
        t = p.texto.strip()
        if len(t) <= 40 and RE_HEAD_REF.match(t):
            achado = i
    return achado


def _eh_inicio_entrada(texto, prev_texto, modo_recuo, x0, x_min):
    if modo_recuo:
        return x0 <= x_min + 2.5
    if RE_TRACO.match(texto) or LEGAL_CAPS.match(texto) or RE_APA.match(texto):
        return True
    if RE_ABNT.match(texto) or RE_ABNT_ENT.match(texto):
        if re.match(r"^[A-ZÀ-Ú][A-ZÀ-Ú'’\-]+,\s*\d{4}", texto):
            return False  # "UNESP, 2007." e editora + ano, continuacao
        if prev_texto is None:
            return True
        fim = prev_texto.rstrip()[-1:]
        if fim in (":", ",", "-", "–", "/", ";"):
            return False
        return True
    return False


def extrai_referencias(doc: Documento, model: ArticleModel, i_ref: Optional[int]) -> Optional[int]:
    """Devolve o indice do primeiro paragrafo de back matter apos as referencias (ou None)."""
    if i_ref is None:
        model.aviso("Lista de referências não encontrada (R01).")
        return None
    linhas = []
    i_back = None
    for k, p in enumerate(doc.paragrafos[i_ref + 1:], start=i_ref + 1):
        t0 = p.linhas[0].texto.strip()
        if KW_BACK.match(t0) and len(t0) < 80:
            i_back = k
            break
        if RE_HEAD_REF.match(p.texto.strip()):
            continue
        linhas.extend(p.linhas)
    if not linhas:
        model.aviso("Lista de referências vazia após o título (R01).")
        return i_back
    # estilo numerado (Vancouver): "1. Autor...", "2. Autor..." em sequencia; a numeracao manda no agrupamento
    seq = _sequencia_numerada(linhas)
    if seq:
        entradas_num, atual_num, esperado = [], [], 1
        for l in linhas:
            n = _num_entrada(l.texto)
            if n == esperado:
                if atual_num:
                    entradas_num.append(atual_num)
                atual_num = [l.texto]
                esperado += 1
                continue
            atual_num.append(l.texto)
        if atual_num:
            entradas_num.append(atual_num)
        _monta_entradas(model, entradas_num, "numeração (estilo Vancouver)")
        _liga_citacoes(model)
        return i_back
    xs = Counter(round(l.x0) for l in linhas)
    x_min = min(xs)
    n_esq = sum(c for x, c in xs.items() if x <= x_min + 2.5)
    n_dir = sum(c for x, c in xs.items() if x_min + 4 <= x <= x_min + 40)
    # recuo frances: primeiras linhas na margem (20-60% das linhas) e continuacoes recuadas (>= 30%)
    modo_recuo = 0.2 * len(linhas) <= n_esq <= 0.6 * len(linhas) and n_dir >= 0.3 * len(linhas) and len(linhas) >= 8

    def agrupa(modo):
        ent, at, pv = [], [], None
        for l in linhas:
            if at and _eh_inicio_entrada(l.texto, pv, modo, l.x0, x_min):
                ent.append(at)
                at = []
            at.append(l.texto)
            pv = l.texto
        if at:
            ent.append(at)
        return ent

    entradas = agrupa(modo_recuo)
    if modo_recuo:
        media = sum(len(" ".join(e)) for e in entradas) / max(len(entradas), 1)
        if media < 60:  # recuo mal detectado: entradas curtas demais
            modo_recuo = False
            entradas = agrupa(False)
    _monta_entradas(model, entradas, "recuo francês" if modo_recuo else "padrões de início de entrada")
    _liga_citacoes(model)
    return i_back


# "1. Autor", "1) Autor" (Vancouver) e "[1] Autor" (ABNT numerico / IEEE, comum em exatas)
RE_NUM_ENTRADA = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])\s*(?=[A-ZÀ-Ú])")


def _num_entrada(texto):
    m = RE_NUM_ENTRADA.match(texto or "")
    return int(m.group(1) or m.group(2)) if m else None


def _sequencia_numerada(linhas) -> bool:
    """Ha uma numeracao 1., 2., 3. ... abrindo entradas? Exige comecar em 1 e pelo menos 4 numeros em ordem."""
    nums = [n for n in (_num_entrada(l.texto) for l in linhas) if n is not None]
    if len(nums) < 4 or 1 not in nums:
        return False
    esperado, achados = 1, 0
    for n in nums:
        if n == esperado:
            achados += 1
            esperado += 1
    return achados >= 4 and achados >= 0.6 * esperado


def _monta_entradas(model: ArticleModel, entradas, origem: str):
    abnt = apa = 0
    for e in entradas:
        texto = juntar_linhas(e).strip()
        if len(texto) < 15:
            continue
        texto = RE_NUM_ENTRADA.sub("", texto, count=1) if origem.startswith("numeração") else texto
        if e is entradas[-1]:
            # o rodape da revista so gruda na ultima entrada; cortar em todas arriscaria comer titulo
            texto = RE_RODAPE_ARTIGO.sub("", texto).strip(" ;,")
            if len(texto) < 15:
                continue
        r = Referencia(texto=texto)
        m = RE_ANO_PAREN.search(texto)
        sem_acesso = RE_ACESSO.sub("", texto)
        anos = [a for a in RE_ANO.findall(sem_acesso)]
        r.ano = m.group(1) if m else (anos[-1] if anos else None)
        md = RE_DOI.search(texto)
        r.doi = limpa_doi(md.group(0)) if md else None
        mu = RE_URL.search(texto)
        r.url = mu.group(0).rstrip(".") if mu else None
        r.tipo = _tipo(texto)
        r.autores = _autores(texto)
        if RE_TRACO.match(texto) and model.referencias:
            r.autores = list(model.referencias[-1].autores)  # "______." = mesmo autor da entrada anterior (ABNT)
        if RE_ABNT.match(texto) or RE_ABNT_ENT.match(texto) or LEGAL.match(texto):
            abnt += 1
        elif RE_APA.match(texto):
            apa += 1
        model.referencias.append(r)
    n = len(model.referencias)
    if n:
        if origem.startswith("numeração"):
            model.estilo_referencias = "numérico (Vancouver)"
        else:
            model.estilo_referencias = "ABNT" if abnt >= 0.6 * n else ("APA" if apa >= 0.6 * n else f"misto (ABNT {abnt}, APA {apa})")
        model.marca("referencias", f"lido ({origem})")


def _tipo(t):
    if LEGAL.match(t) or re.search(r"\b(Lei\s+n|Decreto-lei|Habeas corpus|S[úu]mula|Constitui[çc][ãa]o (da|de la|of)|Emenda Constitucional|C[óo]digo (Civil|Penal|de Processo))\b", t, re.I):
        return "legal-doc"
    if THESIS.search(t):
        return "thesis"
    if CONF.search(t):
        return "confproc"
    if NEWS.search(t) and (RE_DIA_MES.search(t) or WEB.search(t)) and not re.search(r"\b(v|vol)\.\s*\d+", t):
        return "newspaper"
    if JOURNAL.search(t) and not re.search(r"\bIn:\s", t):
        return "journal"
    if REPORT.search(t):
        return "report"
    if re.search(r"\bIn:\s", t):
        return "book"  # capitulo de livro (element-citation book + chapter-title)
    if WEB.search(t) or RE_URL.search(t):
        return "webpage"
    return "book"


def _autores(t):
    if RE_TRACO.match(t):
        return []
    m = RE_ANO_PAREN.search(t)
    if m and RE_APA.match(t):
        cab = t[: m.start()]
    else:
        cab = cabecalho_autores(t)
        if len(cab) > 160:
            cab = cab[:160]
    partes = re.split(r";\s*|\s+(?:e|and|y|&)\s+(?=[A-ZÀ-Ú])", cab)
    out = []
    for p in partes:
        p = p.strip(" .,")
        if not p or len(p) > 80:
            continue
        if re.match(r"^[A-ZÀ-Ú][A-ZÀ-Ú'’\-]+(?: [A-ZÀ-Ú][A-ZÀ-Ú'’\-]+)*(,\s*.+)?$", p) or RE_APA.match(p + " ") or re.match(r"^[A-ZÀ-Ú][a-zà-ú'’\-]+,\s", p):
            out.append(p)
    return out[:8]


def _liga_citacoes(model: ArticleModel):
    idx = []
    for k, r in enumerate(model.referencias):
        chaves = set()
        for a in r.autores:
            sob = normaliza(a.split(",")[0])
            if sob:
                chaves.add(sob)
        if not chaves:
            primeira = normaliza(r.texto.split(",")[0].split(".")[0])
            if primeira:
                chaves.add(primeira)
        idx.append((chaves, (r.ano or "").rstrip("abcdef")))
    for c in model.citacoes:
        sob = normaliza(c.autor.split(" e ")[0].split(" and ")[0].split(" y ")[0].split("&")[0].replace(" et al", ""))
        ano = c.ano.rstrip("abcdef")
        for k, (chaves, rano) in enumerate(idx):
            if sob and any(sob == ch or sob in ch.split() or ch.startswith(sob) for ch in chaves) and rano == ano:
                c.ref_index = k
                model.referencias[k].citada = True
                break
