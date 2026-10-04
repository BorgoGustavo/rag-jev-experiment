# RAG por raciocínio com navegador barato: LC 214/2025

Pergunta de pesquisa: dá para baratear o RAG por raciocínio (estilo PageIndex) trocando o LLM
que navega na árvore por um modelo de decisão barato (Jev, TypeSafe AI) sem perder precisão?
Contexto completo e regras de trabalho em `CLAUDE.md`.

## Decisões de desenho (e por quê)

| Decisão | Escolha | Motivo |
|---|---|---|
| Documento | LC 214/2025 compilada (Planalto, com LC 227/2026), HTML → `artigos.json` | Hierarquia explícita dá gabarito limpo por artigo; é o tipo de documento que o PageIndex atende na prática |
| PDF para o PageIndex | HTML compilado limpo impresso pelo Chrome **com outline (bookmarks)** | Sem outline o detector de layout achatava Capítulos no nível 1; com outline o PageIndex usa os bookmarks como moldura (`toc_source: bookmarks`), como faria com um PDF oficial bem formatado. Modo puramente detectado (`use_embedded_toc=False`) fica como experimento opcional no fim |
| Texto lido nas folhas (B, C, D) | Artigos inteiros do `artigos.json` cobertos pela folha | Mesmo conteúdo que A indexa; evita fragmentos de artigos vizinhos nas bordas de página. Pequeno favor às configurações de árvore em relação ao PDF cru, registrado |
| Atribuição artigo → folha | Pela posição do início da folha no texto da página; cada artigo pertence a exatamente uma folha | Por intervalo de páginas, um artigo caía em duas folhas vizinhas |
| Folhas-ruído | Mantidas (alíneas que o detector tomou por cabeçalho) | É comportamento do PageIndex; o relatório conta quantas são e quantas perguntas têm gabarito nelas |
| Folhas grandes | Primeiro o `optimize="full"` (expand) do PageIndex; só intervimos se sobrar folha > 4.000 tokens, com subtítulos sintéticos no PDF, registrados aqui | Fidelidade ao pipeline antes de qualquer intervenção nossa |
| Custo | Sempre do `usage` devolvido pela API (Anthropic, OpenAI, TypeSafe, LiteLLM) | Tokenizer local só para estatística |
| Resposta final | Mesmo modelo (`gerador_resposta`) e mesmo prompt (`src/prompts.py`) em A, B, C, D | Só o contexto recuperado varia |

## Intervenções no documento

1. Limpeza do HTML antes de imprimir o PDF: texto tachado, anotações do Planalto e anexos da LC 227 removidos.
2. Folhas da árvore com 0 artigos (nós "(intro)" e alíneas-ruído que começam no meio de um artigo) não são
   mostradas ao navegador: o resumo delas vem do texto da página e descreveria um artigo que pertence à folha
   anterior, levando a um trecho vazio. A quantidade ocultada está no `arvore_relatorio.md`. Elas continuam no
   `arvore.json`.
3. Subtítulos sintéticos (critério: folha > 4.000 tokens depois do expand; grupos de artigos de até ~2.500 tokens,
   nunca dividindo artigo; artigo sozinho > 4.000 vira folha própria). Inseridos nos blocos de origem
   (`scripts/gerar_pdf.py`, `DIVIDIR`), portanto valem para o PDF e para o Markdown:
   - Seção VII Da Sujeição Passiva (Tít. I, Cap. II): "Arts. 21 a 23", "Arts. 24 a 25", "Art. 26"
   - Capítulo I Da Zona Franca de Manaus (Livro III, Tít. I): "Arts. 439 a 448", "Arts. 449 a 456", "Art. 457"
   - Título IV Disposições Finais (Livro III): "Arts. 491 a 501", "Arts. 502 a 512", "Arts. 513 a 516",
     "Art. 517" (exceção: 4.116 tokens sozinho), "Arts. 518 a 531", "Arts. 532 a 541", "Art. 542", "Arts. 543 a 544"
   Perguntas com gabarito nessas folhas: q25 (art_445, art_442), q27 (art_544), q32 (art_21).

