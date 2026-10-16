# board.json

The published site carries every number on the page as `board.json`, so a script, a spreadsheet or another site can follow the benchmarks without scraping. `blackwall export` writes it, and the page, the card and the feed are built from the same data.

**Stability.** The file has a `schema` number, currently `1`. Within a schema, keys are only ever added: nothing is renamed, removed or given a new meaning. A change that would break a reader bumps `schema`, and the [changelog](../CHANGELOG.md) says so.

## Top level

| Key | Type | Meaning |
|---|---|---|
| `schema` | number | The version of this layout. |
| `generator` | object | `name` (`"blackwall"`) and `version` of the software that wrote the file. |
| `generated` | number | Unix time the file was written. |
| `suite` | string | The current suite label, such as `full/v1`. |
| `current` | string | The current suite version, the key into `suites`. |
| `hardware` | object | The newest run's `gpu`, `driver` and `vram_mib`. |
| `suites` | object | One entry per suite version, holding that version's rankings. Rankings of different versions measure different tasks and are never mixed. |
| `history` | array | Every finished full or quick run, oldest first, with what each one changed. |
| `published` | object | Present when the folder was exported for publishing: `json` (this file's name) and `feed` (`feed.xml`, or `null`). |
| `indexTasks`, `taskLabels`, `efforts`, `rankings` | | Copies of the current suite's keys of the same name, kept so a reader of the first schema needs only the top level. |

## `suites[version]`

| Key | Meaning |
|---|---|
| `indexTasks` | The tasks the quality index averages, in display order. |
| `taskLabels`, `taskShort`, `taskNotes` | A name, a short name and a sentence for each task. |
| `groups` | The groups the index weights equally, each listing its tasks. |
| `efforts` | The reasoning efforts that have a ranking, most models first. |
| `rankings` | Effort level to an array of models, each the newest complete run of that model at that effort. |
| `health` | Effort level to the tasks that do not separate the ranked models, with the reason. |
| `hosts` | Effort level to the card and driver combinations the ranking's speed numbers come from. |

## A model in `rankings`

| Key | Meaning |
|---|---|
| `id`, `name` | The llama-swap id, and the display name with engine, quantization and context. |
| `engine`, `quantization`, `spec`, `context` | What the server ran. `spec` is the speculative-decoding method. |
| `index` | The quality index: `value` and a 95% interval `lo`, `hi`, in percent. `null` until every task has run. |
| `tasks` | Task id to its score (`value`, `lo`, `hi`, `n`), the tokens per answer, the share cut off by the token budget and a per-length or per-part breakdown in `parts`. |
| `speed` | Speed measurements by key, each `{value, unit, n}`: `decode` (one request, tok/s), `peak` (best across all requests), `conc.N`, `ttft.N` (seconds to first token at a prompt of N tokens) and more. |
| `energy` | `perCorrect`, board watt-hours per correct answer, and `quality`, watt-hours over the quality tasks. |
| `stack` | The card (`gpu`), `driver`, `vramMib` and server `build` that answered. Quality compares across stacks; speed and energy only compare within one. |
| `capacity` | Requests the server took at once and the context they shared. |
| `warnings` | Settings that capped a score, in words. |
| `fingerprint` | A hash of the server's launch settings. A changed launcher or flag is a new configuration, so it is a new fingerprint. |
| `repeats` | `runs`, how many complete runs share this fingerprint, and `spread`, how far apart their decode speeds landed as a percentage, or `null` with one run. |
| `lmx`, `submissions` | Scores and submission ids from [localmaxxing](https://www.localmaxxing.com), when the run was submitted. Empty otherwise. |
| `deviceClass`, `thermal`, `battery`, `verdict`, `qualityFrom` | Phone-run fields. `deviceClass` is always `gpu` on the published board, and the others are empty, because phone runs are not published. |
| `run` | The run behind the row: `id`, `suite`, `kind` (`full` or `quick`), `finished`, `effort`, `harness`, notes and what was shared or failed. |
| `history` | The model's runs at any effort in this suite version, newest first and including the one behind the row: `id`, `suite`, `effort`, `finished`, `index`, `decode`. |
| `server` | The server settings recorded with the run. Paths on the measuring machine appear as recorded, with its home directory written `~`. |

## An entry in `history`

One per finished run, oldest first. Quality indexes are only comparable inside one `version` and one `effort`, and the marks below respect that boundary.

| Key | Meaning |
|---|---|
| `run`, `model`, `name` | The run id, the llama-swap id and the display name. |
| `effort`, `suite`, `version`, `kind` | The effort level, the suite label (`full/v1`), its version (`1`) and `full` or `quick`. A quick run is provisional. |
| `finished` | Unix time the run finished. |
| `index`, `lo`, `hi` | The quality index and its 95% interval, `null` when the run did not measure one. |
| `decode`, `peak`, `energyPerCorrect` | Decode speed of one request (tok/s), peak throughput (tok/s) and watt-hours per correct answer; `null` when not measured. |
| `gpu`, `driver`, `build` | The card, driver and server build the run was measured on. |
| `debut` | `true` when it is the model's first run at this effort and version. |
| `record` | `true` when its index beat every earlier full run at this effort and version. A quick run is provisional and never sets a record. |
| `delta`, `previous` | The change in index against the same model's previous run of the same kind (`full` or `quick`) at this effort and version, and that run's id. `null` for a first run. |

## Following along

- **Atom feed.** `feed.xml` has one entry per finished run, newest first, titled with the model and its quality index and marked `(new best)` or `(debut)`. Entry ids are `tag:` URIs built from the run id, so a reader shows each result once.
- **Deep links.** `index.html#<model id>` opens the page on that model, and `#<model id>~<effort>` on that model at that effort. The feed links use the second form.
- **Your own copy.** `blackwall export --out DIR --site-url URL` writes all of this for a database of your own, and `site_url` in `config.toml` sets the address once.
