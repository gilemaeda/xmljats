"""
Extrator de PDF (PoC, caminho C): PDF -> ArticleModel (JSON) + resumo legivel + placar dos seis elementos obrigatorios.

Uso:  python poc/extrair.py "modelos/*.pdf" article.segmented.pdf
Saidas: poc/saida/<nome>.model.json, poc/saida/<nome>.resumo.md, poc/saida/placar.md
"""
import glob
import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extrator import corpo, front, placar, referencias  # noqa: E402
from extrator.leitura import ler_pdf  # noqa: E402
from extrator.modelo import ArticleModel, Figura, Secao, Tabela  # noqa: E402


def extrai(caminho: str, pasta_imagens: str = None):
    """PDF ou DOCX -> (Documento, ArticleModel). O DOCX passa pelo mesmo caminho e, no fim, tem o corpo,
    as tabelas e as equações substituídos pelo que o próprio arquivo declara, em vez de heurística."""
    e_docx = caminho.lower().endswith(".docx")
    if e_docx:
        from extrator.docx import le_docx  # noqa: WPS433
        doc = le_docx(caminho)
    else:
        doc = ler_pdf(caminho)
    model = ArticleModel(
        arquivo=os.path.basename(caminho), paginas=doc.paginas,
        gerado_por=doc.metadata.get("creator") or doc.metadata.get("producer"),
        fonte_corpo_pt=doc.corpo_size, layout=doc.layout, cabecalhos=list(doc.cabecalhos),
    )
    # PDF escaneado: só imagem, sem camada de texto. O motor lê texto e ainda não faz OCR; melhor dizer isso
    # do que devolver "título não identificado" para tudo.
    if not e_docx:
        chars = sum(len((l.texto or "").strip()) for l in doc.linhas)
        ocr_paginas = list(getattr(doc, "ocr_paginas", None) or [])
        if ocr_paginas and chars >= 40 * max(1, doc.paginas):
            model.marca("texto", f"OCR em {len(ocr_paginas)} de {doc.paginas} página(s)")
            model.avisos.append(f"Texto obtido por OCR em {len(ocr_paginas)} de {doc.paginas} página(s), porque o PDF é uma "
                                "imagem escaneada: confira com atenção título, autores, resumo e referências, porque OCR erra "
                                "acentos e quebras (D02).")
        elif chars < 40 * max(1, doc.paginas):
            from extrator import ocr as _ocr  # noqa: WPS433
            model.sem_texto = True
            motivo = "o OCR não está disponível neste servidor" if not _ocr.tessdata_dir() else "o OCR não conseguiu ler o texto"
            model.avisos.append(f"O PDF não tem camada de texto ({chars} caractere(s) em {doc.paginas} página(s)): é um "
                                f"documento escaneado, e {motivo}. Envie o DOCX ou o PDF gerado pelo editor de texto (D01).")
    i_sec = corpo.indice_primeira_secao(doc)
    i_ref = referencias.indice_referencias(doc, i_sec)
    if i_sec is not None and i_ref is not None and i_ref <= i_sec:
        i_ref = None
    lf = front._linhas_front(doc, i_sec)
    front.extrai_identificadores(doc, model, lf)
    front.extrai_heading(doc, model, lf)
    front.extrai_titulos_e_autores(doc, model, lf)
    front.extrai_resumos(doc, model, lf)
    corpo.extrai_corpo(doc, model, i_sec, i_ref)
    referencias.extrai_referencias(doc, model, i_ref)
    front.extrai_datas_e_licenca(doc, model)
    # tipo de artigo (inferencia simples; sempre confirmar)
    pista = " ".join(filter(None, [model.heading or "", model.titulo_principal or ""])).lower()
    if "editorial" in pista:
        model.tipo_artigo = "editorial"
    elif re.search(r"resenha|book review|reseña", pista):
        model.tipo_artigo = "book-review"
    else:
        model.tipo_artigo = "research-article"
    model.marca("tipo_artigo", "inferido (heading/título); confirmar")
    # imagens das figuras: grava arquivos provisorios (o nome SPS <base>-gfNN vem no gerador/pacote)
    n = 0
    for f in model.figuras:
        if f.imagem_indice is None:
            continue
        im = doc.imagens[f.imagem_indice]
        n += 1
        f.arquivo = f"fig{n:02d}.{im['ext']}"
        if pasta_imagens and im.get("dados"):
            os.makedirs(pasta_imagens, exist_ok=True)
            with open(os.path.join(pasta_imagens, f.arquivo), "wb") as fh:
                fh.write(im["dados"])
    # imagens de tabelas cuja grade nao e confiavel (tabNN.png)
    brutas_tab = {(g["pagina"], tuple(g["bbox"])): g for g in doc.tabelas}
    for k, t in enumerate(model.tabelas, start=1):
        g = brutas_tab.get((t.pagina, tuple(t.bbox))) if t.bbox else None
        if not g or not g.get("png"):
            continue
        t.arquivo, t.largura, t.altura = f"tab{k:02d}.png", g.get("largura"), g.get("altura")
        if pasta_imagens:
            os.makedirs(pasta_imagens, exist_ok=True)
            with open(os.path.join(pasta_imagens, t.arquivo), "wb") as fh:
                fh.write(g["png"])
    # imagens das equacoes recortadas do PDF (eqNN.png)
    for k, (eq, bruta) in enumerate(zip(model.equacoes, doc.equacoes), start=1):
        if not bruta.get("png"):
            continue
        eq.arquivo = f"eq{k:02d}.png"
        if pasta_imagens:
            os.makedirs(pasta_imagens, exist_ok=True)
            with open(os.path.join(pasta_imagens, eq.arquivo), "wb") as fh:
                fh.write(bruta["png"])
    usadas = {f.imagem_indice for f in model.figuras if f.imagem_indice is not None}
    soltas = len([i for i in range(len(doc.imagens)) if i not in usadas])
    if soltas:
        model.aviso(f"{soltas} imagem(ns) no PDF sem legenda 'Figura N' associada; não entram no XML (F01).")
    model.proveniencia["_indices"] = {"primeira_secao": i_sec, "referencias": i_ref, "paragrafos": len(doc.paragrafos), "notas": len(doc.notas), "laterais": len(doc.laterais), "margens": len(doc.margens)}
    if e_docx:
        _aplica_estrutura_docx(doc, model, pasta_imagens)
    return doc, model