## Variantes de árvore

- `data/index/arvore.json`: PageIndex flash, resumos escritos pelo gpt-5.6-luna a partir do texto das
  **páginas** do nó (podem descrever seções vizinhas na mesma página).
- `data/index/arvore_pageindex_md.json`: PageIndex em **modo Markdown** (`md_to_tree`), sobre o Markdown gerado
  dos mesmos blocos limpos (um nível de cabeçalho por nível da lei). Resumos do próprio pipeline (gpt-5.6-luna),
  por nó, a partir do texto do nó; folhas com menos de 200 tokens usam o próprio texto como resumo; nós internos
  recebem `prefix_summary` (texto antes do primeiro filho). Exceção autorizada à regra de economia de API (~US$ 0,08).
  Script: `src/gerar_arvore_md.py`.
- `data/index/arvore_resumo_por_no.json`: variante explorada e **fora das rodadas completas**: resumos escritos
  manualmente, sem API, a partir dos artigos de cada folha. Ficaram com metade do tamanho dos do PageIndex
  (mediana 81 contra 153 palavras), o que distorceria a comparação de custo. Script: `scripts/resumos_por_no.py`.

## Observações registradas

- Árvore markdown: os nós internos têm só `prefix_summary` (texto antes do primeiro filho, em geral o
  próprio título), comportamento documentado do `md_to_tree`. No teste de fumaça (C, 3 perguntas) o navegador
  desviou mais nos níveis de cima (escolheu Título V antes do IV, Capítulo III antes do II) do que na árvore
  PDF, cujos internos têm resumo da subárvore. Não corrigido: faz parte do que se mede.
- Configuração D (Jev): modelagem M1 com seleção múltipla (`src/navegadores/jev.py`). Um `Choice` por passo
  com opções = filhos + `nenhum_destes` (voltar) + `ja_lido_basta` (suficiente, só quando há algo lido).
  Desce pela vencedora e por até 2 outros filhos com probabilidade >= 0,20 (corte fixado antes de qualquer
  teste, para dar ao Jev a mesma liberdade do LLM, que escolhe até 3). Confiança do passo =
  probabilidade da vencedora; o `confidence` do Jev fica registrado à parte. Escalonamento por passo para
  `navegador_grande` abaixo de `navigate.jev_confidence_threshold` (null = o Jev sempre decide).
- `navigate.max_tokens` era 256 nas rodadas da fase 1 e truncou saídas do navegador: em B, 4 de 160
  chamadas (q12, q14, q19, q32; q12 e q19 viraram abstenções); em C PDF, 146 de 490 (o Haiku explicava
  após o JSON). Corrigido para 1024 com "responda somente com o JSON" no prompt (o mesmo para B, C e para
  o escalonamento de D). Truncamento (`stop_reason`) e JSON ilegível agora viram passo `erro`, contado em
  `erros` no resultado, nunca "voltar" silencioso. B e C na árvore PDF serão rerodados; **C markdown não
  será rerodado** e seus números valem com `max_tokens: 256`.
- McNemar (recuperação, 40 perguntas, teste exato nos pares discordantes): B vs C significativo
  (9 x 0, p = 0,004); B vs A não significativo com 40 perguntas (8 x 2, p = 0,109).

- Navegação (B, C, D): o navegador desce um nível por vez e tende a parar na primeira folha que parece
  bastar ("suficiente"), o que pesa nas perguntas de referência cruzada (duas folhas distintas). É escolha do
  nosso desenho de busca (`src/config_arvore.py`), não do PageIndex, e não será alterada nesta rodada.
- Custo: mesmo com navegação de custo zero, o contexto maior enviado ao gerador (folhas inteiras, ~6k tokens
  contra ~2k dos 5 chunks de A) mantém a árvore mais cara por pergunta que o vetorial.

