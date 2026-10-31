# Self-Healing Question Bank Agent

Autonomous QA agent for assessment banks: mines attempt statistics, independently re-solves suspect questions, proposes and self-verifies fixes, sends each fix with evidence to a human reviewer.

## Quick start
`ash
cp .env.example .env          # add your GROQ_API_KEY
pip install -r requirements.txt
python -m src.seed.build --seed 0
python -m src.agent --seed 0
streamlit run app.py
pytest -q
`

## Commands
| Command | What it does |
|---|---|
| python -m src.seed.build --seed 0 | Creates data/qbank.db + hidden data/ground_truth.json |
| python -m src.agent --seed 0 | Headless agent run |
| python -m src.evaluate --seeds 0 1 2 | Metrics table + eports/eval.json |
| streamlit run app.py | Demo UI |
| pytest -q | Unit tests |

## Architecture
See SPEC.md §2 for the full architecture diagram.

## Env vars
See .env.example for all required environment variables.
