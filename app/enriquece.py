"""
Completar o que o PDF não traz, buscando em bases públicas: Crossref pelo DOI e ORCID pelo número.

Motivo: os campos que a SciELO exige e o PDF quase nunca mostra (volume, número, licença, ORCID de
cada autor, resumo, afiliação) costumam já existir no registro do DOI. Em vez de digitar tudo à mão,
a tela busca, mostra o que achou com a origem, e a pessoa aplica campo a campo. Nada é gravado sozinho.

Fontes, as duas abertas e sem chave (testadas em 05/09/2026):
- api.crossref.org/works/<doi>  — título, volume, número, páginas, licença, resumo, autores com ORCID e afiliação.
- pub.orcid.org/v3.0/<orcid>/person — nome de quem é o ORCID, para conferir se bate com o autor.

Limite conhecido: a data de publicação no Crossref costuma vir só com o ano nos DOI da SciELO. Quando
vier com dia e mês, é aproveitada; quando não, o campo continua em falta, porque inventar dia e mês
seria pior do que deixar em branco.
"""
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

UA = {"User-Agent": "xmljats/1.0 (+https://github.com/gilemaeda/xmljats)", "Accept": "application/json"}
TIMEOUT = 15
CROSSREF = "https://api.crossref.org/works/"
ORCID = "https://pub.orcid.org/v3.0/{}/person"
RE_DOI = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)")
RE_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.I)
RE_TAG = re.compile(r"<[^>]+>")


def _pega(url: str, timeout: int = TIMEOUT):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def normaliza_doi(bruto: str) -> Optional[str]:
    m = RE_DOI.search((bruto or "").strip())
    return m.group(1).rstrip(".,;)") if m else None


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def _data(m: dict) -> Optional[str]:
    """Data de publicação completa, só quando o Crossref tiver dia e mês. Ano sozinho não serve à SPS."""
    for chave in ("published-print", "published-online", "published", "issued"):
        partes = ((m.get(chave) or {}).get("date-parts") or [[]])[0]
        if len(partes) == 3:
            a, mes, d = partes
            return f"{a:04d}-{mes:02d}-{d:02d}"
    return None


def _licenca(m: dict) -> Optional[str]:
    for lic in m.get("license") or []:
        url = (lic.get("URL") or "").replace("http://", "https://")
        if "creativecommons.org/licenses/" in url:
            # o Crossref às vezes traz /legalcode ou versão diferente de 4.0
            achado = re.match(r"(https://creativecommons\.org/licenses/[a-z-]+)/(\d\.\d)", url)
            return f"{achado.group(1)}/{achado.group(2)}/" if achado else url
    return None


def por_doi(doi_bruto: str) -> dict:
    """Consulta o Crossref pelo DOI. Devolve {'ok','mensagem','campos':{campo: valor}, 'autores':[...], 'bruto':{...}}."""
    doi = normaliza_doi(doi_bruto)
    if not doi:
        return {"ok": False, "mensagem": "DOI inválido: precisa começar com 10. seguido do sufixo.", "campos": {}, "autores": []}
    try:
        m = (_pega(CROSSREF + urllib.parse.quote(doi, safe="/")) or {}).get("message") or {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "mensagem": f"O DOI {doi} não está registrado no Crossref. Confira o número, ou o "
                                             "registro pode estar em outra agência (DataCite, por exemplo).",
                    "campos": {}, "autores": []}
        return {"ok": False, "mensagem": f"O Crossref respondeu HTTP {e.code}.", "campos": {}, "autores": []}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "mensagem": f"Não consegui falar com o Crossref agora ({str(e)[:80]}).", "campos": {}, "autores": []}

    campos = {}
    if m.get("title"):
        campos["titulo_0_texto"] = m["title"][0].strip()
    if m.get("volume"):
        campos["volume"] = str(m["volume"]).strip()
    if m.get("issue"):
        campos["numero"] = str(m["issue"]).strip()
    if m.get("page"):
        campos["paginas"] = str(m["page"]).strip()
    if m.get("DOI"):
        campos["doi"] = m["DOI"]
    data = _data(m)
    if data:
        campos["data_publicado"] = data
    lic = _licenca(m)
    if lic:
        campos["licenca"] = lic
    resumo = m.get("abstract")
    if resumo:
        limpo = RE_TAG.sub(" ", resumo)
        limpo = re.sub(r"\s+", " ", limpo).strip()
        limpo = re.sub(r"^(Resumo|Abstract|Resumen)\s+", "", limpo)
        campos["resumo_0_texto"] = limpo
    autores = []
    for a in m.get("author") or []:
        orcid = (a.get("ORCID") or "").rsplit("/", 1)[-1] if a.get("ORCID") else None
        autores.append({
            "sobrenome": (a.get("family") or "").strip(),
            "nomes": (a.get("given") or "").strip(),
            "orcid": orcid,
            "afiliacao": (a.get("affiliation") or [{}])[0].get("name", "").strip() or None,
        })
    ano = ((m.get("published") or {}).get("date-parts") or [[]])[0]
    if ano and not data:
        campos["ano"] = str(ano[0])
    revista = {"titulo": (m.get("container-title") or [""])[0], "issn": (m.get("ISSN") or [None])[0],
               "editora": m.get("publisher"), "tipo": m.get("type")}
    faltou_data = not data
    msg = f"Registro do DOI {doi} encontrado no Crossref: {len(campos)} campo(s) e {len(autores)} autor(es)."
    if faltou_data:
        msg += " A data de publicação veio só com o ano, então dia e mês continuam em falta: pegue no OJS."
    return {"ok": True, "mensagem": msg, "campos": campos, "autores": autores, "revista": revista, "doi": doi}


def confere_orcid(numero: str, nome_esperado: str = "") -> dict:
    """Confere se o ORCID existe e de quem é. Devolve {'ok','existe','nome','confere','mensagem'}."""
    m = RE_ORCID.search((numero or "").strip())
    if not m:
        return {"ok": False, "existe": False, "mensagem": "ORCID no formato 0000-0000-0000-0000."}
    orcid = m.group(1).upper()
    try:
        d = _pega(ORCID.format(orcid))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": True, "existe": False, "orcid": orcid,
                    "mensagem": f"O ORCID {orcid} não existe no registro público. Confira o número com o autor."}
        return {"ok": False, "existe": False, "orcid": orcid, "mensagem": f"O ORCID respondeu HTTP {e.code}."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "existe": False, "orcid": orcid, "mensagem": f"Não consegui consultar o ORCID ({str(e)[:70]})."}
    n = d.get("name") or {}
    nome = " ".join(x for x in [((n.get("given-names") or {}) or {}).get("value"),
                                ((n.get("family-name") or {}) or {}).get("value")] if x).strip()
    if not nome:
        nome = ((n.get("credit-name") or {}) or {}).get("value") or ""
    confere = None
    if nome and nome_esperado:
        a, b = _sem_acento(nome).split(), _sem_acento(nome_esperado).split()
        confere = bool(set(a) & set(b)) if (a and b) else None
    if not nome:
        msg = f"O ORCID {orcid} existe, mas o dono mantém o nome privado. Confirme com o autor."
    elif confere is False:
        msg = f"Atenção: o ORCID {orcid} é de \"{nome}\", que não bate com \"{nome_esperado}\". Confira antes de publicar."
    else:
        msg = f"O ORCID {orcid} é de {nome}."
    return {"ok": True, "existe": True, "orcid": orcid, "nome": nome, "confere": confere, "mensagem": msg}
