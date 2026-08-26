# Makefile for ambient-expense-agent

.PHONY: install playground run

# Install dependencies and sync environment
install:
	agents-cli install

# Start the ADK playground UI
playground:
	agents-cli playground

# Run the FastAPI ambient web service on port 8080
run:
	uv run python -m expense_agent.fast_api_app