RE_LEGENDA_FIG = re.compile(r"^\s*(figura|fig\.?|gr[áa]fico|imagem|foto|quadro)\s*(\d{1,3})\b[\s.:\-–]*(.*)$", re.I)
RE_LEGENDA_TAB = re.compile(r"^\s*(tabela|table|tabla)\s*(\d{1,3})\b[\s.:\-–]*(.*)$", re.I)
RE_FONTE = re.compile(r"^\s*(fonte|source|fuente)\s*[:.]\s*(.+)$", re.I)
RE_HEAD_REF_SIMPLES = re.compile(r"^(refer[êe]ncias?|references|bibliografia|bibliography)\b", re.I)


def _aplica_estrutura_docx(doc, model, pasta_imagens=None):
    """Troca o que foi adivinhado pelo que o DOCX declara: seções pelos estilos de título, tabelas com
    células de verdade e equações já em MathML. O front matter (autores, resumos, datas) continua vindo
    das mesmas heurísticas, porque nem o DOCX marca isso."""
    linhas = doc.linhas
    secoes = [s for s in getattr(doc, "secoes_docx", []) if s["nivel"] >= 1]
    # o que vem antes do primeiro título de nível 1 é front matter; o que vem do "Referências" em diante é back
    i_ref = next((s["indice_linha"] for s in secoes if RE_HEAD_REF_SIMPLES.match(s["titulo"])), None)
    corpo_secoes = [s for s in secoes if not RE_HEAD_REF_SIMPLES.match(s["titulo"])
                    and (i_ref is None or s["indice_linha"] < i_ref)]
    # resumo e abstract são front matter, não seções do corpo
    corpo_secoes = [s for s in corpo_secoes
                    if not re.match(r"^(resumo|abstract|resumen|palavras[- ]chave|keywords)\b", s["titulo"], re.I)]
    # titulo com estilo de cabecalho: num DOCX ninguem poe secao do corpo antes do resumo, entao um
    # Heading que apareca antes dele e o titulo do artigo, nao secao.
    # o resumo tanto pode ser um titulo com estilo quanto uma linha comum comecando por "Resumo:"
    i_resumo = next((x["indice_linha"] for x in secoes
                     if re.match(r"^(resumo|abstract|resumen)", x["titulo"], re.I)), None)
    if i_resumo is None:
        i_resumo = next((i for i, l in enumerate(linhas)
                         if l.zona == "corpo" and re.match(r"^(resumo|abstract|resumen|palavras[- ]chave|keywords)\b\s*[:.]",
                                                           l.texto or "", re.I)), None)
    if i_resumo is not None:
        antes = [x for x in corpo_secoes if x["indice_linha"] < i_resumo]
        if antes:
            candidato = antes[-1]["titulo"].strip()
            atual = (model.titulo_principal or "").strip()
            if candidato and candidato.lower() != atual.lower() and len(candidato) > 15:
                for t in model.titulos:
                    if t.tipo == "article-title":
                        t.texto = candidato
                        break
                else:
                    from extrator.modelo import Titulo
                    model.titulos.insert(0, Titulo(texto=candidato, idioma=model.idioma, tipo="article-title"))
                model.marca("titulos", "titulo pelo estilo de cabecalho que vem antes do resumo, no DOCX")
            corpo_secoes = [x for x in corpo_secoes if x["indice_linha"] >= i_resumo]
    if not corpo_secoes:
        return
    fim_corpo = i_ref if i_ref is not None else len(linhas)
    novas = []
    for k, s in enumerate(corpo_secoes):
        ate = corpo_secoes[k + 1]["indice_linha"] if k + 1 < len(corpo_secoes) else fim_corpo
        pars = [linhas[i].texto for i in range(s["indice_linha"] + 1, min(ate, len(linhas)))
                if linhas[i].zona == "corpo" and linhas[i].texto.strip()]
        pars = [p for p in pars if not RE_LEGENDA_FIG.match(p) and not RE_LEGENDA_TAB.match(p) and not RE_FONTE.match(p)]
        titulo = s["titulo"].strip()
        numero = None
        mn = re.match(r"^(\d+(?:\.\d+)*)[.)\s]+(.+)$", titulo)
        if mn:
            numero, titulo_limpo = mn.group(1), mn.group(2).strip()
        else:
            titulo_limpo = titulo
        novas.append(Secao(titulo=titulo_limpo, nivel=s["nivel"], numero=numero, titulo_completo=s["titulo"].strip(),
                           pagina=linhas[s["indice_linha"]].pagina if s["indice_linha"] < len(linhas) else 1,
                           paragrafos=pars))
    model.secoes = novas
    model.marca("secoes", f"{len(novas)} seção(ões) pelos estilos de título do DOCX (Heading), não por heurística")

    def _secao_de(indice_linha):
        """Em que seção do corpo cai um elemento que estava nesta posição do arquivo."""
        anterior = [(n, s) for n, s in enumerate(corpo_secoes) if s["indice_linha"] <= indice_linha]
        if not anterior:
            return None, 0
        n, s = anterior[-1]
        pos = sum(1 for i in range(s["indice_linha"] + 1, min(indice_linha, len(linhas)))
                  if linhas[i].zona == "corpo" and linhas[i].texto.strip())
        return n, pos

    def _legenda_perto(indice_linha, regex):
        """Legenda e fonte na vizinhança do elemento (o Word põe logo acima ou logo abaixo)."""
        for i in list(range(indice_linha, min(indice_linha + 4, len(linhas)))) + \
                 list(range(max(0, indice_linha - 3), indice_linha)):
            m = regex.match(linhas[i].texto or "")
            if m:
                fonte = None
                for j in range(i + 1, min(i + 4, len(linhas))):
                    mf = RE_FONTE.match(linhas[j].texto or "")
                    if mf:
                        fonte = mf.group(2).strip()
                        break
                return m.group(1).strip().capitalize() + " " + m.group(2), m.group(2), (m.group(3) or "").strip(), fonte
        return None, None, "", None

    # ---- tabelas: o DOCX já entrega as células separadas, então nada vai como imagem
    if doc.tabelas:
        model.tabelas = []
        for t in doc.tabelas:
            rotulo, numero, legenda, fonte = _legenda_perto(t["indice_linha"], RE_LEGENDA_TAB)
            si, pos = _secao_de(t["indice_linha"])
            model.tabelas.append(Tabela(
                numero=numero, rotulo=rotulo or "", legenda=legenda, fonte=fonte, pagina=t.get("pagina", 1),
                celulas=t["celulas"], linhas_cabecalho=t["linhas_cabecalho"], colunas=t["colunas"],
                secao_indice=si, pos_paragrafo=pos, qualidade="alta",
                chamada_no_texto=bool(numero and any(re.search(rf"tabela\s*{numero}\b", p, re.I)
                                                     for s in novas for p in s.paragrafos))))
        model.marca("tabelas", f"{len(model.tabelas)} tabela(s) com células vindas do DOCX (nenhuma vai como imagem)")

    # ---- equações: OMML do Word convertido em MathML, que é o que a SciELO exige
    if doc.equacoes:
        from extrator.modelo import Equacao  # noqa: WPS433
        model.equacoes = []
        for k, e in enumerate(doc.equacoes, start=1):
            si, pos = _secao_de(e["indice_linha"])
            eq = Equacao(numero=str(k), rotulo=f"({k})", pagina=e.get("pagina", 1), secao_indice=si, pos_paragrafo=pos)
            eq.mathml = e["mathml"]
            eq.latex = ""
            model.equacoes.append(eq)
        model.marca("equacoes", f"{len(model.equacoes)} equação(ões) em MathML, convertidas do OMML do Word")

    # ---- figuras: as imagens do DOCX, casadas com a legenda "Figura N" mais próxima
    if doc.imagens:
        model.figuras = []
        n = 0
        for idx, im in enumerate(doc.imagens):
            rotulo, numero, legenda, fonte = _legenda_perto(im["indice_linha"], RE_LEGENDA_FIG)
            if not rotulo:
                continue
            si, pos = _secao_de(im["indice_linha"])
            n += 1
            arquivo = f"fig{n:02d}.{im.get('ext') or 'png'}"
            model.figuras.append(Figura(tipo="fig", rotulo=rotulo, legenda=legenda, fonte=fonte,
                                        pagina=im.get("pagina", 1), numero=numero, secao_indice=si,
                                        pos_paragrafo=pos, imagem_indice=idx, arquivo=arquivo,
                                        ext=im.get("ext"),
                                        chamada_no_texto=bool(numero and any(re.search(rf"figura\s*{numero}\b", p, re.I)
                                                                             for s in novas for p in s.paragrafos))))
            if pasta_imagens and im.get("dados"):
                os.makedirs(pasta_imagens, exist_ok=True)
                with open(os.path.join(pasta_imagens, arquivo), "wb") as fh:
                    fh.write(im["dados"])
        sem_legenda = len(doc.imagens) - n
        if sem_legenda:
            model.aviso(f"{sem_legenda} imagem(ns) no DOCX sem legenda 'Figura N' por perto; não entram no XML (F01).")


