# Benchmarking a phone

Blackwall's board is the RTX PRO 6000's alone; this is the older side project that runs the same suite on an iPhone. Its runs stay in the database and in `blackwall ls --device phone`, and the board does not publish them.

The same llama.cpp that serves your card also runs on an iPhone, so a phone is measured on the same terms as the desktop. The question it answers is not which model is cleverest but **which one the device can live with**: a model that makes the phone dim its screen is disqualified however well it scores.

<img src="phone.png" alt="The phone tab: every model the iPhone Air can hold, with the speed it settles at once hot and whether the phone can live with it">

```
ios/mbenchd/scripts/build-llama.sh     cross-compile llama.cpp for arm64 iOS
ios/mbenchd/scripts/install.sh         build, sign and install it, then check the phone agrees
blackwall phone installed                 which build the device is actually holding
blackwall phone launch                    start it on the device
blackwall phone push model.gguf           copy the weights over the cable
blackwall phone forward                   llama-server on 18080, mbenchd on 18081
blackwall run <id> --quality-from <run>   measure the phone
```

<details>
<summary><b>How a phone runs the suite</b> — one app, two ports, no Mac</summary>

`ios/mbenchd` is llama.cpp's own `llama-server`, cross-compiled for arm64 iOS from Linux and run inside an app. No Mac and no Xcode: `GGML_METAL_EMBED_LIBRARY` ships the Metal kernels as *source*, so the phone compiles them itself at first load and the build needs nothing but clang and the iPhoneOS sysroot xtool already carries. The app and the desktop therefore run the same commit, which is what makes their numbers comparable at all.

| Port | What answers |
|---|---|
| 8080 | `llama-server` itself, unproxied — blackwall measures straight against it, so no timing passes through code of ours |
| 8081 | mbenchd: `/mb/health`, `/mb/models`, `/mb/load`, `/mb/unload`, and llama-swap's `/running` and `/unload` |

blackwall reaches both over the cable (`pymobiledevice3 usbmux forward`), loads the model by POSTing the `phone` table to `/mb/load`, and then talks plain OpenAI to the phone as if it were any other server. In place of the driver's power and VRAM, it polls `/mb/health` once a second for thermal state, the memory the process holds and the battery, so every speed row carries the conditions it was measured under. If the app stops answering — backgrounded, jetsammed, cable out — the run stops and says so rather than scoring the silence.

The app must stay in the foreground with the screen on; iOS suspends a backgrounded app and its sockets go with it. `xtool launch` cannot start it on iOS 17+, so `blackwall phone launch` uses DVT process control instead.

</details>

<details>
<summary><b>What a phone run measures</b> — and what it refuses to</summary>

- **Tokens at full speed.** Twenty answers a second apart, the protocol the published sustained-load measurements of phone inference use, from a device that has held its cold thermal state for a minute first. The board reports the cold speed, the speed it settles at, how many tokens it delivered before throughput fell under 90% of cold, and **stability** — the slowest answer over the fastest, the same ratio a GPU stress test reports, where 97% is the bar a device that is not throttling clears. A card scores 99; a phone does not.
- **Where the context wall is.** The memory the app actually held, beside the context it managed to load. A model that loads at 16k and refuses at 64k says so.
- **A verdict, not a ranking.** *holds up* keeps four fifths of its cold speed and delivers 2k tokens before giving any of it up; *fades* loses a fifth or slows sooner; *barely runs* is under 8 tok/s once settled, under half its cold speed, or slowing inside 512 tokens. The last is a failure, not a low score.
- **Thermal state and battery, as context only.** Both are recorded and shown, and neither decides anything: a charger, a warm room or a different handset moves them, and none of those move what the model delivered. A run made off the charger extrapolates its discharge to a full charge the way a phone battery test does, and reads as hours of continuous generation; a charging run reports nothing rather than pretending the drain was zero.
- **The same file, proved twice.** Both sides hash the weights they served, and a phone row inherits quality only from a run whose sha256 matches. Each run also keeps a greedy answer to one fixed question, so the board can say how far the two agreed before diverging — which catches a different chat template or a different quantisation path that a matching hash cannot.
- **Quality, measured off the device and never made easier.** A 4B model answering a 64k-token reasoning budget at phone speed takes days, so quality comes from a desktop run of *the same .gguf*, named with `--quality-from`. The phone suite measures speed and nothing else — there is no reduced question set a small model could be scored against, and the linked run has to be a full or quick one. A 0.6B answers the same SuperGPQA questions and the same 128k MRCR conversations as a 120B, and takes the zeros its context earns.

Phone rows are ranked against each other and never mixed with the card's — the quality index compares across stacks, tokens per second never do.

</details>

<details>
<summary><b>Declaring a phone model</b> — a <code>phone</code> table instead of a llama-swap command</summary>

A phone model has no llama-swap entry, so `models.toml` says everything. What the `phone` table says is the load request mbenchd sends, so changing the context or the KV type counts as a new configuration, the same way editing a launcher script does. `file` names the `.gguf` on the device when it differs from the model id; ids containing a dot need quoting.

```toml
["qwen3-1.7b-air"]
name = "Qwen3 1.7B · llama.cpp · Q4_K_M · iPhone Air"
hf_id = "unsloth/Qwen3-1.7B-GGUF"
quantization = "Q4_K_M"
thinking = "qwen"
efforts = ["none", "medium"]
phone = { file = "Qwen3-1.7B-Q4_K_M.gguf", n_ctx = 16384, parallel = 4, flash_attn = "on", cache_type_k = "q8_0", cache_type_v = "q8_0", extra_args = ["-kvu"] }
```

`control_url` and `server_url` in the same table point blackwall at a phone that is not on this cable.

</details>
