"""ExamGuard Pro — Database Initializer & Seeder.
Run: python database/init_db.py
     python database/init_db.py --demo   (also adds sample demo questions/exam for trying the app out)
"""
import sqlite3, json, uuid, bcrypt, os, sys
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "examguard.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    print("✅  Schema applied")
    return conn

def hash_pw(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
def uid(): return str(uuid.uuid4())

def seed_users(conn):
    """Creates the login accounts (student/staff/admin) — always run so
    there's a way to log in, including to self-register real accounts."""
    cur = conn.cursor()
    users = [
        (uid(),"Rahul Kumar","student@demo.com","rahul123",hash_pw("1234"),"student",
         "Computer Science and Engineering","CSE","1CS21CS001","BE","3rd","A",None,None,"[]",None),
        (uid(),"Anjali Singh","anjali@demo.com","anjali123",hash_pw("1234"),"student",
         "Computer Science and Engineering","CSE","1CS21CS002","BE","3rd","A",None,None,"[]",None),
        (uid(),"Kiran Patel","kiran@demo.com","kiran123",hash_pw("1234"),"student",
         "Mechanical Engineering","ME","1ME21ME001","BE","3rd","A",None,None,"[]",None),
        (uid(),"Prof. Priya Meena","staff@demo.com","priya123",hash_pw("1234"),"staff",
         "Computer Science and Engineering","CSE",None,None,None,None,"CSE001","Associate Professor",
         '["Data Structures","Algorithms","Web Technologies"]',None),
        (uid(),"Prof. Ravi Sharma","ravi@demo.com","ravi123",hash_pw("1234"),"staff",
         "Mechanical Engineering","ME",None,None,None,None,"ME001","Assistant Professor",
         '["Thermodynamics","Fluid Mechanics"]',None),
        (uid(),"Admin","admin@demo.com","admin123",hash_pw("admin123"),"admin",
         None,None,None,None,None,None,None,None,"[]",None),
    ]
    cur.executemany("""INSERT OR IGNORE INTO users
        (id,name,email,username,password,role,department,branch_code,usn,course,semester,section,
         employee_id,designation,subjects,phone) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", users)
    conn.commit()
    print(f"✅  Seeded {len(users)} login accounts")
    print("\n🎓  Demo credentials:")
    print("    Student → student@demo.com / 1234")
    print("    Staff   → staff@demo.com   / 1234")
    print("    Admin   → admin@demo.com   / admin123")

def seed_demo_content(conn):
    """Optional sample questions + exam, only added when --demo is passed.
    NOTE: these are illustrative placeholders — e.g. the coding question's
    "starter code" for each language is a COMPLETE working solution, not a
    scaffold, purely so you can see what a solved submission looks like end
    to end. Don't leave this exam active for real students to attempt, or
    replace/delete it (see cleanup_demo_data.py) before going live."""
    cur = conn.cursor()
    staff_row = cur.execute("SELECT id FROM users WHERE email='staff@demo.com'").fetchone()
    if not staff_row:
        print("⚠️  Demo staff account not found — run without --demo first, or seed users too.")
        return
    staff_id = staff_row["id"]

    questions = [
        (uid(),staff_id,"mcq","Web Technologies","Which HTML tag creates a hyperlink?",1,"easy",
         json.dumps(["<div>","<span>","<a>","<p>"]),2,None,1,0,1,0,None,None,None,'["python","c","cpp","java"]'),
        (uid(),staff_id,"mcq","Web Technologies","What does HTML stand for?",1,"easy",
         json.dumps(["HyperText Markup Language","HighText Markup Language","HyperText Making Language","None"]),0,None,1,0,1,0,None,None,None,'["python","c","cpp","java"]'),
        (uid(),staff_id,"mcq","Web Technologies","Which CSS property changes text color?",1,"medium",
         json.dumps(["font-color","text-color","color","fg-color"]),2,None,1,0,1,0,None,None,None,'["python","c","cpp","java"]'),
        (uid(),staff_id,"descriptive","Web Technologies","What is CSS? Explain its purpose.",2,"easy",
         None,None,None,1,0,2,0,300,None,None,'["python","c","cpp","java"]'),
        (uid(),staff_id,"descriptive","Web Technologies","What is JavaScript used for? Describe with syntax.",5,"medium",
         None,None,None,1,1,3,2,300,None,None,'["python","c","cpp","java"]'),
        (uid(),staff_id,"coding","Web Technologies","Write a program to add two numbers given as input.",5,"medium",
         None,None,None,0,0,0,0,None,
         json.dumps({"python":"# Write your Python solution here\n\n",
                     "c":"#include <stdio.h>\n\nint main() {\n    // Write your C solution here\n    return 0;\n}\n",
                     "cpp":"#include <iostream>\nusing namespace std;\n\nint main() {\n    // Write your C++ solution here\n    return 0;\n}\n",
                     "java":"public class Main {\n    public static void main(String[] args) {\n        // Write your Java solution here\n    }\n}\n"}),
         json.dumps([{"input":"5 10","expected":"15"},{"input":"20 30","expected":"50"},{"input":"100 200","expected":"300"}]),
         '["python","c","cpp","java"]'),
    ]
    cur.executemany("""INSERT OR IGNORE INTO questions
        (id,created_by,type,subject,question_text,marks,difficulty,options,correct_option,
         model_answer,has_theory,has_diagram,theory_marks,diagram_marks,
         word_limit,starter_code,test_cases,allowed_langs)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", questions)
    conn.commit()
    print(f"✅  Seeded {len(questions)} demo questions (starter code left BLANK — a scaffold, not a solved answer)")

    now = datetime.utcnow()
    e1 = uid()
    exams = [
        (e1,staff_id,"CIE-1","Web Technologies","Mixed exam covering HTML, CSS, JS.",
         "mixed",45,12,5,"No external resources. Camera must be on.","active","CSE",'["CSE"]',
         now.isoformat(),(now+timedelta(days=7)).isoformat(),
         json.dumps({"camera":True,"noise":True,"tab_switch":True,"max_tab_violations":3,"face_detection":True})),
    ]
    cur.executemany("""INSERT OR IGNORE INTO exams
        (id,created_by,title,subject,description,exam_type,duration_mins,total_marks,pass_marks,
         instructions,status,branch_code,target_branches,start_time,end_time,proctor_config)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", exams)
    conn.commit()

    all_q_ids = [r[0] for r in cur.execute(
        "SELECT id FROM questions WHERE created_by=? ORDER BY created_at", (staff_id,)).fetchall()]
    eq = [(uid(), e1, q, i+1, None) for i, q in enumerate(all_q_ids)]
    cur.executemany("INSERT OR IGNORE INTO exam_questions(id,exam_id,question_id,order_num,marks) VALUES(?,?,?,?,?)", eq)
    conn.commit()
    print(f"✅  Seeded {len(exams)} demo exam(s) with {len(all_q_ids)} questions linked")

if __name__ == "__main__":
    conn = init_db()
    seed_users(conn)
    if "--demo" in sys.argv:
        seed_demo_content(conn)
    else:
        print("\nℹ️   No sample questions/exam were created (this is now the default).")
        print("     Run with --demo if you want placeholder content to try the app out:")
        print("       python database/init_db.py --demo")
    conn.close()
    print("\n✅  Database ready!")
