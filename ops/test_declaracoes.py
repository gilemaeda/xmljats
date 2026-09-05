"""Declaracoes editoriais, editor-chefe no cadastro, revista para clientes e autopreenchimento marcado."""
import io
import json
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-dec-")
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
    "titulos": [{"texto": "Prova das declarações editoriais", "idioma": "pt", "tipo": "article-title"}],
    "autores": [{"nome_completo": "Ana Silva", "sobrenome": "Silva", "nomes": "Ana", "orcid": "0000-0002-1825-0097",
                 "orcid_valido": True, "email": "ana@exemplo.org", "aff_ids": ["aff1"], "correspondente": True,
                 "papel": "author"}],
    "afiliacoes": [{"id": "aff1", "texto_original": "UERJ", "instituicao": "UERJ", "cidade": "Rio de Janeiro",
                    "pais": "Brasil", "pais_iso": "BR", "confianca": "alta"}],
    "resumos": [{"idioma": "pt", "rotulo": "Resumo", "texto": "Resumo.", "palavras_chave": ["direito"]}],
    "secoes": [{"titulo": "Introdução", "titulo_completo": "1 Introdução", "nivel": 1, "pagina": 1,
                "paragrafos": ["Parágrafo do corpo."]}],
    "citacoes": [], "notas": [], "figuras": [], "tabelas": [], "equacoes": [], "quadros": [], "dialogos": [],
    "referencias": [{"texto": "SILVA, Ana. Livro. São Paulo: Editora, 2020.", "tipo": "book",
                     "autores": ["SILVA, Ana"], "ano": "2020"}],
    "estilo_referencias": "ABNT",
    "dec_agradecimentos": "Agradecemos aos pareceristas.",
    "dec_financiamento": "Esta pesquisa não foi realizada com financiamento.",
    "dec_contribuicao": "Ana Silva: concepção, redação e revisão.",
    "dec_dados": "Os dados estão no próprio artigo.",
    "dec_dados_situacao": "data-available",
    "dec_conflito": "Não há conflitos de interesse.",
    "dec_ia": "Não foi utilizada ferramenta de IA neste trabalho.",
    "dec_editor": "Carolina Vestena. ORCID: https://orcid.org/0000-0002-1825-0097",
}

# ---------------------------------------------------------------- XML: cada declaracao no lugar da SciELO
for versao in ("1.9", "1.10"):
    res = xml_jats.gera_xml(json.loads(json.dumps(MODELO)), REVISTA, versao)
    ok(not res.bloqueantes, f"SPS {versao}: sem bloqueantes ({'; '.join(res.bloqueantes[:2])})")
    xml = (res.xml or b"").decode("utf-8")
    back = xml.split("<back>")[1] if "<back>" in xml else ""
    an = xml.split("<author-notes>")[1].split("</author-notes>")[0] if "<author-notes>" in xml else ""
    ok("<ack>" in back and "Agradecemos aos pareceristas." in back, f"SPS {versao}: agradecimento em <ack>")
    ok('fn-type="con"' in an and "concepção, redação" in an, f"SPS {versao}: contribuição em author-notes fn-type=con")
    ok('fn-type="conflict"' in an and "Não há conflitos" in an, f"SPS {versao}: conflito em author-notes fn-type=conflict")
    ok('fn-type="edited-by"' in an and "Carolina Vestena" in an, f"SPS {versao}: editor em author-notes fn-type=edited-by")
    ok('sec-type="data-availability"' in back and 'specific-use="data-available"' in back,
       f"SPS {versao}: dados como seção do back com specific-use")
    ok('fn-type="other"' in back and "ferramenta de IA" in back, f"SPS {versao}: declaração de IA em fn-group")
    ok('fn-type="supported-by"' in back and "não foi realizada com financiamento" in back,
       f"SPS {versao}: financiamento sem numero de processo sai como supported-by")
    caminho = os.path.join(tempfile.mkdtemp(), res.nome_base + ".xml")
    with open(caminho, "wb") as f:
        f.write(res.xml)
    dtd_ok, sps_ok, erros, _ = valida_packtools(caminho)
    ok(dtd_ok is True, f"SPS {versao}: válido no DTD ({[e for e in erros if 'DTD' in e][:1]})")
    if versao == "1.9":
        ok(sps_ok is True, f"SPS {versao}: válido no Schematron ({[e for e in erros if 'DTD' not in e][:2]})")

# declaracao vazia nao gera elemento vazio
m2 = json.loads(json.dumps(MODELO))
for k in ("dec_agradecimentos", "dec_dados", "dec_ia", "dec_conflito", "dec_contribuicao", "dec_editor", "dec_financiamento"):
    m2[k] = ""