## Resultados (fase 2, árvore PDF, 40 perguntas, max_tokens 1024)

Recuperação = gabarito inteiro dentro do que foi lido. Resposta avaliada pelo agente, sem API, mesmo critério
em todas as configurações (`data/eval/avaliacao_respostas.json`; amostra de 12 para conferência manual, 3 por
config, em `data/eval/amostra_manual.md`). Custo por pergunta pelo usage das APIs em todas as linhas: as três
variantes de D tiveram respostas geradas (navegação feita uma vez por variante; respostas em
`results/D_limiar0_resp.jsonl`, `D_limiar0.7_resp.jsonl` e `D.jsonl`).

| Config | Recuperação | direta | cruzada | vocab. | Resposta correta | Abstenções | US$/pergunta | Lat. mediana | Passos | Escalonamento (passos de decisão) |
|---|---|---|---|---|---|---|---|---|---|---|
| A vetorial | 28/40 | 13/15 | 5/12 | 10/13 | 28 (+3 parciais) | 9 | 0,0064 | 2,7 s | - | - |
| B Opus | 37/40 | 15/15 | 9/12 | 13/13 | 39 (+1) | 0 | 0,1095 | 12,1 s | 6,3 | - |
| C Haiku | 26/40 | 13/15 | 4/12 | 9/13 | 28 (+4) | 8 | 0,0413 | 9,8 s | 8,6 | - |
| D Jev puro | 26/40 | 11/15 | 4/12 | 11/13 | 28 (+4) | 7 | 0,0100 | 3,6 s | 4,8 | 0% |
| D limiar 0,70 | 31/40 | 14/15 | 5/12 | 12/13 | 33 (+2) | 5 | 0,0327 | 5,4 s | 5,2 | 24% (21/40 perguntas) |
| D limiar 0,80 | 33/40 | 15/15 | 6/12 | 12/13 | 35 (+1) | 3 | 0,0470 | 7,2 s | 5,3 | 39% (30/40 perguntas) |

Gráfico custo por pergunta (log) x recuperação, custos reais: `results/custo_vs_acerto.png`.

Detalhe das variantes de D (navegação; `scripts/relatorio_fase2.py`):

| | Jev puro | limiar 0,70 | limiar 0,80 |
|---|---|---|---|
| Custo de navegação, TypeSafe | US$ 0,025 | US$ 0,026 | US$ 0,026 |
| Custo de navegação, Anthropic (Opus escalado) | 0 | US$ 0,874 | US$ 1,431 |
| Navegação por pergunta | US$ 0,0006 | US$ 0,0225 | US$ 0,0364 |
| Contexto ao gerador (usage, média / mediana) | 3.350 / 2.419 tok | 3.709 / 2.934 | 3.862 / 3.210 |
| Folhas lidas por pergunta | 1,4 | 1,5 | 1,6 |
| Término: esgotado / suficiente / suficiente por escalado | 32 / 8 / 0 | 30 / 9 / 1 | 29 / 9 / 2 |
| Seleção múltipla acionada | 27 passos | 5 | 0 |
| Jev disse nenhum_destes / ja_lido_basta | 4 / 8 | 1 / 9 | 1 / 9 |
| p da vencedora (Jev): p25 / mediana / p75 | 0,68 / 0,83 / 0,94 | 0,72 / 0,85 / 0,96 | 0,70 / 0,84 / 0,96 |

Nenhuma busca de D (nem de B) bateu em max_steps; C bateu 6 vezes. "Esgotado" domina porque o Jev quase sempre
desce por um único filho até a folha e a pilha esvazia; "suficiente" só aparece quando a seleção múltipla deixou
outro ramo pendente.

Navegação pelos logs (`logs/calls.jsonl`, rodadas completas da fase 2; só o navegador, sem gerador):

