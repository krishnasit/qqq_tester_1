# QQQ London Session Strategy

## Setup

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_backtest.py
streamlit run dashboard/app.py
python bot/alpaca_bot.py
