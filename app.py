from __future__ import annotations
import json
import streamlit as st
from langgraph.types import Command
from backend.config import settings
from backend.database import init_db
from backend.export_service import case_markdown, case_pdf, case_txt
from backend.graph import build_graph
from backend.seed_data import seed_database
from backend.ticket_service import delete_case, list_cases, load_case, new_thread_id, new_ticket_id

st.set_page_config(page_title="ResolveAI",page_icon="🛡️",layout="wide")
st.markdown("""<style>
:root{--brand:#6d5dfc;--mint:#23c6a5}.block-container{padding-top:1.4rem;max-width:1400px}.hero{padding:1.2rem 1.4rem;border:1px solid rgba(128,128,128,.22);border-radius:18px;background:linear-gradient(135deg,rgba(109,93,252,.16),rgba(35,198,165,.10));margin-bottom:1rem}.eyebrow{font-size:.75rem;letter-spacing:.13em;text-transform:uppercase;color:#8a7cff;font-weight:700}.card{border:1px solid rgba(128,128,128,.22);border-radius:16px;padding:1rem;margin:.4rem 0;background:rgba(128,128,128,.035)}.badge{display:inline-block;padding:.25rem .65rem;border-radius:999px;font-size:.78rem;font-weight:700;background:rgba(109,93,252,.16);color:#8d82ff}.warning{border-left:5px solid #ffb020;background:rgba(255,176,32,.10);padding:1rem;border-radius:12px}.ok{border-left:5px solid #23c6a5;background:rgba(35,198,165,.10);padding:1rem;border-radius:12px}.small{opacity:.74;font-size:.85rem}div[data-testid=stSidebar]{border-right:1px solid rgba(128,128,128,.2)}
</style>""",unsafe_allow_html=True)
init_db()
if 'thread_id' not in st.session_state: st.session_state.thread_id=new_thread_id()
if 'ticket_id' not in st.session_state: st.session_state.ticket_id=new_ticket_id()
if 'result' not in st.session_state: st.session_state.result={}
if 'pending' not in st.session_state: st.session_state.pending=False
SAMPLES={
"Damaged headphones — low value":("NC-100001","My headphones arrived damaged yesterday. I want a replacement."),
"Damaged smartwatch — approval":("NC-100002","My ₹12,999 smartwatch is damaged and I want a refund."),
"Refund outside 30 days":("NC-100003","I want a refund for an item delivered 45 days ago."),
"Still in transit":("NC-100004","My order is still in transit. Please refund it."),
"Delivered, not received":("NC-100005","Tracking says delivered, but I never received the package."),
"Wrong item":("NC-100006","I received the wrong item. Please replace it."),
"Delayed 12 days":("NC-100007","My order has been delayed for 12 days. Where is it?"),
}
with st.sidebar:
    st.markdown("## 🛡️ ResolveAI")
    st.caption("Grounded, policy-aware support resolution with human approval for risky actions.")
    if st.button("＋ New case",use_container_width=True):
        st.session_state.thread_id=new_thread_id(); st.session_state.ticket_id=new_ticket_id(); st.session_state.result={}; st.session_state.pending=False; st.rerun()
    st.markdown("### Case history")
    search=st.text_input("Search cases",placeholder="Ticket, order, message")
    filt=st.selectbox("Status",["all","open","pending_approval","resolved","escalated"])
    for case in list_cases(search,filt):
        label = (
            f"{case['ticket_id']} · {case['status']}\n\n"
            f"{(case.get('summary') or case['customer_message'])[:44]}"
        )
        if st.button(label,key='case_'+case['ticket_id'],use_container_width=True):
            st.session_state.selected_ticket=case['ticket_id']
    st.divider(); st.caption("Demo data only · No live CRM, payments, or messages")
    with st.expander("Demo setup"):
        if st.button("Reseed 100 orders"): seed_database(100,False); st.success("Demo orders ready")

