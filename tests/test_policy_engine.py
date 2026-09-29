from datetime import date,timedelta
from backend.policy_engine import evaluate_policy
def order(amount=3000,status='delivered',days=5,stock=True):return {'amount_inr':amount,'status':status,'delivery_date':str(date.today()-timedelta(days=days)) if days is not None else None,'replacement_stock_available':stock,'return_status':'none','address_verified':True,'notes':''}
def test_damaged_low_value_replacement():
 d=evaluate_policy('damaged_product',order(),{}); assert d.recommended_action=='replacement' and not d.requires_approval
def test_damaged_high_value_needs_approval():
 d=evaluate_policy('damaged_product',order(amount=12999),{}); assert d.recommended_action=='replacement' and d.requires_approval
def test_refund_after_45_days_not_automatic():
 d=evaluate_policy('refund_request',order(days=45),{}); assert d.eligibility=='not_eligible' and d.requires_approval
def test_in_transit_no_post_delivery_refund():
 d=evaluate_policy('refund_request',order(status='in_transit',days=None),{}); assert d.recommended_action in {'wait_provide_delivery_update','shipment_investigation'}
def test_dnr_high_value_escalates():
 d=evaluate_policy('delivered_not_received',order(amount=23999),{}); assert d.requires_approval and d.recommended_action=='shipment_investigation'
