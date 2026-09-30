from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os
import re
import sqlite3

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_DATABASE = os.path.join(os.path.dirname(__file__), "exam_system.db")


def is_postgres():
    return bool(DATABASE_URL) and DATABASE_URL.startswith(("postgres://", "postgresql://"))


def _convert_sql(sql):
    if is_postgres():
        return sql.replace("?", "%s")
    return sql


class DBResult:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self._cloudexam_lastrowid = lastrowid

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class DBConnection:
    def __init__(self):
        self.postgres = is_postgres()
        if self.postgres:
            if not psycopg:
                raise RuntimeError("PostgreSQL is configured but psycopg is not installed. Run pip install -r requirements.txt")
            url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
            self.conn = psycopg.connect(url, row_factory=dict_row)
            self.conn.autocommit = False
        else:
            self.conn = sqlite3.connect(SQLITE_DATABASE)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, params=()):
        sql = _convert_sql(sql)
        # PostgreSQL does not expose SQLite's lastrowid. Returning the generated id
        # lets the rest of the application work with both databases.
        if self.postgres and re.match(r"\s*INSERT\s+INTO\s+(users|exams|attempts)\b", sql, re.I) and " RETURNING " not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        last_id = None
        if self.postgres and "RETURNING id" in sql.upper():
            row = cur.fetchone()
            if row:
                last_id = row["id"]
        elif not self.postgres:
            last_id = cur.lastrowid
        return DBResult(cur, last_id)

    def executescript(self, script):
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for statement in statements:
            self.execute(statement)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    return DBConnection()


