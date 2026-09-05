"""
Leitura de DOCX: o arquivo do Word como fonte, no lugar do PDF.

Por que vale a pena: o DOCX diz o que o PDF obriga a adivinhar. O título é o parágrafo com estilo
`Title`, as seções são os `Heading1/2/3`, a tabela é uma tabela de verdade (`w:tbl`) com as células
separadas, a nota de rodapé está em `footnotes.xml` ligada à chamada, e a equação vem em OMML, o
formato de fórmula do Word, que converte para MathML sem perda. No PDF tudo isso é heurística sobre
posição e tamanho de letra.

O que este módulo faz: monta um `Documento` igual ao que `leitura.ler_pdf` devolve, para reaproveitar
todo o resto do extrator (identificadores, autores, afiliações, resumos, datas, licença, referências),
e por cima entrega o que só o DOCX sabe: seções pelos estilos, tabelas com células, equações em MathML,
notas de rodapé e imagens.

Limite honesto: um DOCX gerado por conversão de PDF herda os defeitos da conversão (por exemplo, o
título com espaços perdidos). O sistema não conserta isso sozinho; o campo aparece na revisão para ser
corrigido, como qualquer outro.
"""
import os
import re
import zipfile
from typing import List, Optional

from lxml import etree

from .leitura import Documento, Linha, _paragrafos
from .util import RE_MARCADOR

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
MATHML = "http://www.w3.org/1998/Math/MathML"

# estilo do Word -> tamanho em pontos que o resto do extrator usa para decidir o que é título
TAMANHO_POR_ESTILO = {"title": 17.0, "subtitle": 13.0, "heading1": 13.5, "heading2": 12.5, "heading3": 11.5,
                      "heading4": 11.0, "heading5": 11.0, "heading6": 11.0, "quote": 9.5, "footnotetext": 8.5}
CORPO_PT = 10.5
NIVEL_HEADING = re.compile(r"^heading(\d)$", re.I)
LARGURA = 595.0
ALTURA = 842.0
MARGEM = 70.0
ALTURA_LINHA = 13.0


def _texto_do(no) -> str:
    """Texto de um parágrafo ou run, com quebras e tabulações como espaço."""
    partes = []
    for el in no.iter():
        if el.tag == W + "t":
            partes.append(el.text or "")
        elif el.tag in (W + "tab",):
            partes.append(" ")
        elif el.tag in (W + "br", W + "cr"):
            partes.append(" ")
    return _sem_repeticao(re.sub(r"[  ]+", " ", "".join(partes)).strip())


