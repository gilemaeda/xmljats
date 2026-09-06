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
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "poc"))
sys.path.insert(0, str(RAIZ / "app"))

from contas import COOKIE, PAPEIS, ROTULO_PAPEL, Contas  # noqa: E402  (app/contas.py)
import tempo  # noqa: E402  (app/tempo.py: tudo no horário de Brasília)
from correio import CAIXAS, RE_EMAIL_SIMPLES, ROTULO_CAIXA, Correio, corpo_confirmacao, token_confirmacao  # noqa: E402
import scielo  # noqa: E402  (app/scielo.py: consulta de periódico por ISSN na SciELO)
import issn as issn_api  # noqa: E402  (app/issn.py: consulta em cascata — ISSN.org, SciELO, DOAJ, Crossref, OpenAlex)
import visual  # noqa: E402  (app/visual.py: páginas do PDF renderizadas + camada de texto para o revisar)
import obrigatorios  # noqa: E402  (app/obrigatorios.py: o que a SPS exige e o PDF não traz)
import entrega  # noqa: E402  (app/entrega.py: conferência do pacote, FTP da SciELO e e-mails obrigatórios)
import enriquece  # noqa: E402  (app/enriquece.py: completa o que falta pelo DOI no Crossref e confere o ORCID)
import novidades  # noqa: E402  (app/novidades.py: o que mudou em cada versão, filtrado por papel, e quem já viu)
import fila  # noqa: E402  (app/fila.py: envio em lote entra numa fila; um trabalhador processa um arquivo por vez)
import organizacoes  # noqa: E402  (app/organizacoes.py: editora/instituição que agrupa contas; membros veem os mesmos documentos)
import lotes  # noqa: E402  (app/lotes.py: até 5 artigos prontos da mesma revista/número num só pacote de entrega)

import extrair as cli  # noqa: E402  (poc/extrair.py)
import gerar_xml as gx  # noqa: E402  (poc/gerar_xml.py)
from extrator import xml_jats  # noqa: E402
from extrator import ocr as ocr_mod  # noqa: E402  (poc/extrator/ocr.py: Tesseract via PyMuPDF para PDF escaneado)
from extrator.util import RE_ORCID, orcid_valido  # noqa: E402

DATA = Path(os.environ.get("XMLJATS_DATA", RAIZ / "data"))
DOCS = DATA / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
MAX_LOTE = int(os.environ.get("XMLJATS_MAX_LOTE", "20"))  # arquivos por envio; entram na fila e saem um a um
VERSAO_APP = "0.26.1"
if novidades.ATUAL != VERSAO_APP:  # as notas de versão saem junto com a versão: as duas têm de andar juntas
    raise RuntimeError(f"app/novidades.py está em {novidades.ATUAL}, mas VERSAO_APP é {VERSAO_APP}")
CONTAS = Contas(DATA)
CORREIO = Correio(DATA)
ORGS = organizacoes.Organizacoes(DATA / "organizacoes.json")
AVATARES = DATA / "avatares"
AVATARES.mkdir(parents=True, exist_ok=True)

# etapas do artigo no fluxo de entrega a SciELO (anotadas a mao no painel)
# papel "cliente" vê só os próprios documentos; "operador" vê todos; "admin" também administra
# formatos de entrada aceitos: o DOCX diz o que o PDF obriga a adivinhar (seções, tabelas, fórmulas)
FORMATOS = {".pdf", ".docx"}
# Da quarta em diante são os status que a SciELO usa no título dos e-mails do fluxo de publicação (SPS 1.10):
# Entrega, Entrega Confirmada, Pré-QA (Correção), QA (Correção), QA Finalizado.
ETAPAS = [("recebido", "Recebido"), ("em_revisao", "Em revisão"), ("pronto", "Pronto para entrega"),
          ("entregue", "Entregue à SciELO"), ("entrega_confirmada", "Entrega confirmada"), ("pre_qa", "Pré-QA"), ("qa", "QA"),
          ("correcao_pedida", "Correção pedida pela SciELO"), ("qa_finalizado", "QA finalizado"), ("publicado", "Publicado")]
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
# CSS e JS que o packtools empacota para a pre-visualizacao ficar com a cara da SciELO sem depender do site dela
try:
    import packtools as _pt

    _ESTATICO_PREVIA = Path(_pt.__file__).parent / "catalogs" / "htmlgenerator" / "static"
    if _ESTATICO_PREVIA.is_dir():
        app.mount("/previa-estatico", StaticFiles(directory=str(_ESTATICO_PREVIA)), name="previa-estatico")
except Exception:  # noqa: BLE001
    _ESTATICO_PREVIA = None
templates = Jinja2Templates(directory=str(RAIZ / "app" / "templates"))
templates.env.globals["versao"] = VERSAO_APP
templates.env.globals["novidades_pendentes"] = novidades.pendentes  # o que esta pessoa ainda não viu (já filtrado por papel)
templates.env.globals["novidades_conta"] = novidades.conta_itens
templates.env.globals["organizacoes_lista"] = ORGS.lista
templates.env.globals["organizacao_de"] = lambda u: ORGS.por_id((u or {}).get("organizacao"))
templates.env.globals["organizacao_nome"] = ORGS.nome_de
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
CAMPOS_SIMPLES = ("heading", "tipo_artigo", "idioma", "volume", "numero", "ano", "elocation", "order", "doi",
                  "licenca", "financiamento_texto", "paginas_total") + tuple("dec_" + k for k, _, _ in xml_jats.DECLARACOES) + ("dec_dados_situacao",)
# grupos editaveis em lista: o indice pode passar do que foi extraido, e ai o item e criado a mao
GRUPOS_LISTA = {"titulo": "titulos", "autor": "autores", "aff": "afiliacoes", "resumo": "resumos",
                "secao": "secoes", "tabela": "tabelas", "figura": "figuras", "equacao": "equacoes",
                "quadro": "quadros", "dialogo": "dialogos", "fomento": "financiamentos"}
RE_CAMPO_LISTA = re.compile(r"^(" + "|".join(GRUPOS_LISTA) + r")_(\d+)_(\w+)$")
# quantos itens em branco a tela oferece para criar a mao, por grupo
VAGAS_NOVAS = 1


# ---------------------------------------------------------------- utilidades

LOCAL = {"id": "local", "nome": "local", "email": "local", "papel": "admin"}