st.markdown("""<div class='hero'><div class='eyebrow'>Agentic ticket investigation</div><h1>ResolveAI — Customer Support Resolution Copilot</h1><div>Investigate orders, retrieve policy evidence, apply deterministic rules, and route risky recommendations for human approval.</div></div>""",unsafe_allow_html=True)
if settings.demo_mode: st.info("Demo mode: MISTRAL_API_KEY is not configured. Deterministic triage and drafting remain available; vector search falls back to local lexical retrieval.")

if st.session_state.get('selected_ticket'):
    saved=load_case(st.session_state.selected_ticket)
    if saved:
        with st.expander(f"Saved case · {saved['ticket_id']}",expanded=False):
            st.write(saved['customer_message']); st.caption(f"Status: {saved['status']} · Order: {saved.get('order_id') or 'missing'}")
            c1,c2,c3=st.columns(3)
            c1.download_button("Markdown",case_markdown(saved),f"{saved['ticket_id']}.md")
            c2.download_button("TXT",case_txt(saved),f"{saved['ticket_id']}.txt")
            try:c3.download_button("PDF",case_pdf(saved),f"{saved['ticket_id']}.pdf",mime="application/pdf")
            except Exception:c3.caption("Install fpdf2 for PDF")
            if st.checkbox("Confirm deletion",key='confirm_delete') and st.button("Delete case",type='secondary'):
                delete_case(saved['ticket_id']); st.session_state.selected_ticket=None; st.rerun()

left,right=st.columns([.92,1.35],gap='large')
with left:
    st.markdown("### Ticket intake")
    sample=st.selectbox("Load sample scenario",["Choose a scenario…",*SAMPLES])
    default_order,default_msg=SAMPLES.get(sample,("",""))
    ticket_id=st.text_input("Ticket ID",value=st.session_state.ticket_id)
    order_id=st.text_input("Order ID",value=default_order,placeholder="NC-100001")
    message=st.text_area("Customer message",value=default_msg,height=170,placeholder="Describe the customer issue…")
    if st.button("Investigate ticket",type="primary",use_container_width=True,disabled=st.session_state.pending):
        st.session_state.ticket_id=ticket_id; st.session_state.thread_id=st.session_state.thread_id
        initial={"thread_id":st.session_state.thread_id,"ticket_id":ticket_id,"customer_message":message,"order_id":order_id or None,"conversation_messages":[],"tool_events":[],"error_messages":[],"sources":[]}
        config={"configurable":{"thread_id":st.session_state.thread_id},"run_name":"resolveai-ticket-investigation"}
        try:
            with st.status("Investigating case…",expanded=True) as status:
                st.write("Reviewing ticket…"); st.write("Checking order details…"); st.write("Retrieving policy evidence…"); st.write("Comparing similar cases…"); st.write("Applying policy rules…")
                result=build_graph().invoke(initial,config=config)
                status.update(label="Investigation paused for approval" if '__interrupt__' in result else "Investigation complete",state="complete")
            st.session_state.result=result; st.session_state.pending='__interrupt__' in result
            if st.session_state.pending:
                from backend.ticket_service import upsert_ticket
                upsert_ticket(ticket_id,st.session_state.thread_id,order_id or None,message,'pending_approval',result.get('issue_type'),result.get('ticket_summary'))
            st.rerun()
        except Exception as exc: st.error(f"Could not complete the investigation: {type(exc).__name__}: {exc}")

