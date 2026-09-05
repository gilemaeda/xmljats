"""Ferramentas que completam o que o arquivo nao traz: busca no documento, DOI no Crossref e ORCID."""
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-ferr-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "app"))
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
import enriquece as E  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- DOI: formato antes da rede
ok(E.normaliza_doi("https://doi.org/10.1590/2179-8966/2026/92016") == "10.1590/2179-8966/2026/92016",
   "DOI colado como URL e reconhecido")
ok(E.normaliza_doi("10.1590/abc.") == "10.1590/abc", "ponto final colado no DOI e removido")
ok(E.normaliza_doi("sem doi aqui") is None, "texto sem DOI devolve None")
r = E.por_doi("abc")
ok(r["ok"] is False and "10." in r["mensagem"], "DOI invalido nao vai a rede e explica o formato")
r = E.por_doi("10.9999/naoexiste-xmljats-teste")
ok(r["ok"] is False and "Crossref" in r["mensagem"], f"DOI inexistente devolve mensagem clara: {r['mensagem'][:70]}")

# ---------------------------------------------------------------- DOI: consulta de verdade
r = E.por_doi("10.1590/2179-8966/2026/92016")
ok(r["ok"], "consulta o registro real no Crossref")
if r["ok"]:
    print("     campos:", ", ".join(sorted(r["campos"])))
    ok(r["campos"].get("volume") == "17" and r["campos"].get("numero") == "3",
       f"volume e numero vindos do Crossref: {r['campos'].get('volume')}/{r['campos'].get('numero')}")
    ok((r["campos"].get("licenca") or "").startswith("https://creativecommons.org/licenses/"),
       f"licenca em URL Creative Commons: {r['campos'].get('licenca')}")
    ok(len(r["campos"].get("resumo_0_texto") or "") > 200, "resumo do registro veio inteiro")
    ok(not (r["campos"].get("resumo_0_texto") or "").startswith("<"), "resumo sem as etiquetas do JATS do Crossref")
    ok(r["autores"] and r["autores"][0]["orcid"] == "0000-0002-6969-7585",
       f"ORCID do autor vem do registro: {(r['autores'] or [{}])[0].get('orcid')}")
    ok("dia e mês" in r["mensagem"] or "data_publicado" in r["campos"],
       "quando a data vem so com o ano, a mensagem diz que dia e mes continuam faltando")
    ok("data_publicado" not in r["campos"] or len(r["campos"]["data_publicado"]) == 10,
       "data so entra completa (nunca so o ano)")

# ---------------------------------------------------------------- ORCID
ok(E.confere_orcid("abc")["ok"] is False, "ORCID fora do formato nao vai a rede")
r = E.confere_orcid("0000-0002-6969-7585", "Sara da Nova Quadros Côrtes")
ok(r["existe"] and r["confere"] is not False, f"ORCID real confere com o nome: {r['mensagem'][:70]}")
r = E.confere_orcid("0000-0002-1825-0097", "Sara Côrtes")
ok(r["existe"] and r["confere"] is False and "não bate" in r["mensagem"],
   f"ORCID de outra pessoa e apontado: {r['mensagem'][:80]}")
r = E.confere_orcid("0000-0000-0000-0000")
ok(r["ok"] and not r["existe"], "ORCID inexistente e apontado sem quebrar")

# ---------------------------------------------------------------- rotas do site
c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "Ferramentas", "email": "ferr@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    up = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc = up.headers["location"].rsplit("/", 1)[-1]

j = c.get(f"/doc/{doc}/doi?numero=10.1590/2179-8966/2026/92016").json()
ok(j["ok"] and j["campos"].get("volume") == "17", "rota do DOI responde com os campos")
j = c.get("/orcid?numero=0000-0002-6969-7585&nome=Sara Côrtes").json()
ok(j["existe"], "rota do ORCID responde")
ok(c.get("/orcid?numero=xxx").json()["ok"] is False, "rota do ORCID recusa numero invalido")

pag = c.get(f"/doc/{doc}/editar").text
ok('id="busca-texto"' in pag and 'id="busca-prox"' in pag, "campo de busca e navegacao entre ocorrencias na tela")
ok('id="doi-buscar"' in pag, "botao de completar pelo DOI na tela")
ok("data-confere-orcid" in pag, "botao de conferir ORCID por autor")
js = open(os.path.join(RAIZ, "app", "static", "revisar.js"), encoding="utf-8").read()
ok("semAcento" in js and "buscaTexto" in js, "busca compara sem acento")
ok("pintaBusca" in js and "andaBusca" in js, "busca destaca e navega entre as ocorrencias")

# ---------------------------------------------------------------- pre-visualizacao (htmlgenerator do packtools)
prev = c.get(f"/doc/{doc}/previa")
ok(prev.status_code == 200 and len(prev.text) > 20000, f"previa gerada ({prev.status_code}, {len(prev.text)} bytes)")
ok("<body" in prev.text and "<html" in prev.text.lower(), "previa e uma pagina completa")
import re as _re
proprias = [x for x in _re.findall(r'<img[^>]*src="([^"]*)"', prev.text) if not x.startswith("http")]
ok(all(x.startswith(f"/doc/{doc}/img/") for x in proprias),
   f"toda imagem propria da previa aponta para este documento: {proprias[:3]}")
ok("-gf01.tif" not in prev.text, "nenhum nome de arquivo do pacote sobra quebrado na previa")
ok('data-aba="previa"' in pag and 'id="quadro-previa"' in pag, "aba 'Como fica' com o quadro da previa")

# a consulta de outro documento nao vaza para quem nao e dono
c2 = TestClient(app, follow_redirects=False)
r2 = c2.post("/registrar", data={"nome": "Outro", "email": "outro@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r2.cookies["xmljats_sessao"])
ok(c2.get(f"/doc/{doc}/doi").status_code == 403, "conta que nao e dona do documento nao consulta por ele")
ok(c2.get(f"/doc/{doc}/previa").status_code == 403, "previa de documento de outra conta nao vaza")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