def resumo_md(m: ArticleModel) -> str:
    L = [f"# {m.arquivo}", "",
         f"- páginas {m.paginas} · corpo {m.fonte_corpo_pt} pt · {m.layout} · gerado por {m.gerado_por}",
         f"- revista: {m.revista_titulo} · ISSN {m.issn} · DOI {m.doi} · v.{m.volume} n.{m.numero} ({m.ano}) · elocation {m.elocation} · p. {m.fpage}-{m.lpage}",
         f"- heading: {m.heading} · tipo: {m.tipo_artigo} · idioma: {m.idioma} · licença: {m.licenca}",
         f"- datas: recebido {m.datas.recebido} · revisado {m.datas.revisado} · aceito {m.datas.aceito} · publicado {m.datas.publicado}",
         "", "## Títulos"]
    for t in m.titulos:
        L.append(f"- [{t.tipo} · {t.idioma}] {t.texto}")
    L += ["", "## Autores"]
    for a in m.autores:
        affs = "; ".join(f"{x.id}: {x.instituicao or '?'} · {x.divisao or ''} · {x.cidade or '?'}/{x.estado or '?'}/{x.pais_iso or '?'} ({x.origem})" for x in m.afiliacoes if x.id in a.aff_ids)
        L.append(f"- {a.nome_completo} → sobrenome '{a.sobrenome}' · marcadores {a.marcadores} · ORCID {a.orcid} ({'ok' if a.orcid_valido else ('inválido' if a.orcid_valido is False else '—')}) · {a.email}")
        L.append(f"  - afiliação: {affs or '—'}")
    if m.editores:
        L.append(f"- editores: {[e.nome_completo for e in m.editores]}")
    if m.orcids_nao_atribuidos:
        L.append(f"- ORCIDs não atribuídos: {[(o['orcid'], o['zona'], o['contexto'][:40]) for o in m.orcids_nao_atribuidos]}")
    L += ["", "## Resumos"]
    for r in m.resumos:
        L.append(f"- [{r.rotulo} → {r.idioma}] {len(r.texto.split())} palavras · palavras-chave ({r.rotulo_palavras}): {r.palavras_chave}")
    if m.tabelas:
        L += ["", f"## Tabelas ({len(m.tabelas)})"]
        for t in m.tabelas:
            L.append(f"- p.{t.pagina} {t.rotulo or '(sem rótulo)'} · {len(t.celulas)}x{t.colunas} células · cabeçalho {t.linhas_cabecalho} linha(s) · "
                     f"{'chamada no texto' if t.chamada_no_texto else 'sem chamada'} · {t.legenda[:70]}")
    if m.equacoes:
        L += ["", f"## Equações ({len(m.equacoes)})"]
        for e in m.equacoes:
            L.append(f"- p.{e.pagina} {e.rotulo or '(sem número)'} · {'imagem ' + str(e.arquivo) if e.arquivo else 'sem recorte'} · {e.texto[:70]}")
    L += ["", f"## Seções ({len(m.secoes)})"]
    for s in m.secoes:
        L.append(f"- p.{s.pagina} nível {s.nivel} [{s.sec_type or '-'}] {s.numero or ''} {s.titulo} · {len(s.paragrafos)} parágrafos")
    unicas = {(c.autor, c.ano) for c in m.citacoes}
    ligadas = sum(1 for c in m.citacoes if c.ref_index is not None)
    L += ["", f"## Citações: {len(m.citacoes)} ({len(unicas)} únicas, {ligadas} ligadas a referências)", "- " + "; ".join(f"{a} {y}" for a, y in sorted(unicas)[:25])]
    L += ["", f"## Notas ({len(m.notas)})"]
    for n in m.notas[:40]:
        L.append(f"- fn{n.id[2:]} rótulo '{n.rotulo}' p.{n.pagina} tipo {n.tipo} chamada {'sim' if n.chamada_no_texto else 'não'} {('→ ' + n.ligada_a) if n.ligada_a else ''}: {n.texto[:70]}")
    L += ["", f"## Figuras e tabelas ({len(m.figuras)})"]
    for f in m.figuras:
        L.append(f"- p.{f.pagina} {f.tipo} {f.rotulo}: {f.legenda[:60]} · fonte: {(f.fonte or '')[:40]} · chamada {'sim' if f.chamada_no_texto else 'não'}")
    tipos = {}
    for r in m.referencias:
        tipos[r.tipo] = tipos.get(r.tipo, 0) + 1
    L += ["", f"## Referências ({len(m.referencias)}) · estilo {m.estilo_referencias} · tipos {tipos} · citadas {sum(1 for r in m.referencias if r.citada)}"]
    for r in m.referencias[:60]:
        L.append(f"- [{r.tipo} {r.ano}] {r.texto[:110]}")
    if m.back_matter:
        L += ["", "## Back matter"] + [f"- {b['titulo']}: {b['texto'][:80]}" for b in m.back_matter]
    L += ["", "## Avisos"] + [f"- {a}" for a in m.avisos]
    L += ["", "## Proveniência"] + [f"- {k}: {v}" for k, v in m.proveniencia.items()]
    return "\n".join(L)


