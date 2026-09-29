from backend.seed_data import seed_database
from backend.tools import get_order_details
def test_valid_seeded_order_lookup():
 seed_database(100,False); r=get_order_details.invoke({'order_id':'NC-100001'}); assert r['found'] and r['order']['customer_email'].startswith('a***')
def test_invalid_order_id_is_safe():
 r=get_order_details.invoke({'order_id':'bad'}); assert not r['found'] and 'Invalid' in r['error']