result=st.session_state.result
with right:
    st.markdown("### Resolution workspace")
    if not result: st.markdown("<div class='card'><b>No active investigation</b><br><span class='small'>Load a sample or enter a ticket to begin.</span></div>",unsafe_allow_html=True)
    else:
        status='Pending manager approval' if st.session_state.pending else 'Resolution drafted'
        st.markdown(f"<span class='badge'>{status}</span>",unsafe_allow_html=True)
        st.markdown(f"**Summary:** {result.get('ticket_summary','—')}")
        a,b,c=st.columns(3); a.metric("Issue",result.get('issue_type','—').replace('_',' ').title()); b.metric("Urgency",result.get('urgency','—').title()); c.metric("Confidence",f"{result.get('confidence',0)*100:.0f}%")
        order=result.get('order_details',{})
        with st.expander("Order details",expanded=True):
            if order:
                x,y,z=st.columns(3); x.metric("Amount",f"₹{float(order.get('amount_inr',0)):,.2f}"); y.metric("Status",str(order.get('status','')).replace('_',' ').title()); z.metric("Product",order.get('product_name','—'))
                st.caption(f"Customer email: {order.get('customer_email','—')} · Tracking: {order.get('shipping_tracking_status','—')}")
            else: st.warning("No verified order facts available.")
        decision=result.get('policy_decision',{}); rec=result.get('recommendation',{})
        st.markdown(f"<div class='card'><div class='eyebrow'>Recommended action</div><h3>{rec.get('action',decision.get('recommended_action','—')).replace('_',' ').title()}</h3><div>{decision.get('decision_reason','')}</div></div>",unsafe_allow_html=True)
        st.text_area("Customer reply draft",value=result.get('drafted_customer_response',''),height=160,key='draft_box')
        if st.button("Save draft", use_container_width=True, disabled=st.session_state.pending):
            from backend.tools import save_resolution_draft
            saved = save_resolution_draft.invoke(
                {
                    "ticket_id": result.get("ticket_id", st.session_state.ticket_id),
                    "recommendation": rec,
                    "customer_response": st.session_state.draft_box,
                    "sources": result.get("sources", []),
                }
            )
            st.success(f"Draft saved locally (resolution {saved['resolution_id']}).")

if st.session_state.pending and result:
    payload=result.get('__interrupt__',[None])[0]
    payload=getattr(payload,'value',payload) or result.get('approval_payload',{})
    st.markdown("---"); st.markdown("<div class='warning'><h3>⚠️ Manager approval required</h3>Risky recommendations remain paused until a manager approves, rejects, or edits the draft.</div>",unsafe_allow_html=True)
    st.write("**Reasons:**",", ".join(payload.get('reasons',[]))); st.write("**Recommended:**",payload.get('recommended_action','—').replace('_',' ').title()); st.write("**Amount:**",f"₹{float(payload.get('amount') or 0):,.2f}")
    edited=st.text_area("Manager-editable reply",value=payload.get('proposed_customer_reply',''),height=140,key='approval_edit')
    reason=st.text_input("Manager note (optional)")
    c1,c2,c3=st.columns(3)
    decision=None
    if c1.button("Approve",type='primary',use_container_width=True): decision={"decision":"approve","reason":reason}
    if c2.button("Reject",use_container_width=True): decision={"decision":"reject","reason":reason}
    if c3.button("Edit and approve",use_container_width=True): decision={"decision":"edit_and_approve","reason":reason,"edited_response":edited}
    if decision:
        try:
            config={"configurable":{"thread_id":st.session_state.thread_id},"run_name":"resolveai-manager-resume"}; resumed=build_graph().invoke(Command(resume=decision),config=config); st.session_state.result=resumed; st.session_state.pending=False; st.success("Manager decision recorded and graph resumed."); st.rerun()
        except Exception as exc: st.error(f"Could not resume approval: {exc}")

if result:
    with st.expander("Evidence used"):
        st.markdown("#### Policy citations")
        for s in result.get('sources',[]): st.markdown(f"- **{s.get('source')}** · {s.get('section')} · page/section {s.get('page_number')} · `{s.get('chunk_id')}`")
        st.markdown("#### Retrieved snippets")
        for d in result.get('retrieved_policy_docs',[]): st.caption(d.get('content','')[:500])
        st.markdown("#### Similar historical cases")
        for h in result.get('similar_cases',[]): st.write(f"- {h.get('content','')[:220]} — *historical guidance, not binding policy*.")
    with st.expander("Agent activity"):
        for e in result.get('tool_events',[]): st.write(f"✓ {e.get('event','').replace('_',' ').title()} — {e.get('detail','')}")
        st.caption("Safe execution summary only. Hidden chain-of-thought is never displayed.")
