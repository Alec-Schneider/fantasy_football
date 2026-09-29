#!/usr/bin/env bash

uv run fantasy-analyzer commentary recap 1389350137481932800 --week 1 --total-weeks 18 --generate --model claude-sonnet-5 --effort medium && \
uv run fantasy-analyzer commentary recap 1389754945892274176 --week 1 --total-weeks 18 --generate --model claude-sonnet-5 --effort medium && \
uv run fantasy-analyzer commentary recap 1389707229824815104 --week 1 --total-weeks 18 --generate --model claude-sonnet-5 --effort medium
