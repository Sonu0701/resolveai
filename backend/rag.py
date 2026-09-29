from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any
from backend.config import BASE_DIR, settings

_vectorstores: dict[str, Any] = {}
def _embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=settings.embedding_model, encode_kwargs={"normalize_embeddings": True})
def _store(collection: str):
    if collection not in _vectorstores:
        from langchain_chroma import Chroma
        _vectorstores[collection]=Chroma(collection_name=collection, embedding_function=_embeddings(), persist_directory=str(settings.chroma_dir))
    return _vectorstores[collection]
def _split_markdown(text: str, source: str) -> list[tuple[str,str]]:
    parts=re.split(r"(?=^##? )",text,flags=re.M); out=[]
    for i,p in enumerate(parts):
        if p.strip():
            title=(p.strip().splitlines()[0].lstrip("# ") or f"Section {i}")
            out.append((p.strip(),title))
    return out

def ingest_knowledge_base(reset: bool=False) -> dict[str,int]:
    from langchain_core.documents import Document
    if reset:
        import shutil
        shutil.rmtree(settings.chroma_dir,ignore_errors=True); settings.chroma_dir.mkdir(parents=True,exist_ok=True); _vectorstores.clear()
    docs=[]
    for path in sorted((BASE_DIR/'data/policies').glob('*.md')):
        text=path.read_text(encoding='utf-8'); category=path.stem.replace('_policy','')
        for i,(chunk,section) in enumerate(_split_markdown(text,path.name)):
            docs.append(Document(page_content=chunk,metadata={"source":path.name,"document_type":"policy","category":category,"policy_version":"1.0","page_number":i+1,"section":section,"chunk_id":f"{path.stem}-{i:03d}","last_updated":"2026-01-15"}))
    tickets=json.loads((BASE_DIR/'data/resolved_tickets/historical_tickets.json').read_text())
    hdocs = [
        Document(
            page_content=(
                f"Issue: {x['customer_message']}\n"
                f"Outcome: {x['outcome']}\n"
                f"Reason: {x['reason']}\n"
                f"Notes: {x['resolution_notes']}"
            ),
            metadata={
                "source": "historical_tickets.json",
                "document_type": "resolved_ticket",
                "category": x["issue_type"],
                "ticket_id": x["ticket_id"],
                "outcome": x["outcome"],
                "policy_reference": x["policy_reference"],
                "manager_approved": str(x["manager_approved"]),
            },
        )
        for x in tickets
    ]
    if docs: _store(settings.policy_collection).add_documents(docs,ids=[d.metadata['chunk_id'] for d in docs])
    if hdocs: _store(settings.ticket_collection).add_documents(hdocs,ids=[d.metadata['ticket_id'] for d in hdocs])
    return {"policy_chunks":len(docs),"historical_tickets":len(hdocs)}

def _lexical_policy_search(query: str, category: str|None, k: int) -> list[dict[str,Any]]:
    terms=set(re.findall(r"[a-z]{4,}",query.lower())); scored=[]
    for p in (BASE_DIR/'data/policies').glob('*.md'):
        cat=p.stem.replace('_policy','')
        if category and category not in cat: continue
        for i,(chunk,section) in enumerate(_split_markdown(p.read_text(),p.name)):
            score=len(terms & set(re.findall(r"[a-z]{4,}",chunk.lower())))
            scored.append((score,{"content":chunk,"metadata":{"source":p.name,"document_type":"policy","category":cat,"policy_version":"1.0","page_number":i+1,"section":section,"chunk_id":f"{p.stem}-{i:03d}","last_updated":"2026-01-15"}}))
    return [x[1] for x in sorted(scored,key=lambda x:x[0],reverse=True)[:k]]
def search_policies(query: str, category: str|None=None, k:int=4) -> list[dict[str,Any]]:
    try:
        filt={"category":category} if category else None
        docs=_store(settings.policy_collection).max_marginal_relevance_search(query,k=k,fetch_k=max(8,k*2),filter=filt)
        if docs: return [{"content":d.page_content,"metadata":d.metadata} for d in docs]
    except Exception: pass
    return _lexical_policy_search(query,category,k)
def search_historical(query: str, issue_type: str|None=None, k:int=3) -> list[dict[str,Any]]:
    try:
        filt={"category":issue_type} if issue_type else None; docs=_store(settings.ticket_collection).similarity_search(query,k=k,filter=filt)
        if docs: return [{"content":d.page_content,"metadata":d.metadata,"notice":"Historical guidance, not binding policy."} for d in docs]
    except Exception: pass
    rows=json.loads((BASE_DIR/'data/resolved_tickets/historical_tickets.json').read_text()); terms=set(query.lower().split())
    if issue_type: rows=[r for r in rows if r['issue_type']==issue_type] or rows
    rows=sorted(rows,key=lambda r:len(terms & set(r['customer_message'].lower().split())),reverse=True)[:k]
    return [{"content":f"Outcome: {r['outcome']}. {r['reason']}","metadata":{"ticket_id":r['ticket_id'],"category":r['issue_type'],"policy_reference":r['policy_reference']},"notice":"Historical guidance, not binding policy."} for r in rows]
