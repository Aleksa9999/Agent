.PHONY: hooks install lint test check stack-up stack-down native-up native-down validate-skills

hooks:
	pre-commit install

install:
	pip install -r requirements-dev.txt

lint:
	ruff check . && ruff format --check .

test:
	python3 -m pytest

validate-skills:
	python3 -I tools/validate_skills.py

check: lint test validate-skills

# Test stack in Docker (the server). ENV_FILE defaults to .env.test, created from .env.example.
stack-up:
	docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml up -d --build

stack-down:
	docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml down

# The same app on real PostgreSQL and Redis without Docker (development machines).
native-up:
	deploy/native-stack.sh up

native-down:
	deploy/native-stack.sh down