def column_exists(conn, table, column):
    if conn.postgres:
        row = conn.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name=? AND column_name=?
        """, (table, column)).fetchone()
        return bool(row)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db():
    conn = get_db()
    if conn.postgres:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')),
            created_at TEXT NOT NULL
        )
        """
        conn.execute(schema)
        conn.execute("""CREATE TABLE IF NOT EXISTS exams (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT, duration INTEGER NOT NULL DEFAULT 30,
            teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            is_published INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL, question_type TEXT NOT NULL CHECK(question_type IN ('mcq','descriptive')),
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, correct_answer TEXT,
            marks INTEGER NOT NULL DEFAULT 1)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
            id SERIAL PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, started_at TEXT NOT NULL,
            submitted_at TEXT, score REAL NOT NULL DEFAULT 0, total_marks REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'in_progress')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS answers (
            id SERIAL PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE, answer_text TEXT,
            marks_awarded REAL NOT NULL DEFAULT 0, evaluated INTEGER NOT NULL DEFAULT 0)""")
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')), created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT,
            duration INTEGER NOT NULL DEFAULT 30, teacher_id INTEGER NOT NULL, is_published INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL,
            question_text TEXT NOT NULL, question_type TEXT NOT NULL CHECK(question_type IN ('mcq','descriptive')),
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, correct_answer TEXT,
            marks INTEGER NOT NULL DEFAULT 1, FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL, started_at TEXT NOT NULL, submitted_at TEXT, score REAL NOT NULL DEFAULT 0,
            total_marks REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'in_progress',
            FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE, FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL, answer_text TEXT, marks_awarded REAL NOT NULL DEFAULT 0, evaluated INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE, FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE);
        """)

    # Safe migrations for an older copy of the original project.
    migrations = []
    for table, column, dtype in migrations:
        if not column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")

    demo_users = [
        ("Administrator", "admin@example.com", "admin123", "admin"),
        ("Demo Teacher", "teacher@example.com", "teacher123", "teacher"),
        ("Demo Student", "student@example.com", "student123", "student"),
    ]
    for name, email, password, role in demo_users:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not existing:
            conn.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                         (name, email, generate_password_hash(password), role, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_user():
    return {"current_user": session.get("name"), "current_role": session.get("role"), "cloud_mode": "PostgreSQL" if is_postgres() else "SQLite"}


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip(); email = request.form["email"].strip().lower(); password = request.form["password"]
        role = request.form.get("role", "student") if request.form.get("role") in ("teacher", "student") else "student"
        if not name or not email or not password:
            flash("All fields are required.", "danger"); return render_template("register.html")
        conn = get_db()
        try:
            conn.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                         (name, email, generate_password_hash(password), role, datetime.now().isoformat()))
            conn.commit(); flash("Registration successful. Please login.", "success"); return redirect(url_for("login"))
        except Exception as exc:
            conn.rollback()
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                flash("Email is already registered.", "danger")
            else:
                flash("Registration failed. Please try again.", "danger")
            return render_template("register.html")
        finally: conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower(); password = request.form["password"]
        conn = get_db(); user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone(); conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]; session["name"] = user["name"]; session["role"] = user["role"]
            flash("Welcome back!", "success"); return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear(); flash("You have been logged out.", "success"); return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    if session["role"] == "teacher":
        exams = conn.execute("""SELECT e.*, COUNT(q.id) AS question_count FROM exams e LEFT JOIN questions q ON e.id=q.exam_id
            WHERE e.teacher_id=? GROUP BY e.id ORDER BY e.id DESC""", (session["user_id"],)).fetchall()
        conn.close(); return render_template("teacher_dashboard.html", exams=exams)
    if session["role"] == "admin":
        stats = {"users": conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"], "exams": conn.execute("SELECT COUNT(*) AS total FROM exams").fetchone()["total"],
                 "attempts": conn.execute("SELECT COUNT(*) AS total FROM attempts").fetchone()["total"], "questions": conn.execute("SELECT COUNT(*) AS total FROM questions").fetchone()["total"]}
        exams = conn.execute("""SELECT e.*, u.name AS teacher_name, COUNT(q.id) AS question_count FROM exams e JOIN users u ON u.id=e.teacher_id
            LEFT JOIN questions q ON q.exam_id=e.id GROUP BY e.id ORDER BY e.id DESC""").fetchall()
        conn.close(); return render_template("admin_dashboard.html", stats=stats, exams=exams)
    exams = conn.execute("""SELECT e.*, u.name AS teacher_name, COUNT(q.id) AS question_count,
        CASE WHEN EXISTS(SELECT 1 FROM attempts a WHERE a.exam_id=e.id AND a.student_id=?) THEN 1 ELSE 0 END AS attempted
        FROM exams e JOIN users u ON u.id=e.teacher_id LEFT JOIN questions q ON q.exam_id=e.id
        WHERE e.is_published=1 GROUP BY e.id ORDER BY e.id DESC""", (session["user_id"],)).fetchall()
    results = conn.execute("SELECT a.*, e.title FROM attempts a JOIN exams e ON e.id=a.exam_id WHERE a.student_id=? AND a.status='submitted' ORDER BY a.submitted_at DESC",
                           (session["user_id"],)).fetchall()
    conn.close(); return render_template("student_dashboard.html", exams=exams, results=results)


@app.route("/teacher/exam/create", methods=["GET", "POST"])
@role_required("teacher")
def create_exam():
    if request.method == "POST":
        title = request.form["title"].strip(); description = request.form["description"].strip(); duration = max(1, int(request.form.get("duration", 30)))
        if not title:
            flash("Exam title is required.", "danger"); return render_template("create_exam.html")
        conn = get_db(); cur = conn.execute("INSERT INTO exams(title,description,duration,teacher_id,created_at) VALUES(?,?,?,?,?)",
            (title, description, duration, session["user_id"], datetime.now().isoformat())); exam_id = cur._cloudexam_lastrowid; conn.commit(); conn.close()
        return redirect(url_for("manage_questions", exam_id=exam_id))
    return render_template("create_exam.html")


@app.route("/teacher/exam/<int:exam_id>/questions", methods=["GET", "POST"])
@role_required("teacher")
def manage_questions(exam_id):
    conn = get_db(); exam = conn.execute("SELECT * FROM exams WHERE id=? AND teacher_id=?", (exam_id, session["user_id"])).fetchone()
    if not exam:
        conn.close(); flash("Exam not found.", "danger"); return redirect(url_for("dashboard"))
    if request.method == "POST":
        qtype = request.form["question_type"]; question_text = request.form["question_text"].strip(); marks = max(1, int(request.form.get("marks", 1))); correct_answer = request.form.get("correct_answer", "").strip()
        if not question_text: flash("Question text is required.", "danger")
        elif qtype == "mcq" and correct_answer not in ("A", "B", "C", "D"): flash("Select a valid correct option.", "danger")
        else:
            conn.execute("""INSERT INTO questions(exam_id,question_text,question_type,option_a,option_b,option_c,option_d,correct_answer,marks)
                VALUES(?,?,?,?,?,?,?,?,?)""", (exam_id, question_text, qtype, request.form.get("option_a", "").strip(), request.form.get("option_b", "").strip(), request.form.get("option_c", "").strip(), request.form.get("option_d", "").strip(), correct_answer if qtype == "mcq" else None, marks))
            conn.commit(); flash("Question added.", "success")
    questions = conn.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY id", (exam_id,)).fetchall(); conn.close()
    return render_template("manage_questions.html", exam=exam, questions=questions)


@app.post("/teacher/question/<int:question_id>/delete")
@role_required("teacher")
def delete_question(question_id):
    conn = get_db(); q = conn.execute("SELECT q.id, q.exam_id FROM questions q JOIN exams e ON e.id=q.exam_id WHERE q.id=? AND e.teacher_id=?", (question_id, session["user_id"])).fetchone()
    if q:
        conn.execute("DELETE FROM questions WHERE id=?", (question_id,)); conn.commit(); flash("Question deleted.", "success"); exam_id = q["exam_id"]
    else: flash("Question not found.", "danger"); exam_id = None
    conn.close(); return redirect(url_for("manage_questions", exam_id=exam_id)) if exam_id else redirect(url_for("dashboard"))


@app.post("/teacher/exam/<int:exam_id>/publish")
@role_required("teacher")
def publish_exam(exam_id):
    conn = get_db(); exam = conn.execute("SELECT * FROM exams WHERE id=? AND teacher_id=?", (exam_id, session["user_id"])).fetchone(); count = conn.execute("SELECT COUNT(*) AS total FROM questions WHERE exam_id=?", (exam_id,)).fetchone()["total"]
    if exam and count > 0:
        conn.execute("UPDATE exams SET is_published=? WHERE id=?", (0 if exam["is_published"] else 1, exam_id)); conn.commit(); flash("Exam status updated.", "success")
    else: flash("Add at least one question before publishing.", "warning")
    conn.close(); return redirect(url_for("dashboard"))


@app.route("/exam/<int:exam_id>/start")
@role_required("student")
def start_exam(exam_id):
    conn = get_db(); exam = conn.execute("""SELECT e.*, COUNT(q.id) AS question_count FROM exams e LEFT JOIN questions q ON e.id=q.exam_id
        WHERE e.id=? AND e.is_published=1 GROUP BY e.id""", (exam_id,)).fetchone()
    if not exam or exam["question_count"] == 0:
        conn.close(); flash("This exam is not available.", "danger"); return redirect(url_for("dashboard"))
    existing = conn.execute("SELECT * FROM attempts WHERE exam_id=? AND student_id=? AND status='in_progress' ORDER BY id DESC LIMIT 1", (exam_id, session["user_id"])).fetchone()
    if existing: attempt_id = existing["id"]
    else:
        total = conn.execute("SELECT COALESCE(SUM(marks),0) AS total_marks FROM questions WHERE exam_id=?", (exam_id,)).fetchone()["total_marks"]
        cur = conn.execute("INSERT INTO attempts(exam_id,student_id,started_at,total_marks,status) VALUES(?,?,?,?,?)", (exam_id, session["user_id"], datetime.now().isoformat(), total, "in_progress")); attempt_id = cur._cloudexam_lastrowid; conn.commit()
    questions = conn.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY id", (exam_id,)).fetchall(); conn.close()
    return render_template("take_exam.html", exam=exam, questions=questions, attempt_id=attempt_id)


@app.post("/exam/<int:exam_id>/submit")
@role_required("student")
def submit_exam(exam_id):
    attempt_id = int(request.form["attempt_id"]); conn = get_db()
    attempt = conn.execute("SELECT * FROM attempts WHERE id=? AND exam_id=? AND student_id=? AND status='in_progress'", (attempt_id, exam_id, session["user_id"])).fetchone()
    if not attempt:
        conn.close(); flash("Invalid or already submitted attempt.", "danger"); return redirect(url_for("dashboard"))
    questions = conn.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY id", (exam_id,)).fetchall(); score = 0
    for q in questions:
        answer = request.form.get(f"q_{q['id']}", "").strip(); awarded = 0; evaluated = 0
        if q["question_type"] == "mcq":
            evaluated = 1
            if answer and answer.upper() == q["correct_answer"]: awarded = q["marks"]; score += q["marks"]
        conn.execute("INSERT INTO answers(attempt_id,question_id,answer_text,marks_awarded,evaluated) VALUES(?,?,?,?,?)", (attempt_id, q["id"], answer, awarded, evaluated))
    conn.execute("UPDATE attempts SET submitted_at=?, score=?, status='submitted' WHERE id=?", (datetime.now().isoformat(), score, attempt_id)); conn.commit(); conn.close()
    return redirect(url_for("result", attempt_id=attempt_id))


@app.route("/result/<int:attempt_id>")
@login_required
def result(attempt_id):
    conn = get_db(); attempt = conn.execute("""SELECT a.*, e.title, e.description, u.name AS student_name FROM attempts a JOIN exams e ON e.id=a.exam_id JOIN users u ON u.id=a.student_id WHERE a.id=?""", (attempt_id,)).fetchone()
    if not attempt:
        conn.close(); flash("Result not found.", "danger"); return redirect(url_for("dashboard"))
    if session["role"] == "student" and attempt["student_id"] != session["user_id"]:
        conn.close(); flash("Access denied.", "danger"); return redirect(url_for("dashboard"))
    questions = conn.execute("""SELECT q.*, an.answer_text, an.marks_awarded, an.evaluated
        FROM questions q LEFT JOIN answers an ON an.question_id=q.id AND an.attempt_id=? WHERE q.exam_id=? ORDER BY q.id""", (attempt_id, attempt["exam_id"])).fetchall(); conn.close()
    percentage = round((attempt["score"] / attempt["total_marks"]) * 100, 2) if attempt["total_marks"] else 0
    return render_template("result.html", attempt=attempt, questions=questions, percentage=percentage)


@app.route("/teacher/results/<int:exam_id>")
@role_required("teacher", "admin")
def exam_results(exam_id):
    conn = get_db()
    exam = conn.execute("SELECT * FROM exams WHERE id=?" + (" AND teacher_id=?" if session["role"] == "teacher" else ""), (exam_id, session["user_id"]) if session["role"] == "teacher" else (exam_id,)).fetchone()
    if not exam:
        conn.close(); flash("Exam not found.", "danger"); return redirect(url_for("dashboard"))
    attempts = conn.execute("SELECT a.*, u.name AS student_name, u.email AS student_email FROM attempts a JOIN users u ON u.id=a.student_id WHERE a.exam_id=? AND a.status='submitted' ORDER BY a.score DESC", (exam_id,)).fetchall(); conn.close()
    return render_template("exam_results.html", exam=exam, attempts=attempts)


@app.route("/teacher/attempt/<int:attempt_id>/evaluate", methods=["GET", "POST"])
@role_required("teacher", "admin")
def evaluate_attempt(attempt_id):
    conn = get_db(); attempt = conn.execute("""SELECT a.*, e.title, e.teacher_id, u.name AS student_name FROM attempts a JOIN exams e ON e.id=a.exam_id JOIN users u ON u.id=a.student_id WHERE a.id=?""", (attempt_id,)).fetchone()
    if not attempt or (session["role"] == "teacher" and attempt["teacher_id"] != session["user_id"]):
        conn.close(); flash("Attempt not found.", "danger"); return redirect(url_for("dashboard"))
    if request.method == "POST":
        answers = conn.execute("SELECT an.*, q.question_type, q.marks FROM answers an JOIN questions q ON q.id=an.question_id WHERE an.attempt_id=?", (attempt_id,)).fetchall(); score = 0
        for an in answers:
            if an["question_type"] == "descriptive":
                raw = request.form.get(f"marks_{an['id']}", "0")
                try: awarded = max(0, min(float(raw), float(an["marks"])))
                except ValueError: awarded = 0
                conn.execute("UPDATE answers SET marks_awarded=?, evaluated=1 WHERE id=?", (awarded, an["id"]))
            else: awarded = an["marks_awarded"]
            score += awarded
        conn.execute("UPDATE attempts SET score=? WHERE id=?", (score, attempt_id)); conn.commit(); flash("Evaluation saved.", "success")
    questions = conn.execute("""SELECT q.*, an.id AS answer_id, an.answer_text, an.marks_awarded, an.evaluated
        FROM questions q JOIN answers an ON an.question_id=q.id WHERE an.attempt_id=? ORDER BY q.id""", (attempt_id,)).fetchall(); conn.close()
    return render_template("evaluate_attempt.html", attempt=attempt, questions=questions)


@app.route("/student/results")
@role_required("student")
def student_results():
    conn = get_db(); results = conn.execute("SELECT a.*, e.title FROM attempts a JOIN exams e ON e.id=a.exam_id WHERE a.student_id=? AND a.status='submitted' ORDER BY a.submitted_at DESC", (session["user_id"],)).fetchall(); conn.close()
    return render_template("student_results.html", results=results)


@app.route("/student/analytics")
@role_required("student")
def student_analytics():
    conn = get_db()
    results = conn.execute("""SELECT a.*, e.title FROM attempts a JOIN exams e ON e.id=a.exam_id
        WHERE a.student_id=? AND a.status='submitted' ORDER BY a.submitted_at DESC""", (session["user_id"],)).fetchall()
    descriptive = conn.execute("""SELECT COUNT(*) AS total, SUM(CASE WHEN an.evaluated=1 THEN 1 ELSE 0 END) AS evaluated,
        COALESCE(SUM(CASE WHEN q.question_type='descriptive' THEN an.marks_awarded ELSE 0 END),0) AS descriptive_score
        FROM answers an JOIN questions q ON q.id=an.question_id JOIN attempts a ON a.id=an.attempt_id
        WHERE a.student_id=? AND a.status='submitted'""", (session["user_id"],)).fetchone()
    conn.close()
    percentages = [round((r["score"] / r["total_marks"]) * 100, 2) for r in results if r["total_marks"]]
    average = round(sum(percentages) / len(percentages), 2) if percentages else 0
    best = max(percentages) if percentages else 0
    trend = "Improving" if len(percentages) >= 2 and percentages[0] > percentages[-1] else "Needs more practice" if percentages else "No data yet"
    strengths = "Consistent performance" if average >= 70 else "Basic concepts are developing" if average >= 50 else "Keep practicing core concepts"
    weak = "Review difficult topics and descriptive answers" if average < 70 else "Focus on advanced questions and time management"
    analytics = {"average": average, "best": best, "trend": trend, "strengths": strengths, "weak": weak, "next": "Review low-scoring questions and practice regularly."}
    return render_template("student_analytics.html", results=results, analytics=analytics, descriptive=descriptive)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
