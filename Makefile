ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export PYTHONPATH := $(ROOT):$(ROOT)/scraper:$(ROOT)/clean
VENV := $(ROOT).venv/bin/python

.PHONY: venv dev-scraper dev-clean test clean-cli-credits

venv:
	python3 -m venv $(ROOT).venv
	$(VENV) -m pip install -q --upgrade pip
	$(VENV) -m pip install -q -r $(ROOT)requirements.txt

dev-scraper:
	cd $(ROOT)scraper && streamlit run app.py

dev-clean:
	cd $(ROOT)clean && streamlit run app.py

PY := $(if $(wildcard $(ROOT).venv/bin/python),$(ROOT).venv/bin/python,python3)

test:
	cd $(ROOT) && $(PY) -m pytest scraper/tests shared/tests -q
	cd $(ROOT)clean && $(PY) -m pytest tests -q

clean-cli-credits:
	cd $(ROOT)clean && python cli.py credits
