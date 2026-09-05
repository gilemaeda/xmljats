"""
xmljats - site minimo (Fase 2, MVP): validador de PDF -> modelo -> XML SciELO PS -> packtools.

Rotas:
  GET  /                 validador + documentos recentes
  POST /validar          upload do PDF, extracao, geracao e validacao do XML
  GET  /doc/{id}         resultado (bloqueantes, avisos, packtools, resumo da extracao)
  GET  /doc/{id}/xml     download do XML (nome-base SPS)
  GET  /doc/{id}/modelo.json, /doc/{id}/resumo.md, /doc/{id}/validacao.json
  GET  /revistas         cadastro de revistas (modelos/revistas.json)
  GET  /saude            healthcheck

Protecao: se a variavel APP_SENHA estiver definida, todas as rotas (menos /saude) pedem HTTP Basic com essa senha.
Armazenamento: XMLJATS_DATA (padrao ./data) / docs / <id> / {original.pdf, model.json, resumo.md, <base>.xml, validacao.json}
"""
import datetime as dt
import io
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "poc"))

import extrair as cli  # noqa: E402  (poc/extrair.py)
import gerar_xml as gx  # noqa: E402  (poc/gerar_xml.py)
from extrator import xml_jats  # noqa: E402

DATA = Path(os.environ.get("XMLJATS_DATA", RAIZ / "data"))
DOCS = DATA / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
VERSAO_APP = "0.1.0"

