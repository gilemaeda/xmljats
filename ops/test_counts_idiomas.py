"""page-count, counts sem zeros, 'como citar' editavel, pistas em varios idiomas, datas na caixa e DOCX na tela."""
import io
import json
import os
import re
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-cnt-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "poc"))
sys.path.insert(0, os.path.join(RAIZ, "app"))
os.chdir(RAIZ)
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402
from extrator import xml_jats  # noqa: E402
from extrator.util import parse_data  # noqa: E402
from gerar_xml import valida_packtools  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- 1. data com ano de dois digitos
for texto, esperado in [("23/12/24", "2024-12-23"), ("05/01/25", "2025-01-05"), ("22/02/26", "2026-02-22"),
                        ("15/03/99", "1999-03-15"), ("23/12/2024", "2024-12-23"), ("2024-12-23", "2024-12-23"),
                        ("p. 37-68", None), ("v. 5, n. 1", None)]:
    ok(parse_data(texto) == esperado, f"data {texto!r} -> {parse_data(texto)} (esperado {esperado})")

# ---------------------------------------------------------------- 2. counts conforme a documentacao da SPS
REV = {"acronimo": "rdp", "titulo": "R", "abrev": "R", "issn_epub": "2179-8966", "editora": "E",
       "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "continua"}
BASE = {"idioma": "pt", "tipo_artigo": "research-article", "heading": "Artigos", "doi": "10.1590/x/2026/1",
        "volume": "17", "numero": "1", "ano": "2026", "elocation": "e99999", "order": "99999",
        "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "arquivo": "artigo.pdf", "paginas": 12,
        "datas": {"recebido": "2025-03-01", "aceito": "2025-06-01", "publicado": "2026-02-10"},
        "titulos": [{"texto": "T", "idioma": "pt", "tipo": "article-title"}],
        "autores": [{"nome_completo": "A S", "sobrenome": "S", "nomes": "A", "orcid": "0000-0002-1825-0097",
                     "orcid_valido": True, "email": "a@e.org", "aff_ids": ["aff1"], "correspondente": True}],
        "afiliacoes": [{"id": "aff1", "instituicao": "U", "pais_iso": "BR", "texto_original": "U"}],
        "resumos": [{"idioma": "pt", "rotulo": "Resumo", "texto": "R", "palavras_chave": ["k"]}],
        "secoes": [{"titulo": "I", "titulo_completo": "1 I", "nivel": 1, "paragrafos": ["p"]}],
        "referencias": [{"texto": "SILVA, A. Livro. Sao Paulo: E, 2020.", "tipo": "book", "autores": ["SILVA, A."], "ano": "2020"}],
        "citacoes": [], "notas": [], "figuras": [], "tabelas": [], "equacoes": [], "estilo_referencias": "ABNT"}

res = xml_jats.gera_xml(json.loads(json.dumps(BASE)), REV, "1.9")
xml = (res.xml or b"").decode("utf-8")
counts = re.search(r"<counts>.*?</counts>", xml, re.S).group(0)
ok('<page-count count="12"/>' in counts, f"page-count vem do total de paginas do arquivo: {counts}")
ok("table-count" not in counts and "equation-count" not in counts and "fig-count" not in counts,
   "contador zerado sai do <counts>, como a documentacao manda")
ok('<ref-count count="1"/>' in counts, "ref-count continua, porque ha referencia")

com_paginas = json.loads(json.dumps(BASE))
com_paginas.update({"fpage": "10", "lpage": "25", "elocation": None, "paginas": 40})
x2 = (xml_jats.gera_xml(com_paginas, dict(REV, modo_publicacao="regular"), "1.9").xml or b"").decode("utf-8")
ok('<page-count count="16"/>' in x2, "com fpage/lpage, o page-count vem da faixa (10 a 25 = 16), nao do arquivo")

docx = json.loads(json.dumps(BASE))
docx["arquivo"] = "artigo.docx"
r3 = xml_jats.gera_xml(docx, REV, "1.9")
ok("<page-count" not in (r3.xml or b"").decode("utf-8"),
   "no DOCX a paginacao e estimada, entao nao vira page-count sozinha")
ok(any("(A15)" in a for a in r3.avisos), "e o aviso pede o total de paginas")
docx["paginas_total"] = 18
x4 = (xml_jats.gera_xml(docx, REV, "1.9").xml or b"").decode("utf-8")
ok('<page-count count="18"/>' in x4, "no DOCX, o total digitado a mao vira page-count")

com_tudo = json.loads(json.dumps(BASE))
com_tudo["tabelas"] = [{"rotulo": "Tabela 1", "legenda": "L", "celulas": [["a", "b"]], "linhas_cabecalho": 1,
                        "colunas": 2, "qualidade": "alta", "secao_indice": 0, "pos_paragrafo": 0}]
x5 = (xml_jats.gera_xml(com_tudo, REV, "1.9").xml or b"").decode("utf-8")
ok('<table-count count="1"/>' in x5, "com tabela, o table-count aparece")
caminho = os.path.join(tempfile.mkdtemp(), "c.xml")
open(caminho, "wb").write(x5.encode("utf-8"))
d, sp, erros, _ = valida_packtools(caminho)
ok(d is True and sp is True, f"XML com os counts novos segue valido (DTD {d} SPS {sp}) {[e for e in erros if 'DTD' not in e][:2]}")

# ---------------------------------------------------------------- 3. 'como citar' sai como nota
citar = json.loads(json.dumps(BASE))
citar["dec_como_citar"] = "SILVA, A. Titulo. Revista, v. 17, n. 1, e99999, 2026."
x6 = (xml_jats.gera_xml(citar, REV, "1.9").xml or b"").decode("utf-8")
ok('id="fn-como-citar"' in x6 and "SILVA, A. Titulo." in x6, "'como citar' preenchido sai como nota no fim do artigo")
ok("fn-como-citar" not in (xml_jats.gera_xml(json.loads(json.dumps(BASE)), REV, "1.9").xml or b"").decode("utf-8"),
   "em branco, nao sai nota nenhuma")

# ---------------------------------------------------------------- 4. pistas em varios idiomas
casos = [
    ("Acknowledgement", "dec_agradecimentos"), ("Agradecimentos", "dec_agradecimentos"),
    ("Reconocimientos", "dec_agradecimentos"),
    ("IA Statement", "dec_ia"), ("AI statement", "dec_ia"), ("Declaração sobre o uso de IA", "dec_ia"),
    ("Artificial intelligence declaration", "dec_ia"),
    ("Conflict of interest declaration", "dec_conflito"), ("Conflito de interesses", "dec_conflito"),
    ("Declaration of authorship", "dec_contribuicao"), ("Authorship information", "dec_contribuicao"),
    ("Data availability statement", "dec_dados"), ("Disponibilidad de los datos", "dec_dados"),
    ("Funding", "dec_financiamento"), ("Financiación", "dec_financiamento"),
    ("How to cite (ABNT Brazil)", "dec_como_citar"), ("Como citar", "dec_como_citar"),
    ("Editorial team", "dec_editor"),
]
for titulo, campo in casos:
    achadas = M.declaracoes_do_artigo({"back_matter": [{"titulo": titulo, "texto": "conteudo da declaracao aqui"}]})
    ok(campo in achadas, f"'{titulo}' -> {campo} (achou {list(achadas)})")
ok("dec_editor" not in M.declaracoes_do_artigo({"back_matter": [{"titulo": "Editorial process dates", "texto": "x"}]}),
   "'Editorial process dates' continua fora do campo de editor")
ok("dec_contribuicao" not in M.declaracoes_do_artigo({"back_matter": [{"titulo": "Declaration of originality", "texto": "x"}]}),
   "'Declaration of originality' nao vira contribuicao dos autores")

# ---------------------------------------------------------------- 5. artigo real: datas da caixa e page-count
c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "C", "email": "c@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "1227_VF+-+Simioni (3).pdf"), "rb") as f:
    up = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "anamps", "sps": "1.9"})
