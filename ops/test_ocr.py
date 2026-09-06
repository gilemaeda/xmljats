"""OCR de PDF escaneado: página sem texto passa pelo Tesseract (por + eng), o resultado avisa que veio de OCR,
o visualizador ganha camada de texto e PDF normal não é tocado. Precisa do Tesseract na máquina."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-ocr-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "poc"))
sys.path.insert(0, os.path.join(RAIZ, "app"))
os.chdir(RAIZ)
import pymupdf  # noqa: E402
from extrator import ocr  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


ok(ocr.tessdata_dir() is not None, f"dados de idioma do Tesseract encontrados em {ocr.tessdata_dir()}")
ok(ocr.disponivel(), "o PyMuPDF consegue chamar o Tesseract")
ok("por" in ocr.idiomas() and "eng" in ocr.idiomas(), f"português e inglês instalados ({ocr.idiomas()})")
if not ocr.disponivel():
    print("\nFALHAS:", len(falhas), "- sem OCR nesta máquina, o resto do teste não roda")
    sys.exit(1)

from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402
import extrair as cli  # noqa: E402

# ---------------------------------------------------------------- 1. PDF escaneado de verdade (3 páginas viradas em imagem)
src = pymupdf.open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"))
esc = pymupdf.open()
for i in range(3):
    pix = src[i].get_pixmap(dpi=150)
    pg = esc.new_page(width=src[i].rect.width, height=src[i].rect.height)
    pg.insert_image(pg.rect, pixmap=pix)
caminho = os.path.join(tmp, "escaneado.pdf")
esc.save(caminho)
ok(not pymupdf.open(caminho)[0].get_text().strip(), "o PDF de prova não tem camada de texto")

doc, model = cli.extrai(caminho, pasta_imagens=os.path.join(tmp, "img"))
m = model.to_dict()
ok(doc.ocr_paginas == [1, 2, 3], f"as três páginas passaram pelo OCR: {doc.ocr_paginas}")
texto = " ".join(l.texto for l in doc.linhas).lower()
ok("hegeliana" in texto and "direito" in texto and "jurisdição" in texto,
   f"o texto reconhecido tem as palavras do artigo, com acento ({len(texto)} caracteres)")
ok(not m.get("sem_texto"), "não é mais tratado como 'sem texto'")
ok(any("(D02)" in a and "OCR" in a for a in m.get("avisos", [])), "o aviso diz que o texto veio de OCR e pede conferência")
ok(not any("(D01)" in a for a in m.get("avisos", [])), "e não sai o aviso de PDF sem texto")
ok((m.get("proveniencia") or {}).get("texto", "").startswith("OCR"), "a proveniência registra o OCR")
ok(not m.get("figuras"), f"a imagem da página escaneada não vira figura ({len(m.get('figuras') or [])})")
print("     título lido:", (model.titulo_principal or "")[:90])
print("     autores:", [a.get("nome_completo") for a in m.get("autores", [])][:3], "| refs:", len(m.get("referencias") or []))

# ---------------------------------------------------------------- 2. PDF normal não passa pelo OCR
doc2, _ = cli.extrai(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), pasta_imagens=os.path.join(tmp, "img2"))
ok(doc2.ocr_paginas == [], "PDF com camada de texto não passa pelo OCR")

# ---------------------------------------------------------------- 3. pelo site: resultado e visualizador
c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "Ocr", "email": "ocr@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
             headers={"x-forwarded-for": "10.3.3.3"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
with open(caminho, "rb") as f:
    up = c.post("/validar", files={"arquivo": ("escaneado.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.10"})
ok(up.status_code == 303, f"PDF escaneado é processado ({up.status_code})")
doc_id = up.headers["location"].rsplit("/", 1)[-1]
val = json.load(io.open(os.path.join(tmp, "docs", doc_id, "validacao.json"), encoding="utf-8"))
ok(not any("(D01)" in b for b in val.get("bloqueantes") or []), "não há bloqueante de PDF sem texto")
ok(any("(D02)" in a for a in (val.get("avisos_extrator") or [])), "o aviso de OCR aparece no resultado")
ok("OCR" in c.get(f"/doc/{doc_id}").text, "a tela do resultado fala em OCR")
idx = c.get(f"/doc/{doc_id}/paginas.json").json()
p1 = (idx.get("paginas") or [{}])[0]
ok(len(p1.get("palavras") or []) > 50, f"o visualizador tem camada de texto por OCR ({len(p1.get('palavras') or [])} palavras na página 1)")
ok(c.get("/saude").json().get("ocr") is True, "/saude informa que o servidor tem OCR")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
