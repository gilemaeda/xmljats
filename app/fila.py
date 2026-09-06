"""Fila de processamento: envio em lote entra na fila e um trabalhador (thread) processa um arquivo por vez.

Por que assim: o motor (PyMuPDF + packtools) é trabalho de CPU. Com vários arquivos de uma vez, o melhor é
processá-los em sequência numa thread própria e deixar a pessoa navegar; a lista de documentos mostra "na fila",
"processando", o resultado ou o erro. Um envio de um arquivo só continua síncrono: a pessoa espera alguns
segundos e cai direto no resultado, como sempre foi.

O estado de cada documento fica no config.json dele ("na_fila", "processando", "concluido", "erro"), então a
fila sobrevive a reinício: ao subir de novo, o que estava na fila ou no meio do processamento volta para ela.
O trabalhador sobe na primeira necessidade, não no import (os testes criam o app sem evento de startup).
"""
import os
import queue
import threading
import traceback
from pathlib import Path
from typing import Callable, List, Optional

ESTADOS = ("na_fila", "processando", "concluido", "erro")
_fila: "queue.Queue[Path]" = queue.Queue()
_trava = threading.Lock()
_threads: List[threading.Thread] = []
_em_processamento: set = set()
_cfg: dict = {"docs": None, "processa": None, "le": None, "grava": None, "agora": None}


def configura(docs: Path, processa: Callable[[Path], object], le_json, grava_json, agora_iso) -> None:
    """Liga a fila ao app: pasta dos documentos, função que processa um documento e utilitários de JSON/hora."""
    _cfg.update(docs=docs, processa=processa, le=le_json, grava=grava_json, agora=agora_iso)


def _muda(pasta: Path, **campos) -> dict:
    cfg = _cfg["le"](pasta / "config.json", {}) or {}
    cfg.update(campos)
    _cfg["grava"](pasta / "config.json", cfg)
    return cfg


def enfileira(pasta: Path) -> int:
    """Põe o documento na fila e devolve quantos estão na frente dele (0 = é o próximo)."""
    garante_trabalhador()  # antes de marcar o estado: a retomada de pendentes não pode pegar este e duplicá-lo
    _muda(pasta, estado="na_fila", fila_em=_cfg["agora"](), erro=None)
    na_frente = tamanho()
    _fila.put(pasta)
    return na_frente


def tamanho() -> int:
    """Quantos documentos esperam ou estão sendo processados."""
    return _fila.qsize() + len(_em_processamento)


def posicao(pasta: Path) -> Optional[int]:
    """Posição na fila (1 = próximo a ser processado; 0 = processando agora); None se não está nela."""
    if pasta in _em_processamento:
        return 0
    with _fila.mutex:
        itens = list(_fila.queue)
    return itens.index(pasta) + 1 if pasta in itens else None


def trabalhando() -> bool:
    return any(t.is_alive() for t in _threads)


def garante_trabalhador() -> None:
    """Sobe o(s) trabalhador(es) na primeira necessidade e recoloca na fila o que ficou pendente."""
    subiu = False
    with _trava:
        if not any(t.is_alive() for t in _threads):
            n = max(1, int(os.environ.get("XMLJATS_TRABALHADORES") or 1))
            _threads.clear()
            for i in range(n):
                t = threading.Thread(target=_loop, name=f"xmljats-fila-{i + 1}", daemon=True)
                t.start()
                _threads.append(t)
            subiu = True
    if subiu:
        retoma()


def retoma() -> int:
    """Documentos que ficaram 'na_fila' ou 'processando' (queda no meio) voltam para a fila, do mais antigo ao
    mais novo. Quem já tem validacao.json só recebe o estado 'concluido'."""
    docs = _cfg["docs"]
    if not docs or not Path(docs).is_dir():
        return 0
    with _fila.mutex:
        ja = set(_fila.queue)
    voltaram = 0
    for pasta in sorted(Path(docs).iterdir()):
        if not pasta.is_dir() or pasta in ja or pasta in _em_processamento:
            continue
        cfg = _cfg["le"](pasta / "config.json", {}) or {}
        if cfg.get("estado") not in ("na_fila", "processando"):
            continue
        if (pasta / "validacao.json").exists():
            _muda(pasta, estado="concluido", concluido_em=_cfg["agora"]())
            continue
        _fila.put(pasta)
        voltaram += 1
    return voltaram


def conclui(pasta: Path) -> None:
    """Reprocessamento síncrono terminou bem: o estado (se havia) vira 'concluido'."""
    cfg = _cfg["le"](pasta / "config.json", {}) or {}
    if cfg.get("estado"):
        _muda(pasta, estado="concluido", concluido_em=_cfg["agora"](), erro=None)


def _loop() -> None:
    while True:
        pasta = _fila.get()
        try:
            processa(pasta)
        except Exception:  # noqa: BLE001  (o trabalhador nunca morre por causa de um documento)
            pass
        finally:
            _fila.task_done()


def processa(pasta: Path) -> None:
    cfg = _cfg["le"](pasta / "config.json", {}) or {}
    if cfg.get("estado") == "concluido" and (pasta / "validacao.json").exists():
        return  # entrou duas vezes na fila; já está pronto
    _em_processamento.add(pasta)
    try:
        _muda(pasta, estado="processando", processando_em=_cfg["agora"]())
        try:
            _cfg["processa"](pasta)
            _muda(pasta, estado="concluido", concluido_em=_cfg["agora"](), erro=None)
        except Exception as e:  # noqa: BLE001
            (pasta / "erro.txt").write_text(traceback.format_exc(), encoding="utf-8")
            _muda(pasta, estado="erro", concluido_em=_cfg["agora"](), erro=f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        _em_processamento.discard(pasta)
