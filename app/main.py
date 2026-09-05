"""
xmljats - site (Fase 2): validador de PDF -> modelo -> revisao -> XML SciELO PS -> packtools -> pacote.

Rotas:
  GET  /                        validador + documentos recentes
  POST /validar                 upload do PDF: extracao, geracao e validacao
  GET  /doc/{id}                resultado (bloqueantes, erros packtools, avisos, extracao)
  GET  /doc/{id}/editar         formulario "Revisar e editar" (corrige metadados; edicoes viram overrides)
  POST /doc/{id}/editar         salva edicoes, regenera o XML e revalida
  POST /doc/{id}/reprocessar    reextrai do PDF (mantem as edicoes)
  GET  /doc/{id}/xml            download do XML (nome-base SPS)
  GET  /doc/{id}/pacote.zip     XML + PDF renomeado no padrao SPS
  GET  /doc/{id}/modelo.json, /doc/{id}/resumo.md, /doc/{id}/validacao.json
  POST /doc/{id}/etapa          muda a etapa do artigo no fluxo SciELO (recebido ... publicado)
  GET  /painel                  documentos do usuario (cliente ve so os seus), com filtros
  GET  /conta, POST /conta/senha, GET /ajuda    area da conta
  GET  /admin, /admin/documentos                administracao (visao geral e todos os documentos)
  GET  /revistas, /revistas/nova, /revistas/{acr}, POST idem, POST /revistas/{acr}/remover   cadastro editavel (admin)
  GET/POST /entrar, POST /sair  login por sessao (cookie assinado); GET/POST /usuarios... (admin)
  GET  /saude                   healthcheck

Protecao: login por sessao (app/contas.py; usuarios em XMLJATS_DATA/usuarios.json). Com APP_SENHA definida e nenhum
usuario cadastrado, o admin "admin" e criado com essa senha no primeiro acesso; APP_SENHA tambem vale como HTTP Basic
para scripts. Sem APP_SENHA e sem usuarios (desenvolvimento), o app roda sem login.
Cadastro de revistas editavel em XMLJATS_DATA/revistas.json (semeado de modelos/revistas.json).
Pasta do documento (XMLJATS_DATA/docs/<id>): original.pdf, nome_original.txt, model.json (extracao), edicoes.json
(overrides do usuario), config.json (revista, versao SPS), resumo.md, <base>.xml, validacao.json.
"""
import copy
import datetime as dt
import urllib.parse
import io
import json
import os
import re
import secrets
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "poc"))
sys.path.insert(0, str(RAIZ / "app"))

from contas import COOKIE, PAPEIS, ROTULO_PAPEL, Contas  # noqa: E402  (app/contas.py)
import tempo  # noqa: E402  (app/tempo.py: tudo no horário de Brasília)
from correio import CAIXAS, ROTULO_CAIXA, Correio, corpo_confirmacao, token_confirmacao  # noqa: E402
import scielo  # noqa: E402  (app/scielo.py: consulta de periódico por ISSN)

import extrair as cli  # noqa: E402  (poc/extrair.py)
import gerar_xml as gx  # noqa: E402  (poc/gerar_xml.py)
from extrator import xml_jats  # noqa: E402
from extrator.util import RE_ORCID, orcid_valido  # noqa: E402

DATA = Path(os.environ.get("XMLJATS_DATA", RAIZ / "data"))
DOCS = DATA / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
VERSAO_APP = "0.10.0"
CONTAS = Contas(DATA)
CORREIO = Correio(DATA)
AVATARES = DATA / "avatares"
AVATARES.mkdir(parents=True, exist_ok=True)

# etapas do artigo no fluxo de entrega a SciELO (anotadas a mao no painel)
# papel "cliente" vê só os próprios documentos; "operador" vê todos; "admin" também administra
ETAPAS = [("recebido", "Recebido"), ("em_revisao", "Em revisão"), ("pronto", "Pronto para entrega"),
          ("entregue", "Entregue à SciELO"), ("pre_qa", "Pré-QA"), ("qa", "QA"), ("qa_finalizado", "QA finalizado"), ("publicado", "Publicado")]
ETAPA_ROTULO = dict(ETAPAS)
# A área não muda o XML (JATS é o mesmo para todas), mas muda o que esperar do artigo: estilo de referências,
# presença de tabelas e equações. Serve para conferir a extração e para orientar quem opera.
AREAS = ["Ciências Sociais Aplicadas (Direito, Administração, Economia)", "Ciências Humanas", "Linguística, Letras e Artes",
         "Ciências da Saúde", "Ciências Biológicas", "Ciências Exatas e da Terra", "Engenharias", "Ciências Agrárias", "Multidisciplinar"]
ESTILOS_REF = [("", "Detectar pelo texto"), ("ABNT", "ABNT (autor-data)"), ("APA", "APA (autor-data)"),
               ("numérico", "Numérico (Vancouver 1. / IEEE [1])")]
LICENCAS = [("https://creativecommons.org/licenses/by/4.0/", "CC BY 4.0"), ("https://creativecommons.org/licenses/by-nc/4.0/", "CC BY-NC 4.0"),
            ("https://creativecommons.org/licenses/by-nc-sa/4.0/", "CC BY-NC-SA 4.0"), ("https://creativecommons.org/licenses/by-nc-nd/4.0/", "CC BY-NC-ND 4.0"),
            ("https://creativecommons.org/licenses/by-sa/4.0/", "CC BY-SA 4.0"), ("https://creativecommons.org/licenses/by-nd/4.0/", "CC BY-ND 4.0")]

