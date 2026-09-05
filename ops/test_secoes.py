"""Texto das secoes editavel, anexos ancorados no ponto do texto e preenchimento pelo cadastro da revista."""
import io
import json
import os
import re
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-secoes-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "app"))
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


c = TestClient(app, follow_redirects=False)
r = c.post("/registrar", data={"nome": "Secoes", "email": "sec@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc = r.headers["location"].rsplit("/", 1)[-1]
pasta = __import__("pathlib").Path(tmp) / "docs" / doc

# ---------------------------------------------------------------- 1. texto das secoes na tela
pag = c.get(f"/doc/{doc}/editar").text
ok('name="secao_0_paragrafos"' in pag, "cada secao tem o texto editavel, nao so a contagem")
ok("Texto da seção" in pag, "o campo do texto aparece rotulado")
modelo = M.modelo_efetivo(pasta)
primeiro = (modelo.get("secoes") or [{}])[0].get("paragrafos") or []
ok(len(primeiro) > 1, f"a secao 1 tem varios paragrafos ({len(primeiro)})")
v = M.valores_editaveis(modelo)
ok(v["secao_0_paragrafos"].count("\n\n") == len(primeiro) - 1,
   "os paragrafos vem separados por linha em branco, um por bloco")
ok(primeiro[0][:40] in pag, "o texto do primeiro paragrafo aparece na tela")

# ---------------------------------------------------------------- 2. botoes de inserir dentro da secao
ok('data-add="tabela" data-secao="0"' in pag, "botao de inserir tabela dentro da secao 1")
ok(pag.count('class="btn small" type="button" data-add="figura" data-secao=') >= 1, "inserir imagem por secao")
ok("Vai na seção" in pag or not (M.modelo_efetivo(pasta).get("tabelas") or []),
   "os anexos existentes mostram em que secao vao")
ok("Inserir nesta seção" in pag, "a secao diz que os botoes inserem ali")

# ---------------------------------------------------------------- 3. editar o texto chega ao XML
base = M.valores_editaveis(M.modelo_efetivo(pasta))
pend = M.obrigatorios.pendencias(M.modelo_efetivo(pasta), next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp"))
form = {**base, "acao": "salvar", "revista": "rdp"}
for campo in pend:
    form[campo] = {"order": "92016", "licenca": "CC BY 4.0"}.get(campo, "2026-02-10" if campo.startswith("data_") else "x")
form["secao_0_paragrafos"] = "Primeiro paragrafo reescrito na revisao.\n\nSegundo paragrafo reescrito na revisao."
form["secao_0_titulo"] = "1 Introducao revisada"
r = c.post(f"/doc/{doc}/editar", data=form)
ok(r.status_code == 303, f"salva com o texto reescrito ({r.status_code})")
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
ok("Primeiro paragrafo reescrito na revisao." in xml and "Segundo paragrafo reescrito na revisao." in xml,
   "os dois paragrafos reescritos estao no XML")
ok("<title>1 Introducao revisada</title>" in xml, "titulo da secao reescrito")
corpo = xml.split("<body>")[1]
ok(corpo.count("<p>Primeiro paragrafo reescrito") == 1, "cada bloco virou um <p>, sem duplicar")

# ---------------------------------------------------------------- 4. anexo ancorado no ponto do texto
form2 = dict(form)
form2.update({
    "tabela_0_rotulo": "Tabela 1", "tabela_0_legenda": "Casos por ano",
    "tabela_0_celulas": "Ano | Casos\n2024 | 12", "tabela_0_cabecalho": "1",
    "tabela_0_secao": "0", "tabela_0_posicao": "2",
    "quadro_0_rotulo": "Quadro 1", "quadro_0_legenda": "Criterios", "quadro_0_texto": "Texto do quadro.",
    "quadro_0_secao": "0", "quadro_0_posicao": "1",
})
r = c.post(f"/doc/{doc}/editar", data=form2)
ok(r.status_code == 303, f"salva com tabela e quadro ancorados ({r.status_code})")
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
sec1 = xml.split("<body>")[1].split("</sec>")[0]
pos_quadro = sec1.find("<boxed-text")
pos_p1 = sec1.find("Primeiro paragrafo reescrito")
pos_tabela = sec1.find("<table-wrap")
pos_p2 = sec1.find("Segundo paragrafo reescrito")
ok(0 < pos_quadro < pos_p1, f"quadro em 'antes do paragrafo 1' vem antes do primeiro paragrafo ({pos_quadro} < {pos_p1})")
ok(pos_p1 < pos_tabela < pos_p2, f"tabela em 'antes do paragrafo 2' cai entre os dois ({pos_p1} < {pos_tabela} < {pos_p2})")
mod = M.modelo_efetivo(pasta)
ok(mod["tabelas"][0]["secao_indice"] == 0 and mod["tabelas"][0]["pos_paragrafo"] == 1,
   f"a posicao da tela (1-based) vira indice no modelo (0-based): {mod['tabelas'][0]['pos_paragrafo']}")
pag = c.get(f"/doc/{doc}/editar").text
ok("antes do parágrafo 2" in pag, "a secao lista os anexos que caem nela, com a posicao")
ok('name="tabela_0_secao"' in pag and 'name="tabela_0_posicao"' in pag,
   "a tabela ganha os campos de secao e posicao para ser movida")

# mover o anexo para outra secao muda o lugar no XML
form3 = dict(form2, **{"tabela_0_secao": "1", "tabela_0_posicao": "1"})
c.post(f"/doc/{doc}/editar", data=form3)
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
secs = xml.split("<body>")[1].split("<sec")
ok(not any("<table-wrap" in s for s in secs[1:2]) and any("<table-wrap" in s for s in secs[2:3]),
   "mudar a secao move a tabela de lugar no XML")

# ---------------------------------------------------------------- 5. a revista preenche o que e dela
lista = M.carrega_revistas()
rev = next(x for x in lista if x["acronimo"] == "rdp")
rev["secao_padrao"] = "Artigos inéditos"
rev["idioma_padrao"] = "pt"
rev["licenca_url"] = "https://creativecommons.org/licenses/by-nc/4.0/"
M.grava_revistas(lista)
c2 = TestClient(app, follow_redirects=False)
r2 = c2.post("/registrar", data={"nome": "Vinculo", "email": "vinc@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r2.cookies["xmljats_sessao"])
with open(os.path.join(RAIZ, "modelos", "1222+-+VF (5).pdf"), "rb") as f:
    r2 = c2.post("/validar", files={"arquivo": ("b.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc2 = r2.headers["location"].rsplit("/", 1)[-1]
pasta2 = __import__("pathlib").Path(tmp) / "docs" / doc2
antes = M.modelo_efetivo(pasta2)
falta_antes = M.obrigatorios.pendencias(antes, rev)
pag2 = c2.get(f"/doc/{doc2}/editar").text
ok("preenchido pelo cadastro" in pag2, "a tela avisa quais campos vieram do cadastro da revista")
da_rev = M.campos_da_revista(antes, rev)
print("     o cadastro forneceu:", {k: t[0] for k, t in da_rev.items()})
ok("licenca" in da_rev or (antes.get("licenca_url") or ""), "a licenca da revista preenche o artigo")
depois = M.obrigatorios.pendencias({**antes, **{("licenca_url" if k == "licenca" else k): t[0] for k, t in da_rev.items()}}, rev)
ok(len(depois) < len(falta_antes) or not falta_antes,
   f"vincular a revista reduz as pendencias: {len(falta_antes)} -> {len(depois)}")
ok(all(k not in depois for k in da_rev), "os campos que a revista forneceu deixam de ser cobrados")
ok(M.campos_da_revista(antes, None) == {}, "sem revista, nada e preenchido")
cheio = dict(antes)
cheio["heading"] = "Ja tinha secao"
ok("heading" not in M.campos_da_revista(cheio, rev), "campo que o arquivo ja trouxe nao e sobrescrito")

# ---------------------------------------------------------------- 6. cadastro guarda o idioma
adm = TestClient(app, follow_redirects=False)
ra = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"})
adm.cookies.set("xmljats_sessao", ra.cookies["xmljats_sessao"])
r = adm.post("/revistas/nova", data={"acronimo": "provaidi", "titulo": "Prova", "abrev": "Prov.", "issn_epub": "2446-8088",
                                   "editora": "E", "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
                                   "modo_publicacao": "continua", "na_scielo": "nao", "idioma_padrao": "zz"})
ok(r.status_code == 400, "idioma fora da lista e recusado no cadastro")
import issn as I  # noqa: E402
ok(I.IDIOMA_ISO3.get("POR") == "pt" and I.IDIOMA_ISO3.get("ENG") == "en", "codigo de idioma do DOAJ e traduzido")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
