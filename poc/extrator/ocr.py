"""OCR para PDF escaneado (só imagem), com o Tesseract por dentro do PyMuPDF.

Só entra em página sem camada de texto: PDF normal não passa por aqui. Precisa dos dados de idioma do
Tesseract (por + eng). No container, o Dockerfile instala tesseract-ocr-por e tesseract-ocr-eng e aponta
TESSDATA_PREFIX; na máquina de desenvolvimento, serve a pasta do instalador ou %LOCALAPPDATA%/xmljats/tessdata.
Sem Tesseract, nada quebra: o PDF escaneado continua sendo avisado como sem texto (D01), sem OCR.
"""
import os
from typing import List, Optional

IDIOMAS = ("por", "eng")
_cache: dict = {}


def candidatos() -> List[str]:
    lista = [os.environ.get("TESSDATA_PREFIX"), os.environ.get("XMLJATS_TESSDATA")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        lista.append(os.path.join(local, "xmljats", "tessdata"))
    lista += [r"C:\Program Files\Tesseract-OCR\tessdata", "/usr/share/tesseract-ocr/5/tessdata",
              "/usr/share/tesseract-ocr/4.00/tessdata", "/usr/share/tessdata", "/usr/local/share/tessdata"]
    return [c for c in lista if c]


def _tem(pasta: str, idioma: str) -> bool:
    return os.path.isfile(os.path.join(pasta, f"{idioma}.traineddata"))


def tessdata_dir() -> Optional[str]:
    """Primeira pasta com dados de idioma; prefere a que tem português e inglês."""
    melhor = None
    for c in candidatos():
        if not (_tem(c, "eng") or _tem(c, "por")):
            continue
        if _tem(c, "por") and _tem(c, "eng"):
            return c
        melhor = melhor or c
    return melhor


def idiomas(pasta: Optional[str] = None) -> str:
    pasta = pasta or tessdata_dir()
    if not pasta:
        return ""
    return "+".join(i for i in IDIOMAS if _tem(pasta, i))


def disponivel() -> bool:
    """Tesseract acessível pelo PyMuPDF e pelo menos um idioma instalado (resultado guardado após a primeira vez)."""
    if "disponivel" in _cache:
        return _cache["disponivel"]
    pasta = tessdata_dir()
    ok = False
    if pasta:
        try:
            import pymupdf
            doc = pymupdf.open()
            page = doc.new_page(width=200, height=100)
            page.get_textpage_ocr(language=idiomas(pasta), dpi=72, full=True, tessdata=pasta)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
    _cache["disponivel"] = ok
    return ok


def textpage(page, dpi: int = 300):
    """TextPage por OCR da página inteira, ou None se o OCR não está disponível ou falhou."""
    pasta = tessdata_dir()
    if not pasta:
        return None
    try:
        return page.get_textpage_ocr(language=idiomas(pasta), dpi=dpi, full=True, tessdata=pasta)
    except Exception:  # noqa: BLE001
        return None


def sem_texto(page, minimo: int = 20) -> bool:
    """Página sem camada de texto (ou quase): candidata a OCR."""
    try:
        return len((page.get_text("text") or "").strip()) < minimo
    except Exception:  # noqa: BLE001
        return False
