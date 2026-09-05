/*
 * Revisar e editar: visualizador do arquivo original, seleção de trecho ligada ao campo,
 * inserção de tabela/imagem/quadro/diálogo/equação e prévia da grade das tabelas.
 *
 * O visualizador funciona como um leitor de PDF: a página vem renderizada em imagem e, por cima,
 * uma camada transparente com uma caixa por palavra, nas coordenadas do PDF. A imagem dá a aparência,
 * a camada de texto dá a seleção. Selecionar um trecho e clicar em "Aplicar" escreve o texto no campo
 * que estava sendo editado, sem digitar de novo.
 */
(function () {
  'use strict';
  var DOC = window.XMLJATS_DOC;
  if (!DOC) return;

  function $(sel, raiz) { return (raiz || document).querySelector(sel); }
  function $$(sel, raiz) { return Array.prototype.slice.call((raiz || document).querySelectorAll(sel)); }

  /* ------------------------------------------------------------------ abas do visualizador */
  $$('.visor-abas .aba').forEach(function (b) {
    b.addEventListener('click', function () {
      $$('.visor-abas .aba').forEach(function (x) { x.classList.toggle('ativa', x === b); });
      $$('.visor-corpo .painel').forEach(function (p) { p.classList.toggle('ativo', p.dataset.painel === b.dataset.aba); });
      var barra = $('.visor-barra'), busca = $('.visor-busca');
      var noPdf = b.dataset.aba === 'pdf';
      if (barra) barra.style.display = noPdf ? '' : 'none';
      if (busca) busca.style.display = noPdf ? '' : 'none';
      // a prévia só é gerada quando alguém abre a aba: é o validador oficial rodando por trás
      if (b.dataset.aba === 'previa') {
        var q = $('#quadro-previa');
        if (q && !q.src) q.src = '/doc/' + DOC + '/previa';
      }
    });
  });

  /* ------------------------------------------------------------------ páginas do PDF */
  var caixa = $('#pdf-paginas'), indice = null, escala = 1.0, atual = 1;

  function desenhaPagina(p) {
    var div = document.createElement('div');
    div.className = 'pdf-pagina';
    div.dataset.n = p.n;
    div.style.width = (p.largura * escala) + 'px';
    div.style.height = (p.altura * escala) + 'px';
    var img = document.createElement('img');
    img.src = '/doc/' + DOC + '/pagina/' + p.arquivo;
    img.alt = 'Página ' + p.n;
    img.loading = 'lazy';
    div.appendChild(img);
    var camada = document.createElement('div');
    camada.className = 'camada-texto';
    p.palavras.forEach(function (w) {
      var s = document.createElement('span');
      s.textContent = w[4] + ' ';
      s.style.left = (w[0] * escala) + 'px';
      s.style.top = (w[1] * escala) + 'px';
      s.style.height = ((w[3] - w[1]) * escala) + 'px';
      s.style.fontSize = ((w[3] - w[1]) * escala * 0.92) + 'px';
      camada.appendChild(s);
    });
    div.appendChild(camada);
    var rot = document.createElement('span');
    rot.className = 'pdf-num';
    rot.textContent = p.n;
    div.appendChild(rot);
    return div;
  }

  function redesenha() {
    if (!indice || !indice.paginas.length) return;
    caixa.innerHTML = '';
    var continua = $('#rolagem-continua').checked;
    var lista = continua ? indice.paginas : indice.paginas.filter(function (p) { return p.n === atual; });
    lista.forEach(function (p) { caixa.appendChild(desenhaPagina(p)); });
    $('#pg-conta').textContent = (continua ? indice.paginas.length + ' páginas' : atual + ' / ' + indice.paginas.length);
    if (indice.cortadas) {
      var m = document.createElement('p');
      m.className = 'small muted';
      m.style.padding = '12px';
      m.textContent = 'Mostrando as primeiras ' + indice.paginas.length + ' páginas; o PDF tem mais ' + indice.cortadas + '.';
      caixa.appendChild(m);
    }
  }

  function carrega() {
    fetch('/doc/' + DOC + '/paginas.json', { headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(function (j) {
        indice = j;
        if (!j.paginas || !j.paginas.length) {
          caixa.innerHTML = '<p class="small muted" style="padding:16px">' + (j.erro || 'Este documento não tem o arquivo original guardado.') + '</p>';
          return;
        }
        redesenha();
        if (busca.termo) buscaTexto(busca.termo);
      })
      .catch(function () {
        caixa.innerHTML = '<p class="small crit-text" style="padding:16px">Não consegui abrir o arquivo original. ' +
          'Tente recarregar a página; se persistir, use "Reprocessar" no resultado.</p>';
      });
  }
  carrega();

  $('#pg-ant').addEventListener('click', function () { if (atual > 1) { atual--; $('#rolagem-continua').checked = false; redesenha(); } });
  $('#pg-prox').addEventListener('click', function () { if (indice && atual < indice.paginas.length) { atual++; $('#rolagem-continua').checked = false; redesenha(); } });
  $('#zoom-mais').addEventListener('click', function () { escala = Math.min(2.4, escala + 0.15); redesenha(); pintaBusca(false); });
  $('#zoom-menos').addEventListener('click', function () { escala = Math.max(0.5, escala - 0.15); redesenha(); pintaBusca(false); });
  $('#rolagem-continua').addEventListener('change', function () { redesenha(); pintaBusca(false); });

  /* ------------------------------------------------------------------ seleção ligada ao campo */
  var ultimoCampo = null, barraSel = $('#visor-selecao'), seletor = $('#alvo-campo');

  function rotuloDe(el) {
    var lab = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
    var bloco = el.closest('.fs');
    var titulo = bloco ? $('header h2', bloco) : null;
    return ((titulo ? titulo.textContent + ' · ' : '') + (lab ? lab.textContent.replace('*', '').trim() : el.name));
  }

  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el.matches('#form-revisar input[type=text], #form-revisar input[type=date], #form-revisar input[type=number], #form-revisar textarea')) {
      ultimoCampo = el;
    }
  });

  function preencheSeletor() {
    var campos = $$('#form-revisar input[type=text], #form-revisar input[type=date], #form-revisar textarea');
    seletor.innerHTML = '';
    campos.forEach(function (c) {
      var o = document.createElement('option');
      o.value = c.name;
      o.textContent = rotuloDe(c);
      if (ultimoCampo && c.name === ultimoCampo.name) o.selected = true;
      seletor.appendChild(o);
    });
  }

  document.addEventListener('mouseup', function (e) {
    if (!e.target.closest || !e.target.closest('.camada-texto')) return;
    var txt = (window.getSelection() || '').toString().replace(/\s+/g, ' ').trim();
    if (!txt) { barraSel.hidden = true; return; }
    preencheSeletor();
    barraSel.hidden = false;
    barraSel.dataset.texto = txt;
    barraSel.querySelector('.small').textContent = 'Usar "' + (txt.length > 40 ? txt.slice(0, 40) + '…' : txt) + '" em:';
  });

  $('#fechar-selecao').addEventListener('click', function () { barraSel.hidden = true; });
  $('#aplicar-selecao').addEventListener('click', function () {
    var txt = barraSel.dataset.texto || '', nome = seletor.value;
    var campo = document.querySelector('#form-revisar [name="' + CSS.escape(nome) + '"]');
    if (!campo || !txt) return;
    if (campo.tagName === 'TEXTAREA' && campo.value.trim()) campo.value = campo.value.replace(/\s*$/, ' ') + txt;
    else campo.value = txt;
    campo.dispatchEvent(new Event('input', { bubbles: true }));
    var caixaCampo = campo.closest('.field');
    if (caixaCampo) { caixaCampo.classList.add('is-edit'); caixaCampo.classList.remove('is-block'); }
    campo.focus();
    campo.scrollIntoView({ block: 'center', behavior: 'smooth' });
    barraSel.hidden = true;
    window.getSelection().removeAllRanges();
  });


  /* ------------------------------------------------------------------ busca no documento
   * Percorre as palavras que vieram do PDF, junta o texto de cada página e procura ali. Comparação
   * sem acento e sem caixa, porque ninguém digita "jurisdição" com til numa busca rápida.
   */
  var busca = { termo: '', hits: [], atual: -1 };

  function semAcento(t) {
    return (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

  function indexaPagina(p) {
    if (p._indice) return p._indice;
    var texto = '', mapa = [];
    p.palavras.forEach(function (w, k) {
      var t = semAcento(w[4]);
      mapa.push({ ini: texto.length, fim: texto.length + t.length, palavra: k });
      texto += t + ' ';
    });
    p._indice = { texto: texto, mapa: mapa };
    return p._indice;
  }

  function buscaTexto(termo) {
    busca.termo = termo;
    busca.hits = [];
    busca.atual = -1;
    var alvo = semAcento(termo).trim();
    if (!indice || alvo.length < 2) { pintaBusca(); return; }
    indice.paginas.forEach(function (p) {
      var ix = indexaPagina(p), de = 0, achou;
      while ((achou = ix.texto.indexOf(alvo, de)) !== -1) {
        var primeira = null, ultima = null;
        ix.mapa.forEach(function (m) {
          if (m.fim > achou && m.ini < achou + alvo.length) {
            if (primeira === null) primeira = m.palavra;
            ultima = m.palavra;
          }
        });
        if (primeira !== null) busca.hits.push({ pagina: p.n, de: primeira, ate: ultima });
        de = achou + Math.max(1, alvo.length);
      }
    });
    if (busca.hits.length) busca.atual = 0;
    pintaBusca(true);
  }

  function pintaBusca(vaiParaOAtual) {
    $$('.camada-texto span.achado').forEach(function (e) { e.classList.remove('achado', 'atual'); });
    var conta = $('#busca-conta');
    if (conta) conta.textContent = busca.termo.trim().length < 2 ? '' :
      (busca.hits.length ? (busca.atual + 1) + ' de ' + busca.hits.length : 'nada encontrado');
    if (!busca.hits.length) return;
    busca.hits.forEach(function (h, n) {
      var pag = document.querySelector('.pdf-pagina[data-n="' + h.pagina + '"]');
      if (!pag) return;
      var spans = pag.querySelectorAll('.camada-texto span');
      for (var k = h.de; k <= h.ate && k < spans.length; k++) {
        spans[k].classList.add('achado');
        if (n === busca.atual) spans[k].classList.add('atual');
      }
    });
    if (vaiParaOAtual !== false) irParaHit();
  }

  function irParaHit() {
    var h = busca.hits[busca.atual];
    if (!h) return;
    if (!$('#rolagem-continua').checked && atual !== h.pagina) {
      atual = h.pagina;
      redesenha();
      pintaBusca(false);
    }
    var alvo = document.querySelector('.camada-texto span.atual');
    if (alvo) alvo.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  function andaBusca(passo) {
    if (!busca.hits.length) return;
    busca.atual = (busca.atual + passo + busca.hits.length) % busca.hits.length;
    pintaBusca();
  }

  var campoBusca = $('#busca-texto');
  if (campoBusca) {
    var atraso = null;
    campoBusca.addEventListener('input', function () {
      clearTimeout(atraso);
      atraso = setTimeout(function () { buscaTexto(campoBusca.value); }, 250);
    });
    campoBusca.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); andaBusca(e.shiftKey ? -1 : 1); }
      if (e.key === 'Escape') { campoBusca.value = ''; buscaTexto(''); }
    });
    $('#busca-prox').addEventListener('click', function () { andaBusca(1); });
    $('#busca-ant').addEventListener('click', function () { andaBusca(-1); });
  }

  /* ------------------------------------------------------------------ completar pelo DOI (Crossref) */
  var ROTULO_CAMPO = {
    titulo_0_texto: 'Título', volume: 'Volume', numero: 'Número', doi: 'DOI', ano: 'Ano',
    licenca: 'Licença', data_publicado: 'Data de publicação', resumo_0_texto: 'Resumo', paginas: 'Páginas'
  };

  function escapa(t) { var d = document.createElement('div'); d.textContent = t == null ? '' : t; return d.innerHTML; }

  function aplicaCampo(nome, valor) {
    var el = document.querySelector('#form-revisar [name="' + CSS.escape(nome) + '"]');
    if (!el) return false;
    el.value = valor;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    var caixa = el.closest('.field');
    if (caixa) { caixa.classList.add('is-edit'); caixa.classList.remove('is-block'); }
    return true;
  }

  var botaoDoi = $('#doi-buscar'), saidaDoi = $('#doi-saida');
  if (botaoDoi) {
    botaoDoi.addEventListener('click', function () {
      var doi = (document.getElementById('doi') || {}).value || '';
      botaoDoi.disabled = true; botaoDoi.textContent = 'Consultando…';
      saidaDoi.hidden = false;
      saidaDoi.innerHTML = '<p class="small muted">Consultando o Crossref…</p>';
      fetch('/doc/' + DOC + '/doi?numero=' + encodeURIComponent(doi), { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          botaoDoi.disabled = false; botaoDoi.textContent = 'Buscar no Crossref';
          var h = '<p class="small ' + (j.ok ? '' : 'crit-text') + '">' + escapa(j.mensagem) + '</p>';
          if (j.ok) {
            h += '<table class="tbl mini doi-tabela"><thead><tr><th>Campo</th><th>O que o Crossref tem</th><th></th></tr></thead><tbody>';
            Object.keys(j.campos || {}).forEach(function (k) {
              if (!document.querySelector('#form-revisar [name="' + CSS.escape(k) + '"]')) return;
              var atual = (document.querySelector('#form-revisar [name="' + CSS.escape(k) + '"]') || {}).value || '';
              var igual = semAcento(atual).trim() === semAcento(j.campos[k]).trim();
              h += '<tr><td>' + escapa(ROTULO_CAMPO[k] || k) + '</td><td class="small">' + escapa(String(j.campos[k]).slice(0, 160)) +
                '</td><td>' + (igual ? '<span class="chip ok">já igual</span>' :
                  '<button class="btn small" type="button" data-aplica="' + escapa(k) + '">aplicar</button>') + '</td></tr>';
            });
            (j.autores || []).forEach(function (a, n) {
              var alvo = document.querySelector('#form-revisar [name="autor_' + n + '_orcid"]');
              if (!alvo || !a.orcid) return;
              var igual = (alvo.value || '').indexOf(a.orcid) >= 0;
              h += '<tr><td>ORCID de ' + escapa((a.nomes || '') + ' ' + (a.sobrenome || '')) + '</td><td class="mono small">' + escapa(a.orcid) +
                '</td><td>' + (igual ? '<span class="chip ok">já igual</span>' :
                  '<button class="btn small" type="button" data-aplica="autor_' + n + '_orcid" data-valor="' + escapa(a.orcid) + '">aplicar</button>') + '</td></tr>';
            });
            h += '</tbody></table><p class="small"><button class="btn small primary" type="button" id="doi-aplica-tudo">Aplicar tudo que falta</button> ' +
              '<span class="faint">Nada é gravado até você salvar.</span></p>';
          }
          saidaDoi.innerHTML = h;
          saidaDoi.dataset.campos = JSON.stringify(j.campos || {});
          $$('[data-aplica]', saidaDoi).forEach(function (b) {
            b.addEventListener('click', function () {
              var nome = b.dataset.aplica;
              var valor = b.dataset.valor !== undefined ? b.dataset.valor : (j.campos || {})[nome];
              if (aplicaCampo(nome, valor)) { b.outerHTML = '<span class="chip ok">aplicado</span>'; }
            });
          });
          var tudo = $('#doi-aplica-tudo');
          if (tudo) tudo.addEventListener('click', function () {
            $$('[data-aplica]', saidaDoi).forEach(function (b) { b.click(); });
          });
        })
        .catch(function () {
          botaoDoi.disabled = false; botaoDoi.textContent = 'Buscar no Crossref';
          saidaDoi.innerHTML = '<p class="small crit-text">Não consegui falar com o Crossref agora.</p>';
        });
    });
  }

  /* ------------------------------------------------------------------ conferir ORCID no orcid.org */
  $$('[data-confere-orcid]').forEach(function (b) {
    b.addEventListener('click', function () {
      var i = b.dataset.confereOrcid;
      var campo = document.getElementById('autor_' + i + '_orcid');
      var saida = document.getElementById('orcid-saida-' + i);
      if (!campo || !saida) return;
      if (!(campo.value || '').trim()) { saida.innerHTML = '<span class="crit-text">Preencha o ORCID primeiro.</span>'; return; }
      b.disabled = true; saida.innerHTML = '<span class="muted">consultando o orcid.org…</span>';
      fetch('/orcid?numero=' + encodeURIComponent(campo.value) + '&nome=' + encodeURIComponent(b.dataset.nome || ''),
        { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          b.disabled = false;
          var classe = (j.existe && j.confere !== false) ? 'ok-text' : 'crit-text';
          saida.innerHTML = '<span class="' + classe + '">' + escapa(j.mensagem) + '</span>';
        })
        .catch(function () { b.disabled = false; saida.innerHTML = '<span class="crit-text">Não consegui consultar agora.</span>'; });
    });
  });

  /* ------------------------------------------------------------------ inserir itens novos */
  var MOLDES = {
    titulo: function (n) {
      return bloco(n, 'Título traduzido ' + (n + 1), [txt('titulo_' + n + '_texto', 'Título'), sel('titulo_' + n + '_idioma', 'Idioma')], 'titulo');
    },
    autor: function (n) {
      return bloco(n, 'Autor ' + (n + 1), [txt('autor_' + n + '_sobrenome', 'Sobrenome'), txt('autor_' + n + '_nomes', 'Nomes'),
        txt('autor_' + n + '_orcid', 'ORCID'), txt('autor_' + n + '_email', 'E-mail'),
        txt('autor_' + n + '_affs', 'Afiliações (ids separados por vírgula)')], 'autor');
    },
    aff: function (n) {
      return bloco(n, 'Afiliação ' + (n + 1), [txt('aff_' + n + '_id', 'Id (aff1, aff2…)'), txt('aff_' + n + '_instituicao', 'Instituição'),
        txt('aff_' + n + '_divisao', 'Divisão'), txt('aff_' + n + '_cidade', 'Cidade'), txt('aff_' + n + '_pais_iso', 'País (ISO)')], 'aff');
    },
    resumo: function (n) {
      return bloco(n, 'Resumo ' + (n + 1), [sel('resumo_' + n + '_idioma', 'Idioma'), txt('resumo_' + n + '_kw', 'Palavras-chave (separadas por ;)'),
        ta('resumo_' + n + '_texto', 'Texto do resumo', 5)], 'resumo');
    },
    tabela: function (n) {
      return bloco(n, 'Tabela nova', [txt('tabela_' + n + '_rotulo', 'Rótulo (Tabela 1)'), txt('tabela_' + n + '_legenda', 'Legenda'),
        txt('tabela_' + n + '_cabecalho', 'Linhas de cabeçalho', '1'),
        ta('tabela_' + n + '_celulas', 'Conteúdo (uma linha por linha, colunas separadas por |)', 6, true),
        txt('tabela_' + n + '_fonte', 'Fonte'), previa('tabela_' + n + '_celulas')], 'tabela');
    },
    figura: function (n) {
      return bloco(n, 'Figura nova', [txt('figura_' + n + '_rotulo', 'Rótulo (Figura 1)'), txt('figura_' + n + '_legenda', 'Legenda'),
        txt('figura_' + n + '_fonte', 'Fonte'), envio(n)], 'figura');
    },
    equacao: function (n) {
      return bloco(n, 'Equação nova', [txt('equacao_' + n + '_rotulo', 'Rótulo ((1))'),
        ta('equacao_' + n + '_latex', 'LaTeX da fórmula', 3, true)], 'equacao');
    },
    quadro: function (n) {
      return bloco(n, 'Quadro novo', [txt('quadro_' + n + '_rotulo', 'Rótulo (Quadro 1)'), txt('quadro_' + n + '_legenda', 'Legenda'),
        ta('quadro_' + n + '_texto', 'Conteúdo (um parágrafo por linha)', 4)], 'quadro');
    },
    fomento: function (n) {
      return bloco(n, 'Fonte de fomento', [txt('fomento_' + n + '_fonte', 'Agencia ou fonte'),
        txt('fomento_' + n + '_processo', 'Numero do processo')], 'fomento');
    },
    dialogo: function (n) {
      return bloco(n, 'Diálogo novo', [txt('dialogo_' + n + '_rotulo', 'Rótulo (Diálogo 1)'), txt('dialogo_' + n + '_legenda', 'Legenda'),
        ta('dialogo_' + n + '_turnos', 'Falas, uma por linha: "Falante: fala"', 5)], 'dialogo');
    }
  };
  var IDIOMAS = ['pt', 'en', 'es', 'fr', 'it', 'de'];

  function campoHTML(interno, rotulo, id) {
    return '<div class="field" id="f-' + id + '"><label for="' + id + '">' + rotulo + '</label>' + interno + '</div>';
  }
  function txt(nome, rotulo, valor) {
    return campoHTML('<input id="' + nome + '" name="' + nome + '" type="text" value="' + (valor || '') + '">', rotulo, nome);
  }
  function ta(nome, rotulo, linhas, mono) {
    return campoHTML('<textarea id="' + nome + '" name="' + nome + '" rows="' + linhas + '"' + (mono ? ' class="mono"' : '') + '></textarea>', rotulo, nome);
  }
  function sel(nome, rotulo) {
    var op = '<option value="">—</option>' + IDIOMAS.map(function (i) { return '<option value="' + i + '">' + i + '</option>'; }).join('');
    return campoHTML('<select id="' + nome + '" name="' + nome + '">' + op + '</select>', rotulo, nome);
  }
  function previa(nome) { return '<div class="previa" data-previa-de="' + nome + '"></div>'; }
  function envio(n) {
    return '<div class="field"><label>Imagem</label><div class="row" style="gap:8px">' +
      '<span class="small muted">nenhuma — salve o rascunho antes de enviar a imagem</span></div></div>';
  }
  function bloco(n, titulo, partes, grupo) {
    return '<div class="bloco anexo novo"><div class="row between"><b>' + titulo + '</b>' +
      '<label class="check remover"><input type="checkbox" name="' + grupo + '_' + n + '_remover" value="1"> remover</label></div>' +
      partes.join('') + '</div>';
  }

  $$('[data-add]').forEach(function (botao) {
    botao.addEventListener('click', function () {
      var grupo = botao.dataset.add, area = botao.closest('[data-grupo]'), destino = $('.novos', area);
      var proximo = parseInt(area.dataset.inicio, 10) + $$('.bloco.novo', area).length;
      destino.insertAdjacentHTML('beforeend', MOLDES[grupo](proximo));
      var criado = destino.lastElementChild;
      ligaPrevias(criado);
      var primeiro = criado.querySelector('input, textarea, select');
      if (primeiro) primeiro.focus();
      criado.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  });

  /* ------------------------------------------------------------------ CRediT: caixas viram um campo só
   * O XML guarda os termos numa lista; a tela mostra caixas. Este trecho mantém as duas coisas iguais.
   */
  function sincronizaCredit(i) {
    var marcadas = $$('input[name="autor_' + i + '_credit_item"]:checked').map(function (c) { return c.value; });
    var alvo = document.getElementById('credit-' + i);
    if (alvo) alvo.value = marcadas.join(', ');
  }
  $$('input[data-autor]').forEach(function (c) {
    c.addEventListener('change', function () { sincronizaCredit(c.dataset.autor); });
  });

  /* ------------------------------------------------------------------ prévia da grade da tabela */
  function desenhaPrevia(alvo) {
    var nome = alvo.dataset.previaDe;
    var campo = document.querySelector('[name="' + CSS.escape(nome) + '"]');
    if (!campo) return;
    var linhas = campo.value.split('\n').filter(function (l) { return l.trim(); });
    if (!linhas.length) { alvo.innerHTML = '<p class="small muted">A prévia da tabela aparece aqui.</p>'; return; }
    var cabecalho = parseInt((document.querySelector('[name="' + CSS.escape(nome.replace('_celulas', '_cabecalho')) + '"]') || {}).value || '0', 10);
    var html = '<div class="tblwrap"><table class="tbl mini">';
    linhas.forEach(function (l, i) {
      var sep = l.indexOf('\t') >= 0 ? '\t' : '|';
      var cels = l.split(sep).map(function (c) { return c.trim(); });
      var tag = i < cabecalho ? 'th' : 'td';
      html += '<tr>' + cels.map(function (c) {
        var d = document.createElement('div'); d.textContent = c;
        return '<' + tag + '>' + d.innerHTML + '</' + tag + '>';
      }).join('') + '</tr>';
    });
    alvo.innerHTML = html + '</table></div>';
  }
  function ligaPrevias(raiz) {
    $$('.previa', raiz || document).forEach(function (alvo) {
      var nome = alvo.dataset.previaDe;
      var campo = document.querySelector('[name="' + CSS.escape(nome) + '"]');
      if (!campo || campo.dataset.previaLigada) return;
      campo.dataset.previaLigada = '1';
      campo.addEventListener('input', function () { desenhaPrevia(alvo); });
      var cab = document.querySelector('[name="' + CSS.escape(nome.replace('_celulas', '_cabecalho')) + '"]');
      if (cab) cab.addEventListener('input', function () { desenhaPrevia(alvo); });
      desenhaPrevia(alvo);
    });
  }
  ligaPrevias();

  /* ------------------------------------------------------------------ envio de imagem de figura */
  var formFig = $('#form-figura'), inputFig = $('#figura-arquivo');
  $$('[data-envia-figura]').forEach(function (b) {
    b.addEventListener('click', function () {
      $('#figura-indice').value = b.dataset.enviaFigura;
      formFig.action = '/doc/' + DOC + '/figura';
      inputFig.click();
    });
  });
  if (inputFig) inputFig.addEventListener('change', function () { if (inputFig.files.length) formFig.submit(); });

  /* ------------------------------------------------------------------ revista pelo ISSN */
  var selRev = $('#revista'), boxIssn = $('#issn-box');
  if (selRev && boxIssn) {
    var campoIssn = $('#issn-numero'), botaoIssn = $('#issn-buscar'), saidaIssn = $('#issn-saida');
    function alternaIssn() { boxIssn.hidden = selRev.value !== ''; if (boxIssn.hidden) { saidaIssn.hidden = true; saidaIssn.innerHTML = ''; } }
    selRev.addEventListener('change', alternaIssn); alternaIssn();
    function esc(t) { var d = document.createElement('div'); d.textContent = t == null ? '' : t; return d.innerHTML; }
    botaoIssn.addEventListener('click', function () {
      var n = (campoIssn.value || '').trim();
      if (!n) { campoIssn.focus(); return; }
      botaoIssn.disabled = true; botaoIssn.textContent = 'Consultando…';
      saidaIssn.hidden = false; saidaIssn.innerHTML = '<p class="small muted">Consultando as bases de ISSN…</p>';
      fetch('/revistas/consulta?numero=' + encodeURIComponent(n), { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          botaoIssn.disabled = false; botaoIssn.textContent = 'Buscar nas bases';
          var h = '<p class="small ' + (j.ok ? '' : 'crit-text') + '">' + esc(j.mensagem) + '</p>';
          if (j.fontes && j.fontes.length) {
            h += '<ul class="issn-fontes">' + j.fontes.map(function (f) {
              return '<li><span class="chip ' + (f.ok ? 'ok' : 'neutral') + '">' + (f.ok ? 'ok' : 'sem') + '</span> <b>' +
                esc(f.fonte) + '</b> <span class="faint">' + esc(f.mensagem) + '</span></li>';
            }).join('') + '</ul>';
          }
          if (j.ok && j.cadastrada) h += '<p class="small"><button class="btn small" type="button" id="issn-usar">Usar esta revista</button></p>';
          else if (j.ok) h += '<p class="small"><button class="btn small primary" type="submit" form="form-importa-issn">Cadastrar e usar</button></p>';
          saidaIssn.innerHTML = h;
          var usar = $('#issn-usar');
          if (usar) usar.addEventListener('click', function () { selRev.value = j.acronimo; alternaIssn(); });
          $('#issn-importa-numero').value = j.issn || n;
        })
        .catch(function () {
          botaoIssn.disabled = false; botaoIssn.textContent = 'Buscar nas bases';
          saidaIssn.innerHTML = '<p class="small crit-text">Não consegui falar com as bases agora.</p>';
        });
    });
  }

  /* ------------------------------------------------------------------ ir para a primeira pendência */
  var primeiraFalta = $('#form-revisar .field.is-block');
  if (primeiraFalta && location.hash === '') {
    var ir = document.createElement('button');
    ir.type = 'button';
    ir.className = 'btn small';
    ir.textContent = 'Ir para o primeiro campo em falta';
    ir.addEventListener('click', function () {
      primeiraFalta.scrollIntoView({ block: 'center', behavior: 'smooth' });
      var c = primeiraFalta.querySelector('input, textarea, select');
      if (c) c.focus();
    });
    var alvo = $('.pendencias');
    if (alvo) alvo.appendChild(ir);
  }
})();
