from __future__ import annotations
import argparse, random
from datetime import date, timedelta
from backend.config import settings
from backend.database import connection, init_db
PRODUCTS=[("Wireless Headphones","audio",3499),("Smartwatch Pro","wearables",12999),("Cotton Kurta","fashion",1499),("Air Fryer","home",6999),("Mechanical Keyboard","electronics",5499),("Fitness Band","wearables",2999),("4K Monitor","electronics",23999),("Running Shoes","fashion",3999)]
NAMES=["Aarav Sharma","Diya Patel","Ishaan Verma","Meera Nair","Kabir Singh","Ananya Rao","Rohan Das","Sara Khan"]
def _special_orders():
    today=date.today()
    return [
      ("NC-100001","Aarav Sharma","aarav@example.com","Wireless Headphones","audio",3499,today-timedelta(days=12),today-timedelta(days=4),today-timedelta(days=5),"delivered","paid","none",1,"delivered",1,"Package corner crushed; customer reports damage."),
      ("NC-100002","Diya Patel","diya@example.com","Smartwatch Pro","wearables",12999,today-timedelta(days=15),today-timedelta(days=6),today-timedelta(days=7),"delivered","paid","none",1,"delivered",1,"High-value damaged-item test order."),
      ("NC-100003","Ishaan Verma","ishaan@example.com","Air Fryer","home",6999,today-timedelta(days=60),today-timedelta(days=45),today-timedelta(days=48),"delivered","paid","none",0,"delivered",1,"Delivered more than 30 days ago."),
      ("NC-100004","Meera Nair","meera@example.com","Mechanical Keyboard","electronics",5499,today-timedelta(days=8),None,today+timedelta(days=2),"in_transit","paid","none",1,"in_transit",1,"Active carrier movement."),
      ("NC-100005","Kabir Singh","kabir@example.com","4K Monitor","electronics",23999,today-timedelta(days=18),today-timedelta(days=2),today-timedelta(days=5),"delivered","paid","none",1,"delivered",0,"Carrier says delivered; customer disputes receipt."),
      ("NC-100006","Ananya Rao","ananya@example.com","Running Shoes","fashion",3999,today-timedelta(days=14),today-timedelta(days=7),today-timedelta(days=8),"delivered","paid","none",1,"delivered",1,"Warehouse note: possible wrong colour shipped."),
      ("NC-100007","Rohan Das","rohan@example.com","Fitness Band","wearables",2999,today-timedelta(days=20),None,today-timedelta(days=12),"delayed","paid","none",1,"delayed",1,"No carrier movement for 10 days."),
      ("NC-100008","Sara Khan","sara@example.com","Smartwatch Pro","wearables",12999,today-timedelta(days=17),None,today-timedelta(days=9),"delayed","paid","none",1,"delivered",None,"Conflicting status and tracking data."),
    ]
def seed_database(count:int=100,reset:bool=False)->int:
    init_db()
    with connection() as conn:
      if reset:
        for table in ['approval_events','audit_logs','case_resolutions','ticket_messages','thread_metadata','escalation_drafts','tickets','orders']: conn.execute(f"DELETE FROM {table}")
      rows=_special_orders(); random.seed(42); today=date.today(); statuses=['delivered','in_transit','delayed','cancelled','returned','refund_initiated']
      for i in range(len(rows)+1,count+1):
        oid=f"NC-{100000+i:06d}"; name=random.choice(NAMES); product,cat,amount=random.choice(PRODUCTS); order_date=today-timedelta(days=random.randint(2,90)); status=random.choice(statuses); expected=order_date+timedelta(days=random.randint(3,8)); delivery=(expected+timedelta(days=random.randint(-1,4))) if status in ['delivered','returned','refund_initiated'] else None
        rows.append((oid,name,name.lower().replace(' ','_')+'@example.com',product,cat,amount,order_date,delivery,expected,status,'paid' if status!='cancelled' else 'void','received' if status=='returned' else 'none',random.randint(0,1),status if status in ['in_transit','delayed','delivered'] else 'closed',random.randint(0,1),"Synthetic demo order."))
      conn.executemany("""INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",[(r[0],r[1],r[2],r[3],r[4],r[5],str(r[6]),str(r[7]) if r[7] else None,str(r[8]),r[9],r[10],r[11],r[12],r[13],r[14],r[15]) for r in rows])
    return len(rows)
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--count',type=int,default=100); p.add_argument('--reset',action='store_true'); p.add_argument('--ingest',action='store_true'); a=p.parse_args(); print(f"Seeded {seed_database(a.count,a.reset)} orders into {settings.database_path}")
    if a.ingest:
      from backend.rag import ingest_knowledge_base
      print(ingest_knowledge_base(reset=a.reset))
