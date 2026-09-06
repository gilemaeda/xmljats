"""Lotes de entrega: até 5 artigos prontos, da mesma revista e do mesmo volume/número, num só pacote.

A SPS 1.10 diz que, em publicação contínua, um lote é "um artigo ou um conjunto de até 5 XMLs" do mesmo
volume/número, num .zip com uma pasta de mesmo nome (ISSN-acrônimo-volume-número-lote), um relatório xpm.html e um
aviso por e-mail com "Total de XMLs = N". A entrega por artigo (lote de 1) continua existindo; isto junta vários.

Registro: XMLJATS_DATA/lotes.json, chave "pacotes" → {pasta: {pasta, revista, volume, numero, lote, docs, criado_em,
por, depositado_em, correcao}}. Cada documento do lote guarda `lote` e `lote_pasta` no config.json.
"""
import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

MAX_XML = 5
_cfg: dict = {}


def configura(data: Path, docs: Path, le_json, grava_json, agora_iso, carrega_revistas, entrega, lista_docs, proximo_lote,
              registra_lote, liberada=None) -> None:
    """`liberada(cfg) -> (bool, motivo)`: regra de entrega do app/acesso.py (revista com editor-chefe exige a aprovação dele)."""
    _cfg.update(data=Path(data), docs=Path(docs), le=le_json, grava=grava_json, agora=agora_iso, revistas=carrega_revistas,
                entrega=entrega, lista_docs=lista_docs, proximo_lote=proximo_lote, registra_lote=registra_lote, liberada=liberada)


# ---------------------------------------------------------------- registro

def _reg() -> dict:
    return _cfg["le"](_cfg["data"] / "lotes.json", {}) or {}


def _grava_reg(reg: dict) -> None:
    _cfg["grava"](_cfg["data"] / "lotes.json", reg)


def pacotes() -> List[dict]:
    return sorted((_reg().get("pacotes") or {}).values(), key=lambda p: p.get("criado_em") or "", reverse=True)


def por_pasta(pasta: str) -> Optional[dict]:
    return (_reg().get("pacotes") or {}).get(pasta)


def caminho_zip(pasta: str) -> Path:
    return _cfg["data"] / "lotes" / f"{pasta}.zip"


# ---------------------------------------------------------------- agrupamento

def grupo_de(cfg: dict, val: dict) -> tuple:
    """(acrônimo, volume, número) do documento, sem zeros à esquerda."""
    e = _cfg["entrega"]
    meta = e.metadados(val)
    return (cfg.get("revista") or "", e._num(meta.get("volume")), e._num(meta.get("numero")))


def candidatos() -> dict:
    """Documentos prontos e ainda fora de lote, agrupados por (revista, volume, número)."""
    grupos: dict = {}
    for d in _cfg["lista_docs"](0):
        if not d.get("pronto"):
            continue
        cfg = _cfg["le"](_cfg["docs"] / d["id"] / "config.json", {}) or {}
        if cfg.get("lote_pasta"):
            continue
        g = grupo_de(cfg, d)
        if not g[0] or not g[1]:
            continue
        grupos.setdefault(g, []).append({"id": d["id"], "titulo": d.get("titulo") or d.get("arquivo_original") or d["id"],
                                         "nome_base": d.get("nome_base"), "criado_por": cfg.get("criado_por"),
                                         "etapa": cfg.get("etapa") or "recebido"})
    return grupos


# ---------------------------------------------------------------- pacote

def _zip_lote(artigos: List[dict], pasta_pacote: str, relatorio: Optional[bytes]) -> bytes:
    buf = io.BytesIO()
    dentro = pasta_pacote + "/"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a in artigos:
            pasta, base = a["pasta"], a["base"]
            xml = next(pasta.glob("*.xml"), None)
            if xml:
                z.write(str(xml), dentro + f"{base}.xml")
            pdf = pasta / "original.pdf"
            if pdf.exists():
                z.write(str(pdf), dentro + f"{base}.pdf")
            for img in sorted((pasta / "pacote").glob("*")) if (pasta / "pacote").exists() else []:
                z.write(str(img), dentro + img.name)
        if relatorio:
            z.writestr(dentro + _cfg["entrega"].RELATORIO, relatorio)
    return buf.getvalue()


