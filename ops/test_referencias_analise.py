"""Pontos levantados na analise do XML gerado (PDF 'Analise XML SciELO', 05/09/2026), um a um."""
import io
import json
import os
import re
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-anal-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "poc"))
sys.path.insert(0, os.path.join(RAIZ, "app"))
os.chdir(RAIZ)
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from extrator.citacao import campos_referencia  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- 1. (eds.)/(org.) sao editores, nao autores
casos = [
    ("GEWIRTZ, Paul; BROOKS, P. (eds.). Law stories: narrative and rhetoric in the Law. Yale University Press, 1996.",
     ["GEWIRTZ, Paul", "BROOKS, P."], "editores"),
    ("NOVOA, Jorge (org.). Cinema e historia. Salvador: EDUFBA, 2008.", ["NOVOA, Jorge"], "editores"),
    ("SIMIONI, Rafael Lazzarotto. Direito e literatura. Curitiba: Jurua, 2019.", ["SIMIONI, Rafael Lazzarotto"], "autores"),
    ("SILVA, A. Capitulo. In: SOUZA, B. (org.). Livro coletivo. Sao Paulo: Editora, 2020. p. 10-20.", ["SILVA, A."], "autores"),
    ("WARBURG, Aby. A renovacao da antiguidade paga. Sao Paulo: Contraponto, 2013.", ["WARBURG, Aby"], "autores"),
]
for texto, aut, esperado in casos:
    r = campos_referencia(texto, "book", aut)
    a = [x[0] for x in r.get("autores", [])]
    e = [x[0] for x in r.get("editores", [])]
    certo = (esperado == "editores" and e and not a) or (esperado == "autores" and a)
    ok(certo, f"{esperado}: autores={a} editores={e} <- {texto[:46]}")

# ---------------------------------------------------------------- 2. data de acesso sem endereco nao sai
r = campos_referencia("SIMIONI, R. A Jurisprudenz de Klimt. Anamorphosis, v. 5, n. 1, p. 37-68, 2019. "
                      "Disponivel em: . Acesso em: 18 dez. 2024.", "journal", ["SIMIONI, R."])
ok("date-in-citation" not in r, "sem endereco, a data de acesso nao entra no element-citation")
ok(r.get("_acesso_sem_link"), "mas fica registrada para virar aviso na tela")
r2 = campos_referencia("SILVA, A. Artigo. Revista, 2020. Disponivel em: https://exemplo.org/a. Acesso em: 1 jan. 2025.",
                       "journal", ["SILVA, A."])
ok(r2.get("date-in-citation") and r2.get("ext-link"), "com endereco, a data de acesso entra normalmente")

# ---------------------------------------------------------------- 3. rodape do artigo nao gruda na ultima referencia
from extrator import referencias as R  # noqa: E402
ok(R.RE_RODAPE_ARTIGO.search("Sao Paulo: Contraponto, 2013. Idioma original: Portugues Recebido: 23/12/24 Aceito: 05/01/25"),
   "o rodape da revista e reconhecido")
ok(not R.RE_RODAPE_ARTIGO.search("SILVA, A. Como citar Hegel na filosofia do direito. Sao Paulo, 2020."),
   "titulo de referencia com 'Como citar' sem dois-pontos nao dispara o corte")
ok(not R.RE_RODAPE_ARTIGO.search("BRASIL. Lei de acesso a informacao. Brasilia, 2011."),
   "referencia comum nao dispara o corte")

# ---------------------------------------------------------------- 4. artigo de verdade, ponta a ponta
c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "An", "email": "an@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "1227_VF+-+Simioni (3).pdf"), "rb") as f:
    up = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "anamps", "sps": "1.9"})
doc = up.headers["location"].rsplit("/", 1)[-1]
pasta = os.path.join(tmp, "docs", doc)
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
val = json.load(io.open(os.path.join(pasta, "validacao.json"), encoding="utf-8"))

b34 = re.search(r'<ref id="B34">.*?</mixed-citation>', xml, re.S).group(0)
ok("Recebido:" not in b34 and "Idioma original" not in b34,
   f"B34 sem o rodape do artigo: ...{b34.split('<mixed-citation>')[1][-58:]}")