doc = up.headers["location"].rsplit("/", 1)[-1]
pasta = __import__("pathlib").Path(tmp) / "docs" / doc
mod = M.modelo_efetivo(pasta)
ok((mod.get("datas") or {}).get("recebido") == "2024-12-23",
   f"data recebida lida da caixa cinza no fim do artigo: {(mod.get('datas') or {}).get('recebido')}")
ok((mod.get("datas") or {}).get("aceito") == "2025-01-05",
   f"data de aceite lida da caixa: {(mod.get('datas') or {}).get('aceito')}")
ok(mod.get("paginas") == 23, f"total de paginas contado do PDF: {mod.get('paginas')}")
pag = c.get(f"/doc/{doc}/editar").text
ok('name="paginas_total"' in pag and 'value="23"' in pag, "o total de paginas aparece preenchido na tela")
ok('name="dec_como_citar"' in pag, "'como citar' virou campo editavel")
ok("preenchido automaticamente" in pag, "o que veio sozinho fica marcado")

# ---------------------------------------------------------------- 6. previa mostra as imagens
prev = c.get(f"/doc/{doc}/previa").text
nossas = sorted(set(re.findall(rf"/doc/{doc}/img/[\w.]+", prev)))
ok(len(nossas) >= 8, f"a previa aponta as {len(nossas)} imagens para este documento")
ok(all(c.get(u).status_code == 200 for u in nossas[:4]), "e cada uma abre")
ok(not re.findall(r"[\w-]+-gf\d{2}\.\w+", prev), "nenhum nome de arquivo do pacote sobra quebrado")

# ---------------------------------------------------------------- 7. tela aceita DOCX e tem botao de topo
home = c.get("/").text
ok(".docx" in home and "só PDF" not in home, "a tela de envio aceita DOCX")
ok("não é PDF nem DOCX" in home, "a mensagem de formato cita os dois")
ok('id="ao-topo"' in home and "ao-topo" in io.open(os.path.join(RAIZ, "app", "static", "style.css"), encoding="utf-8").read(),
   "botao de voltar ao topo em todas as telas")
with open(os.path.join(RAIZ, "modelos", "RBDPP_2026_v12n2_1498.docx"), "rb") as f:
    r = c.post("/validar", files={"arquivo": ("a.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
               data={"revista": "rbdpp", "sps": "1.9"})
ok(r.status_code == 303, f"DOCX continua sendo aceito pelo servidor ({r.status_code})")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
