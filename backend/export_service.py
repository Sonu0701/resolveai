from __future__ import annotations
import json
from io import BytesIO
from typing import Any

def case_markdown(case:dict[str,Any])->str:
    resolutions=case.get('resolutions',[]); latest=resolutions[0] if resolutions else {}; rec=latest.get('recommendation_json','{}')
    try: rec=json.loads(rec)
    except Exception: pass
    return f"""# ResolveAI Case {case.get('ticket_id')}

- **Status:** {case.get('status')}
- **Order:** {case.get('order_id') or 'Not supplied'}
- **Issue:** {case.get('issue_type') or 'Unclassified'}
- **Created:** {case.get('created_at')}

## Customer message
{case.get('customer_message','')}

## Recommendation
```json
{json.dumps(rec,indent=2,ensure_ascii=False) if isinstance(rec,dict) else rec}
```

## Customer response draft
{latest.get('customer_response','No draft saved.')}

> Simulation only: no refund, replacement, CRM update, or customer message was executed.
"""
def case_txt(case:dict[str,Any])->str:return case_markdown(case).replace('# ','').replace('## ','').replace('**','').replace('```json','').replace('```','')
def case_pdf(case:dict[str,Any])->bytes:
    from fpdf import FPDF
    pdf=FPDF(); pdf.add_page(); pdf.set_font('Helvetica','B',16); pdf.cell(0,10,f"ResolveAI Case {case.get('ticket_id')}",new_x='LMARGIN',new_y='NEXT'); pdf.set_font('Helvetica',size=10)
    safe=case_txt(case).replace('₹','INR ')
    for line in safe.splitlines(): pdf.multi_cell(0,6,line.encode('latin-1','replace').decode('latin-1'))
    return bytes(pdf.output())