app = FastAPI(title="xmljats", version=VERSAO_APP, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(RAIZ / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(RAIZ / "app" / "templates"))
templates.env.globals["versao"] = VERSAO_APP
templates.env.globals["ETAPA_ROTULO"] = ETAPA_ROTULO
templates.env.globals["FUSO"] = tempo.NOME_FUSO
templates.env.globals["ROTULO_PAPEL"] = ROTULO_PAPEL
templates.env.filters["quando"] = tempo.formata
templates.env.filters["quando_dia"] = lambda v: tempo.formata(v, com_hora=False)
templates.env.filters["ha_quanto"] = tempo.ha_quanto
templates.env.filters["online"] = tempo.online
templates.env.tests["online"] = tempo.online
templates.env.globals["ROTULO_CAIXA"] = ROTULO_CAIXA
templates.env.globals["CAIXAS"] = CAIXAS


def _nao_lidas():
    try:
        return CORREIO.contagens().get("nao_lidas", 0)
    except Exception:  # noqa: BLE001
        return 0


templates.env.globals["nao_lidas"] = _nao_lidas


def _filtro_regra(texto):
    """Destaca códigos de regra como (A09) numa etiqueta monoespaçada."""
    from markupsafe import Markup, escape
    t = escape(str(texto))
    return Markup(re.sub(r"\(([A-Z]\d{2})\)", r'<code class="rule">\1</code>', str(t)))


templates.env.filters["regra"] = _filtro_regra


def markdown_html(texto: str) -> str:
    try:
        import markdown
        return markdown.markdown(texto, extensions=["nl2br"])
    except Exception:  # noqa: BLE001
        from markupsafe import escape
        return "<pre>" + str(escape(texto)) + "</pre>"
seguranca = HTTPBasic(auto_error=False)

# codigo da regra (nos bloqueantes) -> campos do formulario que resolvem
CAMPOS_POR_REGRA = {
    "A09": ["data_publicado"], "H01": ["data_recebido", "data_aceito"], "H02": ["data_recebido", "data_aceito"],
    "A04": ["heading"], "A01": ["doi"], "A02": ["order"], "A08": ["volume", "numero", "elocation"], "A05": ["titulo_0_texto"],
    "A03": ["tipo_artigo"], "L01": ["licenca"], "J01": ["revista"], "J03": ["revista"], "J05": ["revista"], "C07": ["corresp"],
}
TIPOS_ARTIGO = ["research-article", "review-article", "editorial", "book-review", "letter", "brief-report", "case-report",
                "article-commentary", "correction", "retraction", "addendum", "rapid-communication", "other"]
IDIOMAS = ["pt", "en", "es", "fr", "it", "de"]
CAMPOS_SIMPLES = ("heading", "tipo_artigo", "idioma", "volume", "numero", "ano", "elocation", "order", "doi", "licenca")
RE_CAMPO_LISTA = re.compile(r"^(titulo|autor|aff|resumo)_(\d+)_(\w+)$")


# ---------------------------------------------------------------- utilidades

LOCAL = {"id": "local", "nome": "local", "email": "local", "papel": "admin"}


def de_onde(request: Request):
    """IP real (o app roda atrás do Traefik, então o IP do cliente vem no cabeçalho) e navegador."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else None)
    return ip, request.headers.get("user-agent")


def autentica(request: Request, cred: Optional[HTTPBasicCredentials] = Depends(seguranca)) -> dict:
    """Usuario da requisicao: sessao (cookie assinado) > HTTP Basic com APP_SENHA (scripts) > modo local sem senha.
    Sem sessao valida numa pagina HTML, redireciona para /entrar. Cada acesso autenticado marca a atividade do usuario
    (ultimo acesso, IP e navegador), que alimenta o painel administrativo."""
    senha = os.environ.get("APP_SENHA")
    CONTAS.garante_admin(senha)
    ip, navegador = de_onde(request)
    u = CONTAS.le_sessao(request.cookies.get(COOKIE))
    if u:
        CONTAS.registra_acesso(u["id"], ip, navegador, request.url.path)
        return u
    # HTTP Basic com APP_SENHA continua valendo para scripts; num navegador, com contas cadastradas, o caminho é o
    # login normal (senão a pessoa fica presa numa sessão sem conta, sem conseguir trocar a própria senha)
    quer_html = "text/html" in (request.headers.get("accept") or "")
    if cred and senha and secrets.compare_digest(cred.password.encode(), senha.encode()) and not (quer_html and CONTAS.lista()):
        return {"id": "api", "nome": cred.username or "api", "email": "api", "papel": "admin"}
    if not senha and not CONTAS.lista():
        return LOCAL
    destino = request.url.path + (("?" + request.url.query) if request.url.query else "")
    raise HTTPException(status_code=303, headers={"Location": "/entrar?proximo=" + urllib.parse.quote(destino, safe="")})


def confirmacao_pendente(usuario: dict) -> bool:
    """Conta que ainda não confirmou o e-mail, quando o sistema exige confirmação."""
    if usuario.get("id") in ("local", "api") or usuario.get("papel") == "admin":
        return False
    c = CORREIO.config()
    return bool(c.get("exigir_confirmacao")) and not usuario.get("email_confirmado")


def envia_confirmacao(usuario: dict, por: str = "sistema", request: Optional[Request] = None) -> Optional[dict]:
    """Gera o token, monta o link e manda o e-mail de confirmação. Sem Resend configurado, devolve None."""
    c = CORREIO.config()
    if not (c.get("resend_chave") and c.get("remetente_email")):
        return None
    token = token_confirmacao()
    CONTAS.define_token_confirmacao(usuario["id"], token)
    # sem endereço configurado, usa o host da própria requisição (assim o link nunca sai quebrado)
    base = (c.get("url_base") or "").rstrip("/") or (str(request.base_url).rstrip("/") if request else "")
    link = f"{base}/confirmar?token={token}"
    texto, html = corpo_confirmacao(usuario["nome"], link)
    return CORREIO.envia_novo(usuario["email"], "Confirme seu e-mail no xmljats", texto, html, tipo="confirmacao", por=por)


def exige_admin(usuario: dict = Depends(autentica)) -> dict:
    if usuario.get("papel") != "admin":
        raise HTTPException(403, "Só administradores podem fazer isso.")
    return usuario


def le_json(caminho: Path, padrao=None):
    if not caminho.exists():
        return padrao
    with io.open(caminho, encoding="utf-8") as f:
        return json.load(f)


def grava_json(caminho: Path, obj):
    with io.open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _arquivo_revistas() -> Path:
    """Cadastro editavel em XMLJATS_DATA/revistas.json, semeado de modelos/revistas.json.
    Revistas novas da semente entram uma unica vez (a lista 'semeadas' guarda o que ja veio de la), para que uma
    atualizacao do codigo traga revistas novas sem ressuscitar as que o administrador removeu nem desfazer edicoes."""
    arq = DATA / "revistas.json"
    semente = (le_json(RAIZ / "modelos" / "revistas.json", {"revistas": []}) or {}).get("revistas", [])
    if not arq.exists():
        grava_json(arq, {"revistas": semente, "semeadas": [r["acronimo"] for r in semente]})
        return arq
    atual = le_json(arq, {"revistas": []}) or {"revistas": []}
    ja = set(atual.get("semeadas") or [r["acronimo"] for r in atual.get("revistas", [])])
    novas = [r for r in semente if r["acronimo"] not in ja]
    # campos que passaram a existir depois (ex.: area, estilo das referencias) sao preenchidos nas revistas ja
    # cadastradas, mas so quando faltam: o que o administrador escreveu nunca e sobrescrito
    por_acr = {r["acronimo"]: r for r in semente}
    mudou = False
    for r in atual.get("revistas", []):
        base = por_acr.get(r["acronimo"])
        if not base:
            continue
        for k, v in base.items():
            if k not in r and v is not None:
                r[k] = v
                mudou = True
    if novas or mudou or "semeadas" not in atual:
        atual["revistas"] = list(atual.get("revistas", [])) + novas
        atual["semeadas"] = sorted(ja | {r["acronimo"] for r in semente})
        grava_json(arq, atual)
    return arq


def carrega_revistas():
    return le_json(_arquivo_revistas(), {"revistas": []})["revistas"]


def grava_revistas(lista):
    arq = _arquivo_revistas()
    atual = le_json(arq, {}) or {}
    atual["revistas"] = lista
    grava_json(arq, atual)


RE_ACRONIMO = re.compile(r"^[a-z][a-z0-9]{1,24}$")
RE_DOI_PREFIXO = re.compile(r"^10\.\d{4,9}(/\S*)?$")


def valida_revista(form: dict, existentes: list, acronimo_atual: Optional[str] = None):
    """Devolve (dados, erros). Nada e inventado: campos vazios ficam vazios; ISSN e DOI sao checados de verdade."""
    from extrator.util import issn_valido  # noqa: WPS433
    d = {k: (form.get(k) or "").strip() for k in ("acronimo", "titulo", "abrev", "issn_epub", "issn_ppub", "editora", "doi_prefixo",
                                                   "licenca_url", "modo_publicacao", "secao_padrao", "site", "_fonte",
                                                   "area", "estilo_referencias")}
    d["acronimo"] = d["acronimo"].lower()
    d["na_scielo"] = (form.get("na_scielo") or "").strip() == "sim"
    erros = {}
    if not RE_ACRONIMO.match(d["acronimo"]):
        erros["acronimo"] = "Acrônimo em minúsculas, letras e números, de 2 a 25 caracteres (ex.: rdp, anamps)."
    elif d["acronimo"] != acronimo_atual and any(r["acronimo"] == d["acronimo"] for r in existentes):
        erros["acronimo"] = f"Já existe a revista '{d['acronimo']}'."
    for campo, rotulo in (("titulo", "o título"), ("abrev", "o título abreviado"), ("editora", "a editora")):
        if not d[campo]:
            erros[campo] = f"Informe {rotulo}."
    if not d["issn_epub"]:
        erros["issn_epub"] = "Informe o e-ISSN (entra no nome de todos os arquivos)."
    for campo in ("issn_epub", "issn_ppub"):
        v = d[campo].upper()
        if v and not (re.fullmatch(r"\d{4}-\d{3}[\dX]", v) and issn_valido(v)):
            erros[campo] = "ISSN inválido: formato 0000-0000 com dígito verificador correto."
        d[campo] = v or None
    if d["doi_prefixo"] and not RE_DOI_PREFIXO.match(d["doi_prefixo"]):
        erros["doi_prefixo"] = "Prefixo DOI começa com 10. seguido de 4 a 9 dígitos (ex.: 10.21119/anamps)."
    if d["licenca_url"] not in {u for u, _ in LICENCAS}:
        erros["licenca_url"] = "Escolha uma licença Creative Commons da lista."
    if d["modo_publicacao"] not in ("continua", "regular"):
        d["modo_publicacao"] = "continua"
    if d["area"] and d["area"] not in AREAS:
        erros["area"] = "Escolha uma área da lista."
    if d["estilo_referencias"] and d["estilo_referencias"] not in {e for e, _ in ESTILOS_REF}:
        erros["estilo_referencias"] = "Escolha um estilo da lista."
    if d["site"] and not re.match(r"^https?://", d["site"]):
        erros["site"] = "O site precisa começar com http:// ou https://."
    for k in ("doi_prefixo", "secao_padrao", "site", "_fonte", "area", "estilo_referencias"):
        d[k] = d[k] or None
    return d, erros


def _pasta(doc_id: str, usuario: Optional[dict] = None) -> Path:
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise HTTPException(404)
    pasta = DOCS / doc_id
    if not pasta.is_dir():
        raise HTTPException(404, "Documento não encontrado")
    if usuario is not None:
        cfg = le_json(pasta / "config.json", {}) or {}
        if not pode_ver(cfg, usuario):
            raise HTTPException(403, "Este documento é de outra conta.")
    return pasta


def pode_ver(doc: dict, usuario: dict) -> bool:
    """Cliente só vê os próprios documentos; operador e admin veem todos."""
    if usuario.get("papel") in ("admin", "operador"):
        return True
    return (doc.get("criado_por_id") or doc.get("criado_por")) in (usuario.get("id"), usuario.get("nome"))


def lista_docs(limite=30, usuario: Optional[dict] = None):
    itens = []
    for pasta in DOCS.iterdir():
        d = le_json(pasta / "validacao.json")
        if not d:
            continue
        d["id"] = pasta.name
        nome = pasta / "nome_original.txt"
        if d.get("arquivo_original") in (None, "original.pdf") and nome.exists():
            d["arquivo_original"] = nome.read_text(encoding="utf-8").strip()
        cfg = le_json(pasta / "config.json", {}) or {}
        d["etapa"] = cfg.get("etapa") or "recebido"
        d["criado_por"] = cfg.get("criado_por")
        d["criado_por_id"] = cfg.get("criado_por_id")
        if usuario is not None and not pode_ver(d, usuario):
            continue
        hist = cfg.get("historico_etapas") or []
        d["etapa_por"] = hist[-1].get("por") if hist else None
        itens.append(d)
    itens.sort(key=lambda d: d.get("atualizado_em") or d.get("criado_em", ""), reverse=True)
    return itens[:limite] if limite else itens


# ---------------------------------------------------------------- edicoes (overrides sobre a extracao)

def valores_editaveis(modelo: dict) -> dict:
    """Achata o modelo nos campos do formulario (valores extraidos, antes de qualquer edicao)."""
    d = modelo.get("datas") or {}
    v = {
        "heading": modelo.get("heading") or "", "tipo_artigo": modelo.get("tipo_artigo") or "research-article",
        "idioma": modelo.get("idioma") or "", "volume": modelo.get("volume") or "", "numero": modelo.get("numero") or "",
        "ano": modelo.get("ano") or "", "elocation": modelo.get("elocation") or "", "order": modelo.get("order") or "",
        "doi": modelo.get("doi") or "", "licenca": modelo.get("licenca") or "",
        "data_recebido": d.get("recebido") or "", "data_aceito": d.get("aceito") or "", "data_publicado": d.get("publicado") or "",
    }
    for k, t in enumerate(modelo.get("titulos", [])):
        v[f"titulo_{k}_texto"] = t.get("texto") or ""
        v[f"titulo_{k}_idioma"] = t.get("idioma") or ""
    corresp = next((i for i, a in enumerate(modelo.get("autores", [])) if a.get("email")), None)
    v["corresp"] = "" if corresp is None else str(corresp)
    for i, a in enumerate(modelo.get("autores", [])):
        v[f"autor_{i}_sobrenome"] = a.get("sobrenome") or ""
        v[f"autor_{i}_nomes"] = a.get("nomes") or ""
        v[f"autor_{i}_orcid"] = a.get("orcid") or ""
        v[f"autor_{i}_email"] = a.get("email") or ""
        v[f"autor_{i}_affs"] = ", ".join(a.get("aff_ids", []))
    for j, af in enumerate(modelo.get("afiliacoes", [])):
        for campo in ("instituicao", "divisao", "cidade", "estado", "pais_iso"):
            v[f"aff_{j}_{campo}"] = af.get(campo) or ""
    for k, r in enumerate(modelo.get("resumos", [])):
        v[f"resumo_{k}_idioma"] = r.get("idioma") or ""
        v[f"resumo_{k}_kw"] = "; ".join(r.get("palavras_chave", []))
    return v


def aplica_edicoes(modelo: dict, campos: dict) -> dict:
    """Devolve uma copia do modelo com os overrides aplicados e a proveniencia marcada."""
    m = copy.deepcopy(modelo)
    prov = m.setdefault("proveniencia", {})
    m.setdefault("datas", {})
    for k, val in campos.items():
        val = (val or "").strip() or None
        prov[k] = "editado à mão"
        if k in CAMPOS_SIMPLES:
            m[k] = val
            if k == "licenca" and val:
                low = val.lower()
                chave = "by-nc-sa" if "sa" in low else ("by-nc" if "nc" in low else "by")
                m["licenca_url"] = f"https://creativecommons.org/licenses/{chave}/4.0/"
        elif k.startswith("data_"):
            m["datas"][k[5:]] = val
        elif k == "corresp":
            for i, a in enumerate(m.get("autores", [])):
                a["correspondente"] = (val is not None and str(i) == val)
        else:
            mt = RE_CAMPO_LISTA.match(k)
            if not mt:
                continue
            grupo, idx, campo = mt.group(1), int(mt.group(2)), mt.group(3)
            lista = {"titulo": "titulos", "autor": "autores", "aff": "afiliacoes", "resumo": "resumos"}[grupo]
            if idx >= len(m.get(lista, [])):
                continue
            alvo = m[lista][idx]
            if grupo == "autor" and campo == "affs":
                alvo["aff_ids"] = [x.strip() for x in (val or "").split(",") if x.strip()]
            elif grupo == "autor" and campo == "orcid":
                mo = RE_ORCID.search(val or "")
                alvo["orcid"] = mo.group(1).upper() if mo else None
                alvo["orcid_valido"] = orcid_valido(alvo["orcid"]) if alvo["orcid"] else None
            elif grupo == "autor" and campo in ("sobrenome", "nomes"):
                alvo[campo] = val
                alvo["nome_completo"] = " ".join(x for x in (alvo.get("nomes"), alvo.get("sobrenome")) if x)
            elif grupo == "resumo" and campo == "kw":
                alvo["palavras_chave"] = [x.strip(" .") for x in re.split(r"[;\n]", val or "") if x.strip(" .")]
            else:
                alvo[campo] = val
    return m


def modelo_efetivo(pasta: Path) -> dict:
    modelo = le_json(pasta / "model.json", {})
    ed = le_json(pasta / "edicoes.json", {}) or {}
    return aplica_edicoes(modelo, ed.get("campos", {})) if ed.get("campos") else modelo


def campos_bloqueados(bloqueantes) -> dict:
    """codigo da regra em cada bloqueante -> campos do formulario a destacar.
    Quando uma regra aponta para varios campos (ex.: H01 -> recebido e aceito), todos ficam marcados, mas a mensagem
    completa so aparece no primeiro; os demais recebem a marca "" (vazia) para nao repetir o texto."""
    out = {}
    for b in bloqueantes:
        for cod in re.findall(r"\(([A-Z]\d{2})\)", b):
            for n, campo in enumerate(CAMPOS_POR_REGRA.get(cod, [])):
                out.setdefault(campo, []).append(b if n == 0 else "")
        m = re.search(r"ORCID (?:ausente|inválido) para (.+?) \(C02\)", b)
        if m:
            out.setdefault("orcid:" + m.group(1), []).append(b)
        m = re.search(r"Autor (.+?) sem afiliação \(C03\)", b)
        if m:
            out.setdefault("affs:" + m.group(1), []).append(b)
        m = re.search(r"Afiliação (aff\d+) sem (instituição|país) \(C05\)", b)
        if m:
            out.setdefault("aff:" + m.group(1), []).append(b)
    return out


# ---------------------------------------------------------------- pipeline

def prepara_imagens_pacote(pasta: Path, imagens) -> dict:
    """Converte as imagens extraidas para TIFF com o nome SPS (<base>-gfNN.tif) em pasta/pacote. Devolve {origem: nome_sps}."""
    import shutil
    destino = pasta / "pacote"
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True, exist_ok=True)
    mapa = {}
    for origem, nome_sps in imagens:
        src = pasta / "imagens" / origem
        if not src.exists():
            continue
        try:
            from PIL import Image
            with Image.open(src) as im:
                im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
                im.save(destino / nome_sps, format="TIFF", compression="tiff_lzw")
        except Exception:  # noqa: BLE001
            shutil.copy(src, destino / (Path(nome_sps).stem + src.suffix))
        mapa[origem] = nome_sps
    return mapa

def extrai_e_salva(pasta: Path):
    doc, model = cli.extrai(str(pasta / "original.pdf"), pasta_imagens=str(pasta / "imagens"))
    grava_json(pasta / "model.json", model.to_dict())
    with io.open(pasta / "resumo.md", "w", encoding="utf-8") as f:
        f.write(cli.resumo_md(model))


def gera_e_valida(pasta: Path) -> dict:
    """Aplica edicoes, gera o XML, valida no packtools e grava validacao.json."""
    cfg = le_json(pasta / "config.json", {}) or {}
    versao_sps = cfg.get("versao_sps", "1.9")
    modelo = modelo_efetivo(pasta)
    revistas = carrega_revistas()
    acr = cfg.get("revista")
    rev = next((r for r in revistas if r["acronimo"] == acr), None) if acr else None
    rev = rev or xml_jats.escolhe_revista(modelo, revistas)
    # autor correspondente escolhido no formulario: o gerador usa o primeiro autor com e-mail, entao os outros
    # e-mails saem temporariamente da lista
    esc = next((a for a in modelo.get("autores", []) if a.get("correspondente") and a.get("email")), None)
    guardados = {}
    if esc:
        for i, a in enumerate(modelo["autores"]):
            if a is not esc and a.get("email"):
                guardados[i], a["email"] = a["email"], None
    res = xml_jats.gera_xml(modelo, rev, versao=versao_sps)
    for i, email in guardados.items():
        modelo["autores"][i]["email"] = email
    for velho in pasta.glob("*.xml"):  # o nome-base pode ter mudado com as edicoes
        velho.unlink()
    base = res.nome_base or "artigo"
    xml_path = pasta / f"{base}.xml"
    with open(xml_path, "wb") as f:
        f.write(res.xml)
    dtd_ok, sps_ok, erros, detalhe = gx.valida_packtools(str(xml_path))
    figuras_pacote = prepara_imagens_pacote(pasta, res.imagens)
    pronto = not res.bloqueantes and bool(dtd_ok) and bool(sps_ok)
    codigos_bloq = {c for b in res.bloqueantes for c in re.findall(r"\(([A-Z]\d{2})\)", b)}
    avisos_extrator = [a for a in modelo.get("avisos", []) if not (set(re.findall(r"\(([A-Z]\d{2})", a)) & codigos_bloq)]
    avisos_gerador = list(res.avisos)
    esperado = (rev or {}).get("estilo_referencias")
    detectado = modelo.get("estilo_referencias") or ""
    if esperado and detectado and esperado.lower() not in detectado.lower():
        avisos_gerador.append(f"O cadastro da revista diz que as referências são {esperado}, mas o texto foi lido como "
                              f"'{detectado}'. Confira a lista de referências (R02).")
    editados = len((le_json(pasta / "edicoes.json", {}) or {}).get("campos", {}))
    nome_original = (pasta / "nome_original.txt").read_text(encoding="utf-8").strip() if (pasta / "nome_original.txt").exists() else modelo.get("arquivo")
    anterior = le_json(pasta / "validacao.json", {}) or {}
    resultado = {
        "criado_em": anterior.get("criado_em") or tempo.agora_iso(),
        "atualizado_em": tempo.agora_iso(),
        "arquivo_original": nome_original,
        "titulo": next((t["texto"] for t in modelo.get("titulos", []) if t["tipo"] == "article-title"), ""),
        "revista": rev["acronimo"] if rev else None,
        "revista_titulo": rev["titulo"] if rev else None,
        "versao_sps": versao_sps,
        "nome_base": base,
        "xml": xml_path.name,
        "pronto": pronto,
        "dtd_ok": dtd_ok,
        "sps_ok": sps_ok,
        "bloqueantes": res.bloqueantes,
        "campos_bloqueados": campos_bloqueados(res.bloqueantes),
        "avisos_gerador": avisos_gerador,
        "avisos_extrator": avisos_extrator,
        "packtools": erros,
        "packtools_detalhe": detalhe,
        "editados": editados,
        "figuras": [{"rotulo": f["rotulo"], "legenda": f.get("legenda"), "fonte": f.get("fonte"), "arquivo": f.get("arquivo"),
                     "href": figuras_pacote.get(f.get("arquivo")), "chamada": f.get("chamada_no_texto")} for f in modelo.get("figuras", []) if f["tipo"] == "fig"],
        "tabelas": [{"rotulo": t.get("rotulo"), "legenda": t.get("legenda"), "colunas": t.get("colunas"), "linhas": len(t.get("celulas") or []),
                     "qualidade": t.get("qualidade"), "chamada": t.get("chamada_no_texto"), "pagina": t.get("pagina"),
                     "arquivo": t.get("arquivo"), "previa": (t.get("celulas") or [])[:4]} for t in modelo.get("tabelas", [])],
        "equacoes": [{"rotulo": e.get("rotulo"), "numero": e.get("numero"), "texto": (e.get("texto") or "")[:120], "pagina": e.get("pagina"),
                      "arquivo": e.get("arquivo"), "chamada": e.get("chamada_no_texto")} for e in modelo.get("equacoes", [])],
        "notas": [{"id": n["id"], "rotulo": n["rotulo"], "tipo": n.get("tipo"), "chamada": n.get("chamada_no_texto"), "ligada_a": n.get("ligada_a"),
                   "texto": (n.get("texto") or "")[:160]} for n in modelo.get("notas", [])],
        "referencias": [{"texto": r["texto"], "tipo": r.get("tipo"), "confianca": c.get("confianca", "baixa"),
                         "autores": c.get("autores", []), "editores": c.get("editores", []),
                         "campos": {k: v for k, v in c.items() if k not in ("autores", "editores", "confianca")}}
                        for r, c in zip(modelo.get("referencias", []), res.campos_referencias)],
        "estilo_referencias": modelo.get("estilo_referencias"),
        "contagens": {
            "paginas": modelo.get("paginas"),
            "autores": len(modelo.get("autores", [])),
            "resumos": len(modelo.get("resumos", [])),
            "secoes": len(modelo.get("secoes", [])),
            "notas": len(modelo.get("notas", [])),
            "figuras": len(modelo.get("figuras", [])),
            "tabelas": len(modelo.get("tabelas", [])),
            "equacoes": len(modelo.get("equacoes", [])),
            "referencias": len(modelo.get("referencias", [])),
            "citacoes": len({(c["autor"], c["ano"]) for c in modelo.get("citacoes", [])}),
        },
        "extracao": {
            "doi": modelo.get("doi"), "idioma": modelo.get("idioma"), "heading": modelo.get("heading"),
            "volume": modelo.get("volume"), "numero": modelo.get("numero"), "elocation": modelo.get("elocation"),
            "datas": modelo.get("datas"), "licenca": modelo.get("licenca"),
            "titulos": modelo.get("titulos", []),
            "autores": [{"nome": a["nome_completo"], "orcid": a.get("orcid"), "email": a.get("email"),
                         "afiliacoes": [x for x in modelo.get("afiliacoes", []) if x["id"] in a.get("aff_ids", [])]} for a in modelo.get("autores", [])],
            "resumos": [{"rotulo": r["rotulo"], "idioma": r["idioma"], "palavras": len(r["texto"].split()), "palavras_chave": r["palavras_chave"]} for r in modelo.get("resumos", [])],
            "secoes": [{"titulo": s.get("titulo_completo") or s["titulo"], "nivel": s["nivel"], "paragrafos": len(s["paragrafos"])} for s in modelo.get("secoes", [])],
            "estilo_referencias": modelo.get("estilo_referencias"),
        },
    }
    grava_json(pasta / "validacao.json", resultado)
    return resultado


# ---------------------------------------------------------------- rotas

@app.get("/saude")
def saude():
    try:
        import packtools
        pk = packtools.__version__
    except Exception:  # noqa: BLE001
        pk = None
    return {"ok": True, "app": VERSAO_APP, "packtools": pk, "docs": sum(1 for _ in DOCS.iterdir())}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, usuario: dict = Depends(autentica)):
    if usuario.get("papel") == "admin":
        return RedirectResponse(url="/admin", status_code=303)  # o admin é ambiente de administração, não de envio
    meus = lista_docs(0, usuario)
    return templates.TemplateResponse(request, "index.html", {"revistas": carrega_revistas(), "docs": meus[:8], "total_docs": len(meus), "usuario": usuario})


@app.post("/validar")
async def validar(request: Request, arquivo: UploadFile = File(...), revista: str = Form(""), sps: str = Form("1.9"), usuario: dict = Depends(autentica)):
    nome = arquivo.filename or "arquivo"
    if not nome.lower().endswith(".pdf"):
        raise HTTPException(400, "Por enquanto só PDF. O caminho DOCX vem na próxima fase.")
    if confirmacao_pendente(usuario):
        raise HTTPException(403, "Confirme seu e-mail antes de enviar arquivos. Veja o link em Minha conta.")
    conteudo = await arquivo.read()
    if len(conteudo) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Arquivo maior que {MAX_MB} MB.")
    if sps not in ("1.9", "1.10"):
        sps = "1.9"
    doc_id = tempo.agora().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    pasta = DOCS / doc_id
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "original.pdf", "wb") as f:
        f.write(conteudo)
    (pasta / "nome_original.txt").write_text(nome, encoding="utf-8")
    agora = tempo.agora_iso()
    grava_json(pasta / "config.json", {"versao_sps": sps, "revista": revista or None, "criado_por": usuario["nome"],
                                       "criado_por_id": usuario["id"], "etapa": "recebido",
                                       "historico_etapas": [{"etapa": "recebido", "por": usuario["nome"], "em": agora}]})
    try:
        extrai_e_salva(pasta)
        gera_e_valida(pasta)
    except Exception as e:  # noqa: BLE001
        (pasta / "erro.txt").write_text(repr(e), encoding="utf-8")
        raise HTTPException(500, f"Falha ao processar o PDF: {e}")
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def ver_doc(request: Request, doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    r = le_json(pasta / "validacao.json")
    if not r:
        raise HTTPException(404, "Documento sem resultado")
    r["id"] = doc_id
    cfg = le_json(pasta / "config.json", {}) or {}
    return templates.TemplateResponse(request, "resultado.html", {"r": r, "usuario": usuario, "etapas": ETAPAS, "etapa": cfg.get("etapa") or "recebido",
                                                                  "historico": cfg.get("historico_etapas") or [], "criado_por": cfg.get("criado_por")})


@app.post("/doc/{doc_id}/etapa")
async def muda_etapa(request: Request, doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    form = await request.form()
    etapa = str(form.get("etapa") or "")
    if etapa not in ETAPA_ROTULO:
        raise HTTPException(400, "Etapa inválida.")
    cfg = le_json(pasta / "config.json", {}) or {}
    if cfg.get("etapa") != etapa:
        cfg["etapa"] = etapa
        cfg.setdefault("historico_etapas", []).append({"etapa": etapa, "por": usuario["nome"], "em": tempo.agora_iso(),
                                                       "nota": (str(form.get("nota") or "").strip() or None)})
        grava_json(pasta / "config.json", cfg)
    voltar = str(form.get("voltar") or f"/doc/{doc_id}")
    if not voltar.startswith("/"):
        voltar = f"/doc/{doc_id}"
    return RedirectResponse(url=voltar, status_code=303)


@app.get("/doc/{doc_id}/editar", response_class=HTMLResponse)
def editar_form(request: Request, doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    modelo = le_json(pasta / "model.json", {})
    ed = le_json(pasta / "edicoes.json", {}) or {}
    campos = ed.get("campos", {})
    valores = valores_editaveis(modelo)
    valores.update({k: (v or "") for k, v in campos.items()})
    cfg = le_json(pasta / "config.json", {}) or {}
    r = le_json(pasta / "validacao.json", {}) or {}
    try:
        original = (pasta / "resumo.md").read_text(encoding="utf-8")
    except OSError:
        original = ""
    return templates.TemplateResponse(request, "editar.html", {
        "id": doc_id, "m": modelo_efetivo(pasta), "v": valores, "editados": set(campos), "bloq": r.get("campos_bloqueados", {}),
        "bloqueantes": r.get("bloqueantes", []), "revistas": carrega_revistas(), "revista_atual": cfg.get("revista") or r.get("revista") or "",
        "tipos": TIPOS_ARTIGO, "idiomas": IDIOMAS, "original_html": markdown_html(original), "usuario": usuario, "r": r,
    })


@app.post("/doc/{doc_id}/editar")
async def editar_salvar(request: Request, doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    form = await request.form()
    modelo = le_json(pasta / "model.json", {})
    originais = valores_editaveis(modelo)
    ed = le_json(pasta / "edicoes.json", {}) or {"campos": {}}
    campos = dict(ed.get("campos", {}))
    for k, val in form.multi_items():
        val = str(val).strip()
        if k == "acao":
            continue
        if k == "revista":
            cfg = le_json(pasta / "config.json", {}) or {}
            cfg["revista"] = val or None
            grava_json(pasta / "config.json", cfg)
            continue
        if k not in originais and not RE_CAMPO_LISTA.match(k):
            continue
        if val == (originais.get(k) or ""):
            campos.pop(k, None)  # voltou ao valor extraido: sem override
        else:
            campos[k] = val
    ed["campos"] = campos
    ed["atualizado_em"] = tempo.agora_iso()
    ed["por"] = usuario["nome"]
    grava_json(pasta / "edicoes.json", ed)
    gera_e_valida(pasta)
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


@app.post("/doc/{doc_id}/reprocessar")
def reprocessar(doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    extrai_e_salva(pasta)
    gera_e_valida(pasta)
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


@app.get("/doc/{doc_id}/xml")
def baixar_xml(doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    xml = next(pasta.glob("*.xml"), None)
    if not xml:
        raise HTTPException(404)
    return FileResponse(str(xml), media_type="application/xml", filename=xml.name)


@app.get("/doc/{doc_id}/pacote.zip")
def baixar_pacote(doc_id: str, usuario: dict = Depends(autentica)):
    """Pacote SPS minimo: <base>.xml + <base>.pdf (o PDF original renomeado). Imagens entram quando o extrator as gerar."""
    pasta = _pasta(doc_id, usuario)
    xml = next(pasta.glob("*.xml"), None)
    if not xml:
        raise HTTPException(404)
    base = xml.stem
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(str(xml), f"{base}/{base}.xml")
        pdf = pasta / "original.pdf"
        if pdf.exists():
            z.write(str(pdf), f"{base}/{base}.pdf")
        for img in sorted((pasta / "pacote").glob("*")) if (pasta / "pacote").exists() else []:
            z.write(str(img), f"{base}/{img.name}")
    buf.seek(0)
    return Response(buf.read(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{base}.zip"'})


@app.get("/doc/{doc_id}/img/{nome}")
def imagem(doc_id: str, nome: str, usuario: dict = Depends(autentica)):
    if not re.fullmatch(r"(fig|eq|tab)\d{2}\.[a-z0-9]{2,5}", nome):
        raise HTTPException(404)
    caminho = _pasta(doc_id, usuario) / "imagens" / nome
    if not caminho.exists():
        raise HTTPException(404)
    return FileResponse(str(caminho))


@app.get("/doc/{doc_id}/modelo.json")
def baixar_modelo(doc_id: str, usuario: dict = Depends(autentica)):
    return FileResponse(str(_pasta(doc_id, usuario) / "model.json"), media_type="application/json", filename=f"{doc_id}-modelo.json")


@app.get("/doc/{doc_id}/validacao.json")
def baixar_validacao(doc_id: str, usuario: dict = Depends(autentica)):
    return FileResponse(str(_pasta(doc_id, usuario) / "validacao.json"), media_type="application/json")


@app.get("/doc/{doc_id}/resumo.md", response_class=PlainTextResponse)
def ver_resumo(doc_id: str, usuario: dict = Depends(autentica)):
    return (_pasta(doc_id, usuario) / "resumo.md").read_text(encoding="utf-8")


@app.get("/revistas", response_class=HTMLResponse)
def revistas(request: Request, usuario: dict = Depends(autentica), mensagem: str = ""):
    return templates.TemplateResponse(request, "revistas.html", {"revistas": carrega_revistas(), "usuario": usuario, "mensagem": mensagem})


def _form_revista(request: Request, usuario: dict, v: dict, erros: dict, nova: bool, docs_da_revista=None, busca=None):
    return templates.TemplateResponse(request, "revista_form.html", {"usuario": usuario, "v": v, "erros": erros, "nova": nova, "licencas": LICENCAS,
                                                                     "areas": AREAS, "estilos": ESTILOS_REF, "busca": busca,
                                                                     "docs_da_revista": docs_da_revista}, status_code=400 if erros else 200)


@app.get("/revistas/nova", response_class=HTMLResponse)
def revista_nova(request: Request, usuario: dict = Depends(exige_admin), issn: str = ""):
    """Formulário em branco ou pré-preenchido com o que a SciELO sabe sobre o ISSN (o admin confere antes de salvar)."""
    v = {"licenca_url": LICENCAS[0][0], "modo_publicacao": "continua"}
    busca = None
    if issn.strip():
        busca = scielo.busca_por_issn(issn)
        v.update(busca.get("dados") or {})
        v.setdefault("issn_epub", scielo.normaliza_issn(issn))
    return _form_revista(request, usuario, v, {}, True, busca=busca)


@app.post("/revistas/nova", response_class=HTMLResponse)
async def revista_criar(request: Request, usuario: dict = Depends(exige_admin)):
    form = dict((await request.form()).items())
    lista = carrega_revistas()
    dados, erros = valida_revista(form, lista)
    if erros:
        return _form_revista(request, usuario, {**form, "na_scielo": dados["na_scielo"]}, erros, True)
    lista.append(dados)
    grava_revistas(lista)
    return RedirectResponse(url="/revistas?mensagem=" + urllib.parse.quote(f"Revista {dados['acronimo']} cadastrada."), status_code=303)


def _revista_ou_404(acronimo: str):
    lista = carrega_revistas()
    rev = next((r for r in lista if r["acronimo"] == acronimo), None)
    if not rev:
        raise HTTPException(404, "Revista não encontrada")
    return lista, rev


@app.get("/revistas/{acronimo}", response_class=HTMLResponse)
def revista_editar(request: Request, acronimo: str, usuario: dict = Depends(exige_admin)):
    _, rev = _revista_ou_404(acronimo)
    n_docs = sum(1 for d in lista_docs(0) if d.get("revista") == acronimo)  # admin: conta de todos
    return _form_revista(request, usuario, rev, {}, False, n_docs)


@app.post("/revistas/{acronimo}", response_class=HTMLResponse)
async def revista_salvar(request: Request, acronimo: str, usuario: dict = Depends(exige_admin)):
    lista, rev = _revista_ou_404(acronimo)
    form = dict((await request.form()).items())
    dados, erros = valida_revista(form, lista, acronimo_atual=acronimo)
    if erros:
        return _form_revista(request, usuario, {**form, "na_scielo": dados["na_scielo"], "acronimo": form.get("acronimo") or acronimo}, erros, False)
    lista[lista.index(rev)] = dados
    grava_revistas(lista)
    return RedirectResponse(url="/revistas?mensagem=" + urllib.parse.quote(f"Revista {dados['acronimo']} atualizada."), status_code=303)


@app.post("/revistas/{acronimo}/remover")
def revista_remover(acronimo: str, usuario: dict = Depends(exige_admin)):
    lista, rev = _revista_ou_404(acronimo)
    lista.remove(rev)
    grava_revistas(lista)
    return RedirectResponse(url="/revistas?mensagem=" + urllib.parse.quote(f"Revista {acronimo} removida do cadastro."), status_code=303)


# ---------------------------------------------------------------- painel

@app.get("/painel", response_class=HTMLResponse)
def painel(request: Request, usuario: dict = Depends(autentica), revista: str = "", etapa: str = "", situacao: str = ""):
    if usuario.get("papel") == "admin":
        return RedirectResponse(url="/admin/documentos", status_code=303)
    docs = lista_docs(0, usuario)
    if revista:
        docs = [d for d in docs if d.get("revista") == revista]
    if etapa:
        docs = [d for d in docs if d.get("etapa") == etapa]
    if situacao == "pronto":
        docs = [d for d in docs if d.get("pronto")]
    elif situacao == "bloqueado":
        docs = [d for d in docs if not d.get("pronto")]
    filtros = {"revista": revista, "etapa": etapa, "situacao": situacao}
    query = "?" + urllib.parse.urlencode({k: v for k, v in filtros.items() if v}) if any(filtros.values()) else ""
    return templates.TemplateResponse(request, "painel.html", {"docs": docs, "revistas": carrega_revistas(), "etapas": ETAPAS, "filtros": filtros,
                                                               "filtro_ativo": any(filtros.values()), "query": query, "usuario": usuario,
                                                               "total_docs": len(lista_docs(0, usuario))})


# ---------------------------------------------------------------- contas

@app.get("/entrar", response_class=HTMLResponse)
def entrar_form(request: Request, proximo: str = "/"):
    CONTAS.garante_admin(os.environ.get("APP_SENHA"))
    if CONTAS.le_sessao(request.cookies.get(COOKIE)):
        return RedirectResponse(url=proximo if proximo.startswith("/") else "/", status_code=303)
    aviso = None if CONTAS.lista() else "Nenhuma conta cadastrada e APP_SENHA não definida: o app está em modo local, sem login."
    return templates.TemplateResponse(request, "entrar.html", {"proximo": proximo, "usuario": None, "aviso": aviso})


@app.post("/entrar", response_class=HTMLResponse)
async def entrar(request: Request):
    form = await request.form()
    email, senha, proximo = str(form.get("email") or ""), str(form.get("senha") or ""), str(form.get("proximo") or "/")
    CONTAS.garante_admin(os.environ.get("APP_SENHA"))
    u = CONTAS.autentica(email, senha)
    if not u:
        return templates.TemplateResponse(request, "entrar.html", {"proximo": proximo, "usuario": None, "email": email, "erro": "E-mail ou senha não conferem."}, status_code=401)
    ip, navegador = de_onde(request)
    CONTAS.registra_login(u["id"], ip, navegador)
    resp = RedirectResponse(url=proximo if proximo.startswith("/") else "/", status_code=303)
    resp.set_cookie(COOKIE, CONTAS.assina_sessao(u["id"]), httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=12 * 3600, path="/")
    return resp


@app.get("/registrar", response_class=HTMLResponse)
def registrar_form(request: Request):
    CONTAS.garante_admin(os.environ.get("APP_SENHA"))
    if CONTAS.le_sessao(request.cookies.get(COOKIE)):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "registrar.html", {"usuario": None})


@app.post("/registrar", response_class=HTMLResponse)
async def registrar(request: Request):
    form = dict((await request.form()).items())
    CONTAS.garante_admin(os.environ.get("APP_SENHA"))
    if (form.get("senha") or "") != (form.get("senha2") or ""):
        return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "erro": "As duas senhas não são iguais.", "form": form}, status_code=400)
    try:
        u = CONTAS.cria(form.get("email", ""), form.get("nome", ""), form.get("senha", ""), "cliente")
    except ValueError as e:
        return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "erro": str(e), "form": form}, status_code=400)
    ip, navegador = de_onde(request)
    CONTAS.registra_login(u["id"], ip, navegador)
    try:
        envia_confirmacao(u, por="registro", request=request)
    except Exception:  # noqa: BLE001  (falha de e-mail não pode impedir o cadastro)
        pass
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(COOKIE, CONTAS.assina_sessao(u["id"]), httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=12 * 3600, path="/")
    return resp


@app.get("/conta", response_class=HTMLResponse)
def conta(request: Request, usuario: dict = Depends(autentica), mensagem: str = "", erro: str = ""):
    meus = lista_docs(0, usuario)
    completo = CONTAS.por_id(usuario["id"]) or usuario
    return templates.TemplateResponse(request, "conta.html", {"usuario": completo, "mensagem": mensagem, "erro": erro,
                                                              "docs": meus, "total_docs": len(meus),
                                                              "exige_confirmacao": CORREIO.config().get("exigir_confirmacao"),
                                                              "pendente": confirmacao_pendente(completo)})


@app.post("/conta/senha")
async def conta_senha(request: Request, usuario: dict = Depends(autentica)):
    form = await request.form()
    atual, nova, nova2 = str(form.get("atual") or ""), str(form.get("nova") or ""), str(form.get("nova2") or "")
    if usuario["id"] in ("local", "api"):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Esta sessão não tem conta própria."), status_code=303)
    if not CONTAS.autentica(usuario["email"], atual):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("A senha atual não confere."), status_code=303)
    if nova != nova2:
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("As duas senhas novas não são iguais."), status_code=303)
    try:
        CONTAS.define_senha(usuario["id"], nova)
    except ValueError as e:
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/conta?mensagem=" + urllib.parse.quote("Senha trocada."), status_code=303)


@app.post("/conta/dados")
async def conta_dados(request: Request, usuario: dict = Depends(autentica)):
    form = await request.form()
    if usuario["id"] in ("local", "api"):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Esta sessão não tem conta própria."), status_code=303)
    try:
        CONTAS.define_dados(usuario["id"], str(form.get("nome") or ""), str(form.get("email") or ""))
    except ValueError as e:
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/conta?mensagem=" + urllib.parse.quote("Dados atualizados."), status_code=303)


@app.get("/confirmar", response_class=HTMLResponse)
def confirmar(request: Request, token: str = ""):
    u = CONTAS.confirma_por_token(token)
    return templates.TemplateResponse(request, "confirmar.html", {"usuario": None, "confirmado": bool(u), "nome": u["nome"] if u else ""},
                                      status_code=200 if u else 400)


@app.post("/conta/confirmar")
def conta_reenvia_confirmacao(request: Request, usuario: dict = Depends(autentica)):
    if usuario["id"] in ("local", "api"):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Esta sessão não tem conta própria."), status_code=303)
    m = envia_confirmacao(usuario, por=usuario["nome"], request=request)
    if not m:
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote(
            "O envio de e-mail ainda não está configurado no sistema. Peça a um administrador."), status_code=303)
    if m.get("caixa") != "enviados":
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Não foi possível enviar: " + (m.get("erro") or "")), status_code=303)
    return RedirectResponse(url="/conta?mensagem=" + urllib.parse.quote("Enviamos um novo e-mail de confirmação."), status_code=303)


@app.post("/conta/foto")
async def conta_foto(request: Request, foto: UploadFile = File(...), usuario: dict = Depends(autentica)):
    """Foto de perfil: imagem pequena, convertida para PNG quadrado de 256 px."""
    if usuario["id"] in ("local", "api"):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Esta sessão não tem conta própria."), status_code=303)
    dados = await foto.read()
    if len(dados) > 5 * 1024 * 1024:
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("A imagem precisa ter menos de 5 MB."), status_code=303)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(dados)) as im:
            im = im.convert("RGB")
            lado = min(im.size)
            esq, topo = (im.width - lado) // 2, (im.height - lado) // 2
            im = im.crop((esq, topo, esq + lado, topo + lado)).resize((256, 256))
            nome = f"{usuario['id']}.png"
            im.save(AVATARES / nome, format="PNG")
    except Exception:  # noqa: BLE001
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Não consegui ler essa imagem. Use PNG ou JPG."), status_code=303)
    CONTAS.define_avatar(usuario["id"], nome)
    return RedirectResponse(url="/conta?mensagem=" + urllib.parse.quote("Foto atualizada."), status_code=303)


@app.post("/conta/foto/remover")
def conta_foto_remover(usuario: dict = Depends(autentica)):
    if usuario["id"] not in ("local", "api"):
        arq = AVATARES / f"{usuario['id']}.png"
        if arq.exists():
            arq.unlink()
        CONTAS.define_avatar(usuario["id"], None)
    return RedirectResponse(url="/conta?mensagem=" + urllib.parse.quote("Foto removida."), status_code=303)


@app.get("/avatar/{nome}")
def avatar(nome: str, usuario: dict = Depends(autentica)):
    if not re.fullmatch(r"[0-9a-f]{6,32}\.png", nome):
        raise HTTPException(404)
    caminho = AVATARES / nome
    if not caminho.exists():
        raise HTTPException(404)
    return FileResponse(str(caminho), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------- correio (administração)

@app.get("/admin/correio", response_class=HTMLResponse)
def correio_caixa(request: Request, usuario: dict = Depends(exige_admin), caixa: str = "entrada", busca: str = "",
                  mensagem: str = "", erro: str = "", aberta: str = ""):
    if caixa not in ROTULO_CAIXA:
        caixa = "entrada"
    msgs = CORREIO.lista(caixa, busca)
    atual = CORREIO.por_id(aberta) if aberta else None
    if atual and not atual.get("lida"):
        CORREIO.marca_lida(atual["id"])
        atual = CORREIO.por_id(aberta)
    return templates.TemplateResponse(request, "correio.html", {
        "usuario": usuario, "caixa": caixa, "mensagens": msgs, "contagens": CORREIO.contagens(),
        "aberta": atual, "busca": busca, "mensagem": mensagem, "erro": erro, "cfg": CORREIO.config_publica()})


@app.post("/admin/correio/nova")
async def correio_nova(request: Request, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    acao = str(form.get("acao") or "enviar")
    try:
        m = CORREIO.cria(str(form.get("para") or ""), str(form.get("assunto") or ""), str(form.get("texto") or ""),
                         caixa="rascunhos" if acao == "rascunho" else "saida", por=usuario["nome"])
    except ValueError as e:
        return RedirectResponse(url="/admin/correio?caixa=rascunhos&erro=" + urllib.parse.quote(str(e)), status_code=303)
    if acao == "rascunho":
        return RedirectResponse(url="/admin/correio?caixa=rascunhos&mensagem=" + urllib.parse.quote("Rascunho salvo."), status_code=303)
    r = CORREIO.envia(m["id"], por=usuario["nome"])
    if r.get("caixa") == "enviados":
        return RedirectResponse(url="/admin/correio?caixa=enviados&mensagem=" + urllib.parse.quote("Mensagem enviada."), status_code=303)
    return RedirectResponse(url="/admin/correio?caixa=saida&erro=" + urllib.parse.quote(r.get("erro") or "Não foi possível enviar."), status_code=303)


@app.post("/admin/correio/{mid}/enviar")
def correio_envia(mid: str, usuario: dict = Depends(exige_admin)):
    r = CORREIO.envia(mid, por=usuario["nome"])
    if r.get("caixa") == "enviados":
        return RedirectResponse(url="/admin/correio?caixa=enviados&mensagem=" + urllib.parse.quote("Mensagem enviada."), status_code=303)
    return RedirectResponse(url="/admin/correio?caixa=saida&erro=" + urllib.parse.quote(r.get("erro") or "Não foi possível enviar."), status_code=303)


@app.post("/admin/correio/{mid}/mover")
async def correio_move(request: Request, mid: str, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    destino = str(form.get("caixa") or "lixeira")
    try:
        CORREIO.move(mid, destino)
    except ValueError as e:
        return RedirectResponse(url="/admin/correio?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url=f"/admin/correio?caixa={destino}&mensagem=" + urllib.parse.quote("Mensagem movida."), status_code=303)


@app.post("/admin/correio/{mid}/apagar")
def correio_apaga(mid: str, usuario: dict = Depends(exige_admin)):
    CORREIO.apaga(mid)
    return RedirectResponse(url="/admin/correio?caixa=lixeira&mensagem=" + urllib.parse.quote("Mensagem apagada."), status_code=303)


@app.post("/admin/correio/reenviar")
def correio_reenvia(usuario: dict = Depends(exige_admin)):
    n = CORREIO.reenvia_pendentes(por=usuario["nome"])
    return RedirectResponse(url="/admin/correio?caixa=enviados&mensagem=" + urllib.parse.quote(f"{n} mensagem(ns) enviada(s)."), status_code=303)


# ---------------------------------------------------------------- configurações do sistema

@app.get("/admin/config", response_class=HTMLResponse)
def config_sistema(request: Request, usuario: dict = Depends(exige_admin), mensagem: str = "", erro: str = ""):
    c = CORREIO.config()
    base = (c.get("url_base") or "").rstrip("/") or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(request, "config.html", {
        "usuario": usuario, "cfg": CORREIO.config_publica(), "mensagem": mensagem, "erro": erro,
        "webhook": f"{base}/webhook/resend?k={c.get('webhook_segredo')}"})


@app.post("/admin/config")
async def config_salva(request: Request, usuario: dict = Depends(exige_admin)):
    form = dict((await request.form()).items())
    try:
        CORREIO.salva_config({**form, "exigir_confirmacao": form.get("exigir_confirmacao") == "on",
                              "remover_chave": form.get("remover_chave") == "on"})
    except ValueError as e:
        return RedirectResponse(url="/admin/config?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/config?mensagem=" + urllib.parse.quote("Configuração salva."), status_code=303)


@app.post("/admin/config/testar")
async def config_testa(request: Request, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    destino = str(form.get("destino") or usuario.get("email") or "")
    m = CORREIO.envia_novo(destino, "Teste de envio do xmljats",
                           "Se você recebeu esta mensagem, o envio pelo Resend está funcionando.",
                           "<p>Se você recebeu esta mensagem, o envio pelo <b>Resend</b> está funcionando.</p>",
                           tipo="teste", por=usuario["nome"])
    if m.get("caixa") == "enviados":
        return RedirectResponse(url="/admin/config?mensagem=" + urllib.parse.quote(f"Mensagem de teste enviada para {destino}."), status_code=303)
    return RedirectResponse(url="/admin/config?erro=" + urllib.parse.quote("Falhou: " + (m.get("erro") or "sem detalhe")), status_code=303)


@app.post("/webhook/resend")
async def webhook_resend(request: Request):
    """Eventos do Resend (entregue, aberto, devolvido) e e-mails recebidos. Protegido pelo segredo da configuração."""
    cfg = CORREIO.config()
    segredo = cfg.get("webhook_segredo")
    enviado = request.query_params.get("k") or request.headers.get("x-webhook-segredo")
    if not segredo or not enviado or not secrets.compare_digest(str(enviado), str(segredo)):
        raise HTTPException(403, "Segredo do webhook não confere.")
    try:
        dados = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Corpo inválido.")
    return {"ok": True, "resultado": CORREIO.registra_evento(dados)}


@app.get("/ajuda", response_class=HTMLResponse)
def ajuda(request: Request, usuario: dict = Depends(autentica)):
    return templates.TemplateResponse(request, "ajuda.html", {"usuario": usuario, "etapas": ETAPAS})


# ---------------------------------------------------------------- administração

def _metricas(docs):
    from collections import Counter
    por_revista, por_etapa, por_usuario, por_dia = Counter(), Counter(), Counter(), Counter()
    bloq = Counter()
    for d in docs:
        por_revista[d.get("revista") or "sem revista"] += 1
        por_etapa[d.get("etapa") or "recebido"] += 1
        por_usuario[d.get("criado_por_id") or "—"] += 1
        quando = tempo.le(d.get("criado_em"))
        if quando:
            por_dia[quando.strftime("%Y-%m-%d")] += 1
        for b in d.get("bloqueantes", []):
            for cod in re.findall(r"\(([A-Z]\d{2})\)", b):
                bloq[cod] += 1
    return por_revista, por_etapa, bloq, por_usuario, por_dia


def _uso_por_usuario(docs, usuarios):
    """Uma linha por conta: validações, prontos, última validação e atividade (online, último acesso, IP)."""
    from collections import Counter
    val, prontos, ultima = Counter(), Counter(), {}
    for d in docs:
        uid = d.get("criado_por_id") or ""
        val[uid] += 1
        if d.get("pronto"):
            prontos[uid] += 1
        quando = d.get("criado_em") or ""
        if quando > ultima.get(uid, ""):
            ultima[uid] = quando
    linhas = []
    for u in usuarios:
        at = u.get("atividade") or {}
        linhas.append({**u, "validacoes": val.get(u["id"], 0), "prontos": prontos.get(u["id"], 0),
                       "ultima_validacao": ultima.get(u["id"]), "ultimo_acesso": at.get("ultimo_acesso"),
                       "ultimo_login": at.get("ultimo_login"), "ip": at.get("ip"), "navegador": at.get("navegador"),
                       "acessos": at.get("acessos") or 0, "logins": at.get("logins") or 0})
    linhas.sort(key=lambda x: (x["ultimo_acesso"] or "", x["validacoes"]), reverse=True)
    return linhas


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, usuario: dict = Depends(exige_admin), dono: str = "", desde: str = ""):
    docs = lista_docs(0)
    usuarios = CONTAS.lista()
    if dono:
        docs = [d for d in docs if (d.get("criado_por_id") or "") == dono]
    if desde:
        docs = [d for d in docs if (d.get("criado_em") or "") >= desde]
    por_revista, por_etapa, bloq, por_usuario, por_dia = _metricas(docs)
    prontos = [d for d in docs if d.get("pronto")]
    uso = _uso_por_usuario(docs, usuarios)
    dias = sorted(por_dia.items())[-14:]
    return templates.TemplateResponse(request, "admin.html", {
        "usuario": usuario, "docs": docs, "total": len(docs), "prontos": len(prontos),
        "por_revista": por_revista.most_common(), "por_etapa": por_etapa, "etapas": ETAPAS,
        "bloqueantes": bloq.most_common(8), "usuarios": usuarios, "revistas": carrega_revistas(),
        "por_papel": {p: sum(1 for u in usuarios if u["papel"] == p) for p in PAPEIS},
        "recentes": docs[:8], "uso": uso, "dias": dias, "filtros": {"dono": dono, "desde": desde},
        "filtro_ativo": bool(dono or desde),
        "online": sum(1 for x in uso if tempo.online(x["ultimo_acesso"])),
    })


@app.get("/admin/documentos", response_class=HTMLResponse)
def admin_documentos(request: Request, usuario: dict = Depends(exige_admin), revista: str = "", etapa: str = "",
                     situacao: str = "", dono: str = ""):
    docs = lista_docs(0)
    if revista:
        docs = [d for d in docs if d.get("revista") == revista]
    if etapa:
        docs = [d for d in docs if d.get("etapa") == etapa]
    if situacao == "pronto":
        docs = [d for d in docs if d.get("pronto")]
    elif situacao == "bloqueado":
        docs = [d for d in docs if not d.get("pronto")]
    if dono:
        docs = [d for d in docs if (d.get("criado_por_id") or "") == dono]
    filtros = {"revista": revista, "etapa": etapa, "situacao": situacao, "dono": dono}
    query = "?" + urllib.parse.urlencode({k: v for k, v in filtros.items() if v}) if any(filtros.values()) else ""
    return templates.TemplateResponse(request, "admin_docs.html", {
        "docs": docs, "revistas": carrega_revistas(), "etapas": ETAPAS, "filtros": filtros, "usuarios": CONTAS.lista(),
        "filtro_ativo": any(filtros.values()), "query": query, "usuario": usuario})


@app.post("/sair")
def sair():
    resp = RedirectResponse(url="/entrar", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/usuarios", response_class=HTMLResponse)
def usuarios(request: Request, usuario: dict = Depends(exige_admin), mensagem: str = "", erro: str = ""):
    uso = _uso_por_usuario(lista_docs(0), CONTAS.lista())
    return templates.TemplateResponse(request, "usuarios.html", {"usuarios": uso, "usuario": usuario, "mensagem": mensagem,
                                                                 "erro": erro, "form": None, "papeis": PAPEIS})


@app.post("/usuarios/{uid}/dados")
async def usuario_dados(request: Request, uid: str, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    try:
        CONTAS.define_dados(uid, str(form.get("nome") or ""), str(form.get("email") or ""))
    except ValueError as e:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote("Dados do usuário atualizados."), status_code=303)


@app.post("/usuarios", response_class=HTMLResponse)
async def usuario_criar(request: Request, usuario: dict = Depends(exige_admin)):
    form = dict((await request.form()).items())
    try:
        u = CONTAS.cria(form.get("email", ""), form.get("nome", ""), form.get("senha", ""), form.get("papel", "operador"))
    except ValueError as e:
        return templates.TemplateResponse(request, "usuarios.html", {"usuarios": CONTAS.lista(), "usuario": usuario, "erro": str(e), "form": form}, status_code=400)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote(f"Usuário {u['nome']} criado."), status_code=303)


@app.post("/usuarios/{uid}/senha")
async def usuario_senha(request: Request, uid: str, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    try:
        CONTAS.define_senha(uid, str(form.get("senha") or ""))
    except ValueError as e:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote("Senha trocada."), status_code=303)


@app.post("/usuarios/{uid}/papel")
async def usuario_papel(request: Request, uid: str, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    if uid == usuario["id"]:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote("Você não pode mudar o próprio papel."), status_code=303)
    try:
        CONTAS.define_papel(uid, str(form.get("papel") or ""))
    except ValueError as e:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote("Papel atualizado."), status_code=303)


@app.post("/usuarios/{uid}/remover")
def usuario_remover(uid: str, usuario: dict = Depends(exige_admin)):
    if uid == usuario["id"]:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote("Você não pode remover a própria conta."), status_code=303)
    try:
        CONTAS.remove(uid)
    except ValueError as e:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote("Usuário removido."), status_code=303)
