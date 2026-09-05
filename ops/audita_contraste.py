"""
Auditoria de contraste (WCAG 2.x) das paletas claro e escuro de app/static/style.css.

Le os tokens do proprio CSS (bloco :root e bloco :root[data-theme="dark"]), mede cada par texto/fundo usado nos
componentes e escreve app/static/contraste.md. Sai com codigo 1 se algum par ficar abaixo do minimo.
Minimos: texto normal 4.5:1; texto grande, icones, bordas de campo e indicadores 3:1.

Uso: python ops/audita_contraste.py
"""
import io
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(RAIZ, "app", "static", "style.css")
SAIDA = os.path.join(RAIZ, "app", "static", "contraste.md")


def lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, pa):
    """color-mix(in srgb, a pa%, b) aproximado."""
    ha, hb = a.lstrip("#"), b.lstrip("#")
    out = ""
    for i in (0, 2, 4):
        va, vb = int(ha[i:i + 2], 16), int(hb[i:i + 2], 16)
        out += f"{round(va * pa + vb * (1 - pa)):02X}"
    return "#" + out


def le_tokens(css, seletor):
    ini = css.index(seletor + "{")
    fim = css.index("}", ini)
    bloco = css[ini:fim]
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", bloco))


def pares(P):
    S, S2, S3, BG = P["surface"], P["surface-2"], P["surface-3"], P["bg"]
    return [
        # (descricao, tinta, fundo, minimo)
        ("texto principal em cartão", P["text"], S, 4.5), ("texto principal no fundo da página", P["text"], BG, 4.5),
        ("texto principal em surface-2 (cabeçalho de grupo, tabela)", P["text"], S2, 4.5), ("texto principal em surface-3 (hover)", P["text"], S3, 4.5),
        ("text-2 (subtítulos, rótulos) em cartão", P["text-2"], S, 4.5), ("text-2 em surface-2", P["text-2"], S2, 4.5), ("text-2 em surface-3 (code.rule)", P["text-2"], S3, 4.5),
        ("muted (legendas) em cartão", P["muted"], S, 4.5), ("muted em surface-2", P["muted"], S2, 4.5), ("muted em surface-3 (chip neutro)", P["muted"], S3, 4.5), ("muted no fundo da página", P["muted"], BG, 4.5),
        ("faint (dicas, rodapé, versão) em cartão", P["faint"], S, 4.5), ("faint em surface-2 (sem imagem)", P["faint"], S2, 4.5), ("faint no fundo da página", P["faint"], BG, 4.5),
        ("link em cartão", P["link"], S, 4.5), ("link no fundo da página", P["link"], BG, 4.5),
        ("accent ('jats' da marca) em topbar", P["accent"], S, 4.5),
        ("brand-ink em brand (botão primário, ícone do status)", P["brand-ink"], P["brand"], 4.5), ("brand-ink em brand-2 (hover do botão)", P["brand-ink"], P["brand-2"], 4.5),
        ("brand-text em brand-soft (nav ativo, passos, avatar)", P["brand-text"], P["brand-soft"], 4.5), ("brand-text em surface (seletor de tema)", P["brand-text"], S, 4.5),
        ("crit-ink em crit-bg (chip, mensagem)", P["crit-ink"], P["crit-bg"], 4.5), ("warn-ink em warn-bg", P["warn-ink"], P["warn-bg"], 4.5),
        ("ok-ink em ok-bg", P["ok-ink"], P["ok-bg"], 4.5), ("info-ink em info-bg", P["info-ink"], P["info-bg"], 4.5),
        ("texto no cartão de status 'pronto' (ok-bg 50%)", P["text"], mix(P["ok-bg"], S, .5), 4.5), ("text-2 no status 'pronto'", P["text-2"], mix(P["ok-bg"], S, .5), 4.5),
        ("texto no status 'não pronto' (crit-bg 40%)", P["text"], mix(P["crit-bg"], S, .4), 4.5), ("text-2 no status 'não pronto'", P["text-2"], mix(P["crit-bg"], S, .4), 4.5),
        ("texto digitado em campo bloqueante (crit-bg 45%)", P["text"], mix(P["crit-bg"], S, .45), 4.5),
        ("texto em seleção (brand-soft-2)", P["text"], P["brand-soft-2"], 4.5),
        ("texto em brand-soft (dropzone em hover)", P["text"], P["brand-soft"], 4.5), ("muted em brand-soft (dropzone em hover)", P["muted"], P["brand-soft"], 4.5),
        ("crit como texto ('vermelho', botão danger) no fundo", P["crit"], BG, 4.5), ("warn como texto ('laranja') no fundo", P["warn"], BG, 4.5),
        ("crit-ink em crit-bg (hover do botão danger)", P["crit-ink"], P["crit-bg"], 4.5),
        ("listra/borda crit em cartão", P["crit"], S, 3.0), ("listra/borda warn em cartão", P["warn"], S, 3.0), ("listra/borda ok em cartão", P["ok"], S, 3.0), ("borda info", P["info"], S, 3.0),
        ("borda de campo e botão (border-strong) em cartão", P["border-strong"], S, 3.0), ("borda de campo em surface-2 (dropzone)", P["border-strong"], S2, 3.0),
        ("borda de foco (brand-2) em cartão", P["brand-2"], S, 3.0), ("borda de foco no fundo", P["brand-2"], BG, 3.0),
        ("ícone do seletor de tema (muted) em surface-2", P["muted"], S2, 3.0),
    ]


def main():
    css = io.open(CSS, encoding="utf-8").read()
    temas = {"Claro": le_tokens(css, ":root"), "Escuro": le_tokens(css, ':root[data-theme="dark"]')}
    # o bloco @media do escuro precisa ser identico ao data-theme="dark"
    media = le_tokens(css, ':root:not([data-theme="light"])')
    if media != temas["Escuro"]:
        print("FALHA: bloco @media (prefers-color-scheme: dark) difere do bloco data-theme=dark:", set(media.items()) ^ set(temas["Escuro"].items()))
        return 1
    falhas = 0
    linhas = ["# Contraste medido (WCAG 2.x)", "", "Gerado por `python ops/audita_contraste.py` a partir dos tokens de `style.css`.",
              "Texto normal precisa de 4.5:1; texto grande, ícones, bordas de campo e indicadores precisam de 3:1.", ""]
    for nome, P in temas.items():
        linhas += [f"## Tema {nome.lower()}", "", "| Par | Tinta | Fundo | Razão | Mínimo | |", "|---|---|---|---|---|---|"]
        for desc, tinta, fundo, minimo in pares(P):
            v = contraste(tinta, fundo)
            ok = v >= minimo
            falhas += 0 if ok else 1
            linhas.append(f"| {desc} | `{tinta}` | `{fundo}` | {v:.2f} | {minimo} | {'ok' if ok else '**FALHA**'} |")
            print(f"{'ok   ' if ok else 'FALHA'} {v:5.2f} >= {minimo}  [{nome}] {desc}")
        linhas.append("")
    linhas.append(f"Falhas: {falhas}")
    io.open(SAIDA, "w", encoding="utf-8").write("\n".join(linhas) + "\n")
    print("falhas:", falhas, "->", os.path.relpath(SAIDA, RAIZ))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
