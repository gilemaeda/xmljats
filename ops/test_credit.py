"""CRediT por autor, financiamento (funding-group) e pedido das pendencias por e-mail."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-credit-")
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
from gerar_xml import valida_packtools  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


REVISTA = {"acronimo": "rdp", "titulo": "Revista Direito e Práxis", "abrev": "Rev. Direito Práx.",
           "issn_epub": "2179-8966", "editora": "UERJ",
           "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "continua"}
MODELO = {
    "idioma": "pt", "tipo_artigo": "research-article", "heading": "Artigos", "doi": "10.1590/2179-8966/2026/99999",
    "volume": "17", "numero": "1", "ano": "2026", "elocation": "e99999", "order": "99999",
    "licenca": "CC BY 4.0", "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
    "datas": {"recebido": "2025-03-01", "aceito": "2025-06-01", "publicado": "2026-02-10"},
    "titulos": [{"texto": "Prova de CRediT e financiamento", "idioma": "pt", "tipo": "article-title"}],
    "autores": [{"nome_completo": "Ana Silva", "sobrenome": "Silva", "nomes": "Ana", "orcid": "0000-0002-1825-0097",
                 "orcid_valido": True, "email": "ana@exemplo.org", "aff_ids": ["aff1"], "correspondente": True,
                 "papel": "author", "credit": ["conceptualization", "writing-original-draft"]}],
    "afiliacoes": [{"id": "aff1", "texto_original": "UERJ", "instituicao": "Universidade do Estado do Rio de Janeiro",
                    "cidade": "Rio de Janeiro", "pais": "Brasil", "pais_iso": "BR", "confianca": "alta"}],
    "resumos": [{"idioma": "pt", "rotulo": "Resumo", "texto": "Resumo da prova.", "palavras_chave": ["direito"]}],
    "secoes": [{"titulo": "Introdução", "titulo_completo": "1 Introdução", "nivel": 1, "pagina": 1,
                "paragrafos": ["Parágrafo único do corpo."]}],
    "citacoes": [], "notas": [], "figuras": [], "tabelas": [], "equacoes": [], "quadros": [], "dialogos": [],
    "referencias": [{"texto": "SILVA, Ana. Livro. São Paulo: Editora, 2020.", "tipo": "book",
                     "autores": ["SILVA, Ana"], "ano": "2020"}],
    "estilo_referencias": "ABNT",
    "financiamentos": [{"fonte": "CNPq", "processo": "310000/2024-0"}, {"fonte": "FAPESP", "processo": ""}],
    "financiamento_texto": "Pesquisa financiada pelo CNPq e pela FAPESP.",
}

for versao in ("1.9", "1.10"):
    res = xml_jats.gera_xml(json.loads(json.dumps(MODELO)), REVISTA, versao)
    ok(not res.bloqueantes, f"SPS {versao}: sem bloqueantes ({'; '.join(res.bloqueantes[:2])})")
    xml = (res.xml or b"").decode("utf-8")
    ok('contributor-roles-conceptualization' in xml and 'contributor-roles-writing-original-draft' in xml,
       f"SPS {versao}: CRediT sai como <role content-type> com a URL que a SciELO valida")
    ok("<funding-group>" in xml and "<funding-source>CNPq</funding-source>" in xml
       and "<award-id>310000/2024-0</award-id>" in xml, f"SPS {versao}: financiamento sai em funding-group/award-group")
    ok("<funding-statement>" in xml, f"SPS {versao}: texto do financiamento sai em funding-statement")
    ok('fn-type="financial-disclosure"' in xml and "310000/2024-0" in xml.split("<back>")[1],
       f"SPS {versao}: o numero do processo tambem aparece na nota de financiamento, como a SciELO cruza")
    caminho = os.path.join(tempfile.mkdtemp(), res.nome_base + ".xml")
    with open(caminho, "wb") as f:
        f.write(res.xml)
    dtd_ok, sps_ok, erros, _ = valida_packtools(caminho)
    ok(dtd_ok is True, f"SPS {versao}: valido no DTD ({[e for e in erros if 'DTD' in e][:1]})")
    if versao == "1.9":
        ok(sps_ok is True, f"SPS {versao}: valido no Schematron ({[e for e in erros if 'DTD' not in e][:2]})")
    else:
        print(f"     SPS 1.10: o packtools 4.16 nao roda o Schematron dessa versao; so o DTD JATS 1.3 e conferido")

# termo fora da taxonomia nao entra
m2 = json.loads(json.dumps(MODELO))
m2["autores"][0]["credit"] = ["inventado", "supervision"]
xml2 = (xml_jats.gera_xml(m2, REVISTA, "1.10").xml or b"").decode("utf-8")
ok("inventado" not in xml2 and "contributor-roles-supervision" in xml2, "termo CRediT invalido e descartado")

# financiamento sem fonte nao gera funding-group vazio
m3 = json.loads(json.dumps(MODELO))
m3["financiamentos"] = []
r3 = xml_jats.gera_xml(m3, REVISTA, "1.10")
ok("<funding-group>" not in (r3.xml or b"").decode("utf-8"), "sem fonte, nao sai funding-group")
ok(any("award-group" in a for a in r3.avisos), "e o aviso explica por que o texto sozinho nao entra")
ok('financial-disclosure' not in (r3.xml or b"").decode("utf-8"), "sem processo, nao sai nota de financiamento sozinha")
m4 = json.loads(json.dumps(MODELO))
m4["financiamentos"] = [{"fonte": "CNPq", "processo": ""}]
r4 = xml_jats.gera_xml(m4, REVISTA, "1.9")
x4 = (r4.xml or b"").decode("utf-8")
ok("<funding-source>CNPq</funding-source>" in x4 and "financial-disclosure" not in x4,
   "fonte sem numero de processo sai no funding-group, sem nota cruzada")
c4 = os.path.join(tempfile.mkdtemp(), r4.nome_base + ".xml")
open(c4, "wb").write(r4.xml)
d4, s4, e4, _ = valida_packtools(c4)
ok(d4 is True and s4 is True, f"fonte sem processo continua valida (DTD {d4} SPS {s4}) {[e for e in e4 if 'DTD' not in e][:1]}")

# ---------------------------------------------------------------- pela tela
c = TestClient(app, follow_redirects=False)
r = c.post("/registrar", data={"nome": "Credit", "email": "credit@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc = r.headers["location"].rsplit("/", 1)[-1]
pasta = __import__("pathlib").Path(tmp) / "docs" / doc

pag = c.get(f"/doc/{doc}/editar").text
ok("Contribuição (CRediT)" in pag and "autor_0_credit_item" in pag, "caixas de CRediT por autor na tela")
ok("Conceituação" in pag and "Escrita: revisão e edição" in pag, "os 13 termos aparecem em português")
ok('data-grupo="fomento"' in pag and "fomento_0_fonte" in pag, "bloco de financiamento na tela")
ok('action="/doc/' in pag and "/pendencias" in pag, "botao de pedir as pendencias por e-mail")

base = M.valores_editaveis(M.modelo_efetivo(pasta))
pend = M.obrigatorios.pendencias(M.modelo_efetivo(pasta), next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp"))
form = {**base, "acao": "salvar", "revista": "rdp",
        "autor_0_credit": "conceptualization, methodology",
        "fomento_0_fonte": "CAPES", "fomento_0_processo": "001",
        "financiamento_texto": "Financiado pela CAPES."}
for campo in pend:
    form[campo] = {"order": "92016", "licenca": "CC BY 4.0"}.get(campo, "2026-02-10" if campo.startswith("data_") else "x")
r = c.post(f"/doc/{doc}/editar", data=form)
ok(r.status_code == 303, "salva com CRediT e financiamento")
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
ok("contributor-roles-conceptualization" in xml and "contributor-roles-methodology" in xml, "CRediT da tela chega ao XML")
ok("<funding-source>CAPES</funding-source>" in xml and "<award-id>001</award-id>" in xml, "financiamento da tela chega ao XML")
val = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
ok(val.get("dtd_ok") is True and val.get("sps_ok") is True, f"XML segue valido (DTD {val.get('dtd_ok')} SPS {val.get('sps_ok')})")

# ---------------------------------------------------------------- pedido das pendencias
c2 = TestClient(app, follow_redirects=False)
r2 = c2.post("/registrar", data={"nome": "Outro", "email": "outro2@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r2.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    r2 = c2.post("/validar", files={"arquivo": ("b.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc2 = r2.headers["location"].rsplit("/", 1)[-1]
r = c2.post(f"/doc/{doc2}/pendencias", data={"destino": ""})
import urllib.parse as _up
ok("Informe o e-mail" in _up.unquote(r.headers["location"]), "pedido sem destinatario e recusado com o motivo")
r = c2.post(f"/doc/{doc2}/pendencias", data={"destino": "editor@revista.org"})
ok(r.status_code == 303 and "rascunhos" in r.headers["location"], "pedido montado como rascunho")
msg = next((m for m in M.CORREIO.lista("rascunhos") if "editor@revista.org" in m["para"]), None)
ok(msg is not None, "rascunho existe no correio")
if msg:
    ok("Order (5 dígitos)" in msg["texto"] or "Order" in msg["texto"], "o pedido lista o que falta pelo nome do campo")
    ok("Data de publicação" in msg["texto"], "o pedido inclui as datas que estao no OJS")
    ok("SciELO" in msg["assunto"] and "Faltam" in msg["assunto"], f"assunto direto: {msg['assunto'][:60]}")
    ok("devolvido" in msg["texto"], "o pedido explica a consequencia de nao ter os dados")
r = c2.post(f"/doc/{doc}/pendencias", data={"destino": "x@y.org"})
ok(r.status_code == 403, "conta que nao e dona do documento nao monta o pedido")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