def main(args):
    paths = []
    for a in args:
        paths.extend(glob.glob(a))
    if not paths:
        print("Nenhum PDF encontrado.")
        return 1
    os.makedirs("poc/saida", exist_ok=True)
    resultados = {}
    for p in paths:
        nome = os.path.splitext(os.path.basename(p))[0]
        try:
            doc, model = extrai(p, pasta_imagens=os.path.join("poc", "saida", "img", nome))
        except Exception:  # noqa: BLE001
            print(f"### {nome}: ERRO\n{traceback.format_exc()}")
            continue
        with open(f"poc/saida/{nome}.model.json", "w", encoding="utf-8") as f:
            json.dump(model.to_dict(), f, ensure_ascii=False, indent=2)
        with open(f"poc/saida/{nome}.resumo.md", "w", encoding="utf-8") as f:
            f.write(resumo_md(model))
        gab = placar.carrega_gabarito(nome)
        resultados[nome] = placar.avalia(model, gab)
        print(f"ok  {nome}: {len(model.titulos)} títulos, {len(model.autores)} autores, {len(model.resumos)} resumos, {len(model.secoes)} seções, {len(model.notas)} notas, {len(model.referencias)} refs, {len(model.avisos)} avisos" + ("" if gab else "  [sem gabarito]"))
    tab = placar.tabela(resultados)
    with open("poc/saida/placar.md", "w", encoding="utf-8") as f:
        f.write("# Placar dos seis elementos obrigatórios\n\n" + tab + "\n")
    print("\n" + tab)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["modelos/*.pdf", "article.segmented.pdf"]))