x2 = (xml_jats.gera_xml(m2, REVISTA, "1.9").xml or b"").decode("utf-8")
ok("<ack>" not in x2 and 'sec-type="data-availability"' not in x2 and 'fn-type="con"' not in x2,
   "declaração em branco não vira elemento vazio no XML")
# situacao invalida e descartada
m3 = json.loads(json.dumps(MODELO))
m3["dec_dados_situacao"] = "inventado"
x3 = (xml_jats.gera_xml(m3, REVISTA, "1.9").xml or b"").decode("utf-8")
ok('specific-use="inventado"' not in x3 and 'sec-type="data-availability"' in x3,
   "situação dos dados fora da lista da SPS é descartada, a declaração fica")

# ---------------------------------------------------------------- cadastro da revista: editor-chefe
adm = TestClient(app, follow_redirects=False)
ra = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"})
adm.cookies.set("xmljats_sessao", ra.cookies["xmljats_sessao"])
base_rev = {"acronimo": "provaed", "titulo": "Revista de Prova", "abrev": "Rev. Prova", "issn_epub": "2317-6172",
            "editora": "Editora", "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
            "modo_publicacao": "continua", "na_scielo": "nao"}
r = adm.post("/revistas/nova", data={**base_rev, "editor_lattes": "https://exemplo.org/naoelattes"})
ok(r.status_code == 400 and "lattes.cnpq.br" in r.text, "Lattes fora do cnpq.br é recusado")
r = adm.post("/revistas/nova", data={**base_rev, "editor_orcid": "0000-0002-1825-0098"})
ok(r.status_code == 400 and "ORCID inválido" in r.text, "ORCID do editor com dígito errado é recusado")
r = adm.post("/revistas/nova", data={**base_rev, "editor_chefe": "Sidney Soares Filho",
                                     "editor_orcid": "https://orcid.org/0000-0002-1825-0097",
                                     "editor_lattes": "http://lattes.cnpq.br/1234567890123456"})
ok(r.status_code == 303, f"revista com editor-chefe é criada ({r.status_code})")
rev = next((x for x in M.carrega_revistas() if x["acronimo"] == "provaed"), None)
ok(rev and rev["editor_chefe"] == "Sidney Soares Filho", "nome do editor gravado")
ok(rev and rev["editor_orcid"] == "0000-0002-1825-0097", f"ORCID normalizado: {rev and rev.get('editor_orcid')}")
ok(rev and rev["editor_lattes"].startswith("http://lattes.cnpq.br/"), "Lattes gravado")
pag = adm.get("/revistas/provaed").text
ok("Editor-chefe" in pag and "Currículo Lattes" in pag, "os campos do editor aparecem no formulário")
linha = M.editor_da_revista(rev)
ok("Sidney Soares Filho" in linha and "orcid.org/0000-0002-1825-0097" in linha and "lattes.cnpq.br" in linha,
   f"a linha do editor junta nome, ORCID e Lattes: {linha[:80]}")

