"""
Visualização do arquivo original dentro do revisar e editar.

A tela mostra o PDF como ele é (página renderizada em imagem) e, por cima, uma camada transparente com uma
caixa por palavra, nas coordenadas do PDF. É assim que um leitor de PDF no navegador funciona: a imagem dá a
aparência, a camada de texto dá a seleção. Com isso dá para selecionar um trecho na página e mandar o texto
para o campo que está sendo editado, sem digitar de novo.

Nada é gerado na hora do pedido: as páginas são renderizadas uma vez e guardadas na pasta do documento
(`paginas/p001.png` e `paginas.json`), porque renderizar um PDF de 30 páginas a cada abertura da tela seria
lento. Se o PDF for reprocessado, a pasta é refeita.

Coordenadas: o PyMuPDF entrega as caixas em pontos do PDF (72 por polegada). Guardamos as caixas em pontos e
o tamanho da página em pontos; o navegador aplica a escala que quiser. A imagem sai em ZOOM vezes o tamanho,
para o texto ficar legível numa tela comum.
"""
import json
from pathlib import Path
from typing import Optional

ZOOM = 2.0            # 2x = ~144 dpi: legível na tela sem estourar o tamanho do arquivo
MAX_PAGINAS = 60      # teto de segurança para PDF muito longo
FUNDO = "png"


def _pasta_paginas(pasta: Path) -> Path:
    return pasta / "paginas"


def indice(pasta: Path) -> Optional[dict]:
    """Índice já gerado, ou None."""
    arq = pasta / "paginas.json"
    if not arq.exists():
        return None
    try:
        with open(arq, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def limpa(pasta: Path) -> None:
    """Apaga o que foi renderizado (usado ao reprocessar o PDF)."""
    import shutil
    shutil.rmtree(_pasta_paginas(pasta), ignore_errors=True)
    try:
        (pasta / "paginas.json").unlink()
    except OSError:
        pass


def prepara(pasta: Path, forca: bool = False) -> dict:
    """Renderiza as páginas e monta a camada de texto. Devolve o índice. Idempotente."""
    if not forca:
        pronto = indice(pasta)
        if pronto:
            return pronto
    pdf = pasta / "original.pdf"
    if not pdf.exists():
        return {"paginas": [], "erro": "O arquivo original não está guardado neste documento."}
    import fitz  # PyMuPDF

    destino = _pasta_paginas(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    paginas = []
    with fitz.open(str(pdf)) as doc:
        total = min(doc.page_count, MAX_PAGINAS)
        for n in range(total):
            page = doc.load_page(n)
            largura, altura = page.rect.width, page.rect.height
            pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
            nome = f"p{n + 1:03d}.{FUNDO}"
            pix.save(str(destino / nome))
            # palavras com caixa: (x0, y0, x1, y1, palavra, bloco, linha, palavra_no_bloco)
            palavras = []
            for p in page.get_text("words"):
                x0, y0, x1, y1, txt, bloco, linha, _ = p
                if not (txt or "").strip():
                    continue
                palavras.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), txt, int(bloco), int(linha)])
            paginas.append({"n": n + 1, "arquivo": nome, "largura": round(largura, 1), "altura": round(altura, 1),
                            "palavras": palavras})
        cortadas = doc.page_count - total
    idx = {"paginas": paginas, "zoom": ZOOM, "total": len(paginas),
           "cortadas": cortadas if cortadas > 0 else 0}
    with open(pasta / "paginas.json", "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    return idx


def resumo(pasta: Path) -> dict:
    """O que a tela precisa saber antes de carregar as páginas (sem renderizar nada)."""
    idx = indice(pasta)
    if idx:
        return {"pronto": True, "total": idx.get("total", 0), "cortadas": idx.get("cortadas", 0)}
    return {"pronto": False, "total": 0, "cortadas": 0}
