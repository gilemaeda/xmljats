"""MathML nas equacoes, quadro (boxed-text), dialogo (speech) e tabela editada a mao: DTD + Schematron SPS."""
import json
import os
import sys
import tempfile

sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML")
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML\poc")
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML\app")
os.chdir(r"C:\Users\gilej\PROJETOS\XML")

from extrator import xml_jats  # noqa: E402
from gerar_xml import valida_packtools  # noqa: E402
import main as M  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


REVISTA = {"acronimo": "rdp", "titulo": "Revista Direito e Práxis", "abrev": "Rev. Direito Práx.",
           "issn_epub": "2179-8966", "editora": "Universidade do Estado do Rio de Janeiro",
           "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "continua"}

MODELO = {
    "idioma": "pt", "tipo_artigo": "research-article", "heading": "Artigos", "doi": "10.1590/2179-8966/2026/99999",
    "volume": "17", "numero": "1", "ano": "2026", "elocation": "e99999", "order": "99999",
    "licenca": "CC BY 4.0", "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
    "datas": {"recebido": "2025-03-01", "aceito": "2025-06-01", "publicado": "2026-02-10"},
    "titulos": [{"texto": "Prova de fogo dos elementos novos", "idioma": "pt", "tipo": "article-title"}],
    "autores": [{"nome_completo": "Ana Silva", "sobrenome": "Silva", "nomes": "Ana", "orcid": "0000-0002-1825-0097",
                 "orcid_valido": True, "email": "ana@exemplo.org", "aff_ids": ["aff1"], "correspondente": True, "papel": "author"}],
    "afiliacoes": [{"id": "aff1", "texto_original": "UERJ", "instituicao": "Universidade do Estado do Rio de Janeiro",
                    "cidade": "Rio de Janeiro", "estado": "RJ", "pais": "Brasil", "pais_iso": "BR", "confianca": "alta"}],
    "resumos": [{"idioma": "pt", "rotulo": "Resumo", "texto": "Texto do resumo para a prova.",
                 "palavras_chave": ["direito", "xml"]}],
    "secoes": [{"titulo": "Introdução", "titulo_completo": "1 Introdução", "nivel": 1, "pagina": 1,
                "paragrafos": ["Primeiro parágrafo do corpo, com a Tabela 1 e a equação (1) citadas."]}],
    "citacoes": [], "notas": [],
    "referencias": [{"texto": "SILVA, Ana. Livro de prova. São Paulo: Editora, 2020.", "tipo": "book",
                     "autores": ["SILVA, Ana"], "ano": "2020"}],
    "figuras": [], "estilo_referencias": "ABNT",
    "tabelas": [{"rotulo": "Tabela 1", "numero": "1", "legenda": "Distribuição das decisões",
                 "celulas": [["Ano", "Casos"], ["2024", "12"], ["2025", "31"]], "linhas_cabecalho": 1, "colunas": 2,
                 "qualidade": "alta", "secao_indice": 0, "pos_paragrafo": 1, "chamada_no_texto": True, "fonte": "Autores"}],
    "equacoes": [{"rotulo": "(1)", "numero": "1", "latex": r"E = mc^2", "secao_indice": 0, "pos_paragrafo": 1}],
    "quadros": [{"rotulo": "Quadro 1", "legenda": "Critérios adotados",
                 "texto": "Primeiro critério.\nSegundo critério.", "secao_indice": 0, "pos_paragrafo": 1}],
    "dialogos": [{"rotulo": "Diálogo 1", "legenda": "Trecho da audiência",
                  "turnos": [{"falante": "Juiz", "fala": "Pode prosseguir."},
                             {"falante": "Advogada", "fala": "Obrigada, Excelência."}],
                  "secao_indice": 0, "pos_paragrafo": 1}],
}

# o MathML é gerado pelo mesmo caminho da tela (latex -> mathml)
mml, erro = M.latex_para_mathml(MODELO["equacoes"][0]["latex"])
ok(erro is None and mml and "<math" in mml, f"LaTeX vira MathML ({erro or 'sem erro'})")
MODELO["equacoes"][0]["mathml"] = mml

res = xml_jats.gera_xml(MODELO, REVISTA, "1.9")
ok(not res.bloqueantes, "sem bloqueantes: " + "; ".join(res.bloqueantes[:3]))
ok(res.xml is not None, "XML gerado")

if res.xml:
    xml = res.xml.decode("utf-8")
    ok("<mml:math" in xml, "equação saiu como MathML, não imagem")
    ok("<graphic" not in xml.split("<back>")[0].split("<disp-formula")[-1][:400], "disp-formula sem <graphic>")
    ok("<boxed-text" in xml and "Critérios adotados" in xml, "quadro saiu como boxed-text")
    ok("<speech>" in xml and "<speaker>Juiz</speaker>" in xml, "diálogo saiu como speech/speaker")
    ok("<thead>" in xml and "<td>2025</td>" in xml, "tabela saiu como tabela de verdade (thead/tbody)")
    ok('equation-count count="1"' in xml and 'table-count count="1"' in xml, "contadores batem")

    caminho = os.path.join(tempfile.mkdtemp(prefix="xmljats-xml-"), res.nome_base + ".xml")
    with open(caminho, "wb") as f:
        f.write(res.xml)
    dtd_ok, sps_ok, erros, _ = valida_packtools(caminho)
    ok(dtd_ok is True, f"XML válido no DTD JATS 1.1 ({[e for e in erros if 'DTD' in e][:2]})")
    ok(sps_ok is True, f"XML válido no Schematron SPS 1.9 ({[e for e in erros if 'DTD' not in e][:3]})")

# ---- equação sem MathML vira bloqueante (é o que o guia da SciELO exige)
sem = json.loads(json.dumps(MODELO))
sem["equacoes"][0].pop("mathml")
sem["equacoes"][0]["arquivo"] = "eq01.png"
r2 = xml_jats.gera_xml(sem, REVISTA, "1.9")
ok(any("MathML ou LaTeX" in b for b in r2.bloqueantes), "equação como imagem é bloqueante")

# ---- LaTeX quebrado avisa em vez de gerar XML inválido
mml2, erro2 = M.latex_para_mathml(r"\frac{a}{")
ok(mml2 is None and erro2, f"LaTeX quebrado devolve erro: {erro2}")

# ---- tabela e figura sem legenda são bloqueantes
sem2 = json.loads(json.dumps(MODELO))
sem2["equacoes"][0]["mathml"] = mml
sem2["tabelas"][0]["legenda"] = ""
r3 = xml_jats.gera_xml(sem2, REVISTA, "1.9")
ok(any("sem legenda" in b for b in r3.bloqueantes), "tabela sem legenda é bloqueante")

# ---- conversões de texto do formulário
ok(M.texto_para_grade("a | b\nc | d") == [["a", "b"], ["c", "d"]], "texto vira grade")
ok(M.texto_para_grade("a\tb\nc\td") == [["a", "b"], ["c", "d"]], "grade colada do Excel (tabulação)")
ok(M.texto_para_grade("a|b|c\nd|e") == [["a", "b", "c"], ["d", "e", ""]], "linha curta é completada")
ok(M.grade_para_texto([["a", "b"]]) == "a | b", "grade vira texto")
t = M.texto_para_turnos("Juiz: fale\nAdvogada: obrigada\ncontinuando a fala")
ok(len(t) == 2 and t[1]["fala"] == "obrigada continuando a fala", "turnos do diálogo, com continuação")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