def de_onde(request: Request):
    """IP real (o app roda atrás do Traefik, então o IP do cliente vem no cabeçalho) e navegador."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else None)
    return ip, request.headers.get("user-agent")


# ---------------------------------------------------------------- freio de tentativas (login e registro)
# Em memória, por processo: o app roda num único processo do uvicorn, e reiniciar zera o freio, o que é aceitável.
FREIO_LIMITE = 10          # falhas de login por IP ou por e-mail dentro da janela...
FREIO_JANELA_S = 15 * 60   # ...e o tempo de espera depois disso
FREIO_REGISTROS = 5        # contas novas por IP dentro da mesma janela
_freio: dict = {}


def freio_conta(chave: str, limite: int) -> Optional[int]:
    """Quantos segundos faltam para a chave poder tentar de novo, ou None se ainda pode."""
    agora = time.time()
    fila = [t for t in _freio.get(chave, []) if agora - t < FREIO_JANELA_S]
    _freio[chave] = fila
    if len(fila) >= limite:
        return int(FREIO_JANELA_S - (agora - fila[0])) + 1
    return None


def freio_marca(chave: str) -> None:
    _freio.setdefault(chave, []).append(time.time())


def freio_limpa(chave: str) -> None:
    _freio.pop(chave, None)


def freio_minutos(segundos: int) -> str:
    m = max(1, (segundos + 59) // 60)
    return f"{m} minuto" + ("s" if m > 1 else "")


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
    for tentativa in range(3):
        try:
            with io.open(caminho, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            # outra thread (a fila) pode estar gravando o arquivo neste instante: espera um pouco e lê de novo
            if tentativa == 2:
                raise
            time.sleep(0.05)
    return padrao


def grava_json(caminho: Path, obj):
    """Grava num arquivo temporário ao lado e troca pelo definitivo: quem lê nunca vê JSON pela metade
    (a fila escreve o config.json do documento enquanto a tela o lê). No Windows a troca falha se alguém
    está com o arquivo aberto naquele instante; aí tenta de novo por até meio segundo."""
    caminho = Path(caminho)
    provisorio = caminho.with_name(caminho.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    with io.open(provisorio, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    for tentativa in range(20):
        try:
            os.replace(provisorio, caminho)
            return
        except PermissionError:
            if tentativa == 19:
                provisorio.unlink(missing_ok=True)
                raise
            time.sleep(0.025)


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


def revistas_para(usuario: dict) -> list:
    """Revistas que esta pessoa pode ver: as públicas (sem organização nem dono), as da organização dela e as que
    ela mesma cadastrou. Operador e administrador veem todas."""
    todas = carrega_revistas()
    if (usuario or {}).get("papel") in ("admin", "operador"):
        return todas
    org = (usuario or {}).get("organizacao")
    uid = (usuario or {}).get("id")
    return [r for r in todas if (not r.get("organizacao") and not r.get("dono"))
            or (org and r.get("organizacao") == org) or (uid and r.get("dono") == uid)]


def _marca_dona(dados: dict, usuario: dict) -> None:
    """Revista cadastrada por cliente fica da organização dele (ou só dele, se não está em nenhuma);
    cadastrada por operador ou administrador fica pública."""
    if (usuario or {}).get("papel") in ("admin", "operador"):
        return
    if usuario.get("organizacao"):
        dados["organizacao"] = usuario["organizacao"]
    else:
        dados["dono"] = usuario.get("id")


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
                                                   "area", "estilo_referencias", "idioma_padrao",
                                                   "editor_chefe", "editor_lattes", "editor_orcid", "email_editorial")}
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
    if d["editor_lattes"] and not re.match(r"^https?://(lattes\.cnpq\.br|buscatextual)", d["editor_lattes"]):
        erros["editor_lattes"] = "O currículo Lattes começa com http://lattes.cnpq.br/ seguido do número."
    if d["editor_orcid"]:
        from extrator.util import orcid_valido  # noqa: WPS433
        so = RE_ORCID.search(d["editor_orcid"])
        if not so or not orcid_valido(so.group(1)):
            erros["editor_orcid"] = "ORCID inválido: use 0000-0000-0000-0000 com dígito verificador correto."
        else:
            d["editor_orcid"] = so.group(1).upper()
    if d["email_editorial"] and not RE_EMAIL_SIMPLES.match(d["email_editorial"]):
        erros["email_editorial"] = "E-mail da equipe editorial inválido."
    if d["idioma_padrao"] and d["idioma_padrao"] not in IDIOMAS:
        erros["idioma_padrao"] = "Use o código de duas letras: " + ", ".join(IDIOMAS) + "."
    for k in ("doi_prefixo", "secao_padrao", "site", "_fonte", "area", "estilo_referencias", "idioma_padrao",
              "editor_chefe", "editor_lattes", "editor_orcid", "email_editorial"):
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
    if (doc.get("criado_por_id") or doc.get("criado_por")) in (usuario.get("id"), usuario.get("nome")):
        return True
    org = usuario.get("organizacao")  # colegas da mesma organização veem os documentos dela
    return bool(org) and doc.get("organizacao") == org


def marca_aberto(pasta: Path, usuario: dict) -> None:
    """Guarda quando e por quem o documento foi aberto pela ultima vez. Serve para achar de novo o que
    se estava mexendo, que e como o trabalho realmente acontece: abre, sai, volta."""
    cfg = le_json(pasta / "config.json", {}) or {}
    agora = tempo.agora_iso()
    # nao reescreve o arquivo a cada clique dentro do mesmo minuto
    anterior = cfg.get("aberto_em") or ""
    if anterior[:16] == agora[:16] and cfg.get("aberto_por") == usuario.get("nome"):
        return
    cfg["aberto_em"] = agora
    cfg["aberto_por"] = usuario.get("nome")
    cfg["aberturas"] = int(cfg.get("aberturas") or 0) + 1
    grava_json(pasta / "config.json", cfg)


# como a lista pode ser ordenada. O valor e a chave da URL; a funcao diz por onde ordenar.
ORDENS = [
    ("atualizado", "Atualizado mais recente", lambda d: (d.get("atualizado_em") or d.get("criado_em") or "", ), True),
    ("aberto", "Aberto mais recente", lambda d: (d.get("aberto_em") or "", ), True),
    ("criado", "Enviado mais recente", lambda d: (d.get("criado_em") or "", ), True),
    ("antigo", "Enviado mais antigo", lambda d: (d.get("criado_em") or "", ), False),
    ("titulo", "Título (A-Z)", lambda d: ((d.get("titulo") or d.get("arquivo_original") or "").lower(), ), False),
    ("revista", "Revista", lambda d: ((d.get("revista") or "zzz").lower(), d.get("titulo") or ""), False),
    ("situacao", "Com mais bloqueantes", lambda d: (len(d.get("bloqueantes") or []), ), True),
    ("etapa", "Etapa no fluxo", lambda d: (ETAPAS_ORDEM.get(d.get("etapa") or "recebido", 0), ), False),
]
ROTULO_ORDEM = {c: r for c, r, _f, _rev in ORDENS}
ETAPAS_ORDEM = {cod: i for i, (cod, _r) in enumerate(ETAPAS)}


def ordena_docs(docs: list, ordem: str) -> list:
    """Ordena a lista pelo criterio escolhido. Documento nunca aberto vai para o fim em 'aberto'."""
    escolha = next((o for o in ORDENS if o[0] == ordem), None) or ORDENS[0]
    _cod, _rot, chave, decrescente = escolha
    return sorted(docs, key=chave, reverse=decrescente)


def lista_docs(limite=30, usuario: Optional[dict] = None):
    itens = []
    for pasta in DOCS.iterdir():
        if not pasta.is_dir():
            continue
        cfg = le_json(pasta / "config.json", {}) or {}
        d = le_json(pasta / "validacao.json")
        if not d:
            # ainda na fila, processando ou com erro: entra na lista com o que o config sabe
            if cfg.get("estado") not in ("na_fila", "processando", "erro"):
                continue
            d = {"titulo": "", "nome_base": "", "pronto": False, "bloqueantes": [], "packtools": [], "revista": cfg.get("revista"),
                 "criado_em": cfg.get("criado_em") or cfg.get("fila_em") or "",
                 "atualizado_em": cfg.get("fila_em") or cfg.get("criado_em") or ""}
        d["id"] = pasta.name
        d["estado"] = cfg.get("estado") or "concluido"
        d["erro"] = cfg.get("erro")
        d["posicao"] = fila.posicao(pasta) if d["estado"] == "na_fila" else None
        nome = pasta / "nome_original.txt"
        if d.get("arquivo_original") in (None, "original.pdf") and nome.exists():
            d["arquivo_original"] = nome.read_text(encoding="utf-8").strip()
        d["etapa"] = cfg.get("etapa") or "recebido"
        d["criado_por"] = cfg.get("criado_por")
        d["criado_por_id"] = cfg.get("criado_por_id")
        d["organizacao"] = cfg.get("organizacao")  # antes de pode_ver: colegas da organização veem o documento
        if usuario is not None and not pode_ver(d, usuario):
            continue
        hist = cfg.get("historico_etapas") or []
        d["etapa_por"] = hist[-1].get("por") if hist else None
        d["aberto_em"] = cfg.get("aberto_em")
        d["aberto_por"] = cfg.get("aberto_por")
        d["aberturas"] = cfg.get("aberturas") or 0
        itens.append(d)
    itens.sort(key=lambda d: d.get("atualizado_em") or d.get("criado_em", ""), reverse=True)
    return itens[:limite] if limite else itens


# ---------------------------------------------------------------- edicoes (overrides sobre a extracao)

RE_LICENCA_CC = re.compile(r"(?i)\bCC[\s-]*BY(?P<resto>(?:[\s-]*(?:NC|SA|ND))*)")


def licenca_url(texto: str) -> Optional[str]:
    """'CC BY-NC-ND 4.0' -> a URL certa. Antes um 'sa' solto em 'by-sa' virava 'by-nc-sa', e o 'nd' sumia."""
    if not texto:
        return None
    t = (texto or "").strip()
    if t.startswith("http"):
        return t if RE_CC_URL.match(t) else None
    m = RE_LICENCA_CC.search(t)
    if not m:
        return None
    partes = re.findall(r"(?i)NC|SA|ND", m.group("resto") or "")
    # a ordem canônica da Creative Commons é by-nc-nd / by-nc-sa / by-sa / by-nd
    ordem = [p for p in ("NC", "SA", "ND") if p.upper() in {x.upper() for x in partes}]
    if "SA" in ordem and "ND" in ordem:  # combinação que não existe: ND vence, é a mais restritiva
        ordem.remove("SA")
    chave = "-".join(["by"] + [p.lower() for p in ordem])
    url = f"https://creativecommons.org/licenses/{chave}/4.0/"
    return url if url in {u for u, _ in LICENCAS} else None


RE_CC_URL = re.compile(r"^https?://creativecommons\.org/licenses/")


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
        v[f"autor_{i}_credit"] = ", ".join(a.get("credit", []))
    for j, af in enumerate(modelo.get("afiliacoes", [])):
        for campo in ("instituicao", "divisao", "cidade", "estado", "pais_iso"):
            v[f"aff_{j}_{campo}"] = af.get(campo) or ""
    for k, r in enumerate(modelo.get("resumos", [])):
        v[f"resumo_{k}_idioma"] = r.get("idioma") or ""
        v[f"resumo_{k}_texto"] = r.get("texto") or ""
        v[f"resumo_{k}_kw"] = "; ".join(r.get("palavras_chave", []))
    v["financiamento_texto"] = modelo.get("financiamento_texto") or ""
    v["paginas_total"] = str(modelo.get("paginas_total") or modelo.get("paginas") or "")
    for chave, _rot, _dest in xml_jats.DECLARACOES:
        v["dec_" + chave] = modelo.get("dec_" + chave) or ""
    v["dec_dados_situacao"] = modelo.get("dec_dados_situacao") or ""
    for k, f in enumerate(modelo.get("financiamentos", [])):
        v[f"fomento_{k}_fonte"] = f.get("fonte") or ""
        v[f"fomento_{k}_processo"] = f.get("processo") or ""
    for k, sec in enumerate(modelo.get("secoes", [])):
        v[f"secao_{k}_titulo"] = sec.get("titulo_completo") or sec.get("titulo") or ""
        # um parágrafo por bloco, separados por linha em branco: é como se edita texto corrido
        v[f"secao_{k}_paragrafos"] = "\n\n".join(sec.get("paragrafos") or [])
    for grupo, lista in (("tabela", "tabelas"), ("figura", "figuras"), ("equacao", "equacoes"),
                         ("quadro", "quadros"), ("dialogo", "dialogos")):
        for k, item in enumerate(modelo.get(lista, [])):
            si = item.get("secao_indice")
            v[f"{grupo}_{k}_secao"] = "" if si is None else str(si)
            # na tela a posição é 1-based ("antes do parágrafo 3"); no modelo é o índice do parágrafo
            v[f"{grupo}_{k}_posicao"] = str(int(item.get("pos_paragrafo") or 0) + 1)
    for k, t in enumerate(modelo.get("tabelas", [])):
        v[f"tabela_{k}_rotulo"] = t.get("rotulo") or ""
        v[f"tabela_{k}_legenda"] = t.get("legenda") or ""
        v[f"tabela_{k}_fonte"] = t.get("fonte") or ""
        v[f"tabela_{k}_cabecalho"] = str(t.get("linhas_cabecalho") or 0)
        v[f"tabela_{k}_celulas"] = grade_para_texto(t.get("celulas") or [])
    for k, f in enumerate(modelo.get("figuras", [])):
        v[f"figura_{k}_rotulo"] = f.get("rotulo") or ""
        v[f"figura_{k}_legenda"] = f.get("legenda") or ""
        v[f"figura_{k}_fonte"] = f.get("fonte") or ""
    for k, e in enumerate(modelo.get("equacoes", [])):
        v[f"equacao_{k}_rotulo"] = e.get("rotulo") or ""
        v[f"equacao_{k}_latex"] = e.get("latex") or ""
    for k, q in enumerate(modelo.get("quadros", [])):
        v[f"quadro_{k}_rotulo"] = q.get("rotulo") or ""
        v[f"quadro_{k}_legenda"] = q.get("legenda") or ""
        v[f"quadro_{k}_texto"] = q.get("texto") or ""
    for k, dl in enumerate(modelo.get("dialogos", [])):
        v[f"dialogo_{k}_rotulo"] = dl.get("rotulo") or ""
        v[f"dialogo_{k}_legenda"] = dl.get("legenda") or ""
        v[f"dialogo_{k}_turnos"] = turnos_para_texto(dl.get("turnos") or [])
    return v


def grade_para_texto(celulas) -> str:
    """Grade da tabela vira texto: uma linha por linha, celulas separadas por |. E o formato que a pessoa edita."""
    return "\n".join(" | ".join((c or "").replace("|", "/").strip() for c in linha) for linha in celulas or [])


def texto_para_grade(texto: str):
    """Texto do formulario vira grade. Aceita | e tabulacao (colar do Word e do Excel funciona)."""
    linhas = []
    for bruta in (texto or "").splitlines():
        if not bruta.strip():
            continue
        sep = "\t" if "\t" in bruta else "|"
        linhas.append([c.strip() for c in bruta.split(sep)])
    largura = max((len(l) for l in linhas), default=0)
    return [l + [""] * (largura - len(l)) for l in linhas]


def turnos_para_texto(turnos) -> str:
    return "\n".join(f"{t.get('falante') or ''}: {t.get('fala') or ''}".strip(": ") for t in turnos or [])


def texto_para_turnos(texto: str):
    """Uma linha por fala, no formato 'Falante: fala'. Linha sem ':' vira continuacao do falante anterior."""
    turnos = []
    for bruta in (texto or "").splitlines():
        linha = bruta.strip()
        if not linha:
            continue
        if ":" in linha and len(linha.split(":", 1)[0]) <= 60:
            falante, fala = linha.split(":", 1)
            turnos.append({"falante": falante.strip(), "fala": fala.strip()})
        elif turnos:
            turnos[-1]["fala"] = (turnos[-1]["fala"] + " " + linha).strip()
        else:
            turnos.append({"falante": "", "fala": linha})
    return [t for t in turnos if t.get("fala")]


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
                m["licenca_url"] = licenca_url(val) or m.get("licenca_url")
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
            lista = GRUPOS_LISTA[grupo]
            itens = m.setdefault(lista, [])
            # indice acima do que foi extraido: item criado a mao na tela (autor novo, tabela nova, dialogo novo)
            while idx >= len(itens):
                itens.append(NOVO_ITEM[grupo]())
            alvo = itens[idx]
            if grupo == "autor" and campo == "affs":
                alvo["aff_ids"] = [x.strip() for x in (val or "").split(",") if x.strip()]
            elif grupo == "autor" and campo == "credit":
                validos = {c for c, _ in xml_jats.CREDIT}
                alvo["credit"] = [x.strip() for x in (val or "").split(",") if x.strip() in validos]
            elif grupo == "autor" and campo == "orcid":
                mo = RE_ORCID.search(val or "")
                alvo["orcid"] = mo.group(1).upper() if mo else None
                alvo["orcid_valido"] = orcid_valido(alvo["orcid"]) if alvo["orcid"] else None
            elif grupo == "autor" and campo in ("sobrenome", "nomes"):
                alvo[campo] = val
                alvo["nome_completo"] = " ".join(x for x in (alvo.get("nomes"), alvo.get("sobrenome")) if x)
            elif grupo == "resumo" and campo == "kw":
                alvo["palavras_chave"] = [x.strip(" .") for x in re.split(r"[;\n]", val or "") if x.strip(" .")]
            elif campo == "remover":
                alvo["_removido"] = bool(val)
            elif grupo == "secao" and campo == "titulo":
                alvo["titulo"] = val
                alvo["titulo_completo"] = val
            elif grupo == "secao" and campo == "paragrafos":
                alvo["paragrafos"] = [p.strip() for p in re.split(r"\n\s*\n", val or "") if p.strip()]
            elif campo == "secao":
                alvo["secao_indice"] = int(val) if (val or "").isdigit() else None
            elif campo == "posicao":
                alvo["pos_paragrafo"] = max(0, int(val) - 1) if (val or "").isdigit() else 0
            elif grupo == "tabela" and campo == "celulas":
                alvo["celulas"] = texto_para_grade(val or "")
                alvo["colunas"] = max((len(x) for x in alvo["celulas"]), default=0)
                # grade conferida por gente vira tabela de verdade no XML, nao imagem
                alvo["qualidade"] = "alta" if alvo["celulas"] else alvo.get("qualidade", "baixa")
            elif grupo == "tabela" and campo == "cabecalho":
                alvo["linhas_cabecalho"] = int(val) if (val or "").isdigit() else 0
            elif grupo == "dialogo" and campo == "turnos":
                alvo["turnos"] = texto_para_turnos(val or "")
            elif grupo == "equacao" and campo == "latex":
                alvo["latex"] = val
                alvo["mathml"], alvo["erro_mathml"] = latex_para_mathml(val) if val else (None, None)
            else:
                alvo[campo] = val
    # item removido fica na lista com a marca _removido, e nao sai dela: tirar do meio renumeraria os que vem
    # depois, e os overrides gravados (autor_2_sobrenome) passariam a valer para outra pessoa. Quem some do XML
    # é decidido em modelo_para_xml(); a tela continua mostrando o item, com a caixa marcada, para dar meia-volta.
    for lista in ("tabelas", "figuras", "quadros", "dialogos", "equacoes"):
        for x in m.get(lista, []):
            if _item_vazio(lista, x):
                x["_removido"] = True
    m["financiamentos"] = [f for f in m.get("financiamentos", []) if (f.get("fonte") or "").strip()]
    return m


def sem_vagas_vazias(modelo: dict) -> dict:
    """Tira do fim de cada lista as vagas que a tela criou e ninguém preencheu. Só do fim: mexer no meio
    renumeraria os itens e os overrides gravados passariam a valer para outro."""
    m = copy.deepcopy(modelo)
    for lista in ("tabelas", "figuras", "quadros", "dialogos", "equacoes"):
        itens = m.get(lista) or []
        while itens and _item_vazio(lista, itens[-1]):
            itens.pop()
        m[lista] = itens
    return m


# campo do artigo -> campo do cadastro da revista que pode fornecê-lo. São dados da revista, não do artigo:
# licença de publicação, seção do sumário e idioma em que ela publica. Não é invenção, é o cadastro.
DA_REVISTA = {"licenca": "licenca_url", "heading": "secao_padrao", "idioma": "idioma_padrao"}


def editor_da_revista(revista: Optional[dict]) -> str:
    """Linha do editor responsável a partir do cadastro: nome, ORCID e Lattes."""
    if not revista:
        return ""
    partes = [(revista.get("editor_chefe") or "").strip()]
    if (revista.get("editor_orcid") or "").strip():
        partes.append("ORCID: https://orcid.org/" + revista["editor_orcid"].strip().rsplit("/", 1)[-1])
    if (revista.get("editor_lattes") or "").strip():
        partes.append("Lattes: " + revista["editor_lattes"].strip())
    return ". ".join(p for p in partes if p)


def campos_da_revista(modelo: dict, revista: Optional[dict]) -> dict:
    """O que o cadastro da revista preenche nos campos do artigo que estão vazios. Devolve {campo: (valor, de_onde)}."""
    if not revista:
        return {}
    fora = {}
    linha_editor = editor_da_revista(revista)
    if linha_editor and not (modelo.get("dec_editor") or "").strip():
        fora["dec_editor"] = (linha_editor, f"editor responsável no cadastro de {revista.get('titulo') or revista.get('acronimo')}")
    for campo, no_cadastro in DA_REVISTA.items():
        valor = (revista.get(no_cadastro) or "").strip()
        if not valor:
            continue
        atual = (modelo.get("licenca_url") if campo == "licenca" else modelo.get(campo)) or ""
        if str(atual).strip():
            continue
        rotulo = {"licenca_url": "licença padrão", "secao_padrao": "seção padrão", "idioma_padrao": "idioma"}[no_cadastro]
        fora[campo] = (valor, f"{rotulo} do cadastro de {revista.get('titulo') or revista.get('acronimo')}")
    return fora


# titulo da declaracao no artigo -> campo do formulario. O extrator ja separa esses blocos do texto
# (corpo._back_matter); aqui eles deixam de ficar escondidos e viram campo editavel.
# As revistas declaram isso em portugues, ingles ou espanhol, e as vezes so com a sigla ("IA Statement").
# A ordem importa: a primeira pista que casar com o titulo leva o bloco.
PISTAS_DECLARACAO = [
    ("ia", re.compile(r"(?i)intelig[êe]ncia artificial|artificial intelligence|inteligencia artificial|"
                      r"\b(?:IA|AI)\b[ -]*(?:statement|declaration|declara|uso|use)|"
                      r"(?:statement|declara[çc][ãa]o|declaraci[óo]n|uso|use)[ -]*(?:sobre |of |de |do )?\b(?:IA|AI)\b|"
                      r"generative (?:ai|artificial)")),
    ("agradecimentos", re.compile(r"(?i)agradecimento|agradecemos|acknowledg|reconocimiento|remerciement|ringraziament")),
    ("financiamento", re.compile(r"(?i)financiamento|financiad|financia[çc]|funding|fomento|apoio financeiro|"
                                 r"grant|financial support|financiaci[óo]n|apoyo financiero")),
    ("contribuicao", re.compile(r"(?i)contribui[çc]|contribution|contribuci[óo]n|autoria|authorship|"
                                r"author.{0,12}(?:statement|declaration)|credit")),
    ("dados", re.compile(r"(?i)disponibilidade de dados|data availability|dados de pesquisa|dados abertos|"
                         r"disponibilidad de (?:los )?datos|research data|open data")),
    ("conflito", re.compile(r"(?i)conflito|conflict|interesse|inter[ée]s|competing interest")),
    ("como_citar", re.compile(r"(?i)como citar|how to cite|c[óo]mo citar|citation|forma de cita")),
    ("editor", re.compile(r"(?i)editor")),
]
# titulos que contem a palavra da pista mas nao sao a declaracao: "Editorial process dates" traz datas
# do fluxo editorial, nao o nome do editor responsavel.
NAO_E_DECLARACAO = {
    "editor": re.compile(r"(?i)process|dates|datas|prazo|pol[íi]tica|guidelines|norma"),
    "dados": re.compile(r"(?i)banco de dados do artigo|coleta de dados"),
    "contribuicao": re.compile(r"(?i)originalidade|originality|plagiarism|pl[áa]gio"),
}


def declaracoes_do_artigo(modelo: dict) -> dict:
    """As declarações que o próprio arquivo traz, casadas por título. Devolve {campo: (texto, de_onde)}."""
    fora = {}
    for b in modelo.get("back_matter") or []:
        titulo = (b.get("titulo") or "").strip()
        texto = (b.get("texto") or "").strip()
        if not texto:
            continue
        for chave, rx in PISTAS_DECLARACAO:
            campo = "dec_" + chave
            if campo in fora or (modelo.get(campo) or "").strip():
                continue
            nao = NAO_E_DECLARACAO.get(chave)
            if rx.search(titulo) and not (nao and nao.search(titulo)):
                fora[campo] = (texto, f"lido do próprio arquivo, na parte \"{titulo.rstrip(':')[:48]}\"")
                break
    return fora


def como_citar(modelo: dict, revista: Optional[dict]) -> str:
    """A referência do próprio artigo, montada dos metadados. A SciELO gera isso sozinha a partir do XML;
    mostrar aqui serve de prova real: se a citação sai errada, é porque um metadado está errado."""
    autores = [a for a in (modelo.get("autores") or []) if not a.get("_removido")]
    nomes = "; ".join(f"{(a.get('sobrenome') or '').upper()}, {a.get('nomes') or ''}".strip(", ")
                      for a in autores[:6]) or "[autoria não lida]"
    titulo = next((t.get("texto") for t in (modelo.get("titulos") or []) if t.get("tipo") == "article-title"), "") or "[título]"
    partes = [f"{nomes}. {titulo.rstrip('.')}."]
    if revista:
        partes.append(f" {revista.get('titulo') or ''},")
    ano = ((modelo.get("datas") or {}).get("publicado") or "")[:4] or modelo.get("ano") or ""
    ident = []
    if modelo.get("volume"):
        ident.append("v. " + modelo["volume"])
    if modelo.get("numero"):
        ident.append("n. " + modelo["numero"])
    if modelo.get("elocation"):
        ident.append(modelo["elocation"])
    elif modelo.get("fpage"):
        ident.append("p. " + str(modelo["fpage"]))
    if ident:
        partes.append(" " + ", ".join(ident) + ",")
    if ano:
        partes.append(f" {ano}.")
    if modelo.get("doi"):
        partes.append(f" DOI: https://doi.org/{modelo['doi']}.")
    return "".join(partes).replace("  ", " ").strip()


def modelo_para_xml(modelo: dict) -> dict:
    """Copia do modelo sem o que foi marcado para remover. É o que vai para o gerador."""
    m = copy.deepcopy(modelo)
    for lista in GRUPOS_LISTA.values():
        if isinstance(m.get(lista), list):
            m[lista] = [x for x in m[lista] if not (isinstance(x, dict) and x.get("_removido"))]
    return m


def _item_vazio(lista: str, item: dict) -> bool:
    """Vaga de criacao que ficou em branco: some, em vez de virar um elemento vazio no XML."""
    if lista == "tabelas":
        return not (item.get("celulas") or item.get("legenda") or item.get("arquivo"))
    if lista == "figuras":
        return not (item.get("arquivo") or item.get("legenda"))
    if lista == "quadros":
        return not (item.get("texto") or "").strip()
    if lista == "dialogos":
        return not item.get("turnos")
    if lista == "equacoes":
        # LaTeX digitado que não compilou fica na lista: some seria esconder o erro de quem digitou
        return not (item.get("arquivo") or item.get("mathml") or (item.get("latex") or "").strip())
    return False


# item novo criado pela tela, com o minimo para o gerador entender
NOVO_ITEM = {
    "titulo": lambda: {"texto": "", "idioma": None, "tipo": "trans-title", "pagina": 1},
    "autor": lambda: {"nome_completo": "", "sobrenome": "", "nomes": "", "marcadores": [], "aff_ids": [], "papel": "author"},
    "aff": lambda: {"id": "", "texto_original": "criada à mão na revisão", "origem": "digitada", "confianca": "alta"},
    "resumo": lambda: {"idioma": None, "rotulo": "Resumo", "texto": "", "palavras_chave": []},
    "secao": lambda: {"titulo": "", "nivel": 1, "pagina": 1, "paragrafos": []},
    "tabela": lambda: {"rotulo": "", "legenda": "", "celulas": [], "linhas_cabecalho": 1, "colunas": 0,
                       "qualidade": "alta", "pagina": 1, "origem": "digitada"},
    "figura": lambda: {"tipo": "fig", "rotulo": "", "legenda": "", "pagina": 1, "origem": "digitada"},
    "fomento": lambda: {"fonte": "", "processo": ""},
    "equacao": lambda: {"rotulo": "", "numero": None, "pagina": 1, "origem": "digitada"},
    "quadro": lambda: {"rotulo": "", "legenda": "", "texto": "", "pagina": 1, "origem": "digitada"},
    "dialogo": lambda: {"rotulo": "", "legenda": "", "turnos": [], "pagina": 1, "origem": "digitada"},
}


def latex_para_mathml(latex: str):
    """Converte LaTeX em MathML. O guia de entrega da SciELO exige as formulas em MathML ou LaTeX, nao em imagem.
    Devolve (mathml, erro): erro preenchido quando o LaTeX nao compila, para a tela dizer o que esta errado."""
    texto = (latex or "").strip()
    if not texto:
        return None, None
    texto = re.sub(r"^\$+|\$+$", "", texto).strip()
    texto = re.sub(r"^\\\[|\\\]$", "", texto).strip()
    try:
        from latex2mathml.converter import convert
        # display="block": a fórmula vai dentro de <disp-formula>, que é fórmula destacada, não em linha
        return convert(texto, display="block"), None
    except Exception as e:  # noqa: BLE001
        detalhe = str(e).strip() or type(e).__name__
        return None, f"LaTeX não reconhecido: {detalhe[:120]}. Confira chaves e barras invertidas."


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



# ---------------------------------------------------------------- revistas pelo ISSN

def sugestao_de_issn(consulta: dict) -> dict:
    """Converte o que as bases devolveram nos campos do formulário de revista. Só copia o que veio; não completa nada."""
    d = consulta.get("dados") or {}
    origem = consulta.get("origem") or {}
    v = {k: d[k] for k in ("acronimo", "titulo", "abrev", "editora", "issn_epub", "issn_ppub", "area", "site",
                           "idioma_padrao") if d.get(k)}
    # valida_revista lê valores de formulário: "sim"/"não", não booleano
    v["na_scielo"] = "sim" if d.get("na_scielo") else "nao"
    if d.get("licenca") in {u for u, _ in LICENCAS}:
        v["licenca_url"] = d["licenca"]
    else:
        v["licenca_url"] = LICENCAS[0][0]
    v.setdefault("modo_publicacao", "continua")
    if d.get("area") and d["area"] not in AREAS:
        v.pop("area", None)
    # sem acrônimo da SciELO, sugere um a partir do título, para a pessoa conferir (o acrônimo entra no nome dos arquivos)
    if not v.get("acronimo") and v.get("titulo"):
        from extrator.util import sem_acentos
        letras = re.sub(r"[^a-z ]", "", sem_acentos(v["titulo"]).lower()).split()
        ignora = {"revista", "de", "da", "do", "das", "dos", "e", "em", "a", "o", "journal", "of", "the", "brazilian", "brasileira"}
        siglas = "".join(p[0] for p in letras if p not in ignora)[:6]
        v["acronimo"] = siglas if len(siglas) >= 2 else None
        if not v["acronimo"]:
            v.pop("acronimo")
    procedencia = "; ".join(f"{c}: {origem[c]}" for c in sorted(origem) if c in v or c in ("licenca", "abrev"))
    v["_fonte"] = f"Importado pelo ISSN {consulta.get('issn')} em {tempo.formata(tempo.agora_iso())}. Origem por campo — {procedencia}."
    return v


def revista_por_issn(numero: str, usuario: dict) -> tuple:
    """Acha a revista cadastrada pelo ISSN ou cadastra uma nova com o que as bases souberem.
    Devolve (acronimo | None, mensagem, consulta). Nunca cadastra pela metade: faltando campo obrigatório, devolve o motivo."""
    numero = issn_api.normaliza(numero)
    lista = carrega_revistas()
    ja = next((r for r in lista if numero in {(r.get("issn_epub") or "").upper(), (r.get("issn_ppub") or "").upper()}), None)
    if ja and ja["acronimo"] not in {r["acronimo"] for r in revistas_para(usuario)}:
        return None, (f"O ISSN {numero} já está cadastrado como {ja['titulo']} ({ja['acronimo']}) por outra organização. "
                      "Uma revista só existe uma vez: peça ao administrador para torná-la pública ou vinculá-la à sua organização."), None
    if ja:
        return ja["acronimo"], f"Revista {ja['titulo']} ({ja['acronimo']}) já estava cadastrada com o ISSN {numero}.", None
    consulta = issn_api.consulta(numero)
    if not consulta.get("ok"):
        return None, consulta.get("mensagem") or "ISSN não encontrado.", consulta
    v = sugestao_de_issn(consulta)
    dados, erros = valida_revista(v, lista)
    if erros:
        falta = ", ".join(sorted(erros))
        return None, (f"As bases responderam, mas faltam campos obrigatórios para cadastrar sozinho ({falta}). "
                      f"Abra Revistas > Nova revista com esse ISSN e complete à mão."), consulta
    _marca_dona(dados, usuario)
    lista.append(dados)
    grava_revistas(lista)
    return dados["acronimo"], (f"Revista {dados['titulo']} cadastrada pelo ISSN {numero} "
                               f"({consulta['mensagem'].split('.')[0].lower()})."), consulta


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
    doc, model = cli.extrai(str(arquivo_original(pasta)), pasta_imagens=str(pasta / "imagens"))
    grava_json(pasta / "model.json", model.to_dict())
    with io.open(pasta / "resumo.md", "w", encoding="utf-8") as f:
        f.write(cli.resumo_md(model))


def arquivo_original(pasta: Path) -> Path:
    """O arquivo enviado, seja qual for o formato. Documentos antigos só têm original.pdf."""
    for ext in sorted(FORMATOS):
        alvo = pasta / ("original" + ext)
        if alvo.exists():
            return alvo
    return pasta / "original.pdf"


def processa_envio(pasta: Path) -> dict:
    """Extrai, gera o XML e valida, medindo o tempo de cada parte. A duração fica no validacao.json e alimenta o
    'tempo médio por artigo' do painel administrativo, a métrica de operação prevista no plano."""
    inicio = time.perf_counter()
    extrai_e_salva(pasta)
    meio = time.perf_counter()
    r = gera_e_valida(pasta)
    registra_duracao(pasta, extracao=meio - inicio, total=time.perf_counter() - inicio)
    return r


fila.configura(DOCS, processa_envio, le_json, grava_json, tempo.agora_iso)


def registra_duracao(pasta: Path, extracao: float, total: float) -> None:
    v = le_json(pasta / "validacao.json", {}) or {}
    if not v:
        return
    v["duracao_extracao_s"] = round(extracao, 1)
    v["duracao_s"] = round(total, 1)
    grava_json(pasta / "validacao.json", v)


def marca_rascunho(xml: Optional[bytes], bloqueantes: list) -> Optional[bytes]:
    """Com bloqueante pendente o XML existe para conferência, mas sai marcado como rascunho logo abaixo da declaração
    (plano, seção 2.6: sem bloqueante resolvido não há XML final, no máximo um rascunho marcado como tal).
    O comentário não muda a validação nem a prévia; some sozinho quando o documento fica pronto, porque o XML
    é gerado de novo a cada salvamento."""
    if not xml or not bloqueantes:
        return xml
    aviso = (f"<!-- xmljats: RASCUNHO. {len(bloqueantes)} bloqueante(s) pendente(s); este XML não está pronto "
             f"para entrega à SciELO. -->").encode("utf-8")
    fim_decl = xml.find(b"?>")
    if xml.startswith(b"<?xml") and fim_decl > 0:
        return xml[:fim_decl + 2] + b"\n" + aviso + xml[fim_decl + 2:]
    return aviso + b"\n" + xml


def gera_e_valida(pasta: Path) -> dict:
    """Aplica edicoes, gera o XML, valida no packtools e grava validacao.json."""
    cfg = le_json(pasta / "config.json", {}) or {}
    versao_sps = cfg.get("versao_sps", "1.9")
    modelo = modelo_para_xml(modelo_efetivo(pasta))
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
        f.write(marca_rascunho(res.xml, res.bloqueantes))
    dtd_ok, sps_ok, erros, detalhe = gx.valida_packtools(str(xml_path))
    figuras_pacote = prepara_imagens_pacote(pasta, res.imagens)
    # <base>-gf01.tif -> fig01.jpeg: a prévia precisa apontar para o arquivo que o navegador abre
    mapa_imagens = {sps: origem for origem, sps in res.imagens}
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
        # medição do envio (processa_envio); salvar a revisão não a apaga
        "duracao_s": anterior.get("duracao_s"), "duracao_extracao_s": anterior.get("duracao_extracao_s"),
        "arquivo_original": nome_original,
        "titulo": next((t["texto"] for t in modelo.get("titulos", []) if t["tipo"] == "article-title"), ""),
        "revista": rev["acronimo"] if rev else None,
        "revista_titulo": rev["titulo"] if rev else None,
        "versao_sps": versao_sps,
        "nome_base": base,
        "mapa_imagens": mapa_imagens,
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
            "ano": modelo.get("ano"), "datas": modelo.get("datas"), "licenca": modelo.get("licenca"),
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
    return {"ok": True, "app": VERSAO_APP, "packtools": pk, "docs": sum(1 for _ in DOCS.iterdir()),
            "ocr": ocr_mod.disponivel(), "ocr_idiomas": ocr_mod.idiomas() or None}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, usuario: dict = Depends(autentica), mensagem: str = "", revista: str = ""):
    if usuario.get("papel") == "admin":
        return RedirectResponse(url="/admin", status_code=303)  # o admin é ambiente de administração, não de envio
    meus = lista_docs(0, usuario)
    return templates.TemplateResponse(request, "index.html", {"revistas": revistas_para(usuario), "docs": meus[:8], "total_docs": len(meus),
                                                              "usuario": usuario, "mensagem": mensagem, "revista_atual": revista})


@app.post("/validar")
async def validar(request: Request, arquivo: List[UploadFile] = File(...), revista: str = Form(""), sps: str = Form("1.10"),
                  issn: str = Form(""), usuario: dict = Depends(autentica)):
    """Um arquivo: processa na hora e cai no resultado. Vários: entram na fila (um trabalhador processa um a um)
    e a pessoa acompanha na lista de documentos, que atualiza sozinha."""
    arquivos = [a for a in arquivo if a is not None and (a.filename or "").strip()]
    if not arquivos:
        raise HTTPException(400, "Escolha pelo menos um arquivo.")
    if len(arquivos) > MAX_LOTE:
        raise HTTPException(400, f"No máximo {MAX_LOTE} arquivos por envio; este tinha {len(arquivos)}.")
    for a in arquivos:
        ext = os.path.splitext(a.filename or "")[1].lower()
        if ext not in FORMATOS:
            raise HTTPException(400, f"Formato não aceito: {a.filename} ({ext or 'sem extensão'}). O sistema lê "
                                     f"{', '.join(sorted(FORMATOS))}.")
    if confirmacao_pendente(usuario):
        raise HTTPException(403, "Confirme seu e-mail antes de enviar arquivos. Veja o link em Minha conta.")
    conteudos = []
    for a in arquivos:
        conteudo = await a.read()
        if len(conteudo) > MAX_MB * 1024 * 1024:
            raise HTTPException(413, f"{a.filename}: maior que {MAX_MB} MB.")
        conteudos.append((a.filename or "arquivo", conteudo))
    if sps not in ("1.9", "1.10"):
        sps = "1.10"
    if revista and revista not in {r["acronimo"] for r in revistas_para(usuario)}:
        raise HTTPException(400, "Revista fora do seu alcance: use uma revista pública ou da sua organização.")
    # "Detectar pelo ISSN": sem revista na lista, o número resolve o cadastro (e o cria, se as bases responderem)
    aviso_revista = None
    if not revista and issn.strip():
        # consulta de rede numa rota async: fora do event loop, senão o site inteiro fica parado esperando
        revista, aviso_revista, _ = await run_in_threadpool(revista_por_issn, issn, usuario)
        revista = revista or ""
    novos = []
    for nome, conteudo in conteudos:
        ext = os.path.splitext(nome)[1].lower()
        doc_id = tempo.agora().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        pasta = DOCS / doc_id
        pasta.mkdir(parents=True, exist_ok=True)
        with open(pasta / ("original" + ext), "wb") as f:
            f.write(conteudo)
        (pasta / "nome_original.txt").write_text(nome, encoding="utf-8")
        agora = tempo.agora_iso()
        grava_json(pasta / "config.json", {"versao_sps": sps, "revista": revista or None, "criado_por": usuario["nome"],
                                           "criado_por_id": usuario["id"], "criado_em": agora, "etapa": "recebido",
                                           "organizacao": usuario.get("organizacao"),
                                           "issn_informado": issn.strip() or None, "aviso_revista": aviso_revista,
                                           "historico_etapas": [{"etapa": "recebido", "por": usuario["nome"], "em": agora}]})
        novos.append((doc_id, pasta))
    if len(novos) == 1:
        doc_id, pasta = novos[0]
        try:
            # extração + XML + packtools levam segundos: fora do event loop, senão o site inteiro espera este envio
            await run_in_threadpool(processa_envio, pasta)
        except Exception as e:  # noqa: BLE001
            (pasta / "erro.txt").write_text(repr(e), encoding="utf-8")
            raise HTTPException(500, f"Falha ao processar o arquivo: {e}")
        return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)
    for _doc_id, pasta in novos:
        fila.enfileira(pasta)
    return RedirectResponse(url="/painel?mensagem=" + urllib.parse.quote(
        f"{len(novos)} arquivos na fila. A lista atualiza sozinha enquanto eles são processados."), status_code=303)


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def ver_doc(request: Request, doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    r = le_json(pasta / "validacao.json")
    cfg = le_json(pasta / "config.json", {}) or {}
    if not r:
        if cfg.get("estado") in ("na_fila", "processando", "erro"):
            nome = (pasta / "nome_original.txt").read_text(encoding="utf-8").strip() if (pasta / "nome_original.txt").exists() else doc_id
            return templates.TemplateResponse(request, "aguardando.html", {
                "usuario": usuario, "id": doc_id, "nome": nome, "estado": cfg.get("estado"), "erro": cfg.get("erro"),
                "posicao": fila.posicao(pasta), "na_fila": fila.tamanho()})
        raise HTTPException(404, "Documento sem resultado")
    marca_aberto(pasta, usuario)
    r["id"] = doc_id
    return templates.TemplateResponse(request, "resultado.html", {"r": r, "usuario": usuario, "etapas": ETAPAS, "etapa": cfg.get("etapa") or "recebido",
                                                                  "historico": cfg.get("historico_etapas") or [], "criado_por": cfg.get("criado_por")})


@app.get("/doc/{doc_id}/estado.json")
def estado_do_documento(doc_id: str, usuario: dict = Depends(autentica)):
    """Estado do processamento, para a página de espera e a lista se atualizarem sozinhas."""
    pasta = _pasta(doc_id, usuario)
    cfg = le_json(pasta / "config.json", {}) or {}
    estado = cfg.get("estado") or ("concluido" if (pasta / "validacao.json").exists() else "na_fila")
    return {"estado": estado, "posicao": fila.posicao(pasta), "na_fila": fila.tamanho(), "erro": cfg.get("erro"),
            "pronto": bool((le_json(pasta / "validacao.json", {}) or {}).get("pronto"))}


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


def _contexto_editar(request: Request, doc_id: str, pasta, usuario: dict, valores: dict, editados: set,
                     pendencias: Optional[dict] = None, mensagem: str = "", erro: str = "",
                     modelo: Optional[dict] = None):
    """Tudo que a tela de revisar precisa. Na volta com pendências recebe o modelo PROPOSTO, não o salvo:
    senão a tabela ou o quadro que a pessoa acabou de criar sumiriam da tela junto com o texto digitado."""
    cfg = le_json(pasta / "config.json", {}) or {}
    r = le_json(pasta / "validacao.json", {}) or {}
    try:
        original = (pasta / "resumo.md").read_text(encoding="utf-8")
    except OSError:
        original = ""
    modelo = sem_vagas_vazias(modelo_efetivo(pasta) if modelo is None else modelo)
    revista = next((x for x in carrega_revistas() if x["acronimo"] == (cfg.get("revista") or "")), None)
    # vincular o artigo a uma revista já preenche o que é dado da revista, e não do artigo
    da_revista = dict(declaracoes_do_artigo(modelo))
    da_revista.update(campos_da_revista(modelo, revista))
    if not (valores.get("dec_como_citar") or "").strip() and "dec_como_citar" not in da_revista:
        citacao = como_citar(modelo, revista)
        if citacao:
            da_revista["dec_como_citar"] = (citacao, "montado a partir dos metadados deste documento")
    for campo, (valor, de_onde) in da_revista.items():
        if not (valores.get(campo) or "").strip():
            valores[campo] = valor
            modelo["licenca_url" if campo == "licenca" else campo] = valor
    pend = obrigatorios.pendencias(modelo, revista, cfg.get("versao_sps") or "1.9") if pendencias is None else pendencias
    return templates.TemplateResponse(request, "editar.html", {
        "id": doc_id, "m": modelo, "v": valores, "editados": editados, "bloq": r.get("campos_bloqueados", {}),
        "bloqueantes": r.get("bloqueantes", []), "revistas": revistas_para(usuario),
        "revista_atual": cfg.get("revista") or r.get("revista") or "",
        "tipos": TIPOS_ARTIGO, "idiomas": IDIOMAS, "original_html": markdown_html(original), "usuario": usuario, "r": r,
        "obrig": pend, "obrig_grupos": obrigatorios.resumo_por_grupo(pend), "paginas": visual.resumo(pasta),
        "credit": xml_jats.CREDIT, "da_revista": {k: t[1] for k, t in da_revista.items()},
        "declaracoes": xml_jats.DECLARACOES, "situacao_dados": xml_jats.SITUACAO_DADOS,
        "como_citar": como_citar(modelo, revista),
        "mensagem": mensagem, "erro": erro, "vagas": VAGAS_NOVAS,
    }, status_code=400 if erro else 200)


@app.get("/doc/{doc_id}/editar", response_class=HTMLResponse)
def editar_form(request: Request, doc_id: str, usuario: dict = Depends(autentica), mensagem: str = ""):
    pasta = _pasta(doc_id, usuario)
    marca_aberto(pasta, usuario)
    modelo = le_json(pasta / "model.json", {})
    campos = (le_json(pasta / "edicoes.json", {}) or {}).get("campos", {})
    valores = valores_editaveis(modelo)
    valores.update({k: (v or "") for k, v in campos.items()})
    # os campos dos itens criados a mão não existem no modelo extraído: vêm das próprias edições
    valores.update(valores_editaveis(modelo_efetivo(pasta)))
    valores.update({k: (v or "") for k, v in campos.items()})
    return _contexto_editar(request, doc_id, pasta, usuario, valores, set(campos), mensagem=mensagem)


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
            if val and val not in {r["acronimo"] for r in revistas_para(usuario)}:
                raise HTTPException(400, "Revista fora do seu alcance: use uma revista pública ou da sua organização.")
            cfg["revista"] = val or None
            grava_json(pasta / "config.json", cfg)
            continue
        if k not in originais and not RE_CAMPO_LISTA.match(k):
            continue
        if k.endswith("_remover"):
            # a caixa desmarcada não é enviada pelo navegador; o formulário manda um campo vazio antes dela,
            # e é isso que permite desfazer uma remoção em vez de ela ficar gravada para sempre
            campos[k] = "1" if val else campos.get(k, "")
            if not val:
                campos.pop(k, None)
            continue
        if val == (originais.get(k) or ""):
            campos.pop(k, None)  # voltou ao valor extraido: sem override
        else:
            campos[k] = val
    ed["campos"] = campos
    ed["atualizado_em"] = tempo.agora_iso()
    ed["por"] = usuario["nome"]
    acao = str(form.get("acao") or "salvar")
    # rascunho: guarda o que foi digitado sem gerar XML, para ninguém perder trabalho no meio do preenchimento
    if acao == "rascunho":
        grava_json(pasta / "edicoes.json", ed)
        return RedirectResponse(url=f"/doc/{doc_id}/editar?mensagem=" +
                                urllib.parse.quote("Rascunho guardado. O XML não foi gerado."), status_code=303)
    # salvar e validar: o que a SciELO exige e o PDF não trouxe tem de estar preenchido
    cfg = le_json(pasta / "config.json", {}) or {}
    revista = next((x for x in carrega_revistas() if x["acronimo"] == (cfg.get("revista") or "")), None)
    proposto = aplica_edicoes(modelo, campos)
    pend = obrigatorios.pendencias(proposto, revista, cfg.get("versao_sps") or "1.9")
    if pend:
        valores = valores_editaveis(proposto)
        valores.update({k: (v or "") for k, v in campos.items()})
        quantos = len(pend)
        return _contexto_editar(request, doc_id, pasta, usuario, valores, set(campos), pendencias=pend, modelo=proposto,
                                erro=f"Faltam {quantos} campo(s) que a SciELO exige. Nada foi salvo ainda: preencha o que "
                                     f"está marcado em vermelho e salve de novo, ou use \"Guardar rascunho\" para não "
                                     f"perder o que já digitou.")
    grava_json(pasta / "edicoes.json", ed)
    await run_in_threadpool(gera_e_valida, pasta)
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


def mapa_de_imagens(pasta) -> dict:
    """Documentos gerados antes de o mapa ser gravado: reconstroi <base>-gfNN.tif -> figNN.ext pela ordem,
    que e a mesma que o gerador usa."""
    modelo = modelo_para_xml(modelo_efetivo(pasta))
    base = (le_json(pasta / "validacao.json", {}) or {}).get("nome_base") or ""
    mapa = {}
    for n, f in enumerate([x for x in modelo.get("figuras", []) if x.get("tipo") == "fig" and x.get("arquivo")], start=1):
        mapa[f"{base}-gf{n:02d}.tif"] = f["arquivo"]
    for n, t in enumerate([x for x in modelo.get("tabelas", []) if x.get("arquivo")], start=1):
        mapa[f"{base}-gt{n:02d}.tif"] = t["arquivo"]
    for n, e in enumerate([x for x in modelo.get("equacoes", []) if x.get("arquivo") and not x.get("mathml")], start=1):
        mapa[f"{base}-e{n:02d}.tif"] = e["arquivo"]
    return mapa


@app.get("/doc/{doc_id}/previa", response_class=HTMLResponse)
def previa_do_artigo(doc_id: str, usuario: dict = Depends(autentica)):
    """O artigo como a SciELO vai publicar, gerado do nosso XML pelo htmlgenerator do packtools.

    Serve para ver de uma vez se figura, tabela e fórmula caíram no lugar certo — coisa que a leitura
    do XML cru não mostra. As imagens são reapontadas para os arquivos deste documento, porque no XML
    elas têm o nome do pacote (<base>-gf01.tif), que o navegador não abre.
    """
    pasta = _pasta(doc_id, usuario)
    xml = next(pasta.glob("*.xml"), None)
    if not xml:
        return HTMLResponse("<p style='font:14px system-ui;padding:24px'>O XML ainda não foi gerado. "
                            "Passe por Revisar e editar.</p>", status_code=404)
    try:
        from lxml import etree as _et
        from packtools import HTMLGenerator
        # o packtools abre o XML resolvendo o DTD pela URL do DOCTYPE; o servidor não alcança
        # jats.nlm.nih.gov e a prévia quebrava só em produção. Aqui o XML é lido sem rede — a
        # validação continua sendo feita, à parte, contra o DTD empacotado.
        arvore = _et.parse(str(xml), _et.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
        hg = HTMLGenerator.parse(
            arvore, valid_only=False,
            css="/previa-estatico/scielo-article-standalone.css",
            print_css="/previa-estatico/scielo-bundle-print.css",
            js="/previa-estatico/scielo-article-standalone-min.js")
        idioma = hg.languages[0] if hg.languages else "pt"
        html = str(hg.generate(idioma))
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(f"<p style='font:14px system-ui;padding:24px;color:#b3261e'>Não consegui gerar a "
                            f"pré-visualização: {str(e)[:200]}</p>", status_code=500)
    mapa = (le_json(pasta / "validacao.json", {}) or {}).get("mapa_imagens") or mapa_de_imagens(pasta)
    # o htmlgenerator troca a extensao do arquivo (o XML diz .tif, ele escreve .jpg, porque a SciELO
    # serve o derivado JPG). Por isso o casamento e pelo nome SEM extensao, senao a imagem sai quebrada.
    por_raiz = {os.path.splitext(nome)[0]: arquivo for nome, arquivo in mapa.items()}
    if por_raiz:
        alvo = re.compile(r"([\w-]+-(?:gf|gt|e)\d{2})\.[A-Za-z0-9]+")
        html = alvo.sub(lambda m: (f"/doc/{doc_id}/img/{por_raiz[m.group(1)]}" if m.group(1) in por_raiz else m.group(0)), html)
    return HTMLResponse(html)


@app.get("/doc/{doc_id}/doi")
def busca_por_doi(doc_id: str, numero: str = "", usuario: dict = Depends(autentica)):
    """O que o Crossref sabe sobre este DOI. A tela mostra campo a campo, e quem revisa decide o que aplicar."""
    pasta = _pasta(doc_id, usuario)
    if not numero.strip():
        modelo = modelo_efetivo(pasta)
        numero = modelo.get("doi") or ""
    return enriquece.por_doi(numero)


@app.post("/doc/{doc_id}/pendencias")
async def manda_pendencias(request: Request, doc_id: str, usuario: dict = Depends(autentica)):
    """Monta no correio a lista do que falta, para pedir de uma vez à revista ou ao autor.
    Na prática é o que mais custa tempo: ORCID, datas do OJS e seção do sumário nunca estão no arquivo."""
    pasta = _pasta(doc_id, usuario)
    form = await request.form()
    destino = str(form.get("destino") or "").strip()
    cfg = le_json(pasta / "config.json", {}) or {}
    r = le_json(pasta / "validacao.json", {}) or {}
    revista = next((x for x in carrega_revistas() if x["acronimo"] == (cfg.get("revista") or "")), None) or {}
    modelo = modelo_efetivo(pasta)
    pend = obrigatorios.pendencias(modelo, revista or None, cfg.get("versao_sps") or "1.9")
    if not pend:
        return RedirectResponse(url=f"/doc/{doc_id}/editar?mensagem=" + urllib.parse.quote(
            "Não há pendências para pedir: está tudo preenchido."), status_code=303)
    if not destino:
        return RedirectResponse(url=f"/doc/{doc_id}/editar?mensagem=" + urllib.parse.quote(
            "Informe o e-mail da revista ou do autor para montar o pedido."), status_code=303)
    titulo = r.get("titulo") or modelo.get("titulos", [{}])[0].get("texto") or r.get("arquivo_original") or doc_id
    linhas = [f"Prezados,", "",
              f"Para fechar o XML SciELO do artigo abaixo, faltam {len(pend)} informação(ões) que não estão no "
              f"arquivo enviado e que a SciELO exige.", "",
              f"Artigo: {titulo}",
              f"Periódico: {revista.get('titulo') or '—'}",
              f"DOI: {modelo.get('doi') or '—'}", "", "O que falta:", ""]
    for grupo, itens in obrigatorios.por_grupo(pend):
        linhas.append(f"- {grupo}:")
        for campo, motivo, _fonte in itens:
            linhas.append(f"    . {obrigatorios.ROTULOS.get(campo, campo)}: {motivo}")
    linhas += ["", "Cada item acima corresponde a uma regra da SciELO Publishing Schema ou do guia de entrega de "
                   "pacotes; sem eles o pacote é devolvido.", "", "Atenciosamente,"]
    assunto = f"Faltam {len(pend)} dado(s) para o XML SciELO — {titulo[:70]}"
    CORREIO.cria(destino or (revista.get("site") and "") or "", assunto, "\n".join(linhas),
                 caixa="rascunhos", tipo="pendencias", por=usuario["nome"])
    return RedirectResponse(url="/admin/correio?caixa=rascunhos&mensagem=" + urllib.parse.quote(
        "Pedido montado como rascunho com o que falta. Confira o destinatário e envie."), status_code=303)


@app.get("/orcid")
def confere_orcid(numero: str = "", nome: str = "", usuario: dict = Depends(autentica)):
    """Confere no registro público do ORCID se o número existe e de quem é."""
    return enriquece.confere_orcid(numero, nome)


@app.post("/doc/{doc_id}/figura")
async def envia_figura(request: Request, doc_id: str, indice: int = Form(...), imagem: UploadFile = File(...),
                       usuario: dict = Depends(autentica)):
    """Imagem de uma figura, enviada à mão na revisão (a que o motor não achou no PDF, ou a que veio errada)."""
    pasta = _pasta(doc_id, usuario)
    dados = await imagem.read()
    if len(dados) > 25 * 1024 * 1024:
        raise HTTPException(413, "Imagem maior que 25 MB.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(dados)) as im:
            im.verify()
        with Image.open(io.BytesIO(dados)) as im:
            largura, altura = im.size
            formato = (im.format or "PNG").lower()
    except Exception:  # noqa: BLE001
        return RedirectResponse(url=f"/doc/{doc_id}/editar?mensagem=" +
                                urllib.parse.quote("O arquivo enviado não é uma imagem que eu consiga ler."), status_code=303)
    ext = {"jpeg": "jpg", "tiff": "tif"}.get(formato, formato)
    if ext not in ("png", "jpg", "tif", "gif", "bmp", "webp"):
        ext = "png"
    (pasta / "imagens").mkdir(parents=True, exist_ok=True)
    nome = f"fig{indice + 1:02d}.{ext}"
    with open(pasta / "imagens" / nome, "wb") as f:
        f.write(dados)
    ed = le_json(pasta / "edicoes.json", {}) or {"campos": {}}
    campos = dict(ed.get("campos", {}))
    campos[f"figura_{indice}_arquivo"] = nome
    campos[f"figura_{indice}_ext"] = ext
    campos[f"figura_{indice}_largura"] = str(largura)
    campos[f"figura_{indice}_altura"] = str(altura)
    campos.setdefault(f"figura_{indice}_tipo", "fig")
    ed["campos"] = campos
    ed["atualizado_em"] = tempo.agora_iso()
    ed["por"] = usuario["nome"]
    grava_json(pasta / "edicoes.json", ed)
    return RedirectResponse(url=f"/doc/{doc_id}/editar?mensagem=" +
                            urllib.parse.quote(f"Imagem {nome} guardada ({largura}x{altura}). Preencha a legenda e salve."),
                            status_code=303)


@app.post("/doc/{doc_id}/reprocessar")
def reprocessar(doc_id: str, usuario: dict = Depends(autentica)):
    pasta = _pasta(doc_id, usuario)
    visual.limpa(pasta)  # o PDF vai ser lido de novo: as páginas renderizadas saem junto
    processa_envio(pasta)
    fila.conclui(pasta)  # documento que veio da fila (ou deu erro nela) volta a 'concluido'
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)




# ---------------------------------------------------------------- visualização do arquivo original

@app.get("/doc/{doc_id}/paginas.json")
def paginas_do_documento(doc_id: str, usuario: dict = Depends(autentica)):
    """Índice das páginas com a caixa de cada palavra. Renderiza na primeira chamada e guarda na pasta do documento."""
    pasta = _pasta(doc_id, usuario)
    try:
        idx = visual.prepara(pasta)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Não consegui renderizar o PDF: {e}")
    return idx


@app.get("/doc/{doc_id}/pagina/{nome}")
def pagina_do_documento(doc_id: str, nome: str, usuario: dict = Depends(autentica)):
    """Imagem de uma página do PDF original."""
    if not re.fullmatch(r"p\d{3}\.png", nome):
        raise HTTPException(404)
    pasta = _pasta(doc_id, usuario)
    caminho = pasta / "paginas" / nome
    if not caminho.exists():
        visual.prepara(pasta)
    if not caminho.exists():
        raise HTTPException(404)
    return FileResponse(str(caminho), media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


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
    return Response(monta_pacote(pasta), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{nome_pacote(pasta)[0]}.zip"'})


# ---------------------------------------------------------------- lotes de entrega (SPS 1.10)
# Em publicação contínua cada depósito é um "lote", numerado em sequência por volume/número (01, 02…, sem
# buracos); o número entra no nome da pasta do pacote e no título do e-mail. O contador fica em lotes.json.

def _chave_lote(revista: dict, doc: dict) -> str:
    return f"{revista.get('acronimo')}|{entrega._num(doc.get('volume'))}|{entrega._num(doc.get('numero'))}"


def proximo_lote(revista: dict, doc: dict) -> int:
    reg = le_json(DATA / "lotes.json", {}) or {}
    return int((reg.get(_chave_lote(revista, doc)) or {}).get("proximo") or 1)


def registra_lote(revista: dict, doc: dict, lote: int, doc_id: str, pacote: str) -> None:
    reg = le_json(DATA / "lotes.json", {}) or {}
    chave = _chave_lote(revista, doc)
    atual = reg.get(chave) or {"proximo": 1, "entregas": []}
    if not any(e.get("doc") == doc_id and e.get("lote") == lote for e in atual["entregas"]):
        atual["entregas"].append({"lote": lote, "doc": doc_id, "pacote": pacote, "em": tempo.agora_iso()})
    atual["proximo"] = max(int(atual.get("proximo") or 1), int(lote) + 1)
    reg[chave] = atual
    grava_json(DATA / "lotes.json", reg)


def lote_do_documento(pasta: Path, revista: Optional[dict], val: dict) -> Optional[int]:
    """Lote gravado no documento; em publicação contínua, sem lote gravado, sugere o próximo da sequência."""
    cfg = le_json(pasta / "config.json", {}) or {}
    if cfg.get("lote"):
        return int(cfg["lote"])
    if revista and entrega.continua(revista) and revista.get("acronimo"):
        return proximo_lote(revista, entrega.metadados(val))
    return None


lotes.configura(DATA, DOCS, le_json, grava_json, tempo.agora_iso, carrega_revistas, entrega, lista_docs, proximo_lote, registra_lote)


def nome_pacote(pasta: Path) -> tuple:
    """(nome da pasta do pacote, nome-base do artigo, revista, lote). A pasta segue a "Nomeação de Pastas" da
    SPS 1.10; sem revista, volume ou lote, cai no nome-base do artigo e a conferência aponta o que falta."""
    xml = next(pasta.glob("*.xml"), None)
    if not xml:
        raise HTTPException(404, "Gere o XML antes de montar o pacote.")
    base = xml.stem
    val = le_json(pasta / "validacao.json", {}) or {}
    cfg = le_json(pasta / "config.json", {}) or {}
    revista = next((x for x in carrega_revistas() if x["acronimo"] == (cfg.get("revista") or "")), None)
    lote = lote_do_documento(pasta, revista, val)
    return (entrega.nome_pasta(revista, entrega.metadados(val), lote) or base), base, revista, lote


def _zip_bruto(pasta: Path, base: str, relatorio: Optional[bytes], pasta_pacote: str) -> bytes:
    """Monta o .zip na estrutura da SPS 1.10: uma pasta com o nome do pacote e, dentro dela, o relatório
    (xpm.html), o XML, o PDF e as imagens. O relatório entra quando já existe."""
    buf = io.BytesIO()
    dentro = pasta_pacote + "/"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        xml = next(pasta.glob("*.xml"), None)
        if xml:
            z.write(str(xml), dentro + f"{base}.xml")
        pdf = pasta / "original.pdf"
        if pdf.exists():
            z.write(str(pdf), dentro + f"{base}.pdf")
        # entrada DOCX: o PDF de publicação ainda não existe, e o guia exige um por idioma.
        # O relatório do pacote registra a falta; o .zip não sai com um PDF inventado.
        for img in sorted((pasta / "pacote").glob("*")) if (pasta / "pacote").exists() else []:
            z.write(str(img), dentro + img.name)
        if relatorio:
            z.writestr(dentro + entrega.RELATORIO, relatorio)
    return buf.getvalue()


def monta_pacote(pasta: Path) -> bytes:
    """Pacote SPS com o relatório de validação dentro, e o relatório já com a conferência do guia.
    É preciso montar duas vezes: a conferência lê o .zip, e o resultado dela entra no relatório."""
    import tempfile

    pasta_pacote, base, _revista, _lote = nome_pacote(pasta)
    val = le_json(pasta / "validacao.json", {}) or {}
    temporaria = Path(tempfile.mkdtemp(prefix="xmljats-pac-"))
    provisorio = temporaria / f"{pasta_pacote}.zip"  # a conferência compara o nome do .zip com o da pasta
    provisorio.write_bytes(_zip_bruto(pasta, base, entrega.relatorio_html(base, val, {"itens": []}), pasta_pacote))
    try:
        conf = entrega.confere_pacote(str(provisorio))
    except Exception:  # noqa: BLE001
        conf = {"itens": []}
    finally:
        provisorio.unlink(missing_ok=True)
        try:
            temporaria.rmdir()
        except OSError:
            pass
    return _zip_bruto(pasta, base, entrega.relatorio_html(base, val, conf), pasta_pacote)


def caminho_pacote(pasta: Path) -> Path:
    """Grava o .zip na pasta do documento (o FTP precisa de um arquivo, não de bytes na memória).
    O .zip tem o nome da pasta interna, como a SPS 1.10 pede; um .zip antigo com outro nome sai."""
    pasta_pacote, _base, _revista, _lote = nome_pacote(pasta)
    destino = pasta / f"{pasta_pacote}.zip"
    for velho in pasta.glob("*.zip"):
        if velho != destino:
            velho.unlink()
    destino.write_bytes(monta_pacote(pasta))
    return destino


@app.get("/doc/{doc_id}/entrega", response_class=HTMLResponse)
def entrega_form(request: Request, doc_id: str, usuario: dict = Depends(autentica), mensagem: str = "", erro: str = ""):
    """Conferência do pacote contra o guia de entrega da SciELO e o depósito no FTP da coleção."""
    pasta = _pasta(doc_id, usuario)
    val = le_json(pasta / "validacao.json", {}) or {}
    cfg = le_json(pasta / "config.json", {}) or {}
    revista = next((x for x in carrega_revistas() if x["acronimo"] == (cfg.get("revista") or "")), None)
    conferencia = None
    try:
        conferencia = entrega.confere_pacote(str(caminho_pacote(pasta)))
    except HTTPException:
        pass
    ftp = entrega.config_ftp(CORREIO.config())
    lote = lote_do_documento(pasta, revista, val)
    try:
        pasta_pacote = nome_pacote(pasta)[0]
    except HTTPException:
        pasta_pacote = val.get("nome_base") or "pacote"
    acr = (revista or {}).get("acronimo") or ""
    meta = entrega.metadados(val)
    assunto, corpo = entrega.email_deposito(revista or {}, meta, lote, ftp["colecao_sigla"], f"{pasta_pacote}.zip",
                                            entrega.caminho_ftp(ftp, acr))
    ano = entrega.ano_do_volume(meta)
    return templates.TemplateResponse(request, "entrega.html", {
        "id": doc_id, "r": val, "usuario": usuario, "revista": revista, "conferencia": conferencia,
        "ftp": ftp, "email_scielo": entrega.EMAIL_SCIELO,
        "mensagem": mensagem, "erro": erro, "etapa": cfg.get("etapa") or "recebido",
        "colecoes": entrega.COLECOES_ATESTADO,
        "lote": lote, "lote_gravado": cfg.get("lote"), "pasta_pacote": pasta_pacote,
        "codigo_lote": entrega.codigo_lote(lote, ano) if (lote and ano) else "????",
        "continua": entrega.continua(revista or {}), "assunto": assunto, "corpo": corpo,
        "caminho_ftp": entrega.caminho_ftp(ftp, acr), "caminho_ftp_correcao": entrega.caminho_ftp(ftp, acr, True),
    })


@app.post("/doc/{doc_id}/entrega")
async def entrega_deposita(request: Request, doc_id: str, usuario: dict = Depends(exige_admin)):
    """Deposita o .zip no FTP da SciELO e deixa o aviso obrigatório pronto no correio."""
    pasta = _pasta(doc_id, usuario)
    form = await request.form()
    correcao = str(form.get("correcao") or "") == "1"
    val = le_json(pasta / "validacao.json", {}) or {}
    cfg = le_json(pasta / "config.json", {}) or {}
    revista = next((x for x in carrega_revistas() if x["acronimo"] == (cfg.get("revista") or "")), None) or {}
    if not val.get("pronto"):
        return RedirectResponse(url=f"/doc/{doc_id}/entrega?erro=" + urllib.parse.quote(
            "Este documento ainda não está pronto: resolva os bloqueantes em Revisar e editar antes de depositar."), status_code=303)
    zipe = caminho_pacote(pasta)
    conf = entrega.confere_pacote(str(zipe))
    if not conf["ok"]:
        falhas = "; ".join(i["que"] for i in conf["itens"] if not i["ok"])
        return RedirectResponse(url=f"/doc/{doc_id}/entrega?erro=" + urllib.parse.quote(
            f"O pacote não passa na conferência do guia ({falhas}). Corrija antes de depositar."), status_code=303)
    acr = revista.get("acronimo") or ""
    r = await run_in_threadpool(entrega.deposita, CORREIO.config(), str(zipe), correcao, acronimo=acr)
    if not r["ok"]:
        return RedirectResponse(url=f"/doc/{doc_id}/entrega?erro=" + urllib.parse.quote(r["mensagem"]), status_code=303)
    ftp = entrega.config_ftp(CORREIO.config())
    lote = lote_do_documento(pasta, revista or None, val)
    meta = entrega.metadados(val)
    assunto, corpo = entrega.email_deposito(revista, meta, lote, ftp["colecao_sigla"], zipe.name,
                                            entrega.caminho_ftp(ftp, acr, correcao), correcao=correcao)
    # o guia manda avisar a SciELO com cópia à equipe editorial da revista
    para = [entrega.EMAIL_SCIELO] + ([revista["email_editorial"]] if revista.get("email_editorial") else [])
    CORREIO.cria(para, assunto, corpo, caixa="rascunhos", tipo="scielo", por=usuario["nome"])
    if lote is not None and revista and not correcao:
        registra_lote(revista, meta, lote, doc_id, zipe.name)
        cfg["lote"] = lote
    cfg["etapa"] = "entregue"
    cfg.setdefault("historico_etapas", []).append({"etapa": "entregue", "por": usuario["nome"], "em": tempo.agora_iso(),
                                                   "nota": f"depositado no FTP da SciELO ({zipe.name})"})
    cfg["entrega"] = {"em": tempo.agora_iso(), "por": usuario["nome"], "arquivo": zipe.name, "correcao": correcao,
                      "passos": r["passos"]}
    grava_json(pasta / "config.json", cfg)
    return RedirectResponse(url=f"/doc/{doc_id}/entrega?mensagem=" + urllib.parse.quote(
        r["mensagem"] + " O aviso já está como rascunho no correio, pronto para revisar e enviar."), status_code=303)


@app.post("/doc/{doc_id}/entrega/lote")
async def entrega_lote(request: Request, doc_id: str, usuario: dict = Depends(exige_admin)):
    """Número do lote deste depósito (SPS 1.10: sequência por volume/número em publicação contínua)."""
    pasta = _pasta(doc_id, usuario)
    form = await request.form()
    bruto = str(form.get("lote") or "").strip()
    if not bruto.isdigit() or not (1 <= int(bruto) <= 999):
        return RedirectResponse(url=f"/doc/{doc_id}/entrega?erro=" + urllib.parse.quote("Lote: número inteiro de 1 a 999."),
                                status_code=303)
    cfg = le_json(pasta / "config.json", {}) or {}
    cfg["lote"] = int(bruto)
    grava_json(pasta / "config.json", cfg)
    for velho in pasta.glob("*.zip"):  # o nome do pacote muda com o lote
        velho.unlink()
    return RedirectResponse(url=f"/doc/{doc_id}/entrega?mensagem=" + urllib.parse.quote(f"Lote {int(bruto):02d} guardado."),
                            status_code=303)


@app.post("/admin/config/ftp")
async def salva_ftp(request: Request, usuario: dict = Depends(exige_admin)):
    form = dict((await request.form()).items())
    try:
        CORREIO.salva_ftp({**form, "tls": bool(form.get("tls"))})
    except ValueError as e:
        return RedirectResponse(url="/admin/config?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/config?mensagem=" + urllib.parse.quote("Credenciais do FTP da SciELO salvas."), status_code=303)


@app.post("/admin/config/ftp/testar")
def testa_ftp(usuario: dict = Depends(exige_admin)):
    r = entrega.testa_conexao(CORREIO.config())
    extra = (" Pastas no servidor: " + ", ".join(r["pastas"])) if r.get("pastas") else ""
    chave = "mensagem" if r["ok"] else "erro"
    return RedirectResponse(url=f"/admin/config?{chave}=" + urllib.parse.quote(r["mensagem"] + extra), status_code=303)


@app.post("/admin/config/atestado")
async def pede_atestado(request: Request, usuario: dict = Depends(exige_admin)):
    """Monta o pedido do atestado de capacidade técnica (o 'selo') como rascunho no correio."""
    form = await request.form()
    empresa = str(form.get("empresa") or "").strip()
    cnpj = str(form.get("cnpj") or "").strip()
    contato = str(form.get("contato") or "").strip()
    if not (empresa and cnpj):
        return RedirectResponse(url="/admin/config?erro=" + urllib.parse.quote(
            "O pedido do atestado exige o nome da empresa e o CNPJ: a SciELO só avalia pessoa jurídica."), status_code=303)
    assunto, corpo = entrega.email_atestado(empresa, cnpj, contato or usuario.get("email") or "")
    CORREIO.cria(entrega.EMAIL_SCIELO, assunto, corpo, caixa="rascunhos", tipo="scielo", por=usuario["nome"])
    return RedirectResponse(url="/admin/correio?caixa=rascunhos&mensagem=" + urllib.parse.quote(
        "Pedido do atestado montado como rascunho. Confira e envie."), status_code=303)


@app.get("/doc/{doc_id}/img/{nome}")
def imagem(doc_id: str, nome: str, usuario: dict = Depends(autentica)):
    if not re.fullmatch(r"(fig|eq|tab)\d{2}\.[a-z0-9]{2,5}", nome):  # figuras extraídas e as enviadas na revisão
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
    return templates.TemplateResponse(request, "revistas.html", {"revistas": revistas_para(usuario), "usuario": usuario, "mensagem": mensagem})


def _form_revista(request: Request, usuario: dict, v: dict, erros: dict, nova: bool, docs_da_revista=None, busca=None):
    return templates.TemplateResponse(request, "revista_form.html", {"usuario": usuario, "v": v, "erros": erros, "nova": nova, "licencas": LICENCAS,
                                                                     "areas": AREAS, "estilos": ESTILOS_REF, "busca": busca,
                                                                     "docs_da_revista": docs_da_revista}, status_code=400 if erros else 200)


@app.get("/revistas/nova", response_class=HTMLResponse)
def revista_nova(request: Request, usuario: dict = Depends(autentica), issn: str = ""):
    """Formulário em branco ou preenchido com o que as bases de ISSN sabem (quem cadastra confere antes de salvar)."""
    v = {"licenca_url": LICENCAS[0][0], "modo_publicacao": "continua"}
    busca = None
    if issn.strip():
        busca = issn_api.consulta(issn)
        v.update(sugestao_de_issn(busca) if busca.get("ok") else {"issn_epub": issn_api.normaliza(issn)})
    return _form_revista(request, usuario, v, {}, True, busca=busca)


@app.get("/revistas/consulta")
def revista_consulta(numero: str = "", usuario: dict = Depends(autentica)):
    """Consulta um ISSN nas bases e devolve JSON. Usada pelo campo 'Detectar pelo ISSN' do validador e do revisar."""
    lista = carrega_revistas()
    alvo = issn_api.normaliza(numero)
    ja = next((r for r in lista if alvo in {(r.get("issn_epub") or "").upper(), (r.get("issn_ppub") or "").upper()}), None)
    if ja and ja["acronimo"] not in {r["acronimo"] for r in revistas_para(usuario)}:
        return {"ok": False, "cadastrada": True, "oculta": True, "issn": alvo, "dados": {}, "fontes": [],
                "mensagem": (f"O ISSN {alvo} já está cadastrado como {ja['titulo']} ({ja['acronimo']}) por outra organização. "
                             "Peça ao administrador para torná-la pública ou vinculá-la à sua organização.")}
    if ja:
        return {"ok": True, "cadastrada": True, "acronimo": ja["acronimo"], "issn": alvo,
                "mensagem": f"Já cadastrada: {ja['titulo']} ({ja['acronimo']}).",
                "dados": {k: ja.get(k) for k in ("titulo", "abrev", "editora", "issn_epub", "acronimo")}, "fontes": []}
    r = issn_api.consulta(numero)
    return {"ok": bool(r.get("ok")), "cadastrada": False, "issn": r.get("issn"), "mensagem": r.get("mensagem"),
            "dados": r.get("dados") or {}, "origem": r.get("origem") or {}, "fontes": r.get("fontes") or []}


@app.post("/revistas/importar")
async def revista_importar(request: Request, usuario: dict = Depends(autentica)):
    """Cadastra a revista a partir do ISSN, com o que as bases responderam. Quem valida precisa da revista no cadastro;
    editar e remover continuam sendo do administrador."""
    form = await request.form()
    acr, msg, _ = await run_in_threadpool(revista_por_issn, str(form.get("numero") or ""), usuario)
    voltar = str(form.get("voltar") or "/revistas")
    if not voltar.startswith("/"):
        voltar = "/revistas"
    sep = "&" if "?" in voltar else "?"
    extra = ("&revista=" + urllib.parse.quote(acr)) if acr else ""
    return RedirectResponse(url=f"{voltar}{sep}mensagem=" + urllib.parse.quote(msg) + extra, status_code=303)


@app.post("/revistas/nova", response_class=HTMLResponse)
async def revista_criar(request: Request, usuario: dict = Depends(autentica)):
    form = dict((await request.form()).items())
    lista = carrega_revistas()
    dados, erros = valida_revista(form, lista)
    if erros:
        return _form_revista(request, usuario, {**form, "na_scielo": dados["na_scielo"]}, erros, True)
    _marca_dona(dados, usuario)
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
    vis = str(form.get("visibilidade") or "")  # "Quem vê esta revista": pública, de uma organização ou como estava
    if vis == "publica":
        dados["organizacao"], dados["dono"] = None, None
    elif vis.startswith("org:") and ORGS.por_id(vis[4:]):
        dados["organizacao"], dados["dono"] = vis[4:], None
    else:
        dados["organizacao"], dados["dono"] = rev.get("organizacao"), rev.get("dono")
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
def painel(request: Request, usuario: dict = Depends(autentica), revista: str = "", etapa: str = "", situacao: str = "",
           ordem: str = "atualizado", mensagem: str = ""):
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
    docs = ordena_docs(docs, ordem)
    filtros = {"revista": revista, "etapa": etapa, "situacao": situacao, "ordem": ordem if ordem != "atualizado" else ""}
    query = "?" + urllib.parse.urlencode({k: v for k, v in filtros.items() if v}) if any(filtros.values()) else ""
    return templates.TemplateResponse(request, "painel.html", {"docs": docs, "revistas": revistas_para(usuario), "etapas": ETAPAS, "filtros": filtros,
                                                               "filtro_ativo": any(v for k, v in filtros.items() if k != "ordem"),
                                                               "query": query, "usuario": usuario, "ordens": ORDENS, "ordem": ordem,
                                                               "total_docs": len(lista_docs(0, usuario)), "mensagem": mensagem,
                                                               "em_fila": any(d.get("estado") in ("na_fila", "processando") for d in docs)})


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
    ip, navegador = de_onde(request)
    chaves = (f"login:ip:{ip}", f"login:email:{email.strip().lower()}")
    espera = max((freio_conta(k, FREIO_LIMITE) or 0) for k in chaves)
    if espera:
        return templates.TemplateResponse(request, "entrar.html", {"proximo": proximo, "usuario": None, "email": email, "erro": (
            f"Muitas tentativas seguidas. Aguarde {freio_minutos(espera)} e tente de novo.")}, status_code=429)
    u = CONTAS.autentica(email, senha)
    if not u:
        for k in chaves:
            freio_marca(k)
        return templates.TemplateResponse(request, "entrar.html", {"proximo": proximo, "usuario": None, "email": email, "erro": "E-mail ou senha não conferem."}, status_code=401)
    freio_limpa(chaves[1])
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
    ip, navegador = de_onde(request)
    espera = freio_conta(f"registro:ip:{ip}", FREIO_REGISTROS)
    if espera:
        return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "form": form, "erro": (
            f"Muitas contas criadas deste endereço em pouco tempo. Aguarde {freio_minutos(espera)} e tente de novo.")}, status_code=429)
    if (form.get("senha") or "") != (form.get("senha2") or ""):
        return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "erro": "As duas senhas não são iguais.", "form": form}, status_code=400)
    convite = str(form.get("convite") or "").strip()
    nova_org = " ".join(str(form.get("organizacao_nova") or "").split())
    org = None
    if convite:
        org = ORGS.por_convite(convite)
        if not org:
            return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "form": form, "erro": (
                "Código de convite não encontrado. Confira com quem passou o código.")}, status_code=400)
    elif nova_org:
        try:
            ORGS.valida_nome(nova_org, ORGS.lista())
        except ValueError as e:
            return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "erro": str(e), "form": form}, status_code=400)
    try:
        u = CONTAS.cria(form.get("email", ""), form.get("nome", ""), form.get("senha", ""), "cliente", novidades_vistas=VERSAO_APP)
    except ValueError as e:
        return templates.TemplateResponse(request, "registrar.html", {"usuario": None, "erro": str(e), "form": form}, status_code=400)
    if org:
        CONTAS.define_organizacao(u["id"], org["id"])
    elif nova_org:
        CONTAS.define_organizacao(u["id"], ORGS.cria(nova_org, por=u["id"])["id"])
    freio_marca(f"registro:ip:{ip}")
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


@app.post("/conta/organizacao")
async def conta_organizacao(request: Request, usuario: dict = Depends(autentica)):
    """Cliente entra numa organização pelo código de convite ou cria a sua. Só quem ainda não está em nenhuma;
    trocar é com o administrador, porque muda quem vê o quê."""
    form = await request.form()
    if usuario.get("papel") != "cliente" or usuario.get("id") in ("local", "api"):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote("Organização é para contas de cliente."), status_code=303)
    atual = CONTAS.por_id(usuario["id"]) or usuario
    if atual.get("organizacao"):
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote(
            "Você já está numa organização; para trocar, fale com o administrador."), status_code=303)
    convite = str(form.get("convite") or "").strip()
    nome = " ".join(str(form.get("nome") or "").split())
    try:
        if convite:
            org = ORGS.por_convite(convite)
            if not org:
                raise ValueError("Código de convite não encontrado.")
        elif nome:
            org = ORGS.cria(nome, por=usuario["id"])
        else:
            raise ValueError("Informe o código de convite ou o nome da nova organização.")
        CONTAS.define_organizacao(usuario["id"], org["id"])
    except ValueError as e:
        return RedirectResponse(url="/conta?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/conta?mensagem=" + urllib.parse.quote(
        f"Você está na organização {org['nome']}. Os documentos novos passam a ser dela; os antigos continuam só seus."), status_code=303)


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
        "ftp": entrega.config_ftp(c), "email_scielo": entrega.EMAIL_SCIELO, "colecoes": entrega.COLECOES_ATESTADO,
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


@app.post("/admin/config/confirmacao")
async def config_confirmacao(request: Request, usuario: dict = Depends(exige_admin)):
    """Liga ou desliga a confirmação de conta por e-mail, sem mexer no resto da configuração."""
    form = await request.form()
    exigir = str(form.get("exigir") or "") == "1"
    try:
        CORREIO.define_confirmacao(exigir)
    except ValueError as e:
        return RedirectResponse(url="/admin/config?erro=" + urllib.parse.quote(str(e)), status_code=303)
    recado = "Confirmação de e-mail passa a ser obrigatória no cadastro." if exigir else         "Confirmação de e-mail desativada: quem se cadastrar já pode enviar arquivos."
    return RedirectResponse(url="/admin/config?mensagem=" + urllib.parse.quote(recado), status_code=303)


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


# ---------------------------------------------------------------- novidades por versão

def _marca_novidades_vistas(usuario: dict) -> None:
    if usuario.get("id") in ("local", "api"):
        return
    try:
        CONTAS.marca_novidades(usuario["id"], VERSAO_APP)
    except ValueError:
        pass


@app.get("/novidades", response_class=HTMLResponse)
def novidades_pagina(request: Request, usuario: dict = Depends(autentica)):
    """Histórico do que mudou, só com o que este papel pode ver. Abrir a página conta como 'visto'."""
    novas = {v["versao"] for v in novidades.pendentes(usuario)}
    _marca_novidades_vistas(usuario)
    return templates.TemplateResponse(request, "novidades.html", {
        "usuario": usuario, "versoes": novidades.visiveis(usuario.get("papel") or "cliente"), "novas": novas})


@app.post("/novidades/vista")
async def novidades_vista(request: Request, usuario: dict = Depends(autentica)):
    """Botão 'Entendi' (ou fechar) da janela: registra a versão e volta para onde a pessoa estava."""
    form = await request.form()
    _marca_novidades_vistas(usuario)
    proximo = str(form.get("proximo") or "/")
    if not proximo.startswith("/") or proximo.startswith("//"):
        proximo = "/"
    return RedirectResponse(url=proximo, status_code=303)


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
    medidos = [d["duracao_s"] for d in docs if isinstance(d.get("duracao_s"), (int, float))]
    tempo_medio = round(sum(medidos) / len(medidos), 1) if medidos else None
    # taxa de erro do motor, medida pelo que o revisor precisou corrigir à mão (campos editados por artigo)
    corrigidos = [d["editados"] for d in docs if isinstance(d.get("editados"), int)]
    media_editados = round(sum(corrigidos) / len(corrigidos), 1) if corrigidos else None
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
        "tempo_medio": tempo_medio, "medidos": len(medidos), "media_editados": media_editados,
    })


@app.get("/admin/documentos", response_class=HTMLResponse)
def admin_documentos(request: Request, usuario: dict = Depends(exige_admin), revista: str = "", etapa: str = "",
                     situacao: str = "", dono: str = "", ordem: str = "atualizado", organizacao: str = ""):
    docs = lista_docs(0)
    if organizacao:
        docs = [d for d in docs if (d.get("organizacao") or "") == organizacao]
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
    docs = ordena_docs(docs, ordem)
    filtros = {"revista": revista, "etapa": etapa, "situacao": situacao, "dono": dono, "organizacao": organizacao,
               "ordem": ordem if ordem != "atualizado" else ""}
    query = "?" + urllib.parse.urlencode({k: v for k, v in filtros.items() if v}) if any(filtros.values()) else ""
    return templates.TemplateResponse(request, "admin_docs.html", {
        "docs": docs, "revistas": carrega_revistas(), "etapas": ETAPAS, "filtros": filtros, "usuarios": CONTAS.lista(),
        "filtro_ativo": any(v for k, v in filtros.items() if k != "ordem"), "query": query, "usuario": usuario,
        "ordens": ORDENS, "ordem": ordem})


@app.post("/sair")
def sair():
    resp = RedirectResponse(url="/entrar", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- organizações (administração)

def _organizacoes_com_totais() -> list:
    usuarios = CONTAS.lista()
    docs = lista_docs(0)
    revistas = carrega_revistas()
    saida = []
    for o in ORGS.lista():
        saida.append({**o, "membros": sum(1 for u in usuarios if u.get("organizacao") == o["id"]),
                      "nomes": sorted(u["nome"] for u in usuarios if u.get("organizacao") == o["id"]),
                      "docs": sum(1 for d in docs if d.get("organizacao") == o["id"]),
                      "revistas": sum(1 for r in revistas if r.get("organizacao") == o["id"])})
    return saida


@app.get("/admin/organizacoes", response_class=HTMLResponse)
def admin_organizacoes(request: Request, usuario: dict = Depends(exige_admin), mensagem: str = "", erro: str = ""):
    return templates.TemplateResponse(request, "admin_orgs.html", {"usuario": usuario, "organizacoes": _organizacoes_com_totais(),
                                                                   "mensagem": mensagem, "erro": erro})


@app.post("/admin/organizacoes")
async def admin_organizacao_criar(request: Request, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    try:
        o = ORGS.cria(str(form.get("nome") or ""), por=usuario["id"])
    except ValueError as e:
        return RedirectResponse(url="/admin/organizacoes?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/organizacoes?mensagem=" + urllib.parse.quote(
        f"Organização {o['nome']} criada. Código de convite: {o['convite']}."), status_code=303)


@app.post("/admin/organizacoes/{oid}/nome")
async def admin_organizacao_nome(request: Request, oid: str, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    try:
        o = ORGS.renomeia(oid, str(form.get("nome") or ""))
    except ValueError as e:
        return RedirectResponse(url="/admin/organizacoes?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/organizacoes?mensagem=" + urllib.parse.quote(f"Organização renomeada para {o['nome']}."), status_code=303)


@app.post("/admin/organizacoes/{oid}/convite")
def admin_organizacao_convite(oid: str, usuario: dict = Depends(exige_admin)):
    try:
        o = ORGS.novo_convite(oid)
    except ValueError as e:
        return RedirectResponse(url="/admin/organizacoes?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/organizacoes?mensagem=" + urllib.parse.quote(
        f"Novo código de {o['nome']}: {o['convite']}. O antigo deixou de valer."), status_code=303)


@app.post("/admin/organizacoes/{oid}/remover")
def admin_organizacao_remover(oid: str, usuario: dict = Depends(exige_admin)):
    if any(u.get("organizacao") == oid for u in CONTAS.lista()):
        return RedirectResponse(url="/admin/organizacoes?erro=" + urllib.parse.quote(
            "A organização ainda tem membros: desvincule as contas em Usuários antes de remover."), status_code=303)
    try:
        ORGS.remove(oid)
    except ValueError as e:
        return RedirectResponse(url="/admin/organizacoes?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/organizacoes?mensagem=" + urllib.parse.quote("Organização removida."), status_code=303)


@app.post("/usuarios/{uid}/novidades")
def usuario_novidades(uid: str, usuario: dict = Depends(exige_admin)):
    """A janela de novidades volta a aparecer para esta conta: mostra de novo a última versão que tem algo para o papel dela."""
    alvo = CONTAS.por_id(uid)
    if not alvo:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote("Usuário não encontrado."), status_code=303)
    visiveis = novidades.visiveis(alvo.get("papel") or "cliente")
    anterior = visiveis[1]["versao"] if len(visiveis) > 1 else None
    try:
        CONTAS.marca_novidades(uid, anterior)
    except ValueError as e:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote("As novidades da versão atual vão aparecer de novo para esta conta."), status_code=303)


@app.post("/usuarios/{uid}/organizacao")
async def usuario_organizacao(request: Request, uid: str, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    oid = str(form.get("organizacao") or "").strip() or None
    if oid and not ORGS.por_id(oid):
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote("Organização não encontrada."), status_code=303)
    try:
        CONTAS.define_organizacao(uid, oid)
    except ValueError as e:
        return RedirectResponse(url="/usuarios?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/usuarios?mensagem=" + urllib.parse.quote(
        f"Conta vinculada a {ORGS.nome_de(oid)}." if oid else "Conta desvinculada de organização."), status_code=303)


# ---------------------------------------------------------------- lotes de entrega (administração)

def _pasta_lote_ok(pasta: str) -> str:
    if not pasta or entrega.confere_nome_pasta(pasta):
        raise HTTPException(404, "Lote não encontrado.")
    return pasta


@app.get("/admin/lotes", response_class=HTMLResponse)
def admin_lotes(request: Request, usuario: dict = Depends(exige_admin), mensagem: str = "", erro: str = ""):
    """Documentos prontos agrupados por revista e volume/número, para juntar até 5 num só pacote; e os lotes já montados."""
    revistas = {r["acronimo"]: r for r in carrega_revistas()}
    grupos = []
    for (acr, vol, num), docs in sorted(lotes.candidatos().items()):
        rev = revistas.get(acr) or {}
        meta = entrega.metadados(le_json(DOCS / docs[0]["id"] / "validacao.json", {}) or {})
        grupos.append({"acronimo": acr, "revista": rev.get("titulo") or acr, "volume": vol, "numero": num, "docs": docs,
                       "continua": entrega.continua(rev), "proximo": proximo_lote(rev, meta) if rev else 1})
    return templates.TemplateResponse(request, "admin_lotes.html", {"usuario": usuario, "grupos": grupos, "pacotes": lotes.pacotes(),
                                                                    "mensagem": mensagem, "erro": erro})


@app.post("/admin/lotes")
async def admin_lote_criar(request: Request, usuario: dict = Depends(exige_admin)):
    form = await request.form()
    ids = [str(x) for x in form.getlist("doc")]
    bruto = str(form.get("lote") or "").strip()
    lote = int(bruto) if bruto.isdigit() and 1 <= int(bruto) <= 999 else None
    try:
        rec = await run_in_threadpool(lotes.cria, ids, lote, usuario["nome"])  # monta o .zip e confere: fora do event loop
    except ValueError as e:
        return RedirectResponse(url="/admin/lotes?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url=f"/admin/lotes/{rec['pasta']}?mensagem=" + urllib.parse.quote(
        f"Lote montado com {len(rec['docs'])} XML(s). Confira o pacote e o aviso antes de depositar."), status_code=303)


def _tela_lote(request: Request, usuario: dict, pasta: str, mensagem: str = "", erro: str = ""):
    rec = lotes.por_pasta(pasta)
    if not rec:
        raise HTTPException(404, "Lote não encontrado.")
    zipe = lotes.caminho_zip(pasta)
    conferencia = entrega.confere_pacote(str(zipe)) if zipe.exists() else None
    revista = next((r for r in carrega_revistas() if r["acronimo"] == rec["revista"]), None) or {}
    docs = []
    for i in rec.get("docs", []):
        val = le_json(DOCS / i / "validacao.json", {}) or {}
        cfg = le_json(DOCS / i / "config.json", {}) or {}
        docs.append({"id": i, "titulo": val.get("titulo") or val.get("arquivo_original") or i, "nome_base": val.get("nome_base"),
                     "etapa": cfg.get("etapa") or "recebido", "criado_por": cfg.get("criado_por")})
    ftp = entrega.config_ftp(CORREIO.config())
    acr = rec["revista"]
    meta = {"volume": rec.get("volume"), "numero": rec.get("numero"), "ano": rec.get("ano"), "titulo": f"{len(docs)} artigo(s) do lote"}
    assunto, corpo = entrega.email_deposito(revista, meta, rec.get("lote"), ftp["colecao_sigla"], f"{pasta}.zip",
                                            entrega.caminho_ftp(ftp, acr), total_xml=len(docs))
    return templates.TemplateResponse(request, "admin_lote.html", {
        "usuario": usuario, "p": rec, "docs": docs, "conferencia": conferencia, "revista": revista, "ftp": ftp,
        "email_scielo": entrega.EMAIL_SCIELO, "assunto": assunto, "corpo": corpo, "mensagem": mensagem, "erro": erro,
        "caminho_ftp": entrega.caminho_ftp(ftp, acr), "caminho_ftp_correcao": entrega.caminho_ftp(ftp, acr, True)})


@app.get("/admin/lotes/{pasta}", response_class=HTMLResponse)
def admin_lote(request: Request, pasta: str, usuario: dict = Depends(exige_admin), mensagem: str = "", erro: str = ""):
    return _tela_lote(request, usuario, _pasta_lote_ok(pasta), mensagem, erro)


@app.get("/admin/lotes/{pasta}/pacote.zip")
def admin_lote_zip(pasta: str, usuario: dict = Depends(exige_admin)):
    z = lotes.caminho_zip(_pasta_lote_ok(pasta))
    if not z.exists():
        raise HTTPException(404, "O .zip do lote não existe mais.")
    return FileResponse(str(z), media_type="application/zip", filename=z.name)


@app.post("/admin/lotes/{pasta}/desfazer")
def admin_lote_desfazer(pasta: str, usuario: dict = Depends(exige_admin)):
    pasta = _pasta_lote_ok(pasta)
    try:
        lotes.desfaz(pasta)
    except ValueError as e:
        return RedirectResponse(url=f"/admin/lotes/{pasta}?erro=" + urllib.parse.quote(str(e)), status_code=303)
    return RedirectResponse(url="/admin/lotes?mensagem=" + urllib.parse.quote(f"Lote {pasta} desfeito; os documentos voltaram a ficar disponíveis."),
                            status_code=303)


@app.post("/admin/lotes/{pasta}/entrega")
async def admin_lote_entrega(request: Request, pasta: str, usuario: dict = Depends(exige_admin)):
    """Deposita o lote no FTP da SciELO, deixa o aviso pronto no correio e marca todos os artigos como entregues."""
    pasta = _pasta_lote_ok(pasta)
    rec = lotes.por_pasta(pasta)
    if not rec:
        raise HTTPException(404, "Lote não encontrado.")
    form = await request.form()
    correcao = str(form.get("correcao") or "") == "1"
    zipe = lotes.caminho_zip(pasta)
    if not zipe.exists():
        return RedirectResponse(url=f"/admin/lotes/{pasta}?erro=" + urllib.parse.quote("O .zip do lote não existe mais: desfaça e monte de novo."),
                                status_code=303)
    conf = entrega.confere_pacote(str(zipe))
    if not conf["ok"]:
        falhas = "; ".join(i["que"] for i in conf["itens"] if not i["ok"])
        return RedirectResponse(url=f"/admin/lotes/{pasta}?erro=" + urllib.parse.quote(
            f"O pacote não passa na conferência ({falhas}). Corrija antes de depositar."), status_code=303)
    revista = next((r for r in carrega_revistas() if r["acronimo"] == rec["revista"]), None) or {}
    acr = rec["revista"]
    r = await run_in_threadpool(entrega.deposita, CORREIO.config(), str(zipe), correcao, acronimo=acr)
    if not r["ok"]:
        return RedirectResponse(url=f"/admin/lotes/{pasta}?erro=" + urllib.parse.quote(r["mensagem"]), status_code=303)
    ftp = entrega.config_ftp(CORREIO.config())
    meta = {"volume": rec.get("volume"), "numero": rec.get("numero"), "ano": rec.get("ano"), "titulo": f"{len(rec['docs'])} artigo(s) do lote"}
    assunto, corpo = entrega.email_deposito(revista, meta, rec.get("lote"), ftp["colecao_sigla"], zipe.name,
                                            entrega.caminho_ftp(ftp, acr, correcao), correcao=correcao, total_xml=len(rec["docs"]))
    para = [entrega.EMAIL_SCIELO] + ([revista["email_editorial"]] if revista.get("email_editorial") else [])
    CORREIO.cria(para, assunto, corpo, caixa="rascunhos", tipo="scielo", por=usuario["nome"])
    lotes.marca_depositado(pasta, usuario["nome"], correcao, r["passos"])
    return RedirectResponse(url=f"/admin/lotes/{pasta}?mensagem=" + urllib.parse.quote(
        r["mensagem"] + " O aviso já está como rascunho no correio; todos os artigos do lote foram marcados como entregues."), status_code=303)


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
        u = CONTAS.cria(form.get("email", ""), form.get("nome", ""), form.get("senha", ""), form.get("papel", "operador"),
                        novidades_vistas=VERSAO_APP)
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