def _sem_repeticao(t: str) -> str:
    """Conversor de PDF para DOCX as vezes gruda o mesmo trecho duas vezes no paragrafo
    ("ANAMORPHOSISANAMORPHOSIS"). Quando o texto e exatamente uma repeticao, fica so uma copia."""
    if len(t) < 40:
        return t
    for n in (2, 3, 4):
        if len(t) % n == 0:
            pedaco = t[: len(t) // n]
            if len(pedaco) >= 20 and pedaco * n == t:
                return pedaco
    return t


def _estilo(p) -> str:
    el = p.find(f"{W}pPr/{W}pStyle")
    return (el.get(W + "val") or "").strip() if el is not None else ""


def _formatacao(p):
    """(negrito, itálico) do parágrafo: vale quando a maioria dos runs com texto está assim."""
    runs = [r for r in p.iter(W + "r") if (r.findtext(f".//{W}t") or "").strip()]
    if not runs:
        return False, False
    def marcado(r, tag):
        el = r.find(f"{W}rPr/{W}{tag}")
        return el is not None and (el.get(W + "val") or "1") not in ("0", "false")
    n = len(runs)
    return sum(marcado(r, "b") for r in runs) * 2 >= n, sum(marcado(r, "i") for r in runs) * 2 >= n


# ---------------------------------------------------------------- OMML (fórmula do Word) -> MathML

def _mml(tag, texto=None, **attrs):
    el = etree.Element(f"{{{MATHML}}}{tag}", nsmap={None: MATHML})
    for k, v in attrs.items():
        el.set(k, v)
    if texto is not None:
        el.text = texto
    return el


def _omml_runs(no, destino):
    """Converte os filhos de um nó OMML para dentro de `destino` (um <mrow>)."""
    for filho in no:
        tag = filho.tag.replace(M, "")
        if tag == "r":
            txt = "".join(t.text or "" for t in filho.iter(M + "t"))
            for pedaco in re.findall(r"\d+\.?\d*|[A-Za-zΑ-Ωα-ω]+|\S", txt):
                if re.fullmatch(r"\d+\.?\d*", pedaco):
                    destino.append(_mml("mn", pedaco))
                elif re.fullmatch(r"[A-Za-zΑ-Ωα-ω]+", pedaco):
                    destino.append(_mml("mi", pedaco))
                else:
                    destino.append(_mml("mo", pedaco))
        elif tag == "f":  # fração
            frac = _mml("mfrac")
            for parte, alvo in (("num", None), ("den", None)):
                sub = filho.find(f"{M}{parte}")
                linha = _mml("mrow")
                if sub is not None:
                    _omml_runs(sub, linha)
                frac.append(linha)
            destino.append(frac)
        elif tag in ("sSup", "sSub", "sSubSup"):
            base = _mml("mrow")
            b = filho.find(f"{M}e")
            if b is not None:
                _omml_runs(b, base)
            if tag == "sSubSup":
                el = _mml("msubsup")
                el.append(base)
                for parte in ("sub", "sup"):
                    linha = _mml("mrow")
                    sub = filho.find(f"{M}{parte}")
                    if sub is not None:
                        _omml_runs(sub, linha)
                    el.append(linha)
            else:
                el = _mml("msup" if tag == "sSup" else "msub")
                el.append(base)
                linha = _mml("mrow")
                sub = filho.find(f"{M}{'sup' if tag == 'sSup' else 'sub'}")
                if sub is not None:
                    _omml_runs(sub, linha)
                el.append(linha)
            destino.append(el)
        elif tag == "rad":  # raiz
            grau = filho.find(f"{M}deg")
            corpo = _mml("mrow")
            e = filho.find(f"{M}e")
            if e is not None:
                _omml_runs(e, corpo)
            if grau is not None and len(grau):
                el = _mml("mroot")
                el.append(corpo)
                linha = _mml("mrow")
                _omml_runs(grau, linha)
                el.append(linha)
            else:
                el = _mml("msqrt")
                el.append(corpo)
            destino.append(el)
        elif tag == "d":  # delimitadores: ( )
            pr = filho.find(f"{M}dPr")
            abre = (pr.find(f"{M}begChr").get(M + "val") if pr is not None and pr.find(f"{M}begChr") is not None else "(")
            fecha = (pr.find(f"{M}endChr").get(M + "val") if pr is not None and pr.find(f"{M}endChr") is not None else ")")
            destino.append(_mml("mo", abre))
            for e in filho.findall(f"{M}e"):
                _omml_runs(e, destino)
            destino.append(_mml("mo", fecha))
        elif tag == "nary":  # somatório, integral
            pr = filho.find(f"{M}naryPr")
            simbolo = pr.find(f"{M}chr").get(M + "val") if (pr is not None and pr.find(f"{M}chr") is not None) else "∫"
            el = _mml("munderover")
            el.append(_mml("mo", simbolo))
            for parte in ("sub", "sup"):
                linha = _mml("mrow")
                sub = filho.find(f"{M}{parte}")
                if sub is not None:
                    _omml_runs(sub, linha)
                el.append(linha)
            destino.append(el)
            e = filho.find(f"{M}e")
            if e is not None:
                _omml_runs(e, destino)
        elif tag in ("e", "num", "den", "sub", "sup", "deg", "oMath"):
            _omml_runs(filho, destino)


def omml_para_mathml(no_omath) -> Optional[str]:
    """<m:oMath> do Word -> string MathML. Devolve None quando não sobra conteúdo."""
    raiz = _mml("math", display="block")
    linha = _mml("mrow")
    _omml_runs(no_omath, linha)
    if not len(linha):
        return None
    raiz.append(linha)
    return etree.tostring(raiz, encoding="unicode")


def _texto_omml(no) -> str:
    return "".join(t.text or "" for t in no.iter(M + "t")).strip()


# ---------------------------------------------------------------- tabelas e imagens

def _tabela(tbl) -> dict:
    """Tabela do Word em grade de células, com as linhas de cabeçalho que o próprio arquivo marca."""
    celulas, n_cab = [], 0
    for k, tr in enumerate(tbl.findall(f"{W}tr")):
        cabecalho = tr.find(f"{W}trPr/{W}tblHeader") is not None
        linha = []
        for tc in tr.findall(f"{W}tc"):
            span = tc.find(f"{W}tcPr/{W}gridSpan")
            texto = " ".join(x for x in (_texto_do(p) for p in tc.findall(f"{W}p")) if x)
            linha.append(texto)
            for _ in range(int(span.get(W + "val")) - 1 if span is not None and span.get(W + "val") else 0):
                linha.append("")
        if any(c for c in linha):
            celulas.append(linha)
            if cabecalho and n_cab == k:
                n_cab += 1
    if celulas and not n_cab:
        # sem marca de cabeçalho no arquivo: a primeira linha vale como cabeçalho se nenhuma célula dela é número
        primeira = celulas[0]
        if primeira and not any(re.fullmatch(r"[\d.,%\s-]+", c or "") for c in primeira if c):
            n_cab = 1
    largura = max((len(l) for l in celulas), default=0)
    return {"celulas": [l + [""] * (largura - len(l)) for l in celulas], "linhas_cabecalho": n_cab,
            "colunas": largura, "qualidade": "alta", "origem": "docx"}


def _relacoes(z: zipfile.ZipFile) -> dict:
    try:
        rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
    except KeyError:
        return {}
    ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    return {r.get("Id"): r.get("Target") for r in rels.findall(f"{ns}Relationship")}


# ---------------------------------------------------------------- leitura principal

def le_docx(caminho: str) -> Documento:
    """DOCX -> Documento no mesmo formato que o leitor de PDF entrega, mais o que só o DOCX sabe."""
    with zipfile.ZipFile(caminho) as z:
        raiz = etree.fromstring(z.read("word/document.xml"))
        rels = _relacoes(z)
        midia = {n: z.read(n) for n in z.namelist() if n.startswith("word/media/")}
        try:
            notas_xml = etree.fromstring(z.read("word/footnotes.xml"))
        except KeyError:
            notas_xml = None
        try:
            props = z.read("docProps/core.xml").decode("utf-8", "replace")
        except KeyError:
            props = ""

    corpo_el = raiz.find(f"{W}body")
    linhas: List[Linha] = []
    secoes_docx: List[dict] = []      # {titulo, nivel, indice_linha}
    tabelas: List[dict] = []
    equacoes: List[dict] = []
    imagens: List[dict] = []
    y = MARGEM
    pagina = 1
    indice_par = 0

    def nova_linha(texto, size, bold, italic, zona="corpo"):
        nonlocal y, pagina
        if y > ALTURA - MARGEM:
            y = MARGEM
            pagina += 1
        ln = Linha(pagina=pagina, texto=texto, size=size, bold=bold, italic=italic, font="docx",
                   x0=MARGEM, y0=y, x1=LARGURA - MARGEM, y1=y + ALTURA_LINHA, bloco=len(linhas),
                   zona=zona, texto_marcado=texto)
        y += ALTURA_LINHA + (6 if size > CORPO_PT else 3)
        linhas.append(ln)
        return ln

    for el in corpo_el:
        tag = el.tag.replace(W, "")
        if tag == "tbl":
            t = _tabela(el)
            if t["celulas"]:
                t["pagina"] = pagina
                t["indice_linha"] = len(linhas)
                t["bbox"] = [MARGEM, y, LARGURA - MARGEM, y + ALTURA_LINHA]
                tabelas.append(t)
            continue
        if tag != "p":
            continue
        estilo = _estilo(el)
        chave = estilo.lower().replace(" ", "")
        size = TAMANHO_POR_ESTILO.get(chave, CORPO_PT)
        bold, italic = _formatacao(el)

        # fórmulas do parágrafo: cada <m:oMath> vira uma equação com MathML
        for om in el.iter(M + "oMath"):
            mml = omml_para_mathml(om)
            if mml:
                equacoes.append({"pagina": pagina, "mathml": mml, "texto": _texto_omml(om),
                                 "indice_linha": len(linhas), "origem": "docx (OMML)",
                                 "bbox": [MARGEM, y, LARGURA - MARGEM, y + ALTURA_LINHA],
                                 "rotulo": None, "numerada": False, "png": None})

        # imagens do parágrafo
        for blip in el.iter(A + "blip"):
            rid = blip.get(R + "embed")
            alvo = rels.get(rid)
            if not alvo:
                continue
            nome = "word/" + alvo.replace("../", "") if not alvo.startswith("word/") else alvo
            dados = midia.get(nome) or midia.get("word/media/" + os.path.basename(alvo))
            if dados:
                imagens.append({"pagina": pagina, "ext": os.path.splitext(alvo)[1].lstrip(".").lower() or "png",
                                "dados": dados, "indice_linha": len(linhas), "bbox": [0, 0, 0, 0],
                                "largura": None, "altura": None})

        texto = _texto_do(el)
        if not texto:
            continue
        nivel = NIVEL_HEADING.match(chave)
        if nivel:
            secoes_docx.append({"titulo": texto, "nivel": int(nivel.group(1)), "indice_linha": len(linhas)})
        elif chave == "title":
            secoes_docx.append({"titulo": texto, "nivel": 0, "indice_linha": len(linhas)})
        nova_linha(texto, size, bold or bool(nivel), italic)
        indice_par += 1

    # notas de rodapé: entram como linhas de zona "nota", que é onde o extrator as procura
    if notas_xml is not None:
        for nota in notas_xml.findall(f"{W}footnote"):
            tipo = nota.get(W + "type")
            if tipo in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            texto = " ".join(x for x in (_texto_do(p) for p in nota.findall(f"{W}p")) if x)
            if texto:
                nova_linha(f"{nota.get(W + 'id')} {texto}", 8.5, False, False, zona="nota")

    # cabeçalho e rodapé repetidos: o Word às vezes deixa o nome da revista dentro do corpo, repetido em
    # toda página. Sem isso, o título do artigo vira o nome da revista.
    from collections import Counter
    repetidos = Counter(l.texto for l in linhas if l.zona == "corpo" and 3 < len(l.texto) < 130)
    correntes = {t for t, n in repetidos.items() if n >= 3}
    for l in linhas:
        if l.texto in correntes:
            l.zona = "cabecalho"

    paragrafos = _paragrafos([l for l in linhas if l.zona == "corpo"], "corpo", MARGEM)
    notas = _paragrafos([l for l in linhas if l.zona == "nota"], "nota", MARGEM)
    metadados = {}
    for campo, rot in (("creator", "author"), ("title", "title")):
        m = re.search(rf"<dc:{campo}>(.*?)</dc:{campo}>", props, re.S)
        if m:
            metadados[rot] = re.sub(r"\s+", " ", m.group(1)).strip()
    metadados["creator"] = metadados.get("author") or "Word (DOCX)"

    doc = Documento(
        caminho=caminho, paginas=pagina, metadata=metadados, largura=LARGURA, altura=ALTURA,
        corpo_size=CORPO_PT, corpo_font="docx", layout="1col", linhas=linhas, cabecalhos=sorted(correntes),
        paragrafos=paragrafos, notas=notas, laterais=[], margens=[],
        imagens_por_pagina=[0] * (pagina + 1), coluna_esquerda={p: MARGEM for p in range(1, pagina + 1)},
        imagens=imagens, tabelas=tabelas, equacoes=equacoes,
    )
    doc.secoes_docx = secoes_docx  # estrutura que só o DOCX tem: usada para montar o corpo sem adivinhar
    return doc
