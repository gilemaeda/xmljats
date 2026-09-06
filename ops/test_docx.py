"""Entrada DOCX: estrutura vinda do proprio arquivo (secoes, tabelas, formulas OMML) e XML valido no fim."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import zipfile

tmp = tempfile.mkdtemp(prefix="xmljats-docx-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "poc"))
sys.path.insert(0, os.path.join(RAIZ, "app"))
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402
import extrair as cli  # noqa: E402
from extrator.docx import omml_para_mathml, _sem_repeticao  # noqa: E402
from lxml import etree  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- OMML -> MathML
NS = ('xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
      'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"')


def omml(interno):
    return etree.fromstring(f'<m:oMath {NS}>{interno}</m:oMath>'.encode("utf-8"))


def texto_mml(x):
    return omml_para_mathml(omml(x)) or ""


casos = [
    ("<m:r><m:t>E = mc</m:t></m:r>", ["<mi>E</mi>", "<mo>=</mo>", "<mi>mc</mi>"], "runs viram mi/mo"),
    ('<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>',
     ["<mfrac>", "<mi>a</mi>", "<mi>b</mi>"], "fracao vira mfrac"),
    ('<m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>',
     ["<msup>", "<mi>x</mi>", "<mn>2</mn>"], "expoente vira msup"),
    ('<m:sSub><m:e><m:r><m:t>a</m:t></m:r></m:e><m:sub><m:r><m:t>i</m:t></m:r></m:sub></m:sSub>',
     ["<msub>"], "indice vira msub"),
    ('<m:rad><m:e><m:r><m:t>x</m:t></m:r></m:e></m:rad>', ["<msqrt>"], "raiz vira msqrt"),
    ('<m:d><m:e><m:r><m:t>y</m:t></m:r></m:e></m:d>', ["<mo>(</mo>", "<mo>)</mo>"], "delimitador vira parenteses"),
    ('<m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr><m:sub><m:r><m:t>i</m:t></m:r></m:sub>'
     '<m:sup><m:r><m:t>n</m:t></m:r></m:sup><m:e><m:r><m:t>x</m:t></m:r></m:e></m:nary>',
     ["<munderover>", "∑"], "somatorio vira munderover"),
]
for entrada, esperados, nome in casos:
    saida = texto_mml(entrada)
    ok(all(e in saida for e in esperados), f"OMML: {nome} -> {saida[:110]}")
ok(texto_mml("") == "", "OMML vazio nao gera MathML")
ok(_sem_repeticao("ANAMORPHOSIS REVISTA" * 2) == "ANAMORPHOSIS REVISTA", "texto colado em dobro e desfeito")
ok(_sem_repeticao("Introducao ao direito comparado no Brasil") == "Introducao ao direito comparado no Brasil",
   "texto normal nao e cortado")

# ---------------------------------------------------------------- DOCX montado a mao, com tudo dentro
DOC_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document {NS}>
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Prova do caminho DOCX</w:t></w:r></w:p>
  <w:p><w:r><w:t>Ana Silva</w:t></w:r></w:p>
  <w:p><w:r><w:t>Universidade Federal da Bahia (UFBA), Salvador, Bahia, Brasil. E-mail: ana@exemplo.org. ORCID: https://orcid.org/0000-0002-1825-0097</w:t></w:r></w:p>
  <w:p><w:r><w:t>Resumo: Este texto existe para provar a leitura de DOCX pelo sistema, com tabela e formula.</w:t></w:r></w:p>
  <w:p><w:r><w:t>Palavras-chave: direito; xml; docx.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>1 Introducao</w:t></w:r></w:p>
  <w:p><w:r><w:t>Primeiro paragrafo do corpo, citando a Tabela 1 e a equacao seguinte.</w:t></w:r></w:p>
  <w:p><w:r><w:t>Tabela 1 - Casos por ano</w:t></w:r></w:p>
  <w:tbl>
   <w:tr><w:trPr><w:tblHeader/></w:trPr>
     <w:tc><w:p><w:r><w:t>Ano</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Casos</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:p><w:r><w:t>2024</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:p><w:r><w:t>2025</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>31</w:t></w:r></w:p></w:tc></w:tr>
  </w:tbl>
  <w:p><w:r><w:t>Fonte: Autores.</w:t></w:r></w:p>
  <w:p><m:oMath><m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>2 Consideracoes finais</w:t></w:r></w:p>
  <w:p><w:r><w:t>Ultimo paragrafo do corpo desta prova, fechando o texto.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Referencias</w:t></w:r></w:p>
  <w:p><w:r><w:t>SILVA, Ana. Livro de prova. Sao Paulo: Editora, 2020.</w:t></w:r></w:p>
  <w:p><w:r><w:t>SOUZA, Bruno. Outro livro. Rio de Janeiro: Editora, 2021.</w:t></w:r></w:p>
 </w:body>
</w:document>"""

caminho = os.path.join(tmp, "prova.docx")
with zipfile.ZipFile(caminho, "w") as z:
    z.writestr("[Content_Types].xml",
               '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="xml" ContentType="application/xml"/></Types>')
    z.writestr("word/document.xml", DOC_XML)

