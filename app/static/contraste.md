# Contraste medido (WCAG 2.x)

Gerado por `python ops/audita_contraste.py` a partir dos tokens de `style.css`.
Texto normal precisa de 4.5:1; texto grande, ícones, bordas de campo e indicadores precisam de 3:1.

## Tema claro

| Par | Tinta | Fundo | Razão | Mínimo | |
|---|---|---|---|---|---|
| texto principal em cartão | `#131A24` | `#FFFFFF` | 17.49 | 4.5 | ok |
| texto principal no fundo da página | `#131A24` | `#F3F5F9` | 16.02 | 4.5 | ok |
| texto principal em surface-2 (cabeçalho de grupo, tabela) | `#131A24` | `#F6F8FB` | 16.44 | 4.5 | ok |
| texto principal em surface-3 (hover) | `#131A24` | `#ECF0F5` | 15.28 | 4.5 | ok |
| text-2 (subtítulos, rótulos) em cartão | `#3E4B5B` | `#FFFFFF` | 8.89 | 4.5 | ok |
| text-2 em surface-2 | `#3E4B5B` | `#F6F8FB` | 8.36 | 4.5 | ok |
| text-2 em surface-3 (code.rule) | `#3E4B5B` | `#ECF0F5` | 7.77 | 4.5 | ok |
| muted (legendas) em cartão | `#5C6979` | `#FFFFFF` | 5.60 | 4.5 | ok |
| muted em surface-2 | `#5C6979` | `#F6F8FB` | 5.26 | 4.5 | ok |
| muted em surface-3 (chip neutro) | `#5C6979` | `#ECF0F5` | 4.89 | 4.5 | ok |
| muted no fundo da página | `#5C6979` | `#F3F5F9` | 5.13 | 4.5 | ok |
| faint (dicas, rodapé, versão) em cartão | `#5F6C7B` | `#FFFFFF` | 5.36 | 4.5 | ok |
| faint em surface-2 (sem imagem) | `#5F6C7B` | `#F6F8FB` | 5.04 | 4.5 | ok |
| faint no fundo da página | `#5F6C7B` | `#F3F5F9` | 4.91 | 4.5 | ok |
| link em cartão | `#1F4E8C` | `#FFFFFF` | 8.31 | 4.5 | ok |
| link no fundo da página | `#1F4E8C` | `#F3F5F9` | 7.61 | 4.5 | ok |
| accent ('jats' da marca) em topbar | `#157A62` | `#FFFFFF` | 5.26 | 4.5 | ok |
| brand-ink em brand (botão primário, ícone do status) | `#FFFFFF` | `#1B3A66` | 11.39 | 4.5 | ok |
| brand-ink em brand-2 (hover do botão) | `#FFFFFF` | `#2B5AA0` | 6.83 | 4.5 | ok |
| brand-text em brand-soft (nav ativo, passos, avatar) | `#1B3A66` | `#E4ECF8` | 9.57 | 4.5 | ok |
| brand-text em surface (seletor de tema) | `#1B3A66` | `#FFFFFF` | 11.39 | 4.5 | ok |
| crit-ink em crit-bg (chip, mensagem) | `#7A1A14` | `#FBE9E7` | 9.02 | 4.5 | ok |
| warn-ink em warn-bg | `#6B3B00` | `#FFF1DA` | 8.37 | 4.5 | ok |
| ok-ink em ok-bg | `#14502F` | `#E3F3E9` | 8.23 | 4.5 | ok |
| info-ink em info-bg | `#1B3D6E` | `#E6EEF9` | 9.26 | 4.5 | ok |
| texto no cartão de status 'pronto' (ok-bg 50%) | `#131A24` | `#F1F9F4` | 16.32 | 4.5 | ok |
| text-2 no status 'pronto' | `#3E4B5B` | `#F1F9F4` | 8.30 | 4.5 | ok |
| texto no status 'não pronto' (crit-bg 40%) | `#131A24` | `#FDF6F5` | 16.39 | 4.5 | ok |
| text-2 no status 'não pronto' | `#3E4B5B` | `#FDF6F5` | 8.33 | 4.5 | ok |
| texto digitado em campo bloqueante (crit-bg 45%) | `#131A24` | `#FDF5F4` | 16.27 | 4.5 | ok |
| texto em seleção (brand-soft-2) | `#131A24` | `#D2DFF3` | 12.98 | 4.5 | ok |
| texto em brand-soft (dropzone em hover) | `#131A24` | `#E4ECF8` | 14.70 | 4.5 | ok |
| muted em brand-soft (dropzone em hover) | `#5C6979` | `#E4ECF8` | 4.71 | 4.5 | ok |
| crit como texto ('vermelho', botão danger) no fundo | `#B3261E` | `#F3F5F9` | 5.99 | 4.5 | ok |
| warn como texto ('laranja') no fundo | `#995607` | `#F3F5F9` | 5.22 | 4.5 | ok |
| crit-ink em crit-bg (hover do botão danger) | `#7A1A14` | `#FBE9E7` | 9.02 | 4.5 | ok |
| listra/borda crit em cartão | `#B3261E` | `#FFFFFF` | 6.54 | 3.0 | ok |
| listra/borda warn em cartão | `#995607` | `#FFFFFF` | 5.69 | 3.0 | ok |
| listra/borda ok em cartão | `#1F7A4D` | `#FFFFFF` | 5.32 | 3.0 | ok |
| borda info | `#2F5FA5` | `#FFFFFF` | 6.36 | 3.0 | ok |
| borda de campo e botão (border-strong) em cartão | `#7F8C9C` | `#FFFFFF` | 3.42 | 3.0 | ok |
| borda de campo em surface-2 (dropzone) | `#7F8C9C` | `#F6F8FB` | 3.22 | 3.0 | ok |
| borda de foco (brand-2) em cartão | `#2B5AA0` | `#FFFFFF` | 6.83 | 3.0 | ok |
| borda de foco no fundo | `#2B5AA0` | `#F3F5F9` | 6.26 | 3.0 | ok |
| ícone do seletor de tema (muted) em surface-2 | `#5C6979` | `#F6F8FB` | 5.26 | 3.0 | ok |

