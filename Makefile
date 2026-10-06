.PHONY: run test

run:
	python -m src.main --vfs ./sample_vfs

test:
	python -m unittest discover -s tests -v