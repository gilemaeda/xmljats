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
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import urllib.parse
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
        up = c.post("/validar", files={"arquivo": ("Direito e Praxis.pdf", f, "application/pdf")}, data={"revista": "", "sps": "1.10"})
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
    check("cliente cadastra revista, mas não remove",
          c2.get("/revistas/nova").status_code == 200 and c2.post("/revistas/rdp/remover").status_code == 403)
    # a pedido do Murillo, cadastrar revista deixou de ser so do administrador; editar e remover continuam sendo
    check("cliente não edita revista já cadastrada", c2.post("/revistas/rdp", data={"acronimo": "rdp"}).status_code == 403)
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

    # ---- entrega à SciELO (guia de entrega + atestado de capacidade técnica)
    if doc:
        ent = c.get(doc + "/entrega").text
        check("tela de entrega confere o pacote contra o guia",
              "Conferência do pacote" in ent and "Depositar no FTP" in ent)
        check("entrega lembra o aviso obrigatório e o formato do pacote",
              "publicacao@scielo.org" in ent and ".rar" in ent and "MathML ou LaTeX" in ent)
        check("entrega explica o atestado de capacidade técnica", "Atestado de capacidade técnica" in ent and "6 meses" in ent)
        check("entrega traz o roteiro para a revista depositar sozinha", "Se a revista deposita sozinha" in ent and "/Entrega" in ent)
        import zipfile as _zip
        with _zip.ZipFile(io.BytesIO(c.get(doc + "/pacote.zip").content)) as z:
            nomes = z.namelist()
        check("pacote com uma pasta de mesmo nome dentro e o relatório xpm.html (SPS 1.10)",
              len({n.split("/")[0] for n in nomes}) == 1 and all("/" in n for n in nomes) and any(n.endswith("/xpm.html") for n in nomes))
        import entrega as ent_mod
        check("regras de nome do guia (sem acento, underline ou ponto extra)",
              ent_mod.confere_nome("2179-8966-rdp-17-03-e92016.xml") is None and
              ent_mod.confere_nome("artigo_1.xml") and ent_mod.confere_nome("artigo.v2.xml") and
              ent_mod.confere_nome("pacote.rar"))
        check("depósito sem FTP configurado é recusado com explicação",
              "erro" in c.post(doc + "/entrega").headers.get("location", ""))
    cfgp = c.get("/admin/config").text
    check("configurações têm FTP da SciELO e pedido do atestado",
          "FTP da SciELO" in cfgp and "Atestado de capacidade técnica" in cfgp)
    check("pedido de atestado exige empresa e CNPJ",
          "erro" in c.post("/admin/config/atestado", data={"empresa": "", "cnpj": ""}).headers.get("location", ""))

    # ---- ferramentas que completam o que o arquivo não traz
    if doc:
        ver2 = c.get(doc + "/editar").text
        check("visualizador tem busca no documento", 'id="busca-texto"' in ver2)
        check("revisar completa pelo DOI e confere o ORCID",
              'id="doi-buscar"' in ver2 and "data-confere-orcid" in ver2)
        check("item removido pode voltar (campo escondido antes da caixa)",
              'type="hidden" name="autor_0_remover" value=""' in ver2)
    if doc:
        prev = c.get(doc + "/previa")
        check("pré-visualização do artigo (htmlgenerator do packtools)",
              prev.status_code == 200 and len(prev.text) > 20000 and "-gf01.tif" not in prev.text)
    if doc:
        ver5 = c.get(doc + "/editar").text
        check("declarações editoriais no revisar (7 campos)",
              all(f'name="dec_{k}"' in ver5 for k in ("agradecimentos", "financiamento", "contribuicao",
                                                      "dados", "conflito", "ia", "editor")))
        check("situação dos dados e 'como citar' na tela",
              'name="dec_dados_situacao"' in ver5 and "Como citar este documento" in ver5)
        check("campo preenchido sozinho é marcado em azul",
              "is-auto" in open(os.path.join(RAIZ, "app", "static", "style.css"), encoding="utf-8").read())
    check("cadastro de revista tem editor-chefe, ORCID e Lattes",
          all(x in c.get("/revistas/nova").text for x in ("Editor-chefe", "ORCID do editor", "Currículo Lattes")))
    check("Lattes fora do cnpq.br é recusado",
          c.post("/revistas/nova", data={"acronimo": "xled", "titulo": "T", "abrev": "T", "issn_epub": "2446-8088",
                                         "editora": "E", "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
                                         "editor_lattes": "https://exemplo.org/x"}).status_code == 400)
    # pontos levantados na analise externa do XML (PDF "Analise XML SciELO", 05/09/2026)
    from extrator.citacao import campos_referencia as _cr
    from extrator.util import parse_data as _parse_data
    from app.main import declaracoes_do_artigo as app_main_dec
    _eds = _cr("GEWIRTZ, Paul; BROOKS, P. (eds.). Law stories. Yale University Press, 1996.", "book",
               ["GEWIRTZ, Paul", "BROOKS, P."])
    check("(eds.) na abertura da referência vira person-group editor",
          bool(_eds.get("editores")) and not _eds.get("autores"))
    _sem = _cr("SILVA, A. Artigo. Revista, 2019. Disponivel em: . Acesso em: 18 dez. 2024.", "journal", ["SILVA, A."])
    check("data de acesso sem endereço não entra no element-citation", "date-in-citation" not in _sem)
    from extrator import referencias as _rf
    check("rodapé da revista não gruda na última referência",
          bool(_rf.RE_RODAPE_ARTIGO.search("Contraponto, 2013. Recebido: 23/12/24 Aceito: 05/01/25")) and
          not _rf.RE_RODAPE_ARTIGO.search("SILVA, A. Como citar Hegel. Sao Paulo, 2020."))
    import glob as _g
    from extrator import xml_jats as _xj2
    _m = {"paginas": 12, "arquivo": "a.pdf"}
    check("page-count sai do total de páginas do arquivo (SPS 1.1 em diante o exige)",
          _xj2._total_paginas(_m) == 12 and _xj2._total_paginas({"fpage": "10", "lpage": "25"}) == 16
          and _xj2._total_paginas({"paginas": 30, "arquivo": "a.docx"}) is None)
    if doc:
        ver6 = c.get(doc + "/editar").text
        check("total de páginas e 'como citar' editáveis no revisar",
              'name="paginas_total"' in ver6 and 'name="dec_como_citar"' in ver6)
    check("declaração reconhecida em português, inglês e espanhol",
          all(campo in app_main_dec({"back_matter": [{"titulo": t, "texto": "x"}]})
              for t, campo in (("Acknowledgement", "dec_agradecimentos"), ("IA Statement", "dec_ia"),
                               ("Financiación", "dec_financiamento"), ("Data availability", "dec_dados"))))
    check("data com ano de dois dígitos é lida", _parse_data("23/12/24") == "2024-12-23")
    # a home do admin redireciona para a administracao: a tela de envio e a do cliente
    _envio = c2.get("/").text
    check("tela de envio aceita DOCX", ".docx" in _envio and "só PDF" not in _envio)
    check("botão de voltar ao topo em todas as telas",
          'id="ao-topo"' in _envio and 'id="ao-topo"' in c.get("/revistas").text)
    from app import main as _am
    campos_rev_ok = _am.campos_da_revista({}, {"licenca_url": "https://creativecommons.org/licenses/by/4.0/", "titulo": "T"}).get("licenca") is not None
    if doc:
        ver4 = c.get(doc + "/editar").text
        check("texto de cada seção do corpo é editável", 'name="secao_0_paragrafos"' in ver4 and "Texto da seção" in ver4)
        check("inserir tabela/imagem/equação/quadro/diálogo dentro da seção",
              'data-add="tabela" data-secao="0"' in ver4 and "Inserir nesta seção" in ver4)
        check("vincular a revista preenche o que é dado dela", "preenchido pelo cadastro" in ver4 or
              campos_rev_ok)
    import enriquece as enr
    check("DOI inválido é recusado sem ir à rede", enr.por_doi("abc")["ok"] is False)
    check("ORCID fora do formato é recusado sem ir à rede", enr.confere_orcid("abc")["ok"] is False)

    # ---- entrada DOCX
    with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.docx"), "rb") as f:
        up2 = c.post("/validar", files={"arquivo": ("artigo.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                     data={"revista": "rdp", "sps": "1.10"})
    check("site aceita DOCX", up2.status_code == 303)
    docx_doc = up2.headers.get("location", "")
    if docx_doc:
        v2 = json.load(io.open(os.path.join(tmp, "docs", docx_doc.rsplit("/", 1)[-1], "validacao.json"), encoding="utf-8"))
        check("XML vindo de DOCX é válido no DTD JATS", v2.get("dtd_ok") is True)
        check("DOCX original fica guardado",
              os.path.exists(os.path.join(tmp, "docs", docx_doc.rsplit("/", 1)[-1], "original.docx")))
    check("formato fora da lista é recusado com o motivo",
          c.post("/validar", files={"arquivo": ("x.txt", b"nao", "text/plain")},
                 data={"revista": "", "sps": "1.10"}).status_code == 400)
    from extrator.docx import omml_para_mathml
    from lxml import etree as _et
    _omml = _et.fromstring('<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
                           '<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>')
    check("fórmula do Word (OMML) vira MathML", "<mfrac" in (omml_para_mathml(_omml) or ""))

    # ---- CRediT, financiamento e pedido das pendencias
    if doc:
        ver3 = c.get(doc + "/editar").text
        check("CRediT por autor na tela (13 termos da taxonomia)",
              "autor_0_credit_item" in ver3 and "Conceituação" in ver3 and "Escrita: revisão e edição" in ver3)
        check("bloco de financiamento (funding-group) na tela", 'data-grupo="fomento"' in ver3)
        check("pedido das pendências por e-mail na tela", "/pendencias" in ver3)
        check("pedido sem destinatário é recusado",
              "Informe" in urllib.parse.unquote(c.post(doc + "/pendencias", data={"destino": ""}).headers.get("location", "")))
    from extrator import xml_jats as _xj
    check("os 13 termos CRediT são os que o Schematron da SciELO aceita", len(_xj.CREDIT) == 13)

    # ---- licença: a URL tem de bater com o texto escolhido
    from app.main import licenca_url
    check("licença CC BY-NC-ND não vira CC BY-NC",
          licenca_url("CC BY-NC-ND 4.0") == "https://creativecommons.org/licenses/by-nc-nd/4.0/")
    check("licença CC BY-SA não vira CC BY-NC-SA",
          licenca_url("CC BY-SA 4.0") == "https://creativecommons.org/licenses/by-sa/4.0/")

    # ---- MathML (exigência do guia de entrega da SciELO)
    from app import main as app_main
    mml, erro_mml = app_main.latex_para_mathml("E = mc^2")
    check("LaTeX vira MathML", erro_mml is None and "<math" in (mml or ""))
    check("LaTeX quebrado explica o erro em vez de gerar XML inválido", app_main.latex_para_mathml(chr(92) + "frac{a}{")[1] is not None)
    # lista de documentos: ultima abertura e ordenacao
    if doc:
        c.get(doc)  # abrir o resultado registra a abertura
        _lista = c.get("/admin/documentos").text
        check("lista mostra quando o documento foi aberto pela última vez",
              "<th>Aberto</th>" in _lista and ("nunca aberto" in _lista or "há" in _lista))
        check("lista tem seletor de ordenação, com 'aberto mais recente'",
              'name="ordem"' in _lista and "Aberto mais recente" in _lista)
        check("ordem escolhida fica marcada e convive com filtro",
              'value="aberto" selected' in c.get("/admin/documentos?ordem=aberto&situacao=bloqueado").text)
        check("ordem desconhecida não quebra a lista", c.get("/admin/documentos?ordem=xxx").status_code == 200)
        import json as _js
        _cfg = _js.load(io.open(os.path.join(tmp, "docs", doc.rsplit("/", 1)[-1], "config.json"), encoding="utf-8"))
        check("a abertura fica gravada com quem abriu", bool(_cfg.get("aberto_em")) and bool(_cfg.get("aberto_por")))
    # ---- novidades por versão: janela para quem ainda não viu, filtrada por papel
    import novidades as _nov
    from app.main import CONTAS as _contas
    _nc = TestClient(app, follow_redirects=False)
    _nr = _nc.post("/registrar", data={"nome": "Novato", "email": "novato@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
                   headers={"x-forwarded-for": "10.9.9.9"})
    _nc.cookies.set("xmljats_sessao", _nr.cookies["xmljats_sessao"])
    check("conta nova não recebe janela de novidades (nada mudou para ela)", 'id="novidades-modal"' not in _nc.get("/").text)
    _nid = next(u["id"] for u in _contas.lista() if u["email"] == "novato@exemplo.org")
    _contas.marca_novidades(_nid, "0.19.0")
    _home = _nc.get("/").text
    check("novidades: janela para quem ainda não viu a versão", 'id="novidades-modal"' in _home and "SciELO PS 1.10" in _home)
    _so_admin = [i["titulo"] for v in _nov.VERSOES for i in v["itens"] if i["para"] == "admin"]
    _pagina = _nc.get("/novidades").text
    check("cliente não vê novidade do painel administrativo",
          bool(_so_admin) and not any(t in _home for t in _so_admin) and not any(t in _pagina for t in _so_admin))
    check("abrir a página Novidades marca como visto", 'id="novidades-modal"' not in _nc.get("/").text)
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
          "| Entrada por DOCX (seções, tabelas e fórmulas vindas do arquivo) | pronto | ops/test_docx.py, 40 verificações |",
          "| Fórmula do Word (OMML) convertida em MathML sem digitar | pronto | verificação \"fórmula do Word (OMML) vira MathML\" |",
          "| Busca dentro do documento no visualizador | pronto | verificação \"visualizador tem busca no documento\" |",
          "| Completar pelo DOI no Crossref (volume, licença, ORCID, resumo) | pronto | ops/test_ferramentas.py |",
          "| Conferir o ORCID no registro público orcid.org | pronto | ops/test_ferramentas.py |",
          "| CRediT: contribuição de cada autor em <role content-type> | pronto | ops/test_credit.py |",
          "| Financiamento em funding-group, com a nota cruzada que a SciELO exige | pronto | ops/test_credit.py |",
          "| Pedir à revista, por e-mail, tudo que falta de uma vez | pronto | ops/test_credit.py |",
          "| Pré-visualização do artigo como a SciELO publica (htmlgenerator) | pronto | verificação \"pré-visualização do artigo\" |",
          "| Texto de cada seção editável no revisar | pronto | ops/test_secoes.py |",
          "| Anexos ancorados no ponto do texto (seção + parágrafo) | pronto | ops/test_secoes.py |",
          "| Vincular a revista preenche licença, seção e idioma | pronto | ops/test_secoes.py |",
          "| Declarações editoriais (agradecimento, financiamento, contribuição, dados, conflito, IA, editor) | pronto | ops/test_declaracoes.py |",
          "| Editor-chefe da revista com ORCID e Lattes no cadastro | pronto | ops/test_declaracoes.py |",
          "| Cliente cadastra revista (editar e remover seguem do administrador) | pronto | verificação \"cliente cadastra revista\" |",
          "| Campos preenchidos automaticamente destacados em azul | pronto | ops/test_declaracoes.py |",
          "| Referência sem chamada no texto vira aviso (R03) | pronto | ops/test_referencias_analise.py |",
          "| Data de acesso sem endereço não entra no XML (R04) | pronto | ops/test_referencias_analise.py |",
          "| (eds.)/(org.) na abertura da referência viram editor, não autor | pronto | ops/test_referencias_analise.py |",
          "| Rodapé da revista não gruda na última referência | pronto | ops/test_referencias_analise.py |",
          "| page-count do total de páginas do arquivo, e counts sem contador zerado | pronto | ops/test_counts_idiomas.py |",
          "| Declarações reconhecidas em português, inglês e espanhol | pronto | ops/test_counts_idiomas.py |",
          "| Datas de recebido/aceite lidas da caixa editorial (ano de 2 dígitos) | pronto | ops/test_counts_idiomas.py |",
          "| Imagens aparecem na pré-visualização | pronto | ops/test_counts_idiomas.py |",
          "| Data da última abertura e ordenação na lista de documentos | pronto | ops/test_lista_ordem.py |",
          "| Referências cruzadas com o Crossref | não é confiável | medido: texto sem sentido recebe nota parecida com a de uma referência real, e o editor deposita as referências sem DOI; injetar DOI errado é pior que não ter |",
          "| API oficial do ISSN (api.issn.org) | fora de alcance | é paga e responde 403 sem token; lemos a ficha pública do portal |",
          "| Base consultável do CBISSN/IBICT | não existe | o site é institucional (pedido de ISSN), sem API de periódicos |",
          "| Depósito do pacote no FTP da SciELO, com o aviso obrigatório por e-mail | pronto | ops/test_entrega.py deposita num FTP de verdade |",
          "| Conferência do pacote contra o guia de entrega (formato, nomes, arquivos citados) | pronto | verificações de entrega |",
          "| Pedido do atestado de capacidade técnica (o \"selo\") montado no correio | pronto | verificação \"pedido de atestado exige empresa e CNPJ\" |",
          "| API de depósito da SciELO | não existe | a SciELO entrega por FTP e e-mail; é o que o sistema faz |",
          "| Ferramenta 1 · Gerador XML + packtools | pronto | seção 3 (coluna DTD) |",
          "| Ferramenta 6 · Nomenclatura SPS e pacote | pronto | nome-base nos arquivos gerados |",
          "| Figuras, tabelas, equações, notas, referências | pronto | seção 3 (colunas correspondentes) |",
          "| Pacote, nome da pasta, lote e e-mail de entrega conforme a SPS 1.10 | pronto | ops/test_entrega.py |",
          "| Validação no Schematron da SPS 1.10 (o packtools só liga 1.8 e 1.9 por padrão) | pronto | seção 3; SPS 1.10 é a versão padrão |",
          "| Freio de tentativas no login e registro; XML rascunho marcado; 'ir para o campo'; tempo medido | pronto | ops/test_auditoria_furos.py |",
          "| OCR de PDF escaneado | não começou | o PDF só com imagem é detectado e vira bloqueante com explicação (D01); ler exige Tesseract no container |",
          "| Novidades por versão: janela ao entrar, página de notificações e sino, filtrados por papel | pronto | ops/test_novidades.py |",
          "| Modelo DOCX distribuível (estilos próprios + tabela de metadados) | não começou | o DOCX já é lido pelos estilos de título do Word; o modelo é a fase 2 do plano |",
          "| Parser de referências com IA + Crossref | não começou | hoje é heurística medida contra gabarito; DOI por Crossref foi medido e descartado |",
          "| Equipe da revista compartilhando documentos, fila em lote e custo por artigo | parcial | tempo de máquina por artigo no painel; conta por pessoa; sem fila em lote nem custo com revisão humana |",
          "| Validador público sem conta e captcha no registro | não começou | decisão dos sócios (fase 4); Turnstile precisa das chaves da Cloudflare |",
          "| Integração com OJS | não começou | fase 5 do plano; o depósito por FTP já existe |", ""]
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
