from __future__ import annotations
import uuid
from typing import Any
from backend.database import execute, fetch_all, fetch_one, json_dumps, now
from backend.security import redact_for_log

def new_ticket_id() -> str: return f"TKT-{uuid.uuid4().hex[:8].upper()}"
def new_thread_id() -> str: return f"thread-{uuid.uuid4().hex}"
def upsert_ticket(ticket_id:str,thread_id:str,order_id:str|None,message:str,status:str='open',issue_type:str|None=None,summary:str|None=None)->None:
    ts=now(); execute("""INSERT INTO tickets(ticket_id,thread_id,order_id,customer_message,issue_type,summary,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(ticket_id) DO UPDATE SET order_id=excluded.order_id,customer_message=excluded.customer_message,issue_type=COALESCE(excluded.issue_type,tickets.issue_type),summary=COALESCE(excluded.summary,tickets.summary),status=excluded.status,updated_at=excluded.updated_at""",(ticket_id,thread_id,order_id,message,issue_type,summary,status,ts,ts))
    execute("""INSERT INTO thread_metadata(thread_id,ticket_id,title,status,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET title=excluded.title,status=excluded.status,updated_at=excluded.updated_at""",(thread_id,ticket_id,(summary or message)[:80],status,ts,ts))
def add_message(ticket_id:str,role:str,content:str)->None: execute("INSERT INTO ticket_messages(ticket_id,role,content,created_at) VALUES(?,?,?,?)",(ticket_id,role,content,now()))
def log_event(ticket_id:str|None,event_type:str,details:dict[str,Any])->None: execute("INSERT INTO audit_logs(ticket_id,event_type,details_json,created_at) VALUES(?,?,?,?)",(ticket_id,event_type,json_dumps({k:redact_for_log(str(v)) for k,v in details.items()}),now()))
def save_approval(ticket_id:str,decision:str,reason:str='',edited_response:str='')->None: execute("INSERT INTO approval_events(ticket_id,decision,reason,edited_response,created_at) VALUES(?,?,?,?,?)",(ticket_id,decision,reason,edited_response,now()))
def list_cases(search:str='',status:str='all')->list[dict[str,Any]]:
    sql="SELECT t.*,m.title FROM tickets t LEFT JOIN thread_metadata m ON m.thread_id=t.thread_id WHERE 1=1"; params=[]
    if search: sql+=" AND (t.ticket_id LIKE ? OR t.customer_message LIKE ? OR t.order_id LIKE ?)"; params += [f'%{search}%']*3
    if status!='all': sql+=" AND t.status=?"; params.append(status)
    return fetch_all(sql+" ORDER BY t.updated_at DESC",tuple(params))
def load_case(ticket_id:str)->dict[str,Any]|None:
    t=fetch_one("SELECT * FROM tickets WHERE ticket_id=?",(ticket_id,))
    if not t:return None
    t['messages']=fetch_all("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id",(ticket_id,)); t['resolutions']=fetch_all("SELECT * FROM case_resolutions WHERE ticket_id=? ORDER BY id DESC",(ticket_id,)); t['approvals']=fetch_all("SELECT * FROM approval_events WHERE ticket_id=? ORDER BY id DESC",(ticket_id,)); t['audit']=fetch_all("SELECT * FROM audit_logs WHERE ticket_id=? ORDER BY id",(ticket_id,)); return t
def delete_case(ticket_id:str)->None:
    execute("DELETE FROM tickets WHERE ticket_id=?",(ticket_id,))