doc, m = cli.extrai(caminho)
ok(m.titulo_principal == "Prova do caminho DOCX", f"titulo pelo estilo Title: {m.titulo_principal!r}")
ok(len(m.secoes) == 2 and m.secoes[0].titulo == "Introducao" and m.secoes[0].numero == "1",
   f"secoes pelos estilos Heading, com numero separado: {[(s.numero, s.titulo) for s in m.secoes]}")
ok(m.secoes[0].paragrafos and "Primeiro paragrafo" in m.secoes[0].paragrafos[0],
   "paragrafos ficam na secao certa")
ok(len(m.tabelas) == 1, f"tabela do Word virou tabela ({len(m.tabelas)})")
if m.tabelas:
    t = m.tabelas[0]
    ok(t.celulas == [["Ano", "Casos"], ["2024", "12"], ["2025", "31"]], f"celulas separadas: {t.celulas}")
    ok(t.linhas_cabecalho == 1, f"cabecalho marcado no proprio arquivo: {t.linhas_cabecalho}")
    ok(t.qualidade == "alta" and not t.arquivo, "tabela do DOCX nunca vai como imagem")
    ok((t.rotulo or "").lower().startswith("tabela 1") and "Casos por ano" in (t.legenda or ""),
       f"legenda casada: {t.rotulo!r} / {t.legenda!r}")
    ok(t.fonte == "Autores.", f"fonte da tabela: {t.fonte!r}")
ok(len(m.equacoes) == 1 and m.equacoes[0].mathml and "<mfrac" in m.equacoes[0].mathml,
   f"formula OMML virou MathML sem ninguem digitar: {len(m.equacoes)}")
ok(len(m.referencias) == 2, f"referencias lidas: {len(m.referencias)}")
ok(any(a.orcid == "0000-0002-1825-0097" for a in m.autores) or m.orcids_nao_atribuidos,
   "ORCID do DOCX e lido")

# ---------------------------------------------------------------- os quatro DOCX que o Murillo enviou
print("\n--- DOCX enviados pelo Murillo")
reais = sorted(f for f in os.listdir(os.path.join(RAIZ, "modelos")) if f.endswith(".docx"))
ok(len(reais) == 4, f"{len(reais)} DOCX na pasta modelos")
for nome in reais:
    doc, mm = cli.extrai(os.path.join(RAIZ, "modelos", nome))
    print(f"     {nome[:30]:32s} titulo={(mm.titulo_principal or '')[:44]!r}")
    print(f"       secoes={len(mm.secoes)} paragrafos={sum(len(s.paragrafos) for s in mm.secoes)} "
          f"refs={len(mm.referencias)} figuras={len(mm.figuras)} resumos={len(mm.resumos)}")
    ok(len(mm.secoes) >= 3, f"{nome}: pelo menos 3 secoes pelos estilos ({len(mm.secoes)})")
    ok(sum(len(s.paragrafos) for s in mm.secoes) >= 40, f"{nome}: corpo com conteudo")
    ok(len(mm.referencias) >= 10, f"{nome}: referencias lidas ({len(mm.referencias)})")
    ok(mm.titulo_principal and "ANAMORPHOSIS – REVISTA" not in (mm.titulo_principal or ""),
       f"{nome}: titulo nao e o cabecalho da revista")

# ---------------------------------------------------------------- site: envio de DOCX ponta a ponta
print("\n--- site")
c = TestClient(app, follow_redirects=False)
r = c.post("/registrar", data={"nome": "Cliente DOCX", "email": "docx@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.docx"), "rb") as f:
    r = c.post("/validar", files={"arquivo": ("artigo.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
               data={"revista": "rdp", "sps": "1.9"})
ok(r.status_code == 303, f"site aceita DOCX ({r.status_code})")
doc_id = r.headers["location"].rsplit("/", 1)[-1]
pasta = os.path.join(tmp, "docs", doc_id)
ok(os.path.exists(os.path.join(pasta, "original.docx")), "o DOCX original fica guardado")
val = json.load(io.open(os.path.join(pasta, "validacao.json"), encoding="utf-8"))
print(f"     bloqueantes: {len(val.get('bloqueantes') or [])} | DTD {val.get('dtd_ok')} | SPS {val.get('sps_ok')}")
ok(val.get("dtd_ok") is True, f"XML do DOCX valido no DTD ({val.get('dtd_ok')})")
pag = c.get(f"/doc/{doc_id}/editar").text
ok("Revisar e editar" in pag, "tela de revisar abre para documento vindo de DOCX")
pg = c.get(f"/doc/{doc_id}/paginas.json").json()
ok(pg.get("erro") and "DOCX" in pg["erro"], f"visualizador explica que DOCX nao tem pagina renderizada: {pg.get('erro','')[:60]}")
r = c.post("/validar", files={"arquivo": ("x.txt", b"nao sou artigo", "text/plain")}, data={"revista": "", "sps": "1.9"})
ok(r.status_code == 400 and "Formato" in r.text, "formato nao aceito e recusado com o motivo")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