| Navegador | US$ por pergunta | Latência média da busca | Chamadas por pergunta | US$ por chamada | Latência por chamada |
|---|---|---|---|---|---|
| Jev puro | 0,00063 | 1,1 s | 3,5 | 0,00018 | 0,33 s |
| C Haiku | 0,0248 | 7,0 s | 5,5 | 0,0045 | 1,26 s |
| B Opus | 0,0969 | 9,6 s | 4,2 | 0,0227 | 2,26 s |

Por pergunta, o Jev navega 39 vezes mais barato e 6,5 vezes mais rápido que o Haiku, e 154 vezes mais barato
e 8,8 vezes mais rápido que o Opus. Por chamada: 25x e 3,8x contra o Haiku; 126x e 6,8x contra o Opus.

McNemar de recuperação (binomial exato nos pares discordantes, `scripts/mcnemar.py`), com o B rerodado:

| Comparação | Só o 1º acertou x só o 2º acertou | p |
|---|---|---|
| B vs A | 9 x 0 | 0,004 |
| B vs C | 11 x 0 | 0,001 |
| D Jev puro vs A | 4 x 6 | 0,754 |
| D Jev puro vs C | 5 x 5 | 1,000 |
| D 0,70 vs A | 6 x 3 | 0,508 |
| D 0,70 vs C | 6 x 1 | 0,125 |
| D 0,80 vs A | 7 x 2 | 0,180 |
| D 0,80 vs C | 7 x 0 | 0,016 |
| D 0,80 vs B | 0 x 4 | 0,125 |

Leitura: D com limiar 0,80 recupera 33/40 e responde 35 corretas por US$ 0,047 por pergunta, 43% do custo
de B (37/40, 39 corretas, US$ 0,110), e supera C (26/40) com significância pelo mesmo preço. Com 40 perguntas,
D 0,80 não se distingue de B (perde 4, p = 0,125) nem de A. O Jev puro custa US$ 0,0006 de navegação por
pergunta e empata com A e com C em recuperação (26 a 28 de 40), com respostas no mesmo nível (28 corretas),
por US$ 0,010 por pergunta. O que separa 26 de 33 acertos é o escalonamento ao Opus em 39% dos passos.

Observações da fase 2:
- B rerodado: 37/40 (fase 1: 34/40). q12 e q19, que eram abstenções por truncamento, agora acertam;
  0 truncamentos e 0 erros de navegação em 170 chamadas.
- **C rerodado: 26/40 (fase 1: 25/40). O Haiku passou a devolver só o JSON (~49 tokens), mas em 23 passos
  (16 perguntas) escolheu ids que não eram filhos do nó atual.** Esses passos contam como erro
  (`ids_invalidos`) e descartam o nó; o Opus e o Jev não erram assim (o Jev só pode escolher entre as opções
  do Choice).
- D: o Jev nunca descartou um ramo nem parou por conta própria quando só havia um ramo. Nas cruzadas
  (4 a 6 de 12) o padrão é o mesmo de B e C: lê a primeira folha e encerra.
- D lê contexto menor que B (3.350 a 3.862 contra 4.826 tokens) porque desce por um filho só.
- Latência total de D inclui o gerador (Sonnet, ~3 a 4 s); a busca em si leva 1,2 s no Jev puro.

## Como rodar

```
uv venv && uv pip install -r requirements.txt && cp .env.example .env   # preencher chaves
python3 src/parse.py                       # HTML -> data/processed/artigos.json + relatório
python3 scripts/validar_perguntas.py       # valida perguntas e gera data/eval/revisao.md
.venv/bin/python scripts/gerar_pdf.py      # PDF com outline
.venv/bin/python src/gerar_arvore.py       # árvore PageIndex com resumos (custo único)
.venv/bin/python src/config_a_vetorial.py --limit 3
.venv/bin/python src/config_arvore.py --config B --limit 3
.venv/bin/python src/config_arvore.py --config D --ids q01 q16 q28   # grava em results/D_fumaca.jsonl
```
