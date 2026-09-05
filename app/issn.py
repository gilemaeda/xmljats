"""
Consulta de periódico pelo ISSN, em cascata, para preencher o cadastro de revistas sem digitar tudo.

O que existe de verdade, testado em 05/09/2026:

- portal.issn.org  — ficha pública do registro. É a autoridade do ISSN e a única fonte que publica o
                     "Abbreviated key title" (o abbrev-journal-title que a SPS exige). Não tem API aberta:
                     a API oficial (api.issn.org) responde 403 "Please provide your personnal token" e é paga.
                     Lemos a ficha pública, que é uma página estável de rótulo e valor.
- api.crossref.org — título e editora, sem chave.
- api.openalex.org — título, instituição mantenedora, país, site.
- doaj.org/api     — licença, idioma, país e área; é a fonte boa para a licença Creative Commons.
- ArticleMeta      — SciELO (app/scielo.py): acrônimo e título abreviado como a SciELO usa. Manda nos campos
                     que a SciELO já tem, porque é o que vai bater no pacote.

cbissn.ibict.br (Centro Brasileiro do ISSN) é um site institucional em WordPress: explica como pedir ISSN,
tem formulário e perguntas frequentes. Não publica base consultável nem API de periódicos — a única API é a
do WordPress, que serve as páginas do site. Por isso ele não entra na cascata; entra como link de apoio para
quem precisa registrar um ISSN novo.

Nada aqui grava sozinho: a tela mostra o que cada fonte respondeu, com a origem de cada campo, e a pessoa
confere antes de salvar. Sem resposta, a mensagem diz isso em vez de devolver um cadastro pela metade.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import scielo

UA = {"User-Agent": "xmljats/1.0 (+https://github.com/gilemaeda/xmljats)", "Accept": "application/json, text/html;q=0.8"}
TIMEOUT = 12          # por requisição
PRAZO_TOTAL = 45      # teto da consulta inteira: quem clica em "Buscar" não pode ficar minutos esperando
RE_ISSN = re.compile(r"^[0-9]{4}-[0-9]{3}[0-9X]$")
PORTAL_FICHA = "https://portal.issn.org/resource/ISSN/{issn}"
CBISSN = "https://cbissn.ibict.br/"

# rótulos da ficha do portal.issn.org -> campo nosso
ROTULOS_PORTAL = {
    "key title": "titulo",
    "title proper": "titulo_proprio",
    "abbreviated key title": "abrev",
    "issn": "issn",
    "issn-l": "issn_l",
    "medium": "meio",
    "earliest publisher": "editora_bruta",
    "country": "pais",
    "language": "idioma_bruto",
    "status": "situacao",
    "frequency": "periodicidade",
    "udc summary": "assunto",
}
PAISES_ISO = {"BRAZIL": "BR", "PORTUGAL": "PT", "ARGENTINA": "AR", "SPAIN": "ES", "MEXICO": "MX",
              "CHILE": "CL", "COLOMBIA": "CO", "URUGUAY": "UY", "PERU": "PE", "CUBA": "CU",
              "UNITED STATES": "US", "FRANCE": "FR", "ITALY": "IT", "GERMANY": "DE", "UNITED KINGDOM": "GB"}
# assunto da CDU (portal.issn.org) / área do DOAJ -> área do nosso cadastro
AREAS_ASSUNTO = [
    (re.compile(r"(?i)\b(law|jurisprudence|direito|social scien|economic|business|management|administra)"),
     "Ciências Sociais Aplicadas (Direito, Administração, Economia)"),
    (re.compile(r"(?i)\b(medicine|health|nursing|public health|saúde|medicina|enfermagem|odontolog)"), "Ciências da Saúde"),
    (re.compile(r"(?i)\b(biolog|zoolog|botan|ecolog)"), "Ciências Biológicas"),
    (re.compile(r"(?i)\b(mathemat|physic|chemis|astronom|geoscien|computer|matemática|física|química)"), "Ciências Exatas e da Terra"),
    (re.compile(r"(?i)\b(engineer|engenharia|technolog)"), "Engenharias"),
    (re.compile(r"(?i)\b(agricultur|veterinar|agron|food scien)"), "Ciências Agrárias"),
    (re.compile(r"(?i)\b(linguistic|literature|art|philolog|letras|lingu)"), "Linguística, Letras e Artes"),
    (re.compile(r"(?i)\b(history|philosoph|psycholog|sociolog|anthropolog|education|geograph|história|filosofia|psicologia)"), "Ciências Humanas"),
]
# codigo de idioma do DOAJ (ISO 639-2) -> o codigo de duas letras que o JATS usa
IDIOMA_ISO3 = {"POR": "pt", "ENG": "en", "SPA": "es", "FRE": "fr", "FRA": "fr", "ITA": "it", "GER": "de", "DEU": "de"}
RE_CC = re.compile(r"(?i)\bCC[ \-]?(BY(?:[ \-]?NC)?(?:[ \-]?SA)?(?:[ \-]?ND)?)\b")


def normaliza(issn: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", issn or "").upper()
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else (issn or "").strip().upper()


def valido(issn: str) -> bool:
    """Formato e dígito verificador (módulo 11) do ISSN."""
    s = normaliza(issn)
    if not RE_ISSN.match(s):
        return False
    d = s.replace("-", "")
    soma = sum((8 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d[:7]))
    resto = (11 - soma % 11) % 11
    return ("X" if resto == 10 else str(resto)) == d[7]


def _pega(url: str, aceita_html: bool = False, timeout: int = TIMEOUT):
    cab = dict(UA)
    if aceita_html:
        cab["Accept"] = "text/html,application/xhtml+xml"
    req = urllib.request.Request(url, headers=cab)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.read().decode("utf-8", "replace")
    return bruto if aceita_html else json.loads(bruto or "null")


def _erro(e) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return "não tem registro para esse ISSN" if e.code == 404 else f"HTTP {e.code}"
    return str(e)[:90]


def _area(*textos) -> str:
    alvo = " ".join(t for t in textos if t)
    for rx, area in AREAS_ASSUNTO:
        if rx.search(alvo):
            return area
    return ""


def _licenca_cc(texto: str) -> str:
    m = RE_CC.search(texto or "")
    if not m:
        return ""
    chave = re.sub(r"[ _]", "-", m.group(1)).lower()
    return f"https://creativecommons.org/licenses/{chave}/4.0/"


# ---------------------------------------------------------------- fontes

def le_portal(issn: str, sobra: int = TIMEOUT) -> dict:
    """Ficha pública do portal.issn.org. Lê os pares rótulo/valor da parte 'Displaying basic data'."""
    html = _pega(PORTAL_FICHA.format(issn=issn), aceita_html=True, timeout=min(sobra, TIMEOUT))
    limpo = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", html)
    linhas = [re.sub(r"\s+", " ", x).strip() for x in re.sub(r"<[^>]+>", "\n", limpo).split("\n")]
    linhas = [x for x in linhas if x]
    # a ficha começa no "Confirmed record"/"Key title:"; antes disso vem o formulário de busca, que repete rótulos
    inicio = next((i for i, x in enumerate(linhas) if x.lower().startswith("key title")), None)
    if inicio is None:
        raise ValueError("a ficha do portal veio sem os campos esperados")
    fim = next((i for i, x in enumerate(linhas[inicio:], inicio) if x.lower().startswith("covered by")), len(linhas))
    dados: dict = {}
    for i in range(inicio, min(fim, len(linhas) - 1)):
        rot = linhas[i].rstrip(":").strip().lower()
        campo = ROTULOS_PORTAL.get(rot)
        if campo and campo not in dados:
            valor = linhas[i + 1].strip()
            if valor and not valor.endswith(":"):
                dados[campo] = valor
    if not dados.get("titulo"):
        raise ValueError("a ficha do portal veio sem o título")
    fora = {}
    if dados.get("titulo"):
        fora["titulo"] = dados["titulo"]
    if dados.get("abrev"):
        fora["abrev"] = dados["abrev"].rstrip(".") if dados["abrev"].count(".") == 1 else dados["abrev"]
    ed = dados.get("editora_bruta") or ""
    if ed:
        # "Rio de Janeiro, RJ: Universidade do Estado do Rio de Janeiro, Faculdade de Direito"
        fora["editora"] = ed.split(":", 1)[1].strip() if ":" in ed else ed
        if ":" in ed:
            fora["cidade"] = ed.split(":", 1)[0].strip()
    pais = (dados.get("pais") or "").upper().strip()
    if pais:
        fora["pais_iso"] = PAISES_ISO.get(pais, "")
        fora["pais_nome"] = dados["pais"].title()
    if dados.get("meio"):
        chave = "issn_epub" if "online" in dados["meio"].lower() else "issn_ppub"
        fora[chave] = issn
    if dados.get("assunto"):
        fora["area"] = _area(dados["assunto"])
        fora["assunto"] = dados["assunto"]
    for k in ("issn_l", "situacao", "periodicidade"):
        if dados.get(k):
            fora[k] = dados[k]
    return fora


def le_crossref(issn: str, sobra: int = TIMEOUT) -> dict:
    j = (_pega(f"https://api.crossref.org/journals/{issn}", timeout=min(sobra, TIMEOUT)) or {}).get("message") or {}
    if not j.get("title"):
        raise ValueError("sem registro")
    fora = {"titulo": j["title"]}
    if j.get("publisher"):
        fora["editora"] = j["publisher"]
    for it in j.get("issn-type") or []:
        if it.get("type") == "electronic":
            fora["issn_epub"] = normaliza(it.get("value"))
        elif it.get("type") == "print":
            fora["issn_ppub"] = normaliza(it.get("value"))
    return fora


def le_openalex(issn: str, sobra: int = TIMEOUT) -> dict:
    j = _pega(f"https://api.openalex.org/sources/issn:{issn}", timeout=min(sobra, TIMEOUT)) or {}
    if not j.get("display_name"):
        raise ValueError("sem registro")
    fora = {"titulo": j["display_name"]}
    if j.get("host_organization_name"):
        fora["editora"] = j["host_organization_name"]
    if j.get("country_code"):
        fora["pais_iso"] = j["country_code"]
    if j.get("homepage_url"):
        fora["site"] = j["homepage_url"]
    for i in j.get("issn") or []:
        fora.setdefault("issn_epub", normaliza(i))
    temas = ", ".join((t.get("display_name") or "") for t in (j.get("topics") or [])[:4])
    area = _area(temas)
    if area:
        fora["area"] = area
    return fora


def le_doaj(issn: str, sobra: int = TIMEOUT) -> dict:
    j = _pega("https://doaj.org/api/search/journals/" + urllib.parse.quote(f"issn:{issn}"),
              timeout=min(sobra, TIMEOUT)) or {}
    res = j.get("results") or []
    if not res:
        raise ValueError("não está no DOAJ")
    b = (res[0].get("bibjson") or {})
    fora = {}
    if b.get("title"):
        fora["titulo"] = b["title"]
    if b.get("alternative_title"):
        fora["abrev"] = b["alternative_title"]
    ed = (b.get("publisher") or {})
    if ed.get("name"):
        fora["editora"] = ed["name"]
    if ed.get("country"):
        fora["pais_iso"] = ed["country"]
    for ident in b.get("identifier") or []:
        if ident.get("type") == "eissn":
            fora["issn_epub"] = normaliza(ident.get("id"))
        elif ident.get("type") == "pissn":
            fora["issn_ppub"] = normaliza(ident.get("id"))
    for lic in b.get("license") or []:
        url = lic.get("url") or ""
        achada = url if "creativecommons.org/licenses/" in url else _licenca_cc(lic.get("type") or "")
        if achada:
            fora["licenca"] = achada
            break
    # idioma que a revista publica: serve para preencher o idioma do artigo quando ele nao vier do arquivo
    idiomas = [IDIOMA_ISO3.get((x or "").upper()) for x in (b.get("language") or [])]
    idiomas = [x for x in idiomas if x]
    if idiomas:
        fora["idioma_padrao"] = idiomas[0]
    assuntos = ", ".join((s.get("term") or "") for s in (b.get("subject") or []))
    area = _area(assuntos)
    if area:
        fora["area"] = area
    if b.get("ref", {}).get("journal"):
        fora["site"] = b["ref"]["journal"]
    return fora


def le_scielo(issn: str, sobra: int = TIMEOUT) -> dict:
    # a SciELO é consultada coleção por coleção; sem teto, 16 coleções lentas seguravam a tela por minutos
    r = scielo.busca_por_issn(issn, timeout=min(6, max(2, sobra)), prazo_total=max(4, min(sobra, 20)))
    if not r.get("achou"):
        raise ValueError(r.get("mensagem") or "não está nas coleções SciELO")
    d = dict(r["dados"])
    d.pop("_fonte", None)
    d["colecao"] = r.get("colecao")
    return d


# ordem importa: a primeira fonte que traz um campo é a que vale (a SciELO manda no que ela já publica,
# e o portal do ISSN manda no título abreviado, que é o que a SPS exige)
FONTES = [
    ("SciELO (ArticleMeta)", "https://articlemeta.scielo.org", le_scielo),
    ("Portal do ISSN (issn.org)", "https://portal.issn.org", le_portal),
    ("DOAJ", "https://doaj.org", le_doaj),
    ("Crossref", "https://api.crossref.org", le_crossref),
    ("OpenAlex", "https://openalex.org", le_openalex),
]
# campos em que uma fonte é melhor que a ordem da cascata: quem manda, em ordem, quando responder.
# O título do portal do ISSN vem com o qualificador de desambiguação ("Anamorphosis (Porto Alegre)"),
# que não é o título da revista — por isso ele fica por último em 'titulo' e manda só no 'abrev'.
PREFERENCIA = {
    "abrev": ["Portal do ISSN (issn.org)"],
    "acronimo": ["SciELO (ArticleMeta)"],
    "licenca": ["DOAJ"],
    "titulo": ["SciELO (ArticleMeta)", "DOAJ", "Crossref", "OpenAlex", "Portal do ISSN (issn.org)"],
}


def consulta(issn_bruto: str, prazo_total: int = PRAZO_TOTAL) -> dict:
    """Consulta as fontes e devolve {'issn', 'ok', 'mensagem', 'dados', 'origem', 'fontes'}.

    'dados' é o cadastro sugerido; 'origem' diz de onde veio cada campo; 'fontes' lista o que cada
    serviço respondeu, para a tela mostrar. Nunca levanta exceção de rede.
    """
    issn = normaliza(issn_bruto)
    if not RE_ISSN.match(issn):
        return {"issn": issn, "ok": False, "mensagem": "ISSN inválido: use o formato 0000-0000.", "dados": {}, "origem": {}, "fontes": []}
    if not valido(issn):
        return {"issn": issn, "ok": False, "mensagem": f"O dígito verificador de {issn} não confere. Confira o número na capa ou no site da revista.",
                "dados": {}, "origem": {}, "fontes": []}
    dados: dict = {}
    origem: dict = {}
    relatorio = []
    respostas = {}
    import time
    fim = time.monotonic() + prazo_total
    for nome, site, ler in FONTES:
        if time.monotonic() >= fim:
            respostas[nome] = {}
            relatorio.append({"fonte": nome, "site": site, "ok": False,
                              "mensagem": f"não consultada: a busca passou do limite de {prazo_total}s"})
            continue
        try:
            r = ler(issn, sobra=max(2, int(fim - time.monotonic()))) or {}
            respostas[nome] = r
            relatorio.append({"fonte": nome, "site": site, "ok": True,
                              "mensagem": f"{len(r)} campo(s): " + ", ".join(sorted(r)) if r else "respondeu sem dados"})
        except Exception as e:  # noqa: BLE001
            respostas[nome] = {}
            relatorio.append({"fonte": nome, "site": site, "ok": False, "mensagem": _erro(e)})
    # a SciELO indexa por um dos ISSN; se perguntamos pelo eletrônico e ela guarda o impresso (ou o contrário),
    # a primeira volta não acha nada. As outras fontes devolvem o número irmão: vale tentar de novo com ele.
    if not respostas.get("SciELO (ArticleMeta)"):
        irmaos = {normaliza(v) for r in respostas.values() for k, v in (r or {}).items()
                  if k in ("issn_l", "issn_ppub", "issn_epub") and v}
        for outro in sorted(irmaos - {issn}):
            if time.monotonic() >= fim:
                break
            try:
                r = le_scielo(outro, sobra=max(2, int(fim - time.monotonic())))
            except Exception:  # noqa: BLE001
                continue
            respostas["SciELO (ArticleMeta)"] = r
            for item in relatorio:
                if item["fonte"] == "SciELO (ArticleMeta)":
                    item.update(ok=True, mensagem=f"achada pelo ISSN irmão {outro}: " + ", ".join(sorted(r)))
            break
    # campos com dono definido primeiro, depois a ordem da cascata
    for campo, donas in PREFERENCIA.items():
        for dona in donas:
            v = (respostas.get(dona) or {}).get(campo)
            if v:
                dados[campo] = v
                origem[campo] = dona
                break
    for nome, _site, _ler in FONTES:
        for campo, valor in (respostas.get(nome) or {}).items():
            if valor in (None, "", []) or campo in dados:
                continue
            dados[campo] = valor
            origem[campo] = nome
    dados.setdefault("issn_epub", issn)
    origem.setdefault("issn_epub", "ISSN informado")
    # o Crossref repete o mesmo número nos dois tipos quando a revista só tem um: não é ISSN impresso
    if dados.get("issn_ppub") and dados["issn_ppub"] == dados.get("issn_epub"):
        dados.pop("issn_ppub")
        origem.pop("issn_ppub", None)
    achou = [r["fonte"] for r in relatorio if r["ok"]]
    if not achou:
        return {"issn": issn, "ok": False, "dados": {}, "origem": {}, "fontes": relatorio,
                "mensagem": f"Nenhuma das {len(FONTES)} fontes tem registro para o ISSN {issn}. Se a revista tem ISSN "
                            "impresso e outro eletrônico, tente o outro número. Se ela ainda não tem ISSN, o pedido é "
                            f"feito no Centro Brasileiro do ISSN ({CBISSN})."}
    return {"issn": issn, "ok": True, "dados": dados, "origem": origem, "fontes": relatorio,
            "mensagem": "Encontrado em: " + ", ".join(achou) + ". Confira os campos antes de salvar."}
