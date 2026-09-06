"""Fila de processamento: envio em lote, estados na lista, página de espera, erro visível, retomada e limites."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import time

tmp = tempfile.mkdtemp(prefix="xmljats-fila-")
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
import fila as F  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


DOCS = os.path.join(tmp, "docs")


def cfg_de(doc):
    return json.load(io.open(os.path.join(DOCS, doc, "config.json"), encoding="utf-8"))


def espera(docs, limite=300):
    t0 = time.time()
    while time.time() - t0 < limite:
        if all(cfg_de(d).get("estado") in ("concluido", "erro") for d in docs):
            return True
        time.sleep(1.5)
    return False


c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "Lote", "email": "lote@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
             headers={"x-forwarded-for": "10.2.2.2"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
ok(not F.trabalhando(), "antes do primeiro lote, nenhum trabalhador está de pé")

# ---------------------------------------------------------------- 1. três arquivos de uma vez
nomes = [("Direito e Praxis.pdf", "application/pdf"), ("1227_VF+-+Simioni (3).pdf", "application/pdf"),
         ("RBDPP_2026_v12n2_1498.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]
abertos = [open(os.path.join(RAIZ, "modelos", n), "rb") for n, _ in nomes]
try:
    r = c.post("/validar", files=[("arquivo", (n, f, t)) for (n, t), f in zip(nomes, abertos)], data={"revista": "rdp", "sps": "1.10"})
finally:
    for f in abertos:
        f.close()
ok(r.status_code == 303 and "/painel" in r.headers["location"] and "fila" in r.headers["location"],
   f"três arquivos vão para a fila e a pessoa volta à lista ({r.status_code} → {r.headers.get('location', '')[:60]})")
docs = sorted(os.listdir(DOCS))
ok(len(docs) == 3, f"cada arquivo virou um documento ({len(docs)})")
estados = [cfg_de(d).get("estado") for d in docs]
ok(all(e in ("na_fila", "processando", "concluido") for e in estados) and estados.count("na_fila") >= 1, f"estados logo após o envio: {estados}")
ok(F.trabalhando(), "o trabalhador subiu na primeira necessidade")
ok(all(cfg_de(d).get("criado_em") for d in docs), "o config guarda quando o documento foi criado")

pag = c.get(r.headers["location"]).text  # a lista, com a mensagem do envio
ok("na fila" in pag or "processando" in pag, "a lista mostra o estado de quem ainda não terminou")
ok("atualiza sozinha" in pag and "location.reload" in pag, "a lista avisa que atualiza sozinha e se recarrega")
ok("3 arquivos na fila" in pag, "a mensagem do envio aparece na lista")

ultimo = docs[-1]
esp = c.get(f"/doc/{ultimo}")
ok(esp.status_code == 200 and ("na fila" in esp.text or "processando" in esp.text) and "/estado.json" in esp.text,
   "abrir um documento na fila mostra a página de espera, que consulta o estado")
est = c.get(f"/doc/{ultimo}/estado.json").json()
ok(est.get("estado") in ("na_fila", "processando", "concluido") and "na_fila" in est, f"estado.json responde: {est}")
outro = TestClient(app, follow_redirects=False)
r2 = outro.post("/registrar", data={"nome": "Outra", "email": "outra@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
                headers={"x-forwarded-for": "10.2.2.3"})
outro.cookies.set("xmljats_sessao", r2.cookies["xmljats_sessao"])
ok(outro.get(f"/doc/{ultimo}/estado.json").status_code == 403, "o estado de um documento de outra conta não é exposto")

ok(espera(docs), "os três terminam dentro do prazo")
estados = [cfg_de(d).get("estado") for d in docs]
ok(estados == ["concluido"] * 3, f"todos concluídos: {estados}")
ok(all(os.path.exists(os.path.join(DOCS, d, "validacao.json")) for d in docs), "cada um tem validacao.json")
res = c.get(f"/doc/{docs[0]}").text
ok("Revisar e editar" in res and "/estado.json" not in res, "terminado, abrir o documento mostra o resultado")
pag = c.get("/painel").text
ok("na fila" not in pag and "processando" not in pag and "location.reload" not in pag, "a lista volta ao normal, sem recarga")
ok(F.tamanho() == 0 and F.posicao(M.DOCS / docs[0]) is None, "a fila fica vazia")
ok(all(isinstance(json.load(io.open(os.path.join(DOCS, d, "validacao.json"), encoding="utf-8")).get("duracao_s"), (int, float)) for d in docs),
   "o tempo de processamento é medido também na fila")

# ---------------------------------------------------------------- 2. um arquivo só continua na hora
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.10"})
um = r.headers["location"].rsplit("/", 1)[-1]
ok(r.status_code == 303 and r.headers["location"] == f"/doc/{um}" and os.path.exists(os.path.join(DOCS, um, "validacao.json")),
   "um arquivo só é processado na hora e cai no resultado")
ok(cfg_de(um).get("estado") is None, "documento síncrono não passa pela fila")

# ---------------------------------------------------------------- 3. erro fica visível, não engole
r = c.post("/validar", files=[("arquivo", ("quebrado.pdf", b"isto nao e um pdf", "application/pdf")),
                              ("arquivo", ("quebrado2.pdf", b"nem isto", "application/pdf"))], data={"revista": "rdp", "sps": "1.10"})
ok(r.status_code == 303, "arquivos quebrados entram na fila sem derrubar o envio")
quebrados = sorted(os.listdir(DOCS))[-2:]
ok(espera(quebrados, 120), "os quebrados saem da fila")
ok(all(cfg_de(d).get("estado") == "erro" and cfg_de(d).get("erro") for d in quebrados), f"viram 'erro' com motivo: {cfg_de(quebrados[0]).get('erro', '')[:60]}")
pe = c.get(f"/doc/{quebrados[0]}")
ok(pe.status_code == 200 and "não conseguiu processar" in pe.text and "Tentar de novo" in pe.text, "a página do documento mostra o erro e oferece tentar de novo")
ok('chip crit" title=' in c.get("/painel").text and ">erro<" in c.get("/painel").text, "a lista marca o erro")
ok(F.trabalhando(), "o trabalhador continua de pé depois do erro")
ok(os.path.exists(os.path.join(DOCS, quebrados[0], "erro.txt")), "o traceback fica gravado para quem for investigar")

# ---------------------------------------------------------------- 4. limites e formatos
muitos = [("arquivo", (f"a{i}.pdf", b"x", "application/pdf")) for i in range(M.MAX_LOTE + 1)]
antes = len(os.listdir(DOCS))
r = c.post("/validar", files=muitos, data={"revista": "rdp", "sps": "1.10"})
ok(r.status_code == 400 and len(os.listdir(DOCS)) == antes, f"acima de {M.MAX_LOTE} arquivos é recusado antes de gravar qualquer um")
r = c.post("/validar", files=[("arquivo", ("a.pdf", b"x", "application/pdf")), ("arquivo", ("b.txt", b"x", "text/plain"))],
           data={"revista": "rdp", "sps": "1.10"})
ok(r.status_code == 400 and len(os.listdir(DOCS)) == antes, "um formato errado no lote recusa o lote inteiro, sem gravar nada")

# ---------------------------------------------------------------- 5. retomada depois de reinício
novo = os.path.join(DOCS, "20260101-000000-retoma")
os.makedirs(novo)
shutil.copy(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), os.path.join(novo, "original.pdf"))
io.open(os.path.join(novo, "nome_original.txt"), "w", encoding="utf-8").write("retomado.pdf")
json.dump({"versao_sps": "1.10", "revista": "rdp", "criado_por": "Lote", "criado_por_id": "x", "etapa": "recebido",
           "estado": "processando", "criado_em": "2026-01-01T00:00:00-03:00"}, io.open(os.path.join(novo, "config.json"), "w", encoding="utf-8"))
voltaram = F.retoma()
ok(voltaram == 1, f"documento que ficou 'processando' numa queda volta para a fila ({voltaram})")
ok(espera(["20260101-000000-retoma"], 240) and cfg_de("20260101-000000-retoma").get("estado") == "concluido", "e é processado")

# ---------------------------------------------------------------- 6. reprocessar limpa o estado de erro
for d in quebrados:
    shutil.copy(os.path.join(RAIZ, "modelos", "1222+-+VF (5).pdf"), os.path.join(DOCS, d, "original.pdf"))
r = c.post(f"/doc/{quebrados[0]}/reprocessar")
ok(r.status_code == 303 and cfg_de(quebrados[0]).get("estado") == "concluido" and not cfg_de(quebrados[0]).get("erro"),
   "corrigido o arquivo, 'tentar de novo' processa e o estado volta a concluído")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