## Tema escuro

| Par | Tinta | Fundo | Razão | Mínimo | |
|---|---|---|---|---|---|
| texto principal em cartão | `#E9EEF4` | `#151C27` | 14.67 | 4.5 | ok |
| texto principal no fundo da página | `#E9EEF4` | `#0E131B` | 15.96 | 4.5 | ok |
| texto principal em surface-2 (cabeçalho de grupo, tabela) | `#E9EEF4` | `#1A2230` | 13.68 | 4.5 | ok |
| texto principal em surface-3 (hover) | `#E9EEF4` | `#212B3A` | 12.23 | 4.5 | ok |
| text-2 (subtítulos, rótulos) em cartão | `#C3CCD7` | `#151C27` | 10.54 | 4.5 | ok |
| text-2 em surface-2 | `#C3CCD7` | `#1A2230` | 9.84 | 4.5 | ok |
| text-2 em surface-3 (code.rule) | `#C3CCD7` | `#212B3A` | 8.79 | 4.5 | ok |
| muted (legendas) em cartão | `#9AA6B4` | `#151C27` | 6.92 | 4.5 | ok |
| muted em surface-2 | `#9AA6B4` | `#1A2230` | 6.45 | 4.5 | ok |
| muted em surface-3 (chip neutro) | `#9AA6B4` | `#212B3A` | 5.77 | 4.5 | ok |
| muted no fundo da página | `#9AA6B4` | `#0E131B` | 7.53 | 4.5 | ok |
| faint (dicas, rodapé, versão) em cartão | `#8B99A9` | `#151C27` | 5.89 | 4.5 | ok |
| faint em surface-2 (sem imagem) | `#8B99A9` | `#1A2230` | 5.49 | 4.5 | ok |
| faint no fundo da página | `#8B99A9` | `#0E131B` | 6.41 | 4.5 | ok |
| link em cartão | `#8FB5EC` | `#151C27` | 8.14 | 4.5 | ok |
| link no fundo da página | `#8FB5EC` | `#0E131B` | 8.86 | 4.5 | ok |
| accent ('jats' da marca) em topbar | `#4CC5A2` | `#151C27` | 8.00 | 4.5 | ok |
| brand-ink em brand (botão primário, ícone do status) | `#FFFFFF` | `#3A6FBF` | 4.99 | 4.5 | ok |
| brand-ink em brand-2 (hover do botão) | `#FFFFFF` | `#3568B8` | 5.49 | 4.5 | ok |
| brand-text em brand-soft (nav ativo, passos, avatar) | `#9DC0F2` | `#1B2C48` | 7.50 | 4.5 | ok |
| brand-text em surface (seletor de tema) | `#9DC0F2` | `#151C27` | 9.17 | 4.5 | ok |
| crit-ink em crit-bg (chip, mensagem) | `#FFD3CE` | `#3B1D1B` | 11.22 | 4.5 | ok |
| warn-ink em warn-bg | `#FFDFA8` | `#3A2A0F` | 10.79 | 4.5 | ok |
| ok-ink em ok-bg | `#C6F0D6` | `#143324` | 11.01 | 4.5 | ok |
| info-ink em info-bg | `#D3E3FA` | `#1B2B45` | 10.92 | 4.5 | ok |
| texto no cartão de status 'pronto' (ok-bg 50%) | `#E9EEF4` | `#142826` | 13.22 | 4.5 | ok |
| text-2 no status 'pronto' | `#C3CCD7` | `#142826` | 9.51 | 4.5 | ok |
| texto no status 'não pronto' (crit-bg 40%) | `#E9EEF4` | `#241C22` | 14.24 | 4.5 | ok |
| text-2 no status 'não pronto' | `#C3CCD7` | `#241C22` | 10.23 | 4.5 | ok |
| texto digitado em campo bloqueante (crit-bg 45%) | `#E9EEF4` | `#261C22` | 14.16 | 4.5 | ok |
| texto em seleção (brand-soft-2) | `#E9EEF4` | `#213858` | 10.16 | 4.5 | ok |
| texto em brand-soft (dropzone em hover) | `#E9EEF4` | `#1B2C48` | 12.00 | 4.5 | ok |
| muted em brand-soft (dropzone em hover) | `#9AA6B4` | `#1B2C48` | 5.66 | 4.5 | ok |
| crit como texto ('vermelho', botão danger) no fundo | `#F08A80` | `#0E131B` | 7.67 | 4.5 | ok |
| warn como texto ('laranja') no fundo | `#F2B95F` | `#0E131B` | 10.54 | 4.5 | ok |
| crit-ink em crit-bg (hover do botão danger) | `#FFD3CE` | `#3B1D1B` | 11.22 | 4.5 | ok |
| listra/borda crit em cartão | `#F08A80` | `#151C27` | 7.05 | 3.0 | ok |
| listra/borda warn em cartão | `#F2B95F` | `#151C27` | 9.68 | 3.0 | ok |
| listra/borda ok em cartão | `#6FD09A` | `#151C27` | 9.10 | 3.0 | ok |
| borda info | `#7FA8E6` | `#151C27` | 7.04 | 3.0 | ok |
| borda de campo e botão (border-strong) em cartão | `#62708A` | `#151C27` | 3.43 | 3.0 | ok |
| borda de campo em surface-2 (dropzone) | `#62708A` | `#1A2230` | 3.20 | 3.0 | ok |
| borda de foco (brand-2) em cartão | `#3568B8` | `#151C27` | 3.12 | 3.0 | ok |
| borda de foco no fundo | `#3568B8` | `#0E131B` | 3.39 | 3.0 | ok |
| ícone do seletor de tema (muted) em surface-2 | `#9AA6B4` | `#1A2230` | 6.45 | 3.0 | ok |

Falhas: 0