app = FastAPI(title="xmljats", version=VERSAO_APP, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(RAIZ / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(RAIZ / "app" / "templates"))
seguranca = HTTPBasic(auto_error=False)


def autentica(cred: Optional[HTTPBasicCredentials] = Depends(seguranca)) -> str:
    senha = os.environ.get("APP_SENHA")
    if not senha:
        return "local"
    if cred and secrets.compare_digest(cred.password.encode(), senha.encode()):
        return cred.username or "usuario"
    raise HTTPException(status_code=401, detail="Senha necessária", headers={"WWW-Authenticate": "Basic realm=xmljats"})


def carrega_revistas():
    with io.open(RAIZ / "modelos" / "revistas.json", encoding="utf-8") as f:
        return json.load(f)["revistas"]


def lista_docs(limite=30):
    itens = []
    for pasta in DOCS.iterdir():
        v = pasta / "validacao.json"
        if v.exists():
            try:
                with io.open(v, encoding="utf-8") as f:
                    d = json.load(f)
                d["id"] = pasta.name
                nome = pasta / "nome_original.txt"
                if d.get("arquivo_original") in (None, "original.pdf") and nome.exists():
                    d["arquivo_original"] = nome.read_text(encoding="utf-8").strip()
                itens.append(d)
            except Exception:  # noqa: BLE001
                continue
    itens.sort(key=lambda d: d.get("criado_em", ""), reverse=True)
    return itens[:limite]


def processa(pasta: Path, versao_sps: str, acronimo: Optional[str]) -> dict:
    """Extrai, gera o XML, valida no packtools e grava tudo na pasta do documento."""
    pdf = pasta / "original.pdf"
    doc, model = cli.extrai(str(pdf))
    modelo = model.to_dict()
    with io.open(pasta / "model.json", "w", encoding="utf-8") as f:
        json.dump(modelo, f, ensure_ascii=False, indent=2)
    with io.open(pasta / "resumo.md", "w", encoding="utf-8") as f:
        f.write(cli.resumo_md(model))
    revistas = carrega_revistas()
    rev = next((r for r in revistas if r["acronimo"] == acronimo), None) if acronimo else None
    rev = rev or xml_jats.escolhe_revista(modelo, revistas)
    res = xml_jats.gera_xml(modelo, rev, versao=versao_sps)
    base = res.nome_base or "artigo"
    xml_path = pasta / f"{base}.xml"
    with open(xml_path, "wb") as f:
        f.write(res.xml)
    dtd_ok, sps_ok, erros, detalhe = gx.valida_packtools(str(xml_path))
    pronto = not res.bloqueantes and bool(dtd_ok) and bool(sps_ok)
    titulo = model.titulo_principal or ""
    nome_original = (pasta / "nome_original.txt").read_text(encoding="utf-8").strip() if (pasta / "nome_original.txt").exists() else modelo.get("arquivo")
    resultado = {
        "criado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "arquivo_original": nome_original,
        "titulo": titulo,
        "revista": rev["acronimo"] if rev else None,
        "revista_titulo": rev["titulo"] if rev else None,
        "versao_sps": versao_sps,
        "nome_base": base,
        "xml": xml_path.name,
        "pronto": pronto,
        "dtd_ok": dtd_ok,
        "sps_ok": sps_ok,
        "bloqueantes": res.bloqueantes,
        "avisos_gerador": res.avisos,
        "avisos_extrator": modelo.get("avisos", []),
        "packtools": erros,
        "packtools_detalhe": detalhe,
        "contagens": {
            "paginas": modelo.get("paginas"),
            "titulos": len(modelo.get("titulos", [])),
            "autores": len(modelo.get("autores", [])),
            "resumos": len(modelo.get("resumos", [])),
            "secoes": len(modelo.get("secoes", [])),
            "notas": len(modelo.get("notas", [])),
            "figuras": len(modelo.get("figuras", [])),
            "referencias": len(modelo.get("referencias", [])),
            "citacoes": len({(c["autor"], c["ano"]) for c in modelo.get("citacoes", [])}),
        },
        "extracao": {
            "doi": modelo.get("doi"),
            "idioma": modelo.get("idioma"),
            "heading": modelo.get("heading"),
            "volume": modelo.get("volume"), "numero": modelo.get("numero"), "elocation": modelo.get("elocation"),
            "datas": modelo.get("datas"),
            "licenca": modelo.get("licenca"),
            "titulos": modelo.get("titulos", []),
            "autores": [{"nome": a["nome_completo"], "orcid": a.get("orcid"), "email": a.get("email"),
                         "afiliacoes": [x for x in modelo.get("afiliacoes", []) if x["id"] in a.get("aff_ids", [])]} for a in modelo.get("autores", [])],
            "resumos": [{"rotulo": r["rotulo"], "idioma": r["idioma"], "palavras": len(r["texto"].split()), "palavras_chave": r["palavras_chave"]} for r in modelo.get("resumos", [])],
            "secoes": [{"titulo": s.get("titulo_completo") or s["titulo"], "nivel": s["nivel"], "paragrafos": len(s["paragrafos"])} for s in modelo.get("secoes", [])],
            "estilo_referencias": modelo.get("estilo_referencias"),
        },
    }
    with io.open(pasta / "validacao.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
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
def index(request: Request, usuario: str = Depends(autentica)):
    return templates.TemplateResponse(request, "index.html", {"revistas": carrega_revistas(), "docs": lista_docs(), "usuario": usuario})


@app.post("/validar")
async def validar(request: Request, arquivo: UploadFile = File(...), revista: str = Form(""), sps: str = Form("1.9"), usuario: str = Depends(autentica)):
    nome = arquivo.filename or "arquivo"
    if not nome.lower().endswith(".pdf"):
        raise HTTPException(400, "Por enquanto só PDF. O caminho DOCX vem na próxima fase.")
    conteudo = await arquivo.read()
    if len(conteudo) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Arquivo maior que {MAX_MB} MB.")
    if sps not in ("1.9", "1.10"):
        sps = "1.9"
    doc_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    pasta = DOCS / doc_id
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "original.pdf", "wb") as f:
        f.write(conteudo)
    with io.open(pasta / "nome_original.txt", "w", encoding="utf-8") as f:
        f.write(nome)
    try:
        processa(pasta, sps, revista or None)
    except Exception as e:  # noqa: BLE001
        with io.open(pasta / "erro.txt", "w", encoding="utf-8") as f:
            f.write(repr(e))
        raise HTTPException(500, f"Falha ao processar o PDF: {e}")
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


def _pasta(doc_id: str) -> Path:
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise HTTPException(404)
    pasta = DOCS / doc_id
    if not pasta.is_dir():
        raise HTTPException(404, "Documento não encontrado")
    return pasta


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def ver_doc(request: Request, doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
    v = pasta / "validacao.json"
    if not v.exists():
        raise HTTPException(404, "Documento sem resultado")
    with io.open(v, encoding="utf-8") as f:
        r = json.load(f)
    r["id"] = doc_id
    return templates.TemplateResponse(request, "resultado.html", {"r": r, "usuario": usuario})


@app.get("/doc/{doc_id}/xml")
def baixar_xml(doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
    xml = next(pasta.glob("*.xml"), None)
    if not xml:
        raise HTTPException(404)
    return FileResponse(str(xml), media_type="application/xml", filename=xml.name)


@app.get("/doc/{doc_id}/modelo.json")
def baixar_modelo(doc_id: str, usuario: str = Depends(autentica)):
    return FileResponse(str(_pasta(doc_id) / "model.json"), media_type="application/json", filename=f"{doc_id}-modelo.json")


@app.get("/doc/{doc_id}/validacao.json")
def baixar_validacao(doc_id: str, usuario: str = Depends(autentica)):
    return FileResponse(str(_pasta(doc_id) / "validacao.json"), media_type="application/json")


@app.get("/doc/{doc_id}/resumo.md", response_class=PlainTextResponse)
def ver_resumo(doc_id: str, usuario: str = Depends(autentica)):
    with io.open(_pasta(doc_id) / "resumo.md", encoding="utf-8") as f:
        return f.read()


@app.get("/revistas", response_class=HTMLResponse)
def revistas(request: Request, usuario: str = Depends(autentica)):
    return templates.TemplateResponse(request, "revistas.html", {"revistas": carrega_revistas(), "usuario": usuario})
