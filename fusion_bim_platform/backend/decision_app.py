"""Standalone v17 service for review/testing without the earlier platform modules.
Run from project root: uvicorn backend.decision_app:app --host 127.0.0.1 --port 8000
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .decision_ledger import register as ledger
from .knowledge_graph import register as graph
from .circulation import register as circulation
ROOT=Path(__file__).resolve().parents[1]
app=FastAPI(title='Fusion — Decision Intelligence v17')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['*'],allow_headers=['*'])
ledger(app,ROOT);graph(app,ROOT);circulation(app,ROOT)
