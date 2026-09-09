# python-mssql-performance

Benchmark reprodutível comparando **pyodbc** e **mssql-python** contra SQL Server
2022, em quatro cenários: query pontual, transporte de result set, concorrência e
escritas (INSERT/UPDATE/DELETE).

**Por que isto existe:** estamos escolhendo o driver para as nossas aplicações
Python contra SQL Server e queríamos medir no nosso próprio perfil de carga em vez
de decidir por intuição. Publicamos porque outras equipes têm a mesma dúvida — e
porque **queremos feedback sobre a configuração**: se alguma opção nossa está
subutilizando um dos drivers, o número está errado e queremos corrigi-lo. Veja
[Feedback que buscamos](#feedback-que-buscamos).

Não é um veredito sobre qual driver é melhor. É uma medição de um ambiente
específico, com o ambiente registrado junto dos números.

## Estrutura

```text
.
├── docker-compose.yml          # sqlserver + db-init (idempotente) + benchmark
├── sql/
│   ├── init.sql                # database + users (10 colunas) + users_writes
│   └── seed.sql                # 100k linhas (set-based) + índice de apoio
├── benchmark/
│   ├── Dockerfile              # python:3.12-slim + msodbcsql18
│   ├── requirements.txt
│   └── src/mssqlbench/
│       ├── __main__.py         # CLI
│       ├── config.py           # config via env + flags
│       ├── drivers.py          # adaptadores (name + connection factory)
│       ├── queries.py          # SQL dos cenários
│       ├── scenarios.py        # os 4 cenários
│       ├── stats.py            # percentis, QPS, rows/s, mediana entre execuções
│       ├── report.py           # tabelas + JSON/CSV + metadata do ambiente
│       ├── charts.py           # PNG (light + dark)
│       └── runner.py           # orquestração
└── results/                    # saída: results.json, results.csv, PNGs
```

Cada driver é reduzido a `(nome, connection_factory)`, então os cenários nunca
fazem `if driver == ...`. Adicionar um terceiro driver (ex.: `pymssql`) é registrar
uma factory em `drivers.py` — nada mais muda.

## Rodar

```bash
docker compose up -d --wait sqlserver
```

```bash
docker compose run --rm db-init
```

```bash
docker compose run --rm --no-deps benchmark --repeat 3
```

`db-init` é idempotente (`init.sql` recria as tabelas), então pode rodar de novo a
qualquer momento. O seed é set-based: 100k linhas em segundos.

### Opções

```bash
docker compose run --rm --no-deps benchmark --scenarios concurrency --workers 1,10,50,200 --concurrency-seconds 15
```

| Flag | Env | Default |
|---|---|---|
| `--drivers` | — | `pyodbc,mssql-python` |
| `--scenarios` | — | `point_select,result_set,concurrency,write_ops` |
| `--repeat` | — | 1 (reporta a mediana por métrica) |
| `--point-iterations` | `BENCH_POINT_ITERATIONS` | 10000 |
| `--result-set-sizes` | `BENCH_RESULT_SET_SIZES` | 100,1000,10000 |
| `--result-set-iterations` | `BENCH_RESULT_SET_ITERATIONS` | 200 |
| `--write-iterations` | `BENCH_WRITE_ITERATIONS` | 5000 |
| `--write-batch-size` | `BENCH_WRITE_BATCH_SIZE` | 1000 |
| `--write-commit-modes` | `BENCH_WRITE_COMMIT_MODES` | `autocommit,transaction` |
| `--workers` | `BENCH_WORKER_LEVELS` | 1,5,10,25,50,100 |
| `--concurrency-seconds` | `BENCH_CONCURRENCY_SECONDS` | 5 |
| `--output-dir` | `BENCH_OUTPUT_DIR` | `/results` |
| `--replot results.json` | — | regera só os gráficos |
| — | `DB_PYODBC_POOLING` | `true` (pooling do Driver Manager ODBC) |

No Git Bash, prefixe com `MSYS_NO_PATHCONV=1` ao passar caminhos absolutos do
container (ex.: `--replot /results/results.json`), senão o shell os converte.

## Cenários

1. **Point select** — `WHERE id = ?`, uma conexão, ids aleatórios com seed fixa.
   Isola overhead por statement: bind, round trip, materialização de 1 linha.
2. **Result set** — `TOP {100,1000,10000}` drenado com `fetchall()`. Mede
   transporte e conversão para objetos Python (`rows/s` é a métrica que importa).
3. **Concorrência** — N workers, cada um com sua própria conexão, executando point
   selects por uma janela fixa de tempo. Conexões e warmup acontecem **antes** do
   cronômetro (barrier), então setup não entra na medição.
4. **Writes** — INSERT (linha a linha, `executemany` e `bulkcopy`), UPDATE e
   DELETE contra `dbo.users_writes` (tabela separada, então os cenários de leitura
   sempre veem as mesmas 100k linhas). Roda em **dois modos de commit**:
   `autocommit` (um commit por statement) e `transaction` (commit a cada 1000).

Sobre caminhos de batch: `fast_executemany` do pyodbc é ligado quando o driver o
expõe, e `cursor.bulkcopy()` do mssql-python é medido como linha própria. As duas
aparecem no relatório porque comparar só `executemany` esconderia metade da
história — cada driver tem um caminho nativo diferente para carga em massa.

## Resultados desta máquina

Mediana de **3 execuções** (`--repeat 3`). Ambiente registrado em
`results/results.json` → `metadata`: SQL Server 2022 CU26 (Developer, 32 vCPU
visíveis, 12,4 GB) em container sobre Docker Desktop/WSL2, cliente
`python:3.12-slim` no mesmo host, pyodbc 5.3.0 + `ODBC Driver 18`,
mssql-python 1.14.0, 100k linhas.

![benchmark](results/benchmark-light.png)

### Leituras

| Cenário | pyodbc | mssql-python | relativo |
|---|---|---|---|
| Point select | 5.560 qps · p95 0,248 ms | 3.719 qps · p95 0,343 ms | 0,67x |
| TOP 100 | 199.851 rows/s | 193.374 rows/s | 0,97x |
| TOP 1000 | 344.344 rows/s | 528.020 rows/s | **1,53x** |
| TOP 10000 | 350.226 rows/s | 574.965 rows/s | **1,64x** |
| 1 worker | 5.663 qps | 3.887 qps | 0,69x |
| 10 workers | 1.357 qps | 7.170 qps | **5,28x** |
| 100 workers | 1.338 qps · p95 88,5 ms | 6.797 qps · p95 44,0 ms | **5,08x** |

### Escritas (5.000 linhas por fase, `rows/s`)

| Operação | commit | pyodbc | mssql-python | relativo |
|---|---|---|---|---|
| INSERT linha a linha | autocommit | 659 | 704 | 1,07x |
| INSERT executemany | autocommit | 920 | 871 | 0,95x |
| UPDATE by id | autocommit | 855 | 741 | 0,87x |
| DELETE by id | autocommit | 825 | 867 | 1,05x |
| INSERT linha a linha | tx/1000 | 5.596 | 4.813 | 0,86x |
| INSERT executemany | tx/1000 | **92.888** | 56.261 | 0,61x |
| UPDATE by id | tx/1000 | 6.483 | 5.687 | 0,88x |
| DELETE by id | tx/1000 | 6.911 | 5.776 | 0,84x |
| **INSERT bulkcopy** | tx/1000 | *não existe na API* | **121.170** | — |

### O que lemos nesses números

- **Single-thread, query pequena: pyodbc à frente.** ~1,5x mais QPS no point
  select. Em `TOP 100` os dois empatam (0,97x) — e vale registrar que numa
  execução única isso aparecia como 0,61x. A mediana de 3 mudou a conclusão, o que
  é o próprio argumento a favor de `--repeat`.
- **Result set grande: mssql-python à frente,** e a vantagem cresce com o tamanho
  (1,53x em 1k, 1,64x em 10k).
- **Escritas: o commit domina, não o driver.** Em autocommit tudo converge para
  ~650–900 rows/s e as diferenças ficam dentro do ruído nas duas direções
  (1,07x / 0,87x) — cada statement paga um flush do log. Em transação explícita a
  mesma carga sai ~7x mais rápida e o driver volta a importar.
- **Carga em massa: cada driver ganha no seu próprio caminho.** Comparando as
  *mesmas* APIs, `executemany` fica com o pyodbc (92.888 vs 56.261 rows/s), porque
  `fast_executemany` faz batch real no protocolo e o mssql-python não expõe esse
  atributo (registrado como `fast_executemany: false` no JSON). Mas o caminho
  nativo do mssql-python, `cursor.bulkcopy()`, entrega **121.170 rows/s** — 1,3x o
  melhor número do pyodbc, que não tem equivalente na API. Comparar apenas
  `executemany` favoreceria o pyodbc por omissão; é por isso que as duas linhas
  estão na tabela.
- **Concorrência: não é comparação, é um teto.** pyodbc *piora* com carga —
  5.663 qps com 1 worker cai para ~1.350 qps de 10 workers em diante, com p95
  crescendo linearmente (88 ms em 100 workers). O platô fixo com latência linear é
  a assinatura de um ponto de serialização, não de saturação do servidor:
  mssql-python, no mesmo servidor, sustenta ~6.800–7.200 qps em todos os níveis.

### Investigando o platô do pyodbc

Duas hipóteses foram testadas neste ambiente:

**1. Connection pooling do ODBC** (`pyodbc.pooling = True` é o default) — exposto
como `DB_PYODBC_POOLING=false`:

```bash
docker compose run --rm --no-deps -e DB_PYODBC_POOLING=false benchmark --drivers pyodbc --scenarios concurrency --workers 1,10,50,100
```

Resultado: **não é a causa.** O platô fica idêntico (1.338 qps com 10 workers,
1.299 com 100, p95 92 ms).

**2. O limite é por processo ou do servidor?** Dois containers pyodbc rodando 10
workers *ao mesmo tempo*:

```text
processo A: 1.186 qps
processo B: 1.258 qps
   total:  ~2.444 qps  (vs ~1.300 qps de um processo só)
```

Dobrar processos praticamente dobrou a vazão total — então o teto de ~1.300 qps é
**por processo**, não do SQL Server. A serialização está dentro do processo Python.
Nossa hipótese de trabalho é o handle de ambiente ODBC compartilhado (pyodbc usa um
único `HENV` para todas as conexões) com o lock do unixODBC em volta dele, e o
padrão de aquisição/liberação do GIL como co-suspeito — mas **isso é hipótese, não
resultado.** Não instrumentamos o driver para confirmar.

Consequência prática para nós: numa aplicação Python multi-thread, o custo por
statement do pyodbc (onde ele ganha) deixa de importar bem antes de 10 threads.

## Feedback que buscamos

Se você mantém um desses drivers ou os opera em produção, estas são as perguntas
onde um erro nosso é mais provável:

1. **Configuração do pyodbc sob concorrência.** Existe alguma opção — `HENV` por
   conexão, ajuste de pooling, threading do unixODBC, `odbcinst.ini` — que remova
   o platô de ~1.300 qps por processo? Se sim, o número 5,28x está medindo a nossa
   configuração, não o driver.
2. **Configuração do mssql-python em single-thread.** O point select ficou em
   0,67x. Tem algo a ligar (pooling, prepared statements, buffers de fetch) que
   melhore o caminho de query pequena?
3. **`executemany` vs `bulkcopy`.** Estamos comparando de forma justa ao mostrar
   as duas? Existe caminho de bulk no pyodbc que ignoramos?
4. **Metodologia.** Latência ~0 (mesmo host) amplifica overhead de driver.
   Interessa mais adicionar um cenário com latência de rede real do que aumentar
   iterações?

Issues e PRs bem-vindos. Se você rodar em outro ambiente, o `results.json` inclui o
metadata completo — abrir uma issue com o seu arquivo já é uma contribuição útil.

## Saída

Cada execução escreve em `results/`:

- `results.json` — números + metadata (versões de driver, hardware, versão do SQL
  Server, parâmetros). Com `--repeat`, `results` traz as medianas e `repeats`
  guarda cada execução individual, para o spread ser auditável.
- `results.csv` — mesma coisa em formato tabular.
- `benchmark-light.png` / `benchmark-dark.png` — 8 painéis.

Cada execução **sobrescreve** esses arquivos. Uma execução parcial (ex.:
`--scenarios write_ops`) substitui uma completa, então copie a pasta antes se
quiser guardar um baseline.

O gráfico é **PNG** porque é matplotlib com backend `Agg`: renderização headless,
sem display, sem navegador — funciona dentro do container e dá para colar num
README, PR ou issue. O JSON é a saída canônica; o PNG é uma visualização dele.

## Ressalvas

- **Cliente e servidor no mesmo host:** a latência de rede é ~0, o que amplifica o
  peso do overhead de driver. Em rede real os números ficam mais próximos. É a
  diferença mais importante em relação a benchmarks feitos contra Azure SQL, onde a
  latência domina e as conclusões podem se inverter.
- **Docker Desktop/WSL2:** o SQL Server roda sob virtualização. Os valores
  absolutos não são comparáveis com bare metal Linux; as razões entre drivers são
  mais robustas que os absolutos.
- **Mediana de 3 execuções.** Melhor que uma, longe de um intervalo de confiança.
- **O platô do pyodbc é medição; a explicação é hipótese.** Ver acima.

## Licença

MIT.
