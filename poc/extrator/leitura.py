"""Leitura do PDF com PyMuPDF: linhas com atributos, zonas (cabecalho, rodape, nota, lateral, margem),
ordem de leitura e agrupamento em paragrafos com juncao de linhas (de-hifenizacao consciente de URL/ORCID)."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pymupdf

from .tabelas import detecta_equacoes, detecta_tabelas, recorta
from .util import RE_MARCADOR, marcador_normalizado

RE_ROTULO_CAIXA = re.compile(
    r"^(contrib|aff|abstract|sec|ref|article-title|trans-title|kwd|kwd-group|fn|title|body|back|front|p\[\d+\]|Legenda tags JATS.*)$",
    re.I,
)
RE_NUM_PAGINA = re.compile(r"^(\d{1,4}|\d{1,4}\s*[|•·]\s*.{0,70}|.{0,70}\s*[|•·]\s*\d{1,4})$")
RE_ROTULO_SO = re.compile(r"^(\d{1,3}|\*{1,4}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|†|‡|§)$")
PREFIXOS_HIFEN = {
    "pos", "pós", "pre", "pré", "anti", "auto", "contra", "semi", "sub", "super", "ex", "vice", "socio", "sócio", "recem", "recém",
    "bem", "mal", "pan", "pro", "pró", "neo", "micro", "macro", "multi", "inter", "intra", "extra", "ultra", "infra", "co", "self",
    "non", "post", "re", "meta", "trans",
}
TERMINAL = ('.', '!', '?', ':', ';', '”', '"', ')', '…', ']')


@dataclass
class Linha:
    pagina: int
    texto: str
    size: float
    bold: bool
    italic: bool
    font: str
    x0: float
    y0: float
    x1: float
    y1: float
    bloco: int
    sup_inicio: str = ""
    sup_fim: str = ""
    sups: List[str] = field(default_factory=list)
    rotacionada: bool = False
    zona: str = "corpo"
    texto_marcado: str = ""  # texto com as chamadas de nota no lugar: "palavra[^3]" (sobrescrito numerico ou simbolo)

    @property
    def largura(self):
        return self.x1 - self.x0

    def copia(self):
        return Linha(**{k: (list(v) if isinstance(v, list) else v) for k, v in self.__dict__.items()})


@dataclass
class Paragrafo:
    pagina: int
    zona: str
    linhas: List[Linha]
    texto: str
    size: float
    bold: bool
    italic: bool
    font: str
    x0: float
    y0: float
    x1: float
    y1: float
    texto_marcado: str = ""

    @property
    def sups(self):
        out = []
        for ln in self.linhas:
            out.extend(ln.sups)
        return out

    @property
    def primeira(self):
        return self.linhas[0]


@dataclass
class Documento:
    caminho: str
    paginas: int
    metadata: dict
    largura: float
    altura: float
    corpo_size: float
    corpo_font: str
    layout: str
    linhas: List[Linha]
    cabecalhos: List[str]
    paragrafos: List[Paragrafo]
    notas: List[Paragrafo]
    laterais: List[Paragrafo]
    margens: List[Paragrafo]
    imagens_por_pagina: List[int]
    coluna_esquerda: Dict[int, float]
    imagens: List[dict] = field(default_factory=list)  # {pagina, bbox, ext, dados, largura, altura}
    tabelas: List[dict] = field(default_factory=list)  # {pagina, bbox, celulas, linhas_cabecalho, colunas}
    equacoes: List[dict] = field(default_factory=list)  # {pagina, bbox, rotulo, texto, numerada, png, largura, altura}
    ocr_paginas: List[int] = field(default_factory=list)  # páginas sem camada de texto lidas por OCR

    def linhas_zona(self, zona):
        return [ln for ln in self.linhas if ln.zona == zona]


# ---------------------------------------------------------------- juncao de linhas

def juntar_linhas(textos: List[str]) -> str:
    out = ""
    for t in textos:
        t = (t or "").strip()
        if not t:
            continue
        if not out:
            out = t
            continue
        if out.endswith("-"):
            ctx = out[-220:]
            em_identificador = re.search(r"(orcid\.org/|doi\.org/|https?://|lattes\.cnpq\.br/|www\.|10\.\d{4,9}/)\S*$", ctx) or re.search(r"\d-$", out)
            if em_identificador:
                out = out + t
            elif t[:1].islower():
                prefixo = re.split(r"[\s(]", out[:-1])[-1].lower()
                out = (out + t) if prefixo in PREFIXOS_HIFEN else (out[:-1] + t)
            else:
                out = out + t
        elif RE_URL_FIM.search(out) and RE_URL_CONT.match(t):
            out = out + t  # URL quebrada em duas linhas sem hifen: "https://www.planalto.gov.br/ccivil_03/" + "leis/lcp80.htm"
        else:
            out = out + " " + t
    return out


RE_URL_FIM = re.compile(r"https?://[^\s]*[/._\-=?&]$")
RE_URL_CONT = re.compile(r"^[a-z0-9][\w\-./%?=&#~]*(?:[\s.,;]|$)")


# ---------------------------------------------------------------- leitura das linhas

# chamada sobrescrita: "3", "1,2", "4-6" (citacao numerica agrupada), asterisco, adaga
RE_CHAMADA_SUP = re.compile(r"^(\d{1,3}(?:\s*[,;–—-]\s*\d{1,3})*|\*{1,4}|†|‡|[¹²³⁰-⁹]{1,3})$")


def _bold(s):
    f = s["font"].lower()
    return bool(s["flags"] & 16) or "bold" in f or "black" in f or "semibold" in f or "heavy" in f


def _ital(s):
    f = s["font"].lower()
    return bool(s["flags"] & 2) or "italic" in f or "oblique" in f


def _linhas_pagina(page, pno, textpage=None):
    # textpage vem do OCR quando a página não tem camada de texto (ver extrator/ocr.py)
    d = page.get_text("dict", textpage=textpage) if textpage is not None else page.get_text("dict")
    out = []
    for bi, b in enumerate(d["blocks"]):
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            spans_todos = ln["spans"]
            spans = [s for s in spans_todos if s["text"].strip()]
            if not spans:
                continue
            sups, partes, sup_objs = [], [], []
            for k, s in enumerate(spans):
                t = s["text"].strip()
                if (s["flags"] & 1) and len(t) <= 4:
                    sups.append((t, "inicio" if k == 0 else ("fim" if k == len(spans) - 1 else "meio")))
                    sup_objs.append(s)
                    continue
                partes.append(s)
            if not partes:  # linha feita so de sobrescrito: rotulo isolado
                partes, sups, sup_objs = spans, [], []
            # o texto usa TODOS os spans (inclusive os que so tem espaco), menos os sobrescritos
            texto = "".join(s["text"] for s in spans_todos if not any(s is o for o in sup_objs))
            texto = re.sub(r"\s+", " ", texto).strip()
            if not texto:
                continue
            # texto_marcado: sobrescritos que parecem chamada de nota (numero ou simbolo, nao no inicio) viram "[^n]"
            partes_m = []
            for s in spans_todos:
                if any(s is o for o in sup_objs):
                    t = s["text"].strip()
                    if RE_CHAMADA_SUP.match(t) and not (sups and sups[0][0] == t and sups[0][1] == "inicio"):
                        partes_m.append("[^" + marcador_normalizado(t) + "]")
                    continue
                partes_m.append(s["text"])
            texto_marcado = re.sub(r"\s+", " ", "".join(partes_m)).strip()
            texto_marcado = re.sub(r"\s+(\[\^[^\]]+\])", r"\1", texto_marcado)  # "palavra [^3]" -> "palavra[^3]"
            sizes, fonts = Counter(), Counter()
            bold = ital = total = 0
            for s in partes:
                n = len(s["text"].strip())
                sizes[round(s["size"], 1)] += n
                fonts[s["font"]] += n
                total += n
                if _bold(s):
                    bold += n
                if _ital(s):
                    ital += n
            x0, y0, x1, y1 = ln["bbox"]
            dx, dy = ln.get("dir", (1.0, 0.0))
            out.append(
                Linha(
                    pagina=pno, texto=texto, size=sizes.most_common(1)[0][0],
                    bold=bold / max(total, 1) > 0.6, italic=ital / max(total, 1) > 0.6,
                    font=fonts.most_common(1)[0][0], x0=x0, y0=y0, x1=x1, y1=y1, bloco=bi,
                    sup_inicio=next((t for t, p in sups if p == "inicio"), ""),
                    sup_fim=next((t for t, p in sups if p == "fim"), ""),
                    sups=[t for t, _ in sups],
                    rotacionada=abs(dx - 1.0) > 0.01 or abs(dy) > 0.01,
                    texto_marcado=texto_marcado,
                )
            )
    return out


def _chave(t):
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", t.lower())).strip()


def _classifica(paginas: Dict[int, List[Linha]], W, H, corpo):
    n = len(paginas)
    contagem = defaultdict(set)
    exemplo = {}
    for pno, lines in paginas.items():
        for ln in lines:
            k = _chave(ln.texto)
            if len(k) >= 4:
                contagem[k].add(pno)
                exemplo.setdefault(k, ln.texto)
    minimo = max(2, round(0.4 * n))
    repetidas = {k for k, ps in contagem.items() if len(ps) >= minimo}
    cabecalhos = []
    for pno, lines in paginas.items():
        for ln in lines:
            if ln.rotacionada:
                ln.zona = "margem"
                continue
            if ln.size <= 7.6 and RE_ROTULO_CAIXA.match(ln.texto):
                ln.zona = "rotulo"
                continue
            k = _chave(ln.texto)
            borda = ln.y0 < 0.15 * H or ln.y1 > 0.85 * H or ln.size < corpo * 0.85
            if k in repetidas and borda:
                ln.zona = "cabecalho" if ln.y0 < H / 2 else "rodape"
                if exemplo[k] not in cabecalhos:
                    cabecalhos.append(exemplo[k])
                continue
            if RE_NUM_PAGINA.match(ln.texto) and (ln.y0 < 0.12 * H or ln.y1 > 0.88 * H) and not _tem_texto_ao_lado(ln, lines, corpo):
                ln.zona = "rodape"
                continue
    # coluna lateral (quadro com metadados editoriais): linhas pequenas, estreitas, alinhadas entre si
    # numa margem diferente da margem principal da pagina, com texto do corpo a direita
    for pno, lines in paginas.items():
        livres = [ln for ln in lines if ln.zona == "corpo"]
        grandes = [round(l.x0) for l in livres if l.size >= corpo * 0.9]
        x_main = Counter(grandes).most_common(1)[0][0] if grandes else (min((l.x0 for l in livres), default=0))
        cands = []
        for ln in livres:
            if ln.size <= corpo * 0.85 and ln.largura < 0.32 * W and ln.x1 < 0.45 * W and abs(ln.x0 - x_main) > 3:
                # precisa haver texto a direita numa faixa vertical proxima (duas linhas para cima ou para baixo)
                faixa0, faixa1 = ln.y0 - 2 * ln.size, ln.y1 + 2 * ln.size
                for outra in livres:
                    if outra is ln or outra.x0 < ln.x1 + 5:
                        continue
                    if min(faixa1, outra.y1) - max(faixa0, outra.y0) > 0:
                        cands.append(ln)
                        break
        # agrupa candidatas por margem esquerda (tolerancia de 3 pt) e aceita grupos com 5+ linhas
        grupo, grupos = [], []
        for ln in sorted(cands, key=lambda l: l.x0):
            if grupo and ln.x0 - grupo[-1].x0 > 3:
                grupos.append(grupo)
                grupo = []
            grupo.append(ln)
        if grupo:
            grupos.append(grupo)
        for g in grupos:
            if len(g) >= 5:
                for ln in g:
                    ln.zona = "lateral"
    # notas de rodape: comecam num marcador em fonte pequena e, a partir dali, so ha linhas pequenas ate o fim da pagina.
    # Tamanho tipico das notas do documento (inicios confiaveis: sobrescrito ou fonte <= 80% do corpo); um inicio
    # candidato maior que isso (ex.: citacao em bloco a 85% do corpo comecando por "1.") so vale se tiver esse tamanho.
    tam_notas = Counter()
    for pno, lines in paginas.items():
        for ln in lines:
            if ln.zona == "corpo" and _eh_inicio_nota(ln, corpo) and (ln.sup_inicio or ln.size <= corpo * 0.8):
                tam_notas[round(ln.size, 1)] += 1
    nota_size = tam_notas.most_common(1)[0][0] if tam_notas else None
    for pno, lines in paginas.items():
        livres = sorted([ln for ln in lines if ln.zona == "corpo"], key=lambda l: (l.y0, l.x0))
        em_nota = False
        for i, ln in enumerate(livres):
            if em_nota:
                if ln.texto.startswith("©"):
                    em_nota = False
                elif ln.size <= corpo * 0.93 + 0.05:
                    ln.zona = "nota"
                    continue
                else:
                    em_nota = False
            if nota_size is not None and ln.size > corpo * 0.8 and abs(ln.size - nota_size) > 0.6 and not ln.sup_inicio:
                continue  # fonte de citacao em bloco, nao de nota
            if ln.size > corpo * 0.8 and not ln.sup_inicio and _recuada_sem_vizinho(ln, livres, corpo):
                continue  # citacao em bloco recuada ("1. ...") com o mesmo tamanho das notas: nota comeca na margem
            if _eh_inicio_nota(ln, corpo) and (ln.y0 > 0.5 * H or ln.size <= corpo * 0.75):
                resto = livres[i + 1:]
                if all(l.size <= corpo * 0.93 + 0.05 or l.texto.startswith("©") for l in resto):
                    ln.zona = "nota"
                    em_nota = True
    return cabecalhos


def _recuada_sem_vizinho(ln: Linha, livres: List[Linha], corpo) -> bool:
    """Linha recuada (> 2 corpos a direita da margem principal da pagina) sem nenhuma linha a sua esquerda na mesma
    altura: e um bloco recuado (citacao longa), nao uma nota de rodape nem a coluna direita de um layout em colunas."""
    grandes = [round(l.x0) for l in livres if l.size >= corpo * 0.9]
    if not grandes:
        return False
    x_main = Counter(grandes).most_common(1)[0][0]
    if ln.x0 <= x_main + 2 * corpo:
        return False
    for outra in livres:
        if outra is not ln and outra.x1 <= ln.x0 and min(ln.y1, outra.y1) - max(ln.y0, outra.y0) > 0:
            return False
    return True


def _tem_texto_ao_lado(ln: Linha, lines: List[Linha], corpo) -> bool:
    """Numero pequeno com texto pequeno logo a direita, na mesma altura: e rotulo de nota de rodape, nao numero de pagina."""
    if ln.size > corpo * 0.7:
        return False
    for outra in lines:
        if outra is ln or outra.x0 < ln.x1 - 1 or outra.x0 > ln.x1 + 3 * corpo:
            continue
        if outra.size <= corpo * 0.93 + 0.05 and min(ln.y1, outra.y1) - max(ln.y0, outra.y0) > 0:
            return True
    return False


def _eh_inicio_nota(ln: Linha, corpo):
    if ln.size > corpo * 0.9 + 0.05:
        return False
    if ln.sup_inicio:
        return True
    if RE_ROTULO_SO.match(ln.texto):
        return True
    m = RE_MARCADOR.match(ln.texto)
    if m:
        marc, resto = m.group(1), ln.texto[m.end():]
        if marc.isdigit() and resto[:1].islower():
            return False
        return bool(resto)
    return False


# ---------------------------------------------------------------- paragrafos

def _mescla_linhas_mesma_altura(lines: List[Linha]) -> List[Linha]:
    rows: List[Linha] = []
    for ln in lines:
        if rows:
            p = rows[-1]
            mesma_altura = abs(ln.y0 - p.y0) < 0.35 * max(ln.size, p.size)
            vao = ln.x0 - p.x1
            if mesma_altura and -3 <= vao <= 4 * max(ln.size, p.size) and ln.pagina == p.pagina:
                p.texto = (p.texto + " " + ln.texto).strip()
                p.x1 = max(p.x1, ln.x1)
                p.y1 = max(p.y1, ln.y1)
                p.sups = p.sups + ln.sups
                p.sup_fim = ln.sup_fim or p.sup_fim
                continue
        rows.append(ln.copia())
    return rows


def _paragrafos(lines: List[Linha], zona: str, col_left: float) -> List[Paragrafo]:
    pars: List[List[Linha]] = []
    for r in lines:
        if not pars:
            pars.append([r])
            continue
        prev = pars[-1][-1]
        if zona == "nota":
            # dentro da zona de notas, so um novo marcador abre outra nota (recuo e bloco nao contam)
            novo = _eh_inicio_nota_texto(r) or bool(r.sup_inicio) or bool(RE_ROTULO_SO.match(r.texto))
            if RE_ROTULO_SO.match(prev.texto):
                novo = False  # rotulo isolado + texto = mesma nota
            if novo:
                pars.append([r])
            else:
                pars[-1].append(r)
            continue
        estilo = abs(r.size - prev.size) > 0.6 or r.bold != prev.bold or r.italic != prev.italic
        gap = r.y0 - prev.y1
        terminal = prev.texto.rstrip().endswith(TERMINAL)
        indent = r.x0 > col_left + 6 and prev.x0 <= col_left + 6
        bloco = r.bloco != prev.bloco
        novo = estilo or gap > 1.6 * r.size or (indent and terminal) or (bloco and (terminal or indent or gap > 1.1 * r.size))
        if novo:
            pars.append([r])
        else:
            pars[-1].append(r)
    out = []
    for grupo in pars:
        textos = [g.texto for g in grupo]
        out.append(
            Paragrafo(
                pagina=grupo[0].pagina, zona=zona, linhas=grupo, texto=juntar_linhas(textos),
                texto_marcado=juntar_linhas([g.texto_marcado or g.texto for g in grupo]),
                size=Counter(round(g.size, 1) for g in grupo).most_common(1)[0][0],
                bold=sum(g.bold for g in grupo) > len(grupo) / 2, italic=sum(g.italic for g in grupo) > len(grupo) / 2,
                font=grupo[0].font, x0=min(g.x0 for g in grupo), y0=grupo[0].y0, x1=max(g.x1 for g in grupo), y1=grupo[-1].y1,
            )
        )
    return out


def _eh_inicio_nota_texto(ln: Linha):
    m = RE_MARCADOR.match(ln.texto)
    if not m:
        return False
    marc, resto = m.group(1), ln.texto[m.end():]
    if marc.isdigit() and resto[:1].islower():
        return False
    return True


def _layout(paginas, W, corpo):
    estreitas_dir = total = 0
    for pno, lines in paginas.items():
        if pno == 1:
            continue
        for ln in lines:
            if ln.zona != "corpo" or abs(ln.size - corpo) > 1:
                continue
            total += 1
            if ln.largura < 0.5 * W and ln.x0 > 0.45 * W:
                estreitas_dir += 1
    return "duas colunas" if total and estreitas_dir / total > 0.2 else "uma coluna"


def ler_pdf(caminho: str) -> Documento:
    pdf = pymupdf.open(caminho)
    W, H = pdf[0].rect.width, pdf[0].rect.height
    from extrator import ocr as _ocr  # noqa: WPS433
    paginas: Dict[int, List[Linha]] = {}
    imagens = []
    blocos_imagem = []
    ocr_paginas: List[int] = []
    for pno, page in enumerate(pdf, start=1):
        # página sem camada de texto (escaneada): o texto vem do OCR, se o Tesseract estiver disponível
        tp = _ocr.textpage(page) if _ocr.sem_texto(page) else None
        if tp is not None:
            ocr_paginas.append(pno)
        paginas[pno] = _linhas_pagina(page, pno, tp)
        imagens.append(len(page.get_images(full=True)))
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 1 or pno in ocr_paginas:
                continue  # numa página escaneada a imagem é a página inteira, não uma figura
            x0, y0, x1, y1 = b["bbox"]
            if (x1 - x0) < 60 or (y1 - y0) < 60:
                continue  # logos, filetes, marcadores
            if y1 < 0.08 * H or y0 > 0.95 * H:
                continue  # cabecalho/rodape
            blocos_imagem.append({"pagina": pno, "bbox": [round(v, 1) for v in b["bbox"]], "ext": b.get("ext", "png"),
                                  "dados": b.get("image"), "largura": b.get("width"), "altura": b.get("height")})
    size_chars, font_chars = Counter(), Counter()
    for lines in paginas.values():
        for ln in lines:
            if ln.size >= 6:
                size_chars[ln.size] += len(ln.texto)
    corpo = size_chars.most_common(1)[0][0] if size_chars else 10.0
    for lines in paginas.values():
        for ln in lines:
            if abs(ln.size - corpo) < 0.3:
                font_chars[ln.font] += len(ln.texto)
    corpo_font = font_chars.most_common(1)[0][0] if font_chars else ""
    cabecalhos = _classifica(paginas, W, H, corpo)
    # tabelas e equacoes saem do fluxo do corpo antes de montar os paragrafos
    tabelas = detecta_tabelas(pdf, paginas, H)
    equacoes = detecta_equacoes(paginas, corpo)
    for tb in tabelas:
        if tb.get("qualidade") == "baixa":
            try:
                tb["png"], tb["largura"], tb["altura"] = recorta(pdf, tb["pagina"], tb["bbox"], zoom=3.0)
            except Exception:  # noqa: BLE001
                tb["png"] = None
    for eq in equacoes:
        try:
            eq["png"], eq["largura"], eq["altura"] = recorta(pdf, eq["pagina"], eq["bbox"])
        except Exception:  # noqa: BLE001  (recorte e opcional; sem ele a equacao vira aviso)
            eq["png"], eq["largura"], eq["altura"] = None, None, None
    layout = _layout(paginas, W, corpo)

    todas, paragrafos, notas, laterais, margens = [], [], [], [], []
    col_esq = {}
    for pno in sorted(paginas):
        lines = paginas[pno]
        corpo_lines = [ln for ln in lines if ln.zona == "corpo"]
        if layout == "uma coluna":
            corpo_lines = sorted(corpo_lines, key=lambda l: (round(l.y0 / 2.0), l.x0))
        corpo_lines = _mescla_linhas_mesma_altura(corpo_lines)
        xs = Counter(round(l.x0) for l in corpo_lines if abs(l.size - corpo) < 0.7)
        col_left = xs.most_common(1)[0][0] if xs else (min((l.x0 for l in corpo_lines), default=0))
        col_esq[pno] = col_left
        paragrafos.extend(_paragrafos(corpo_lines, "corpo", col_left))
        nota_lines = _mescla_linhas_mesma_altura(sorted([ln for ln in lines if ln.zona == "nota"], key=lambda l: (round(l.y0 / 2.0), l.x0)))
        notas.extend(_paragrafos(nota_lines, "nota", min((l.x0 for l in nota_lines), default=0)))
        lat_lines = sorted([ln for ln in lines if ln.zona == "lateral"], key=lambda l: (round(l.y0 / 2.0), l.x0))
        laterais.extend(_paragrafos(lat_lines, "lateral", min((l.x0 for l in lat_lines), default=0)))
        marg_lines = [ln for ln in lines if ln.zona == "margem"]
        margens.extend(_paragrafos(marg_lines, "margem", min((l.x0 for l in marg_lines), default=0)))
        todas.extend(lines)

    return Documento(
        caminho=caminho, paginas=pdf.page_count, metadata={k: v for k, v in pdf.metadata.items() if v}, largura=W, altura=H,
        corpo_size=corpo, corpo_font=corpo_font, layout=layout, linhas=todas, cabecalhos=cabecalhos, paragrafos=paragrafos,
        notas=notas, laterais=laterais, margens=margens, imagens_por_pagina=imagens, coluna_esquerda=col_esq,
        imagens=blocos_imagem, tabelas=tabelas, equacoes=equacoes, ocr_paginas=ocr_paginas,
    )
