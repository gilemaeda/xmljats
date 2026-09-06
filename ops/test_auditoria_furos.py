"""Auditoria de 06/09/2026: freio de login e registro, XML em rascunho, 'ir para o campo', tempo medido,
envio fora do event loop, e-mail editorial no cadastro e textos atualizados."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import threading
import time
import urllib.request

tmp = tempfile.mkdtemp(prefix="xmljats-aud-")
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
from gerar_xml import valida_packtools  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- 1. freio de login
c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "Aud", "email": "aud@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
             headers={"x-forwarded-for": "10.0.0.1"})
ok(reg.status_code == 303, "registro cria a conta")
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])

atacante = TestClient(app, follow_redirects=False)
codigos = []
for i in range(M.FREIO_LIMITE + 1):
    r = atacante.post("/entrar", data={"email": "aud@exemplo.org", "senha": f"errada-{i}", "proximo": "/"},
                      headers={"x-forwarded-for": "10.0.0.9"})
    codigos.append(r.status_code)
ok(codigos[:M.FREIO_LIMITE] == [401] * M.FREIO_LIMITE and codigos[-1] == 429,
   f"depois de {M.FREIO_LIMITE} senhas erradas, a seguinte é freada com 429: {codigos}")
ok("Aguarde" in r.text and "minuto" in r.text, "a tela diz quanto tempo esperar")
r = atacante.post("/entrar", data={"email": "aud@exemplo.org", "senha": "senha-forte-1", "proximo": "/"},
                  headers={"x-forwarded-for": "10.0.0.10"})
ok(r.status_code == 429, "o freio por e-mail vale mesmo com a senha certa vindo de outro IP")
M.freio_limpa("login:email:aud@exemplo.org")
r = atacante.post("/entrar", data={"email": "aud@exemplo.org", "senha": "senha-forte-1", "proximo": "/"},
                  headers={"x-forwarded-for": "10.0.0.10"})
ok(r.status_code == 303, "liberado o e-mail, a senha certa entra de outro IP")
r = atacante.post("/entrar", data={"email": "aud@exemplo.org", "senha": "senha-forte-1", "proximo": "/"},
                  headers={"x-forwarded-for": "10.0.0.9"})
ok(r.status_code == 429, "mas o IP que errou continua freado")
outra = TestClient(app, follow_redirects=False).post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"},
                                                     headers={"x-forwarded-for": "10.0.0.11"})
ok(outra.status_code == 303, "outra conta, de outro IP, não é afetada")
ok(M.freio_minutos(61) == "2 minutos" and M.freio_minutos(30) == "1 minuto", "a espera é arredondada para cima, em minutos")

# ---------------------------------------------------------------- 2. freio de registro
codigos = []
for i in range(M.FREIO_REGISTROS + 1):
    r = TestClient(app, follow_redirects=False).post(
        "/registrar", data={"nome": f"R{i}", "email": f"r{i}@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
        headers={"x-forwarded-for": "10.0.0.77"})
    codigos.append(r.status_code)
ok(codigos[:M.FREIO_REGISTROS] == [303] * M.FREIO_REGISTROS and codigos[-1] == 429,
   f"{M.FREIO_REGISTROS} contas do mesmo IP passam; a seguinte é freada: {codigos}")
ok(not any(u["email"] == f"r{M.FREIO_REGISTROS}@exemplo.org" for u in M.CONTAS.lista()), "a conta freada não foi criada")

# ---------------------------------------------------------------- 3. envio: rascunho, tempo medido, link para o campo
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    up = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
ok(up.status_code == 303, f"envio processa ({up.status_code})")
doc = up.headers["location"].rsplit("/", 1)[-1]
pasta = __import__("pathlib").Path(tmp) / "docs" / doc
val = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
ok(not val.get("pronto") and val.get("bloqueantes"), f"o artigo chega com bloqueante ({len(val.get('bloqueantes') or [])})")
arq_xml = next(pasta.glob("*.xml"))
xml = arq_xml.read_bytes()
ok(xml.startswith(b"<?xml") and b"<!-- xmljats: RASCUNHO" in xml[:400],
   "XML com bloqueante sai marcado como rascunho logo abaixo da declaração")
d, s, erros, _ = valida_packtools(str(arq_xml))
ok(d is True, f"o comentário não estraga a validação do DTD ({d})")
ok(isinstance(val.get("duracao_s"), (int, float)) and val["duracao_s"] > 0
   and 0 < val.get("duracao_extracao_s", 0) <= val["duracao_s"],
   f"tempo de processamento medido: {val.get('duracao_s')} s no total, {val.get('duracao_extracao_s')} s de extração")
pag = c.get(f"/doc/{doc}").text
ok("XML (rascunho)" in pag and "Pacote .zip (rascunho)" in pag, "os botões avisam que é rascunho")
links = re.findall(r'href="/doc/' + doc + r'/editar#f-([a-z_0-9]+)">ir para o campo', pag)
ok(links and "data_publicado" in links, f"bloqueante leva ao campo exato: {links}")
ed = c.get(f"/doc/{doc}/editar").text
ok(all(f'id="f-{alvo}"' in ed for alvo in links), "todos os campos apontados existem na tela de revisar")
ok("is-alvo" in io.open(os.path.join(RAIZ, "app", "static", "revisar.js"), encoding="utf-8").read()
   and ".field.is-alvo" in io.open(os.path.join(RAIZ, "app", "static", "style.css"), encoding="utf-8").read(),
   "o revisar destaca o campo ao chegar pelo link")
ok(c.get(f"/doc/{doc}/xml").status_code == 200, "o rascunho continua podendo ser baixado para conferência")
pv = c.get(f"/doc/{doc}/previa")
ok(pv.status_code == 200 and "<html" in pv.text.lower(), f"a prévia abre com o XML em rascunho ({pv.status_code})")

# completa o que falta: a marca some
modelo = M.modelo_efetivo(pasta)
revista = next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp")
form = {"acao": "salvar", "revista": "rdp"}
for k, v in M.valores_editaveis(modelo).items():
    form[k] = v
for campo in M.obrigatorios.pendencias(modelo, revista):
    if campo.startswith("data_"):
        form[campo] = "2026-02-10"
    elif campo == "order":
        form[campo] = "92016"
    elif campo == "licenca":
        form[campo] = "CC BY 4.0"
    elif campo != "_referencias":
        form.setdefault(campo, "Preenchido")
r = c.post(f"/doc/{doc}/editar", data=form)
val2 = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
ok(r.status_code == 303 and val2.get("pronto") is True, f"documento completo fica pronto ({val2.get('pronto')})")
ok(b"RASCUNHO" not in next(pasta.glob("*.xml")).read_bytes(), "pronto, o XML sai sem a marca de rascunho")
ok("(rascunho)" not in c.get(f"/doc/{doc}").text, "e os botões voltam ao normal")
ok(val2.get("duracao_s") == val.get("duracao_s"), "salvar a revisão não apaga a medição do envio")

# ---------------------------------------------------------------- 4. painel administrativo
adm = TestClient(app, follow_redirects=False)
ra = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"}, headers={"x-forwarded-for": "10.0.0.12"})
adm.cookies.set("xmljats_sessao", ra.cookies["xmljats_sessao"])
pa = adm.get("/admin").text
ok("tempo médio por artigo" in pa and "1 medido(s)" in pa, "o painel mostra o tempo médio e quantos artigos foram medidos")
ok("custo de IA: 0" in pa, "e registra custo de IA zero: não há modelo de linguagem no pipeline")

# ---------------------------------------------------------------- 5. e-mail da equipe editorial
base = {"acronimo": "tst", "titulo": "Teste", "abrev": "Teste", "issn_epub": "1413-9936", "editora": "E",
        "licenca_url": "https://creativecommons.org/licenses/by/4.0/"}
_d, erros = M.valida_revista(dict(base, email_editorial="nao-e-email"), M.carrega_revistas())
ok("email_editorial" in erros, "e-mail editorial inválido é recusado")
d2, e2 = M.valida_revista(dict(base, email_editorial="editoria@revista.org"), M.carrega_revistas())
ok("email_editorial" not in e2 and d2["email_editorial"] == "editoria@revista.org", "e-mail válido fica guardado")
d3, e3 = M.valida_revista(dict(base), M.carrega_revistas())
ok("email_editorial" not in e3 and d3["email_editorial"] is None, "em branco não é erro: o aviso vai só para a SciELO")
ok('name="email_editorial"' in adm.get("/revistas/nova").text, "o campo está no formulário da revista")

# ---------------------------------------------------------------- 6. textos
aj = c.get("/ajuda").text
bloco = aj.split("O que ainda não é feito aqui")[1].split("Perguntas rápidas")[0]
ok("CRediT" not in bloco and "Hoje o sistema lê PDF" not in bloco, "a ajuda não diz mais que CRediT e DOCX faltam")
ok("PDF ou DOCX do artigo" in aj and "equação pede o LaTeX" in aj, "a ajuda fala nos dois formatos e segue o guia nas fórmulas")
ok("PDF ou o DOCX" in c.get("/").text, "a tela inicial fala nos dois formatos")

# ---------------------------------------------------------------- 6b. PDF escaneado é detectado, não engolido
import fitz  # noqa: E402

src = fitz.open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"))
esc = fitz.open()
for i in range(2):
    pix = src[i].get_pixmap(dpi=72)
    pg = esc.new_page(width=src[i].rect.width, height=src[i].rect.height)
    pg.insert_image(pg.rect, pixmap=pix)
caminho_esc = os.path.join(tmp, "escaneado.pdf")
esc.save(caminho_esc)
with open(caminho_esc, "rb") as f:
    up2 = c.post("/validar", files={"arquivo": ("escaneado.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.10"})
ok(up2.status_code == 303, f"PDF escaneado é aceito e processado ({up2.status_code})")
doc2 = up2.headers["location"].rsplit("/", 1)[-1]
val3 = json.load(io.open(__import__("pathlib").Path(tmp) / "docs" / doc2 / "validacao.json", encoding="utf-8"))
ok(bool(val3.get("bloqueantes")) and "camada de texto" in val3["bloqueantes"][0] and "(D01)" in val3["bloqueantes"][0],
   f"o primeiro bloqueante explica que o PDF não tem texto: {(val3.get('bloqueantes') or ['-'])[0][:90]}")
ok("escaneado" in c.get(f"/doc/{doc2}").text, "o resultado diz que o PDF é escaneado")
ok("correções à mão por artigo" in adm.get("/admin").text, "o painel mostra as correções à mão por artigo (taxa de erro do motor)")
ok("Se a revista deposita sozinha" in c.get(f"/doc/{doc}/entrega").text, "a tela de entrega traz o roteiro para a revista depositar sozinha")

# ---------------------------------------------------------------- 7. o envio não trava o site (servidor de verdade)
import httpx  # noqa: E402

PORTA = "8973"
env = dict(os.environ, XMLJATS_DATA=tempfile.mkdtemp(prefix="xmljats-aud-srv-"), APP_SENHA="senha-de-teste-123",
           PYTHONPATH=RAIZ + os.pathsep + os.path.join(RAIZ, "app"))
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", PORTA, "--host", "127.0.0.1"],
                       cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base_url = "http://127.0.0.1:" + PORTA
try:
    subiu = False
    for _ in range(60):
        try:
            urllib.request.urlopen(base_url + "/saude", timeout=2)
            subiu = True
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    ok(subiu, "servidor de verdade no ar")
    sess = httpx.Client(base_url=base_url, follow_redirects=False, timeout=240)
    sess.post("/registrar", data={"nome": "S", "email": "s@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
    estado = {}

    def envia():
        with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
            estado["resp"] = sess.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")},
                                       data={"revista": "rdp", "sps": "1.9"})

    t = threading.Thread(target=envia)
    t.start()
    time.sleep(0.8)  # o envio já está dentro da extração
    latencias = []
    while t.is_alive() and len(latencias) < 6:
        t0 = time.perf_counter()
        try:
            urllib.request.urlopen(base_url + "/saude", timeout=5)
            latencias.append(time.perf_counter() - t0)
        except Exception:  # noqa: BLE001
            latencias.append(99.0)
        time.sleep(0.3)
    t.join()
    ok(estado.get("resp") is not None and estado["resp"].status_code == 303, "o envio pelo servidor de verdade termina bem")
    ok(bool(latencias) and max(latencias) < 2.0,
       f"/saude respondeu enquanto o artigo era processado (latências {[round(x, 2) for x in latencias]} s)")
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:  # noqa: BLE001
        srv.kill()
    shutil.rmtree(env["XMLJATS_DATA"], ignore_errors=True)

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