b27 = re.search(r'<ref id="B27">.*?</ref>', xml, re.S).group(0)
ok("date-in-citation" not in b27, "B27 sem data de acesso solta")
b13 = re.search(r'<ref id="B13">.*?</ref>', xml, re.S).group(0)
ok('person-group-type="editor"' in b13, f"B13 com editor: {re.findall(r'person-group-type=.(\\w+).', b13)}")
ok(xml.count("<ref id=") == 34, f"as 34 referencias continuam la ({xml.count('<ref id=')})")
ok(val.get("dtd_ok") is True, f"XML valido no DTD ({val.get('dtd_ok')})")

avisos = (val.get("avisos_gerador") or []) + (val.get("avisos_extrator") or [])
r03 = [a for a in avisos if "(R03)" in a]
r04 = [a for a in avisos if "(R04)" in a]
ok(r03 and "sem chamada no texto" in r03[0], f"aviso das referencias nao citadas: {r03[0][:110] if r03 else 'nao saiu'}")
ok(all(f"B{n}" in r03[0] for n in (8, 9, 20, 25)) if r03 else False,
   "o aviso nomeia exatamente as referencias sem chamada (B8, B9, B20, B25)")
ok(r04 and "B27" in r04[0], f"aviso da data de acesso sem endereco: {r04[0][:110] if r04 else 'nao saiu'}")

# ---------------------------------------------------------------- 5. page-count: o que a SciELO realmente publica
import glob  # noqa: E402
oficiais = glob.glob(os.path.join(RAIZ, "modelos", "gabarito", "*.xml"))
com_page = [os.path.basename(f) for f in oficiais
            if "<page-count" in io.open(f, encoding="utf-8", errors="replace").read()]
# Contradicao registrada: a documentacao (whatsnew-1.1) diz que page-count e obrigatorio desde a SPS 1.1,
# mas o XML que a propria SciELO publica nao o traz. Seguimos a documentacao, que e o que ela cobra.
print(f"     XML publicados pela SciELO com page-count: {len(com_page)} de {len(oficiais)}")
ok("<page-count" in xml, "nosso XML leva page-count, como a documentacao da SPS exige desde a 1.1")
ok(re.search(r'<page-count count="(\d+)"', xml).group(1) == "23",
   f"o total vem contado do PDF enviado: {re.search(chr(39) + chr(60) + 'page-count count=' + chr(34) + '(.d+)' + chr(34) + chr(39), xml)}")
# artigo com paginas reais continua levando page-count
from extrator import xml_jats  # noqa: E402
m = {"idioma": "pt", "tipo_artigo": "research-article", "heading": "Artigos", "doi": "10.1590/x/2026/1",
     "volume": "17", "numero": "1", "ano": "2026", "fpage": "10", "lpage": "25", "order": "99999",
     "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
     "datas": {"recebido": "2025-03-01", "aceito": "2025-06-01", "publicado": "2026-02-10"},
     "titulos": [{"texto": "T", "idioma": "pt", "tipo": "article-title"}],
     "autores": [{"nome_completo": "A S", "sobrenome": "S", "nomes": "A", "orcid": "0000-0002-1825-0097",
                  "orcid_valido": True, "email": "a@e.org", "aff_ids": ["aff1"], "correspondente": True}],
     "afiliacoes": [{"id": "aff1", "instituicao": "U", "pais_iso": "BR", "texto_original": "U"}],
     "resumos": [{"idioma": "pt", "rotulo": "Resumo", "texto": "R", "palavras_chave": ["k"]}],
     "secoes": [{"titulo": "I", "titulo_completo": "1 I", "nivel": 1, "paragrafos": ["p"]}],
     "referencias": [{"texto": "SILVA, A. Livro. Sao Paulo: E, 2020.", "tipo": "book", "autores": ["SILVA, A."], "ano": "2020"}],
     "citacoes": [], "notas": [], "figuras": [], "tabelas": [], "equacoes": [], "estilo_referencias": "ABNT"}
rev = {"acronimo": "rdp", "titulo": "R", "abrev": "R", "issn_epub": "2179-8966", "editora": "E",
       "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "regular"}
xp = (xml_jats.gera_xml(m, rev, "1.9").xml or b"").decode("utf-8")
ok('<page-count count="16"/>' in xp, "artigo com paginas reais leva page-count calculado (10 a 25 = 16)")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