def monta(pasta_pacote: str, artigos: List[dict]) -> bytes:
    """Duas passadas, como o pacote de um artigo: a conferência lê o .zip e entra no relatório."""
    e = _cfg["entrega"]
    temporaria = Path(tempfile.mkdtemp(prefix="xmljats-lote-"))
    provisorio = temporaria / f"{pasta_pacote}.zip"
    try:
        provisorio.write_bytes(_zip_lote(artigos, pasta_pacote, e.relatorio_lote_html(pasta_pacote, artigos, {"itens": []})))
        try:
            conf = e.confere_pacote(str(provisorio))
        except Exception:  # noqa: BLE001
            conf = {"itens": []}
    finally:
        shutil.rmtree(temporaria, ignore_errors=True)
    return _zip_lote(artigos, pasta_pacote, e.relatorio_lote_html(pasta_pacote, artigos, conf))


def cria(ids: List[str], lote: Optional[int], por: str) -> dict:
    """Valida o conjunto (prontos, mesma revista e volume/número, até 5, fora de outro lote), nomeia a pasta,
    grava o .zip em XMLJATS_DATA/lotes e registra. Devolve o registro do lote."""
    e = _cfg["entrega"]
    ids = [i for i in dict.fromkeys(ids or []) if i]
    if not ids:
        raise ValueError("Escolha pelo menos um documento.")
    if len(ids) > MAX_XML:
        raise ValueError(f"Um lote leva no máximo {MAX_XML} XMLs (SPS 1.10); este tinha {len(ids)}.")
    docs = []
    for i in ids:
        pasta = _cfg["docs"] / i
        if "/" in i or "\\" in i or ".." in i or not pasta.is_dir():
            raise ValueError(f"Documento {i} não encontrado.")
        val = _cfg["le"](pasta / "validacao.json", {}) or {}
        cfg = _cfg["le"](pasta / "config.json", {}) or {}
        if not val:
            raise ValueError(f"Documento {i} ainda não foi processado.")
        if not val.get("pronto"):
            raise ValueError(f"\"{val.get('titulo') or i}\" ainda não está pronto: tem bloqueante ou erro do validador.")
        if cfg.get("lote_pasta"):
            raise ValueError(f"\"{val.get('titulo') or i}\" já está no lote {cfg['lote_pasta']}.")
        if _cfg.get("liberada"):
            liberada, motivo = _cfg["liberada"](cfg)
            if not liberada:
                raise ValueError(f"\"{val.get('titulo') or i}\": {motivo}")
        xml = next(pasta.glob("*.xml"), None)
        if not xml:
            raise ValueError(f"\"{val.get('titulo') or i}\" está sem XML gerado.")
        docs.append((i, pasta, val, cfg, xml.stem))
    grupos = {grupo_de(c, v) for _, _, v, c, _ in docs}
    if len(grupos) != 1:
        raise ValueError("Todos os documentos de um lote precisam ser da mesma revista e do mesmo volume/número.")
    acr, vol, _num = next(iter(grupos))
    revista = next((r for r in _cfg["revistas"]() if r["acronimo"] == acr), None)
    if not revista:
        raise ValueError("A revista do lote não está no cadastro.")
    if not vol:
        raise ValueError("O lote precisa do volume, e ele está em branco no artigo.")
    bases = [b for *_, b in docs]
    if len(set(bases)) != len(bases):
        raise ValueError("Dois documentos têm o mesmo nome-base de arquivo; confira elocation/paginação antes de juntar.")
    meta = e.metadados(docs[0][2])
    if e.continua(revista) and lote is None:
        lote = _cfg["proximo_lote"](revista, meta)
    pasta_pacote = e.nome_pasta(revista, meta, lote if e.continua(revista) else None)
    if not pasta_pacote:
        raise ValueError("Não dá para nomear a pasta do lote: confira volume, número e ano do artigo.")
    if por_pasta(pasta_pacote):
        raise ValueError(f"Já existe o lote {pasta_pacote}: desfaça-o ou use outro número de lote.")
    artigos = [{"base": b, "validacao": v, "pasta": p} for _, p, v, _, b in docs]
    destino = caminho_zip(pasta_pacote)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(monta(pasta_pacote, artigos))
    registro = {"pasta": pasta_pacote, "revista": acr, "volume": e._num(meta.get("volume")), "numero": e._num(meta.get("numero")),
                "ano": e.ano_do_volume(meta), "lote": lote, "docs": [i for i, *_ in docs], "criado_em": _cfg["agora"](),
                "por": por, "depositado_em": None, "correcao": False}
    reg = _reg()
    reg.setdefault("pacotes", {})[pasta_pacote] = registro
    _grava_reg(reg)
    for i, pasta, _v, cfg, _b in docs:
        cfg["lote"] = lote
        cfg["lote_pasta"] = pasta_pacote
        _cfg["grava"](pasta / "config.json", cfg)
    return registro


