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
  GET  /revistas                cadastro de revistas (modelos/revistas.json)
  GET  /saude                   healthcheck

Protecao: se APP_SENHA estiver definida, todas as rotas (menos /saude) pedem HTTP Basic com essa senha.
Pasta do documento (XMLJATS_DATA/docs/<id>): original.pdf, nome_original.txt, model.json (extracao), edicoes.json
(overrides do usuario), config.json (revista, versao SPS), resumo.md, <base>.xml, validacao.json.
"""
import copy
import datetime as dt
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

import extrair as cli  # noqa: E402  (poc/extrair.py)
import gerar_xml as gx  # noqa: E402  (poc/gerar_xml.py)
from extrator import xml_jats  # noqa: E402
from extrator.util import RE_ORCID, orcid_valido  # noqa: E402

DATA = Path(os.environ.get("XMLJATS_DATA", RAIZ / "data"))
DOCS = DATA / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
VERSAO_APP = "0.3.0"

app = FastAPI(title="xmljats", version=VERSAO_APP, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(RAIZ / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(RAIZ / "app" / "templates"))
templates.env.globals["versao"] = VERSAO_APP


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
    "A09": ["data_publicado", "ano"], "H01": ["data_recebido", "data_aceito"], "H02": ["data_recebido", "data_aceito"],
    "A04": ["heading"], "A01": ["doi"], "A02": ["order"], "A08": ["volume", "numero", "elocation"], "A05": ["titulo_0_texto"],
    "A03": ["tipo_artigo"], "L01": ["licenca"], "J01": ["revista"], "J03": ["revista"], "J05": ["revista"], "C07": ["corresp"],
}
TIPOS_ARTIGO = ["research-article", "review-article", "editorial", "book-review", "letter", "brief-report", "case-report",
                "article-commentary", "correction", "retraction", "addendum", "rapid-communication", "other"]
IDIOMAS = ["pt", "en", "es", "fr", "it", "de"]
CAMPOS_SIMPLES = ("heading", "tipo_artigo", "idioma", "volume", "numero", "ano", "elocation", "order", "doi", "licenca")
RE_CAMPO_LISTA = re.compile(r"^(titulo|autor|aff|resumo)_(\d+)_(\w+)$")


# ---------------------------------------------------------------- utilidades

def autentica(cred: Optional[HTTPBasicCredentials] = Depends(seguranca)) -> str:
    senha = os.environ.get("APP_SENHA")
    if not senha:
        return "local"
    if cred and secrets.compare_digest(cred.password.encode(), senha.encode()):
        return cred.username or "usuario"
    raise HTTPException(status_code=401, detail="Senha necessária", headers={"WWW-Authenticate": "Basic realm=xmljats"})


def le_json(caminho: Path, padrao=None):
    if not caminho.exists():
        return padrao
    with io.open(caminho, encoding="utf-8") as f:
        return json.load(f)


def grava_json(caminho: Path, obj):
    with io.open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def carrega_revistas():
    return le_json(RAIZ / "modelos" / "revistas.json")["revistas"]


def _pasta(doc_id: str) -> Path:
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise HTTPException(404)
    pasta = DOCS / doc_id
    if not pasta.is_dir():
        raise HTTPException(404, "Documento não encontrado")
    return pasta


def lista_docs(limite=30):
    itens = []
    for pasta in DOCS.iterdir():
        d = le_json(pasta / "validacao.json")
        if not d:
            continue
        d["id"] = pasta.name
        nome = pasta / "nome_original.txt"
        if d.get("arquivo_original") in (None, "original.pdf") and nome.exists():
            d["arquivo_original"] = nome.read_text(encoding="utf-8").strip()
        itens.append(d)
    itens.sort(key=lambda d: d.get("criado_em", ""), reverse=True)
    return itens[:limite]


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
    """codigo da regra em cada bloqueante -> campos do formulario a destacar."""
    out = {}
    for b in bloqueantes:
        for cod in re.findall(r"\(([A-Z]\d{2})\)", b):
            for campo in CAMPOS_POR_REGRA.get(cod, []):
                out.setdefault(campo, []).append(b)
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

def extrai_e_salva(pasta: Path):
    doc, model = cli.extrai(str(pasta / "original.pdf"))
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
    pronto = not res.bloqueantes and bool(dtd_ok) and bool(sps_ok)
    codigos_bloq = {c for b in res.bloqueantes for c in re.findall(r"\(([A-Z]\d{2})\)", b)}
    avisos_extrator = [a for a in modelo.get("avisos", []) if not (set(re.findall(r"\(([A-Z]\d{2})", a)) & codigos_bloq)]
    editados = len((le_json(pasta / "edicoes.json", {}) or {}).get("campos", {}))
    nome_original = (pasta / "nome_original.txt").read_text(encoding="utf-8").strip() if (pasta / "nome_original.txt").exists() else modelo.get("arquivo")
    anterior = le_json(pasta / "validacao.json", {}) or {}
    resultado = {
        "criado_em": anterior.get("criado_em") or dt.datetime.now().isoformat(timespec="seconds"),
        "atualizado_em": dt.datetime.now().isoformat(timespec="seconds"),
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
        "avisos_gerador": res.avisos,
        "avisos_extrator": avisos_extrator,
        "packtools": erros,
        "packtools_detalhe": detalhe,
        "editados": editados,
        "contagens": {
            "paginas": modelo.get("paginas"),
            "autores": len(modelo.get("autores", [])),
            "resumos": len(modelo.get("resumos", [])),
            "secoes": len(modelo.get("secoes", [])),
            "notas": len(modelo.get("notas", [])),
            "figuras": len(modelo.get("figuras", [])),
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
    (pasta / "nome_original.txt").write_text(nome, encoding="utf-8")
    grava_json(pasta / "config.json", {"versao_sps": sps, "revista": revista or None})
    try:
        extrai_e_salva(pasta)
        gera_e_valida(pasta)
    except Exception as e:  # noqa: BLE001
        (pasta / "erro.txt").write_text(repr(e), encoding="utf-8")
        raise HTTPException(500, f"Falha ao processar o PDF: {e}")
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def ver_doc(request: Request, doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
    r = le_json(pasta / "validacao.json")
    if not r:
        raise HTTPException(404, "Documento sem resultado")
    r["id"] = doc_id
    return templates.TemplateResponse(request, "resultado.html", {"r": r, "usuario": usuario})


@app.get("/doc/{doc_id}/editar", response_class=HTMLResponse)
def editar_form(request: Request, doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
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
async def editar_salvar(request: Request, doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
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
    ed["atualizado_em"] = dt.datetime.now().isoformat(timespec="seconds")
    ed["por"] = usuario
    grava_json(pasta / "edicoes.json", ed)
    gera_e_valida(pasta)
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


@app.post("/doc/{doc_id}/reprocessar")
def reprocessar(doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
    extrai_e_salva(pasta)
    gera_e_valida(pasta)
    return RedirectResponse(url=f"/doc/{doc_id}", status_code=303)


@app.get("/doc/{doc_id}/xml")
def baixar_xml(doc_id: str, usuario: str = Depends(autentica)):
    pasta = _pasta(doc_id)
    xml = next(pasta.glob("*.xml"), None)
    if not xml:
        raise HTTPException(404)
    return FileResponse(str(xml), media_type="application/xml", filename=xml.name)


@app.get("/doc/{doc_id}/pacote.zip")
def baixar_pacote(doc_id: str, usuario: str = Depends(autentica)):
    """Pacote SPS minimo: <base>.xml + <base>.pdf (o PDF original renomeado). Imagens entram quando o extrator as gerar."""
    pasta = _pasta(doc_id)
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
    buf.seek(0)
    return Response(buf.read(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{base}.zip"'})


@app.get("/doc/{doc_id}/modelo.json")
def baixar_modelo(doc_id: str, usuario: str = Depends(autentica)):
    return FileResponse(str(_pasta(doc_id) / "model.json"), media_type="application/json", filename=f"{doc_id}-modelo.json")


@app.get("/doc/{doc_id}/validacao.json")
def baixar_validacao(doc_id: str, usuario: str = Depends(autentica)):
    return FileResponse(str(_pasta(doc_id) / "validacao.json"), media_type="application/json")


@app.get("/doc/{doc_id}/resumo.md", response_class=PlainTextResponse)
def ver_resumo(doc_id: str, usuario: str = Depends(autentica)):
    return (_pasta(doc_id) / "resumo.md").read_text(encoding="utf-8")


@app.get("/revistas", response_class=HTMLResponse)
def revistas(request: Request, usuario: str = Depends(autentica)):
    return templates.TemplateResponse(request, "revistas.html", {"revistas": carrega_revistas(), "usuario": usuario})
