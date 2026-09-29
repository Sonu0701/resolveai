from __future__ import annotations
import json,time
from pathlib import Path
from backend.config import BASE_DIR
from backend.database import init_db
from backend.policy_engine import assess_additional_risk,evaluate_policy
from backend.security import detect_prompt_injection
from backend.tools import get_order_details

def classify(message:str)->str:
    m=message.lower()
    if 'delivered' in m and ('not received' in m or 'never received' in m):return 'delivered_not_received'
    if 'wrong' in m:return 'wrong_item'
    if any(x in m for x in ['damaged','broken']):return 'damaged_product'
    if any(x in m for x in ['delayed','late','where is']):return 'delayed_delivery'
    if 'refund' in m:return 'refund_request'
    return 'other'
def run(path:Path|None=None)->dict:
    init_db(); cases=json.loads((path or BASE_DIR/'data/evaluation/support_eval_dataset.json').read_text()); counts={'issue':0,'policy':0,'escalation_tp':0,'escalation_expected':0,'citations':0,'tool_errors':0}; lat=[]
    for c in cases:
        t=time.perf_counter(); issue=classify(c['customer_message']); counts['issue']+=issue==c['expected_issue_type']; order={}
        if c.get('order_id'):
            r=get_order_details.invoke({'order_id':c['order_id']}); order=r.get('order',{}); counts['tool_errors']+=not r.get('found')
        d=evaluate_policy(issue,order or None,{'security_flags':detect_prompt_injection(c['customer_message'])}); escalated=bool(assess_additional_risk(c['customer_message'],order,d,detect_prompt_injection(c['customer_message'])))
        counts['policy']+=d.recommended_action==c['expected_action']; counts['escalation_expected']+=bool(c['expected_escalation']); counts['escalation_tp']+=bool(c['expected_escalation'] and escalated); counts['citations']+=bool(d.policy_rule_applied); lat.append(time.perf_counter()-t)
    n=len(cases); return {'cases':n,'policy_decision_accuracy':counts['policy']/n,'issue_classification_accuracy':counts['issue']/n,'escalation_recall':counts['escalation_tp']/max(1,counts['escalation_expected']),'citation_source_presence_rate':counts['citations']/n,'tool_error_rate':counts['tool_errors']/n,'average_latency_seconds':sum(lat)/n}
if __name__=='__main__': print(json.dumps(run(),indent=2))