# ---------------------------------------------------------------- cliente cadastra revista
cli = TestClient(app, follow_redirects=False)
rc = cli.post("/registrar", data={"nome": "Cliente", "email": "cli@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
cli.cookies.set("xmljats_sessao", rc.cookies["xmljats_sessao"])
ok(cli.get("/revistas/nova").status_code == 200, "cliente abre a tela de nova revista")
ok("Nova revista" in cli.get("/revistas").text, "o botão de nova revista aparece para o cliente")
r = cli.post("/revistas/nova", data={"acronimo": "docliente", "titulo": "Revista do Cliente", "abrev": "Rev. Cli.",
                                     "issn_epub": "2446-8088", "editora": "E",
                                     "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
                                     "modo_publicacao": "continua", "na_scielo": "nao"})
ok(r.status_code == 303, f"cliente cadastra revista ({r.status_code})")
ok(any(x["acronimo"] == "docliente" for x in M.carrega_revistas()), "a revista do cliente foi gravada")
ok(cli.post("/revistas/rdp/remover").status_code == 403, "cliente continua sem poder remover revista")

# ---------------------------------------------------------------- tela do revisar
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    r = cli.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc = r.headers["location"].rsplit("/", 1)[-1]
pasta = __import__("pathlib").Path(tmp) / "docs" / doc
pag = cli.get(f"/doc/{doc}/editar").text
for campo, rotulo in [("dec_agradecimentos", "Agradecimentos"), ("dec_financiamento", "Financiamento"),
                      ("dec_contribuicao", "contribuição dos autores"), ("dec_dados", "disponibilidade de dados"),
                      ("dec_conflito", "Conflito de interesses"), ("dec_ia", "inteligência artificial"),
                      ("dec_editor", "Editor responsável")]:
    ok(f'name="{campo}"' in pag and rotulo.split()[0] in pag, f"campo '{rotulo}' na tela")
ok('name="dec_dados_situacao"' in pag and "disponíveis mediante pedido" in pag, "situação dos dados como lista")
ok("Como citar este documento" in pag, "bloco 'como citar' na tela")
citacao = M.como_citar(M.modelo_efetivo(pasta), next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp"))
print("     como citar:", citacao[:110])
ok("Revista Direito e Práxis" in citacao and "CÔRTES" in citacao.upper(), "a citação usa autoria e revista de verdade")

# ---------------------------------------------------------------- autopreenchimento vem marcado em azul
# o artigo da Direito e Praxis nao traz declaracoes; o da RBDPP traz oito, entao e nele que isso se prova
with open(os.path.join(RAIZ, "modelos", "RBDPP_2026_v12n2_1498.pdf"), "rb") as f:
    rb = cli.post("/validar", files={"arquivo": ("c.pdf", f, "application/pdf")}, data={"revista": "rbdpp", "sps": "1.9"})
doc_dec = rb.headers["location"].rsplit("/", 1)[-1]
pasta_dec = __import__("pathlib").Path(tmp) / "docs" / doc_dec
pag = cli.get(f"/doc/{doc_dec}/editar").text
mod = M.modelo_efetivo(pasta_dec)
achadas = M.declaracoes_do_artigo(mod)
print("     lidas do arquivo:", {k: t[0][:38] for k, t in achadas.items()})
ok(bool(achadas), f"o que o artigo declara e lido do proprio arquivo ({len(achadas)} campo(s))")
ok(all(t[1].startswith("lido do próprio arquivo") for t in achadas.values()), "cada uma diz de onde veio")
ok("dec_editor" not in achadas or "Submission" not in achadas["dec_editor"][0],
   f"'Editorial process dates' nao e confundido com o editor responsavel: {achadas.get('dec_editor', ('',))[0][:40]}")
ok("dec_conflito" in achadas and "conflict" in achadas["dec_conflito"][0].lower(),
   "a declaracao de conflito do artigo e reconhecida")
ok("is-auto" in pag, "os campos preenchidos sozinhos ficam marcados (azul)")
ok("preenchido automaticamente" in pag, "a tela diz que o preenchimento foi automatico")
css = io.open(os.path.join(RAIZ, "app", "static", "style.css"), encoding="utf-8").read()
bloco_css = css[css.find(".field.is-auto"):css.find(".field.is-auto") + 260]
ok(".field.is-auto" in css and "brand-2" in bloco_css, "o destaque azul esta no CSS")

# o editor do cadastro preenche a declaracao do artigo
lista = M.carrega_revistas()
rdp = next(x for x in lista if x["acronimo"] == "rdp")
rdp["editor_chefe"] = "Carolina Vestena"
rdp["editor_orcid"] = "0000-0002-1825-0097"
M.grava_revistas(lista)
pag = cli.get(f"/doc/{doc}/editar").text
ok("Carolina Vestena" in pag, "o editor do cadastro aparece preenchido na declaracao do artigo")

# salvar leva as declaracoes ao XML
base = M.valores_editaveis(M.modelo_efetivo(pasta))
pend = M.obrigatorios.pendencias(M.modelo_efetivo(pasta), rdp)
form = {**base, "acao": "salvar", "revista": "rdp", "dec_agradecimentos": "Agradecemos ao grupo de pesquisa.",
        "dec_ia": "Nenhuma ferramenta de IA foi usada.", "dec_dados_situacao": "data-not-available",
        "dec_dados": "Nao ha dados para compartilhar."}
for campo in pend:
    form.setdefault(campo, {"order": "92016", "licenca": "CC BY 4.0"}.get(campo, "2026-02-10" if campo.startswith("data_") else "x"))
    form[campo] = {"order": "92016", "licenca": "CC BY 4.0"}.get(campo, "2026-02-10" if campo.startswith("data_") else "x")
r = cli.post(f"/doc/{doc}/editar", data=form)
ok(r.status_code == 303, f"salva com as declaracoes ({r.status_code})")
xml = io.open([os.path.join(pasta, x) for x in os.listdir(pasta) if x.endswith(".xml")][0], encoding="utf-8").read()
ok("Agradecemos ao grupo de pesquisa." in xml and "<ack>" in xml, "agradecimento digitado chega ao XML")
ok('specific-use="data-not-available"' in xml, "situacao dos dados escolhida chega ao XML")
val = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
ok(val.get("dtd_ok") is True and val.get("sps_ok") is True,
   f"XML segue valido (DTD {val.get('dtd_ok')} SPS {val.get('sps_ok')})")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
