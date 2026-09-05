"""
Consulta de periódicos na SciELO pelo ISSN (ArticleMeta), para preencher o cadastro de revistas sem digitar tudo.

Fonte: https://articlemeta.scielo.org/api/v1/journal/?issn=<issn>&collection=<colecao>
Os campos vêm no formato ISIS da SciELO: v100 título, v150 título abreviado, v68 acrônimo, v480/v62 editora,
v435 ISSN por tipo (ONLIN/PRINT), v441 área temática, v340 estrato.

O que vem daqui é sugestão: a tela mostra os dados para o administrador conferir antes de salvar. Nada é gravado
sozinho, e um ISSN sem resposta devolve uma mensagem clara em vez de um cadastro pela metade.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

API = "https://articlemeta.scielo.org/api/v1/journal/"
UA = {"User-Agent": "xmljats/1.0 (+https://github.com/gilemaeda/xmljats)", "Accept": "application/json"}
COLECOES = ["scl", "arg", "chl", "col", "cub", "esp", "mex", "prt", "prg", "ury", "ven", "cri", "bol", "per", "sza", "wid"]
RE_ISSN = re.compile(r"^\d{4}-?\d{3}[\dXx]$")
# área temática da SciELO -> área do nosso cadastro
AREAS_SCIELO = {
    "applied social sciences": "Ciências Sociais Aplicadas (Direito, Administração, Economia)",
    "human sciences": "Ciências Humanas",
    "linguistics, letters and arts": "Linguística, Letras e Artes",
    "health sciences": "Ciências da Saúde",
    "biological sciences": "Ciências Biológicas",
    "exact and earth sciences": "Ciências Exatas e da Terra",
    "engineering": "Engenharias",
    "agricultural sciences": "Ciências Agrárias",
    "multidisciplinary": "Multidisciplinar",
}


def _v(j: dict, campo: str, chave: str = "_") -> Optional[str]:
    lista = j.get(campo) or []
    if not lista:
        return None
    v = lista[0].get(chave)
    return (v or "").strip() or None


def _issn_por_tipo(j: dict, tipo: str) -> Optional[str]:
    for item in j.get("v435") or []:
        if (item.get("t") or "").upper().startswith(tipo):
            return (item.get("_") or "").strip() or None
    return None


def normaliza_issn(issn: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", issn or "").upper()
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else (issn or "").strip()


def busca_por_issn(issn: str, timeout: int = 25) -> dict:
    """Devolve {'achou': bool, 'mensagem': str, 'dados': {...}, 'colecao': str}. Nunca levanta exceção de rede."""
    issn = normaliza_issn(issn)
    if not RE_ISSN.match(issn.replace("-", "")[:4] + "-" + issn.replace("-", "")[4:]) and not RE_ISSN.match(issn):
        return {"achou": False, "mensagem": "ISSN inválido: use o formato 0000-0000.", "dados": {}}
    erro_rede = None
    for colecao in COLECOES:
        url = API + "?" + urllib.parse.urlencode({"issn": issn, "collection": colecao})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                corpo = json.loads(r.read().decode("utf-8") or "[]")
        except urllib.error.HTTPError as e:
            erro_rede = f"HTTP {e.code}"
            continue
        except Exception as e:  # noqa: BLE001
            erro_rede = str(e)[:120]
            continue
        j = corpo[0] if isinstance(corpo, list) and corpo else (corpo if isinstance(corpo, dict) and corpo.get("v100") else None)
        if not j:
            continue
        area_scielo = (_v(j, "v441") or "").lower()
        dados = {
            "acronimo": (_v(j, "v68") or "").lower() or None,
            "titulo": _v(j, "v100"),
            "abrev": _v(j, "v150"),
            "issn_epub": _issn_por_tipo(j, "ONLIN") or (issn if not _issn_por_tipo(j, "PRINT") else None),
            "issn_ppub": _issn_por_tipo(j, "PRINT"),
            "editora": _v(j, "v480") or _v(j, "v62"),
            "na_scielo": True,
            "area": AREAS_SCIELO.get(area_scielo),
            "_fonte": f"dados do periódico na coleção SciELO {colecao.upper()} (ArticleMeta), consultados pelo ISSN {issn}",
        }
        return {"achou": True, "mensagem": f"Periódico encontrado na coleção SciELO {colecao.upper()}.",
                "dados": {k: v for k, v in dados.items() if v is not None}, "colecao": colecao}
    if erro_rede:
        return {"achou": False, "mensagem": f"Não consegui consultar a SciELO agora ({erro_rede}). Preencha à mão.", "dados": {}}
    return {"achou": False, "mensagem": f"O ISSN {issn} não foi encontrado nas coleções SciELO. Se a revista tem ISSN "
                                        "impresso e eletrônico, tente o outro: a SciELO indexa por um deles. Se ela ainda "
                                        "não está na SciELO, preencha os campos à mão.", "dados": {}}
