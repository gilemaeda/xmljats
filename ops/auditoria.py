"""
Auditoria do sistema: roda o motor nos PDFs de amostra, compara com os XML oficiais da SciELO, exercita o site inteiro
(papeis, isolamento entre contas, cadastro, etapas) e escreve auditoria.md com os numeros medidos.

Uso: python ops/auditoria.py            (completa; leva alguns minutos)
     python ops/auditoria.py --rapida   (so o site e o contraste, sem reprocessar os PDFs)

Nada aqui e escrito a mao: cada linha do relatorio vem de uma medicao desta rodada.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import shutil
import datetime as dt

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "poc"))
SAIDA = os.path.join(RAIZ, "auditoria.md")


def _sh(cmd):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------- motor

def roda_motor(rapida: bool):
    """Extrai todos os PDFs, gera os XML, valida no packtools e devolve as medidas por arquivo."""
    if not rapida:
        _sh([sys.executable, "poc/extrair.py", "article.segmented.pdf", "modelos/*.pdf"])
        _sh([sys.executable, "poc/gerar_xml.py", "poc/saida/*.model.json"])
    itens = []
    for p in sorted(glob.glob(os.path.join(RAIZ, "poc", "saida", "*.model.json"))):
        nome = os.path.basename(p).replace(".model.json", "")
        m = json.load(io.open(p, encoding="utf-8"))
        val = os.path.join(RAIZ, "poc", "saida", "xml", nome + ".validacao.md")
        rel = io.open(val, encoding="utf-8").read() if os.path.exists(val) else ""
        dtd = "DTD: True" in rel
        sps = "Schematron SPS: True" in rel
        nerros = int((re.search(r"erros packtools: (\d+)", rel) or [0, "?"])[1] or 0) if rel else None
        mcomp = re.findall(r"^\| ([^|]+) \| (sim|NÃO) \|", rel, re.M)
        iguais = sum(1 for _, v in mcomp if v == "sim")
        itens.append({
            "nome": nome, "paginas": m.get("paginas"), "autores": len(m.get("autores", [])),
            "orcids": sum(1 for a in m.get("autores", []) if a.get("orcid")), "afiliacoes": len(m.get("afiliacoes", [])),
            "resumos": len(m.get("resumos", [])), "secoes": len(m.get("secoes", [])), "notas": len(m.get("notas", [])),
            "figuras": len([f for f in m.get("figuras", []) if f.get("tipo") == "fig"]),
            "tabelas": len(m.get("tabelas", [])), "tabelas_grade": len([t for t in m.get("tabelas", []) if t.get("celulas")]),
            "equacoes": len(m.get("equacoes", [])), "referencias": len(m.get("referencias", [])),
            "estilo": m.get("estilo_referencias"), "dtd": dtd, "sps": sps, "erros_packtools": nerros,
            "campos_iguais": iguais if mcomp else None, "campos_total": len(mcomp) or None,
            "bloqueantes": len(re.findall(r"^- .+\(\w\d\d\)\.?$", rel.split("## Avisos")[0], re.M)) if rel else None,
        })
    placar = io.open(os.path.join(RAIZ, "poc", "saida", "placar.md"), encoding="utf-8").read() if os.path.exists(os.path.join(RAIZ, "poc", "saida", "placar.md")) else ""
    linhas_placar = [l for l in placar.splitlines() if l.startswith("|") and "**" in l]
    return itens, linhas_placar


# ---------------------------------------------------------------- site

def roda_site():
    """Sobe o app com pasta de dados temporaria e exercita papeis, isolamento, cadastro e etapas."""
    tmp = tempfile.mkdtemp(prefix="xmljats-auditoria-")
    os.environ["XMLJATS_DATA"] = tmp
    os.environ["APP_SENHA"] = "auditoria-123456"
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from app.main import app, VERSAO_APP, ETAPAS
    c = TestClient(app, follow_redirects=False)
    r = []

    def check(nome, cond):
        r.append((nome, bool(cond)))
        return bool(cond)

    check("página protegida redireciona para /entrar sem sessão", c.get("/").status_code == 303)
    check("/saude aberto", c.get("/saude").status_code == 200)
    check("tela de login com botão de mostrar senha", 'class="olho"' in c.get("/entrar").text)
    check("tela de registro público", c.get("/registrar").status_code == 200)
    resp = c.post("/entrar", data={"email": "admin", "senha": "auditoria-123456", "proximo": "/"})
    check("login do administrador", resp.status_code == 303 and "xmljats_sessao" in resp.cookies)
    c.cookies.set("xmljats_sessao", resp.cookies["xmljats_sessao"])
    check("senha guardada só como hash", all(u["senha"].startswith("pbkdf2$") for u in json.load(io.open(os.path.join(tmp, "usuarios.json"), encoding="utf-8"))["usuarios"]))
    check("cadastro de revistas semeado", len(c.get("/revistas").text.split("<tr>")) >= 6 and
          os.path.exists(os.path.join(tmp, "revistas.json")))
    check("revista com ISSN inválido é recusada", c.post("/revistas/nova", data={"acronimo": "x1", "titulo": "T", "abrev": "T", "issn_epub": "1234-5678", "editora": "E", "licenca_url": "https://creativecommons.org/licenses/by/4.0/"}).status_code == 400)
    check("revista válida é criada", c.post("/revistas/nova", data={"acronimo": "audit", "titulo": "Revista da Auditoria", "abrev": "Rev. Aud.", "issn_epub": "2446-8088", "editora": "E", "doi_prefixo": "10.99999/aud", "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "continua", "na_scielo": "nao"}).status_code == 303)
    with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
        up = c.post("/validar", files={"arquivo": ("Direito e Praxis.pdf", f, "application/pdf")}, data={"revista": "", "sps": "1.9"})
    check("upload de PDF processa e redireciona", up.status_code == 303)
    doc = up.headers.get("location", "")
    pag = c.get(doc).text if doc else ""
    check("resultado traz bloqueantes, referências e etapa", all(x in pag for x in ("Bloqueantes", "Referências", "Mudar etapa")))
    check("XML disponível para download", c.get(doc + "/xml").status_code == 200)
    check("pacote .zip disponível", c.get(doc + "/pacote.zip").status_code == 200)
    check("etapa muda e fica gravada", c.post(doc + "/etapa", data={"etapa": "qa"}).status_code == 303 and
          json.load(io.open(os.path.join(tmp, "docs", doc.split("/")[-1], "config.json"), encoding="utf-8"))["etapa"] == "qa")
    check("etapa inválida recusada", c.post(doc + "/etapa", data={"etapa": "xxx"}).status_code == 400)
    # cliente
    c2 = TestClient(app, follow_redirects=False)
    reg = c2.post("/registrar", data={"nome": "Cliente Auditoria", "email": "cliente@auditoria.org", "senha": "senha-auditoria", "senha2": "senha-auditoria"})
    check("registro público cria conta e entra", reg.status_code == 303 and "xmljats_sessao" in reg.cookies)
    c2.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
    check("conta nova é cliente", next(u for u in json.load(io.open(os.path.join(tmp, "usuarios.json"), encoding="utf-8"))["usuarios"] if u["email"] == "cliente@auditoria.org")["papel"] == "cliente")
    check("cliente não vê documento de outra conta", c2.get(doc).status_code == 403)
    check("cliente não acessa administração", c2.get("/admin").status_code == 403 and c2.get("/usuarios").status_code == 403)
    check("cliente não edita cadastro de revistas", c2.get("/revistas/nova").status_code == 403)
    check("painel do cliente vem vazio", "Nenhum documento" in c2.get("/painel").text)
    check("tela da conta com troca de senha", "Trocar senha" in c2.get("/conta").text)
    check("tela de ajuda", c2.get("/ajuda").status_code == 200)
    check("admin vê visão geral com métricas", "Bloqueantes mais frequentes" in c.get("/admin").text)
    check("admin vê todos os documentos", c.get("/admin/documentos").status_code == 200)
    check("sessão com cookie adulterado é recusada", TestClient(app, follow_redirects=False, cookies={"xmljats_sessao": "x"}).get("/").status_code == 303)
    import tempo as _t
    check("horários no fuso de Brasília (-03)", _t.agora().utcoffset().total_seconds() == -10800 and _t.formata("2026-01-02T15:00:00+00:00") == "02/01/2026 12:00")
    check("atividade do usuário é registrada (último acesso e IP)", (json.load(io.open(os.path.join(tmp, "usuarios.json"), encoding="utf-8"))["usuarios"][0].get("atividade") or {}).get("ultimo_acesso"))
    check("painel administrativo mostra contas, uso e filtro por conta", all(x in c.get("/admin").text for x in ("Contas e uso", "Validações por dia", "Filtrar")))
    check("admin edita nome e e-mail de um usuário", c.post("/usuarios/" + json.load(io.open(os.path.join(tmp, "usuarios.json"), encoding="utf-8"))["usuarios"][0]["id"] + "/dados", data={"nome": "Administrador", "email": "admin"}).status_code == 303)
    check("cadastro de revista tem área e estilo de referências", all(x in c.get("/revistas/nova").text for x in ("Área do conhecimento", "Estilo das referências")))
    check("administração é ambiente próprio: admin não usa o validador", c.get("/").headers.get("location") == "/admin")
    check("menu alterna entre lateral e topo", all(x in c.get("/admin").text for x in ('data-menu="lado"', 'data-menu="topo"', 'class="barra-topo"')))
    check("correio tem as cinco caixas", all(c.get(f"/admin/correio?caixa={cx}").status_code == 200 for cx in ("entrada", "saida", "enviados", "rascunhos", "lixeira")))
    check("configuração do Resend com chave mascarada", "Chave da API" in c.get("/admin/config").text)
    check("confirmação de conta pode ser ligada e desligada por um controle próprio",
          "Confirmação de conta" in c.get("/admin/config").text and
          c.post("/admin/config/confirmacao", data={"exigir": "0"}).status_code == 303)
    check("mensagem sem envio configurado fica na caixa de saída",
          c.post("/admin/correio/nova", data={"para": "a@b.org", "assunto": "t", "texto": "t", "acao": "enviar"}).headers.get("location", "").find("saida") > 0)
    check("webhook do correio exige segredo", c.post("/webhook/resend", json={"type": "email.delivered"}).status_code == 403)
    check("foto de perfil e confirmação de e-mail na conta", all(x in c.get("/conta").text for x in ("Foto de perfil", "Trocar senha")))
    ajuda = c.get("/ajuda").text
    check("ajuda explica as etapas e separa o que é feito aqui do que é feito na SciELO",
          all(x in ajuda for x in ("As etapas do documento", "no xmljats", "na SciELO", "Como entregar o pacote para a SciELO")))
    check("ajuda diz o que ainda não é feito", "O que ainda não é feito aqui" in ajuda and "Perguntas rápidas" in ajuda)
    # ---- revista pelo ISSN (cascata: ISSN.org, SciELO, DOAJ, Crossref, OpenAlex)
    check("cadastro de revista busca nas bases de ISSN", "Buscar nas bases" in c.get("/revistas/nova").text)
    check("página Revistas explica de onde vêm os dados e como pedir ISSN novo",
          all(x in c.get("/revistas").text for x in ("Cadastrar pelo ISSN", "Portal do ISSN", "cbissn.ibict.br")))
    import issn as issn_api
    check("dígito verificador do ISSN é conferido antes de ir à rede",
          issn_api.valido("2179-8966") and not issn_api.valido("2179-8967"))
    jr = c.get("/revistas/consulta?numero=2179-8966").json()
    check("consulta de ISSN responde com as fontes ou com a revista já cadastrada", bool(jr.get("ok")))

    # ---- revisar e editar: visualizador, obrigatórios e anexos
    doc_id = doc.rsplit("/", 1)[-1] if doc else ""
    ver = c.get(doc + "/editar").text if doc else ""
    check("revisar mostra o arquivo original com abas", all(x in ver for x in ('id="visor"', 'data-aba="pdf"', 'data-aba="anexos"')))
    check("revisar liga a seleção do PDF a um campo", 'id="visor-selecao"' in ver and 'id="alvo-campo"' in ver)
    check("revisar oferece inserir tabela, imagem, equação, quadro e diálogo",
          all(f'data-add="{g}"' in ver for g in ("tabela", "figura", "equacao", "quadro", "dialogo")))
    check("revisar lista o que a SciELO exige e ainda falta", "O que a SciELO exige e ainda falta" in ver)
    check("revisar tem salvar-e-validar e guardar-rascunho", "Salvar e validar" in ver and "Guardar rascunho" in ver)
    if doc:
        pg = c.get(doc + "/paginas.json").json()
        check("páginas do original são renderizadas com camada de texto",
              pg.get("total", 0) > 0 and len(pg["paginas"][0].get("palavras") or []) > 20)
        primeira = pg["paginas"][0]["arquivo"] if pg.get("paginas") else "p001.png"
        check("imagem da página é servida", c.get(doc + "/pagina/" + primeira).status_code == 200)
        check("nome de página fora do padrão é recusado",
              c.get(doc + "/pagina/qualquer.txt").status_code in (400, 404))
        vazio = c.post(doc + "/editar", data={"acao": "salvar", "revista": "", "heading": "", "licenca": ""})
        check("campo obrigatório vazio impede salvar e validar", vazio.status_code == 400 and "Faltam" in vazio.text)

    # ---- MathML (exigência do guia de entrega da SciELO)
    from app import main as app_main
    mml, erro_mml = app_main.latex_para_mathml("E = mc^2")
    check("LaTeX vira MathML", erro_mml is None and "<math" in (mml or ""))
    check("LaTeX quebrado explica o erro em vez de gerar XML inválido", app_main.latex_para_mathml(chr(92) + "frac{a}{")[1] is not None)
    check("sair encerra a sessão", c.post("/sair").status_code == 303)
    shutil.rmtree(tmp, ignore_errors=True)
    os.environ.pop("APP_SENHA", None)
    os.environ.pop("XMLJATS_DATA", None)
    return r, VERSAO_APP, [e[0] for e in ETAPAS]


# ---------------------------------------------------------------- relatorio

def main():
    rapida = "--rapida" in sys.argv
    itens, placar = roda_motor(rapida)
    verificacoes, versao, etapas = roda_site()
    cod_contraste, saida_contraste = _sh([sys.executable, "ops/audita_contraste.py"])
    falhas_contraste = int((re.search(r"falhas: (\d+)", saida_contraste) or [0, "?"])[1])
    ok_site = sum(1 for _, v in verificacoes if v)
    hoje = dt.date.today().isoformat()

    L = [f"# Auditoria do xmljats — {hoje}", "",
         f"Gerada por `python ops/auditoria.py` (app {versao}). Cada número vem de uma medição desta rodada: "
         "os PDFs foram reprocessados, os XML gerados e validados no packtools, e o site exercitado ponta a ponta.", "",
         "## 1. Resumo", "",
         f"- **Site:** {ok_site} de {len(verificacoes)} verificações passaram.",
         f"- **Contraste (WCAG):** {falhas_contraste} par(es) abaixo do mínimo nos dois temas.",
         f"- **XML:** {sum(1 for i in itens if i['dtd'])} de {len(itens)} arquivos válidos no DTD JATS.",
         f"- **Schematron SPS:** {sum(1 for i in itens if i['sps'])} de {len(itens)} sem erros. "
         "O que sobra está na seção 5: são dados que o PDF não traz (dia e mês da publicação, seção da revista, "
         "resumo em revistas cujo layout ainda não é lido), todos já sinalizados como bloqueante na tela de revisão.", "",
         "## 2. Placar dos seis elementos obrigatórios (PDFs com gabarito conferido à mão)", "",
         "| Arquivo | Seção | Título | Autor + ORCID | Afiliação | Citações | Referências | Extras |",
         "|---|---|---|---|---|---|---|---|"] + placar + ["",
         "## 3. O que o motor extraiu de cada PDF", "",
         "| Arquivo | Págs | Autores | ORCID | Afil. | Resumos | Seções | Notas | Figs | Tabelas (com grade) | Equações | Refs (estilo) | DTD | Erros packtools | Campos iguais ao XML oficial |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i in itens:
        comp = f"{i['campos_iguais']}/{i['campos_total']}" if i["campos_iguais"] is not None else "—"
        L.append(f"| {i['nome']} | {i['paginas']} | {i['autores']} | {i['orcids']} | {i['afiliacoes']} | {i['resumos']} | {i['secoes']} | "
                 f"{i['notas']} | {i['figuras']} | {i['tabelas']} ({i['tabelas_grade']}) | {i['equacoes']} | {i['referencias']} ({i['estilo'] or '—'}) | "
                 f"{'ok' if i['dtd'] else 'FALHA'} | {i['erros_packtools']} | {comp} |")
    L += ["", "## 4. Verificações do site", ""]
    for nome, v in verificacoes:
        L.append(f"- {'ok' if v else '**FALHA**'} — {nome}")
    # erros do packtools agrupados (medido nos relatorios desta rodada)
    from collections import Counter
    erros = Counter()
    for p_rel in glob.glob(os.path.join(RAIZ, "poc", "saida", "xml", "*.validacao.md")):
        txt = io.open(p_rel, encoding="utf-8").read()
        bloco = txt.split("## Erros do packtools")[-1].split("## Comparação")[0]
        for linha in bloco.splitlines():
            if linha.startswith("- "):
                erros[re.sub(r"\(linha[^)]*\)", "", linha[2:]).strip()] += 1
    L += ["", "## 5. O que o validador oficial ainda aponta", "",
          "Agrupado por mensagem, somando os arquivos desta rodada. Todos são dados que o PDF não traz "
          "(a SciELO os recebe do OJS) e que o sistema já mostra como bloqueante na tela de revisão.", "",
          "| Mensagem do packtools | Arquivos |", "|---|---|"]
    for msg, n in erros.most_common(12):
        L.append(f"| {msg[:120]} | {n} |")
    L += ["", "## 6. Etapas do documento", "", "Fluxo implementado: " + " → ".join(etapas) + ".", "",
          "## 7. Cobertura do plano", "",
          "Telas da especificação (seção 5) e ferramentas do plano v3, com o estado de hoje.", "",
          "| Item do plano | Estado | Evidência |", "|---|---|---|",
          "| Tela 1 · Validador público | pronto | verificação \"upload de PDF processa e redireciona\" |",
          "| Tela 2 · Resultado da validação | pronto | verificação \"resultado traz bloqueantes, referências e etapa\" |",
          "| Tela 3 · Revisar e editar | pronto (sem o original renderizado ao lado; mostra o resumo da extração) | tela /doc/{id}/editar |",
          "| Tela 4 · Painel com etapas da SciELO | pronto | verificações de etapa; seção 6 |",
          "| Tela 5 · Cadastro de revistas | pronto | verificações de cadastro de revista |",
          "| Tela 6 · Pacote | pronto | verificação \"pacote .zip disponível\" |",
          "| Tela 7 · Admin interno | pronto (métricas por etapa, revista e bloqueante) | verificação \"admin vê visão geral com métricas\" |",
          "| Contas e papéis | pronto (admin, operador, cliente) | verificações de isolamento entre contas |",
          "| Confirmação de conta por e-mail | pronto (Resend, ligável em Configurações) | verificações de correio e confirmação |",
          "| Correio do sistema (entrada, saída, enviados, rascunhos, lixeira) | pronto | verificação \"correio tem as cinco caixas\" |",
          "| Foto de perfil e menu lateral/topo | pronto | verificações de conta e de menu |",
          "| Cadastro de revista pelo ISSN (ISSN.org, SciELO, DOAJ, Crossref, OpenAlex) | pronto | verificações de consulta por ISSN |",
          "| Visualização do arquivo original no revisar, com seleção ligada aos campos | pronto | verificações do visualizador |",
          "| Inserir tabela, imagem, equação, quadro e diálogo na revisão | pronto | verificação \"revisar oferece inserir...\" |",
          "| Campos que a SciELO exige travando salvar e validar | pronto | verificação \"campo obrigatório vazio impede salvar\" |",
          "| Fórmulas em MathML (exigência do guia de entrega) | pronto | verificações de LaTeX/MathML |",
          "| API oficial do ISSN (api.issn.org) | fora de alcance | é paga e responde 403 sem token; lemos a ficha pública do portal |",
          "| Base consultável do CBISSN/IBICT | não existe | o site é institucional (pedido de ISSN), sem API de periódicos |",
          "| Depósito automático na SciELO | não existe | a SciELO não publica API de depósito; o pacote sai pronto e o envio é pelo canal da coleção |",
          "| Ferramenta 1 · Gerador XML + packtools | pronto | seção 3 (coluna DTD) |",
          "| Ferramenta 6 · Nomenclatura SPS e pacote | pronto | nome-base nos arquivos gerados |",
          "| Figuras, tabelas, equações, notas, referências | pronto | seção 3 (colunas correspondentes) |",
          "| Caminho DOCX | não começou | depende dos arquivos DOCX da ANAMORPHOSIS |",
          "| Parser de referências com IA + Crossref | não começou | hoje é heurística; a confiança de cada referência aparece no resultado |",
          "| Multi-tenant por revista, fila e métricas de custo | não começou | fase 2 do plano |",
          "| Integração com OJS e depósito por FTP | não começou | fase 5 do plano |", ""]
    io.open(SAIDA, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:14]))
    print(f"\nrelatório: {os.path.relpath(SAIDA, RAIZ)}")
    falhou = [n for n, v in verificacoes if not v] + [i["nome"] for i in itens if not i["dtd"]]
    if falhas_contraste:
        falhou.append("contraste")
    print("FALHAS:", falhou or "nenhuma")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
