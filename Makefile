# Round-trip experiment & local converter — task runner.
#
#   make help          list all targets
#   make dataset       (re)build the 2/3 train + 1/3 val split  -> rt/manifest.json
#   make synth         render every midi/ file to wav           -> rt/wav/<timbre>/
#   make convert       full round-trip for ONE file             -> rt/out/
#   make eval          batch-evaluate timbre x post combos      -> rt/results_*.json
#   make serve         run the local web app
#
# All Python entry points go through `uv run` so the project venv is used.

PY       := uv run python
CLI      := tools/roundtrip/cli.py

# Tunables (override on the command line, e.g. `make synth TIMBRE=fluidsynth`)
TIMBRE   ?= rich            # pluck | rich | fluidsynth
TIMBRES  ?= fluidsynth rich # space-separated list for `make eval`
SPLIT    ?= val             # train | val | all

.PHONY: help deps dataset synth convert eval eval-resume serve clean distclean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

deps: ## Install Python deps (uv sync) + system deps (fluidsynth + GM soundfont)
	uv sync
	@if ! command -v fluidsynth >/dev/null 2>&1; then \
		apt-get update -q && apt-get install -y -q fluidsynth fluid-soundfont-gm; \
	fi

dataset: ## Discover midi/ files and write the train/val split
	cd tools/roundtrip && $(PY) dataset.py

synth: ## Render all corpus wavs for TIMBRE (rt/wav/<TIMBRE>/)
	$(PY) $(CLI) synth --timbre $(TIMBRE)

convert: ## Round-trip ONE file: FILE=midi/foo.mid [TIMBRE=rich] -> rt/out/
ifndef FILE
	@echo "usage: make convert FILE=midi/foo.mid [TIMBRE=rich|pluck|fluidsynth]"; exit 2
endif
	$(PY) $(CLI) convert --file $(FILE) --timbre $(TIMBRE)

eval: ## Batch-evaluate TIMBRES x posts on SPLIT (resumable, writes rt/ckpt_*.jsonl)
	cd tools/roundtrip && $(PY) -c "\
	import warnings; warnings.filterwarnings('ignore');\
	from eval import run;\
	run(split='$(SPLIT)', timbres=tuple('$(TIMBRES)'.split()), posts=('base','clean'))"

eval-resume: ## Run eval, auto-restarting after OOM kills until complete
	$(PY) $(CLI) resume --split $(SPLIT) --timbres $(TIMBRES)

serve: ## Run the local web app (http://localhost:8000)
	uv run basic-pitch-local

clean: ## Remove regenerable artifacts (wavs, detected midis, checkpoints)
	rm -rf rt/wav rt/det rt/out rt/ckpt_*.jsonl

distclean: clean ## Also remove the manifest and result summaries
	rm -f rt/manifest.json rt/results_*.json
