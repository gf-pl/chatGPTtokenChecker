.PHONY: deploy status logs

deploy:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; fi
	docker compose up -d --build --wait --wait-timeout 120
	docker compose ps

status:
	docker compose ps

logs:
	docker compose logs --tail=100 -f usage-monitor
