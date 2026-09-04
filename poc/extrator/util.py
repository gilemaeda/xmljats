"""Utilitarios: regex de identificadores, validacao de ORCID/ISSN, datas, idioma, paises."""
import re
import unicodedata

RE_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>|]+")
RE_ISSN = re.compile(r"(?<![\d-])(\d{4}-\d{3}[\dXx])(?![\d-])")
RE_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_URL = re.compile(r"https?://[^\s<>\"]+")
RE_LATTES = re.compile(r"lattes\.cnpq\.br/\d+")

SUPERSCRITOS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
# marcador de nota no inicio da linha: 1-3 digitos (nao seguidos de digito, hifen, barra, virgula, parentese ou ordinal),
# asteriscos, digitos sobrescritos, adagas. '§' fica de fora (e simbolo de paragrafo de lei, comum em citacoes).
RE_MARCADOR = re.compile(r"^\s*(\d{1,3}(?![\d\-–/,)%º°])\.?|\*{1,4}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|†|‡)\s*")


def sem_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normaliza(s):
    s = sem_acentos(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def limpa_doi(d):
    return d.rstrip(".,;:)]")


def orcid_valido(o):
    """ISO 7064 MOD 11-2."""
    digs = o.replace("-", "").upper()
    if len(digs) != 16:
        return False
    total = 0
    for ch in digs[:15]:
        if not ch.isdigit():
            return False
        total = (total + int(ch)) * 2
    resto = total % 11
    check = (12 - resto) % 11
    esperado = "X" if check == 10 else str(check)
    return digs[15] == esperado


def issn_valido(i):
    digs = i.replace("-", "").upper()
    if len(digs) != 8:
        return False
    soma = sum(int(d) * (8 - k) for k, d in enumerate(digs[:7]) if d.isdigit())
    resto = soma % 11
    check = "0" if resto == 0 else ("X" if 11 - resto == 10 else str(11 - resto))
    return digs[7] == check


def marcador_normalizado(m):
    m = m.strip()
    if not m:
        return ""
    if all(c in SUPERSCRITOS for c in m):
        return "".join(SUPERSCRITOS[c] for c in m)
    return m


# ---------- idioma ----------
_STOP = {
    "pt": "de a o que e do da em um para é com não uma os no se na por mais as dos como mas foi ao ele das tem à seu sua ou ser quando muito há nos já está eu também só pelo pela até isso ela entre era depois sem mesmo aos ter seus quem nas esse eles estão você foram essa num nem suas às minha têm numa pelos elas seja qual será nós este dele sobre são através partir entre".split(),
    "en": "the of and to in a is that for it as was with be by on not he this are or his from at which but have an they you were her she all their there been one if would more when will what so no can through between about into".split(),
    "es": "de la que el en y a los del se las por un para con no una su al lo como más pero sus le ya o este sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante ellos esto antes algunos qué unos otro otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros mediante través".split(),
    "fr": "le la les de des du et à un une en est que qui dans pour pas sur au avec ce ne se par il elle sont ou plus".split(),
    "it": "il la di e che a in un una per è non con si del della sono come da anche più questo nel alla".split(),
    "de": "der die und in den von zu das mit sich des auf für ist im dem nicht ein eine als auch es an werden aus".split(),
}
_STOPSET = {k: set(v) for k, v in _STOP.items()}
_EXCLUSIVOS = {  # palavras que praticamente so existem num idioma (peso extra)
    "pt": {"não", "é", "uma", "são", "também", "através", "do", "da", "dos", "das", "ao", "aos", "às", "pelo", "pela", "já", "há"},
    "es": {"y", "del", "las", "los", "también", "más", "muy", "hasta", "porque", "sí", "cuando", "según", "hacia", "mientras", "aunque"},
    "en": {"the", "and", "of", "with", "which", "that", "this", "from", "their", "between", "through"},
}


def detecta_idioma(texto):
    """Devolve (idioma, confianca) ou (None, 0) para texto curto/indeciso."""
    toks = re.findall(r"[a-záàâãéêíóôõúüçñ]+", (texto or "").lower())
    if len(toks) < 3:
        return None, 0.0
    scores = []
    for lang, sset in _STOPSET.items():
        hits = sum(1 for t in toks if t in sset)
        extra = sum(1 for t in toks if t in _EXCLUSIVOS.get(lang, ()))
        scores.append(((hits + 2 * extra) / len(toks), lang))
    scores.sort(reverse=True)
    melhor_score, melhor = scores[0]
    segundo = scores[1][0] if len(scores) > 1 else 0.0
    if melhor_score < 0.08 or melhor_score - segundo < 0.04:
        return None, round(melhor_score, 3)
    return melhor, round(melhor_score, 3)


# ---------- datas ----------
_MESES = {
    "jan": 1, "janeiro": 1, "january": 1, "enero": 1, "ene": 1,
    "fev": 2, "fevereiro": 2, "feb": 2, "february": 2, "febrero": 2,
    "mar": 3, "marco": 3, "março": 3, "march": 3, "marzo": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "mai": 5, "maio": 5, "may": 5, "mayo": 5,
    "jun": 6, "junho": 6, "june": 6, "junio": 6,
    "jul": 7, "julho": 7, "july": 7, "julio": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "set": 9, "setembro": 9, "sep": 9, "sept": 9, "september": 9, "septiembre": 9,
    "out": 10, "outubro": 10, "oct": 10, "october": 10, "octubre": 10,
    "nov": 11, "novembro": 11, "november": 11, "noviembre": 11,
    "dez": 12, "dezembro": 12, "dec": 12, "december": 12, "dic": 12, "diciembre": 12,
}
_RE_D1 = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")
_RE_D2 = re.compile(r"\b(\d{1,2})\s*(?:de\s+)?([A-Za-zçÇ]{3,10})\.?\s*(?:de\s+)?(\d{4})\b")
_RE_D3 = re.compile(r"\b([A-Za-z]{3,10})\.?\s+(\d{1,2}),\s*(\d{4})\b")
_RE_D4 = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def parse_data(s):
    """Primeira data reconhecivel em s -> 'AAAA-MM-DD' ou None."""
    if not s:
        return None
    m = _RE_D4.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _RE_D1.search(s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    m = _RE_D2.search(s)
    if m:
        mo = _MESES.get(sem_acentos(m.group(2)).lower())
        if mo:
            return f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}"
    m = _RE_D3.search(s)
    if m:
        mo = _MESES.get(m.group(1).lower())
        if mo:
            return f"{m.group(3)}-{mo:02d}-{int(m.group(2)):02d}"
    return None


# ---------- paises e UFs ----------
PAISES = {
    "brasil": "BR", "brazil": "BR", "br": "BR", "argentina": "AR", "portugal": "PT", "pt": "PT",
    "estados unidos": "US", "estados unidos da america": "US", "united states": "US", "united states of america": "US", "eua": "US", "usa": "US",
    "espanha": "ES", "espana": "ES", "spain": "ES", "mexico": "MX", "colombia": "CO", "chile": "CL", "uruguai": "UY", "uruguay": "UY",
    "peru": "PE", "italia": "IT", "italy": "IT", "franca": "FR", "france": "FR", "alemanha": "DE", "germany": "DE", "deutschland": "DE",
    "reino unido": "GB", "united kingdom": "GB", "inglaterra": "GB", "england": "GB", "canada": "CA", "paraguai": "PY", "paraguay": "PY",
    "bolivia": "BO", "venezuela": "VE", "equador": "EC", "ecuador": "EC", "cuba": "CU", "mocambique": "MZ", "angola": "AO", "holanda": "NL", "netherlands": "NL",
    "belgica": "BE", "belgium": "BE", "suica": "CH", "switzerland": "CH", "australia": "AU", "japao": "JP", "japan": "JP", "china": "CN",
}
UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}
_UF_POR_NOME = {normaliza(v): k for k, v in UFS.items()}


