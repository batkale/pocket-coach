# make data : download nflverse EPA (cached) + run the pipeline -> frontend/data.json + frontend/plays/*.json
# make dev  : serve the app at http://localhost:8000
# make test : run unit tests
data:
	mkdir -p ext
	test -f ext/pbp_2021.parquet || curl -sSL -o ext/pbp_2021.parquet https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2021.parquet
	python backend/pipeline.py
	python backend/coaching.py
dev:
	python -m http.server 8000 --directory frontend
test:
	python -m pytest -q backend/tests
