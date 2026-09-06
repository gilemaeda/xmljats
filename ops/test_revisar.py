"""Revisar e editar: visualizador do original, campos obrigatorios travando o salvar, tabela/figura/quadro/dialogo/equacao."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-revisar-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML")
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML\app")
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app, follow_redirects=False)
falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


r = c.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"})
c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
# admin não tem validador: usa uma conta cliente para enviar
c2 = TestClient(app, follow_redirects=False)
r = c2.post("/registrar", data={"nome": "Revisora", "email": "rev@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])

PDF = r"C:\Users\gilej\PROJETOS\XML\modelos\Direito e Praxis.pdf"
with open(PDF, "rb") as f:
    r = c2.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
ok(r.status_code == 303, "documento enviado")
doc = r.headers["location"].rsplit("/", 1)[-1]
pasta = os.path.join(tmp, "docs", doc)

# ---- visualizador: indice das paginas e imagem
j = c2.get(f"/doc/{doc}/paginas.json").json()
ok(j.get("total", 0) > 0, f"índice das páginas gerado ({j.get('total')} páginas)")
p1 = j["paginas"][0]
ok(p1["largura"] > 100 and p1["altura"] > 100, f"tamanho da página em pontos ({p1['largura']}x{p1['altura']})")
ok(len(p1["palavras"]) > 50, f"camada de texto com {len(p1['palavras'])} palavras na página 1")
ok(all(len(w) == 7 and isinstance(w[4], str) for w in p1["palavras"][:20]), "cada palavra tem caixa e texto")
img = c2.get(f"/doc/{doc}/pagina/{p1['arquivo']}")
ok(img.status_code == 200 and img.headers["content-type"] == "image/png" and len(img.content) > 5000,
   f"página renderizada em PNG ({len(img.content)} bytes)")
ok(os.path.exists(os.path.join(pasta, "paginas", p1["arquivo"])), "página guardada em disco (não renderiza de novo)")
ok(c2.get(f"/doc/{doc}/pagina/../../config.json").status_code in (404, 400), "nome de página fora do padrão é recusado")

# ---- tela de revisar
pag = c2.get(f"/doc/{doc}/editar").text
ok('id="visor"' in pag and "revisar.js" in pag, "tela traz o visualizador")
ok('data-aba="pdf"' in pag and 'data-aba="texto"' in pag and 'data-aba="anexos"' in pag, "abas do visualizador")
ok('id="visor-selecao"' in pag and 'id="alvo-campo"' in pag, "barra de aplicar a seleção num campo")
for grupo in ("tabela", "figura", "equacao", "quadro", "dialogo"):
    ok(f'data-add="{grupo}"' in pag, f"botão de inserir {grupo}")
ok("Guardar rascunho" in pag and "Salvar e validar" in pag, "os dois botões de salvar")
ok("O que a SciELO exige e ainda falta" in pag, "resumo das pendências no topo")

# ---- campos obrigatorios travam o salvar
r = c2.get(f"/doc/{doc}/editar")
pend_antes = json.loads(io.open(os.path.join(pasta, "validacao.json"), encoding="utf-8").read())
form = {"acao": "salvar", "revista": "rdp", "heading": "", "licenca": ""}
r = c2.post(f"/doc/{doc}/editar", data=form)
ok(r.status_code == 400 and "Faltam" in r.text, "salvar com obrigatório vazio é recusado")
ok("Nada foi salvo ainda" in r.text, "a recusa diz que nada foi salvo")
ok(not os.path.exists(os.path.join(pasta, "edicoes.json")), "nada foi gravado na recusa")
ok('name="heading"' in r.text, "o formulário volta inteiro (nada digitado se perde)")

# ---- rascunho guarda sem validar
r = c2.post(f"/doc/{doc}/editar", data={"acao": "rascunho", "revista": "rdp", "heading": "Artigos"})
ok(r.status_code == 303 and "Rascunho" in r.headers["location"], "rascunho aceito")
ed = json.load(io.open(os.path.join(pasta, "edicoes.json"), encoding="utf-8"))
ok(ed["campos"].get("heading") == "Artigos", "rascunho gravou o campo")

# ---- preencher tudo e validar
modelo = M.modelo_efetivo(__import__("pathlib").Path(pasta))
revista = next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp")
pend = M.obrigatorios.pendencias(modelo, revista)
print("     pendências reais deste PDF:", len(pend), "->", ", ".join(sorted(pend)[:10]))
completo = {"acao": "salvar", "revista": "rdp"}
for campo in pend:
    if campo.startswith("data_"):
        completo[campo] = "2025-06-01"
    elif campo.endswith("_orcid"):
        completo[campo] = "0000-0002-1825-0097"
    elif campo == "order":
        completo[campo] = "12345"
    elif campo == "doi":
        completo[campo] = "10.1590/2179-8966/2026/12345"
    elif campo.endswith("_pais_iso"):
        completo[campo] = "BR"
    elif campo.endswith("_affs"):
        completo[campo] = (modelo.get("afiliacoes") or [{}])[0].get("id") or "aff1"
    elif campo == "corresp":
        completo[campo] = "0"
        completo["autor_0_email"] = "autor@exemplo.org"
    elif campo == "licenca":
        completo[campo] = "CC BY 4.0"
    elif campo.endswith("_kw"):
        completo[campo] = "direito; xml"
    elif campo.endswith("_idioma"):
        completo[campo] = "pt"
    elif campo == "_referencias":
        continue
    else:
        completo[campo] = "Preenchido na revisão"
# mantém o que já estava certo
for k, val in M.valores_editaveis(modelo).items():
    completo.setdefault(k, val)
r = c2.post(f"/doc/{doc}/editar", data=completo)
ok(r.status_code == 303, "com tudo preenchido, salva e valida: " +
   ("ok" if r.status_code == 303 else r.text[r.text.find("Faltam"):r.text.find("Faltam") + 200]))

# ---- inserir tabela, quadro, dialogo e equacao pela tela
extra = dict(completo)
extra.update({
    "tabela_0_rotulo": "Tabela 1", "tabela_0_legenda": "Casos por ano",
    "tabela_0_celulas": "Ano | Casos\n2024 | 12\n2025 | 31", "tabela_0_cabecalho": "1", "tabela_0_fonte": "Autores",
    "quadro_0_rotulo": "Quadro 1", "quadro_0_legenda": "Critérios", "quadro_0_texto": "Primeiro critério.\nSegundo critério.",
    "dialogo_0_rotulo": "Diálogo 1", "dialogo_0_legenda": "Audiência",
    "dialogo_0_turnos": "Juiz: pode prosseguir\nAdvogada: obrigada",
    "equacao_0_rotulo": "(1)", "equacao_0_latex": "E = mc^2",
})
r = c2.post(f"/doc/{doc}/editar", data=extra)
ok(r.status_code == 303, "documento com tabela, quadro, diálogo e equação criados à mão salva")
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
ok("<table-wrap" in xml and "<td>2025</td>" in xml, "tabela criada à mão saiu como tabela de verdade no XML")
ok("<boxed-text" in xml and "Critérios" in xml, "quadro saiu como boxed-text")
ok("<speech>" in xml and "<speaker>Juiz</speaker>" in xml, "diálogo saiu como speech")
ok("<mml:math" in xml, "equação saiu como MathML")
val = json.load(io.open(os.path.join(pasta, "validacao.json"), encoding="utf-8"))
ok(val.get("dtd_ok") is True, f"XML continua válido no DTD ({val.get('dtd_ok')})")
ok(val.get("sps_ok") is True, f"XML continua válido no Schematron SPS ({val.get('sps_ok')})")

# ---- LaTeX quebrado não deixa salvar e explica
ruim = dict(extra, **{"equacao_0_latex": r"\frac{a}{"})
r = c2.post(f"/doc/{doc}/editar", data=ruim)
ok(r.status_code == 400 and "LaTeX" in r.text, "LaTeX quebrado é recusado com explicação")

# ---- envio de imagem de figura
from PIL import Image  # noqa: E402
buf = io.BytesIO()
Image.new("RGB", (400, 300), (40, 80, 160)).save(buf, format="PNG")
r = c2.post(f"/doc/{doc}/figura", data={"indice": "0"}, files={"imagem": ("g.png", buf.getvalue(), "image/png")})
ok(r.status_code == 303 and "guardada" in r.headers["location"], "imagem de figura enviada")
ed = json.load(io.open(os.path.join(pasta, "edicoes.json"), encoding="utf-8"))
ok(ed["campos"].get("figura_0_arquivo", "").startswith("fig01."), "figura registrada na edição")
ok(c2.get(f"/doc/{doc}/img/{ed['campos']['figura_0_arquivo']}").status_code == 200, "imagem enviada é servida")
r = c2.post(f"/doc/{doc}/figura", data={"indice": "1"}, files={"imagem": ("x.txt", b"nao sou imagem", "text/plain")})
ok(r.status_code == 303 and "imagem" in r.headers["location"], "arquivo que não é imagem é recusado com aviso")

# ---- reprocessar limpa as paginas renderizadas
ok(os.path.isdir(os.path.join(pasta, "paginas")), "páginas existem antes de reprocessar")
c2.post(f"/doc/{doc}/reprocessar")
ok(not os.path.exists(os.path.join(pasta, "paginas.json")), "reprocessar descarta o índice das páginas")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