def acha_pais(texto):
    """Devolve (nome_como_aparece, ISO) do ultimo pais citado no texto, ou (None, None)."""
    t = normaliza(texto)
    achado = None
    for nome, iso in PAISES.items():
        for m in re.finditer(r"\b" + re.escape(nome) + r"\b", t):
            if achado is None or m.start() > achado[0]:
                achado = (m.start(), nome, iso)
    if not achado:
        return None, None
    return achado[1], achado[2]


def acha_uf(texto):
    """Sigla da UF citada (por sigla isolada ou por nome), ou None."""
    for m in re.finditer(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", texto or ""):
        if m.group(1) in UFS and m.group(1) not in ("BR", "PT", "ES", "US"):
            return m.group(1)
    t = normaliza(texto)
    for nome, sigla in sorted(_UF_POR_NOME.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"\b" + re.escape(nome) + r"\b", t):
            return sigla
    return None


PARTICULAS = {"de", "da", "do", "das", "dos", "e", "del", "della", "di", "van", "von", "der", "la", "le", "y"}
SUFIXOS = {"junior", "júnior", "jr", "jr.", "filho", "neto", "sobrinho", "segundo", "terceiro", "ii", "iii"}


def divide_nome(nome):
    """'Sara da Nova Quadros Côrtes' -> ('Côrtes', 'Sara da Nova Quadros'). Convencao brasileira: ultimo sobrenome."""
    toks = [t for t in re.split(r"\s+", nome.strip()) if t]
    if len(toks) < 2:
        return nome.strip(), ""
    sobrenome = [toks[-1]]
    i = len(toks) - 2
    if toks[-1].lower().rstrip(".") in SUFIXOS and i >= 0:
        sobrenome.insert(0, toks[i])
        i -= 1
    while i >= 1 and toks[i].lower() in PARTICULAS:
        sobrenome.insert(0, toks[i])
        i -= 1
    return " ".join(sobrenome), " ".join(toks[: i + 1])


def titulo_caixa(s):
    """Converte CAIXA ALTA em Frase caixa (mantem siglas curtas). Usado so para exibicao/comparacao."""
    if s == s.upper() and any(c.isalpha() for c in s):
        palavras = []
        for w in s.split(" "):
            palavras.append(w if (len(w) <= 3 and w.isalpha()) else w.capitalize())
        return " ".join(palavras)
    return s