def desfaz(pasta_pacote: str) -> None:
    """Lote ainda não depositado volta atrás: apaga o .zip, solta os documentos e tira o registro."""
    reg = _reg()
    rec = (reg.get("pacotes") or {}).get(pasta_pacote)
    if not rec:
        raise ValueError("Lote não encontrado.")
    if rec.get("depositado_em"):
        raise ValueError("Lote já depositado na SciELO não pode ser desfeito aqui; uma correção vai para a pasta Correcao.")
    for i in rec.get("docs", []):
        pasta = _cfg["docs"] / i
        cfg = _cfg["le"](pasta / "config.json", {}) or {}
        if cfg.get("lote_pasta") == pasta_pacote:
            cfg.pop("lote_pasta", None)
            cfg.pop("lote", None)
            _cfg["grava"](pasta / "config.json", cfg)
    z = caminho_zip(pasta_pacote)
    if z.exists():
        z.unlink()
    del reg["pacotes"][pasta_pacote]
    _grava_reg(reg)


def marca_depositado(pasta_pacote: str, por: str, correcao: bool, passos: list) -> dict:
    """Depois do FTP: registro do lote, etapa 'entregue' em cada documento e a sequência de lotes da revista."""
    reg = _reg()
    rec = (reg.get("pacotes") or {}).get(pasta_pacote)
    if not rec:
        raise ValueError("Lote não encontrado.")
    agora = _cfg["agora"]()
    rec["depositado_em"] = agora
    rec["correcao"] = bool(correcao)
    rec["depositado_por"] = por
    reg["pacotes"][pasta_pacote] = rec
    _grava_reg(reg)
    revista = next((r for r in _cfg["revistas"]() if r["acronimo"] == rec["revista"]), None)
    nome_zip = f"{pasta_pacote}.zip"
    for i in rec.get("docs", []):
        pasta = _cfg["docs"] / i
        cfg = _cfg["le"](pasta / "config.json", {}) or {}
        val = _cfg["le"](pasta / "validacao.json", {}) or {}
        cfg["etapa"] = "entregue"
        cfg.setdefault("historico_etapas", []).append({"etapa": "entregue", "por": por, "em": agora,
                                                       "nota": f"depositado no FTP da SciELO no lote {nome_zip}"})
        cfg["entrega"] = {"em": agora, "por": por, "arquivo": nome_zip, "correcao": bool(correcao), "passos": passos, "lote": pasta_pacote}
        _cfg["grava"](pasta / "config.json", cfg)
        if revista and rec.get("lote") is not None and not correcao:
            _cfg["registra_lote"](revista, _cfg["entrega"].metadados(val), int(rec["lote"]), i, nome_zip)
    return rec
