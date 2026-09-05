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
from extrator.modelo import ArticleModel  # noqa: E402


def extrai(caminho: str, pasta_imagens: str = None):
    doc = ler_pdf(caminho)
    model = ArticleModel(
        arquivo=os.path.basename(caminho), paginas=doc.paginas,
        gerado_por=doc.metadata.get("creator") or doc.metadata.get("producer"),
        fonte_corpo_pt=doc.corpo_size, layout=doc.layout, cabecalhos=list(doc.cabecalhos),
    )
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
    usadas = {f.imagem_indice for f in model.figuras if f.imagem_indice is not None}
    soltas = len([i for i in range(len(doc.imagens)) if i not in usadas])
    if soltas:
        model.aviso(f"{soltas} imagem(ns) no PDF sem legenda 'Figura N' associada; não entram no XML (F01).")
    model.proveniencia["_indices"] = {"primeira_secao": i_sec, "referencias": i_ref, "paragrafos": len(doc.paragrafos), "notas": len(doc.notas), "laterais": len(doc.laterais), "margens": len(doc.margens)}
    return doc, model


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
