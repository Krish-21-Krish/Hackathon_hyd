from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3

app = Flask(__name__)
CORS(app)

DB_NAME = "attendance.db"


def get_conn():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # classes table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS classes (
            class_id INTEGER PRIMARY KEY,
            class_name TEXT NOT NULL,
            department TEXT
        )
        """
    )

    # students table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            reg_no TEXT PRIMARY KEY,
            student_name TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes(class_id)
        )
        """
    )

    # periods table (each period = one class hour)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS periods (
            period_id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            subject_name TEXT,
            period_date TEXT,
            period_number INTEGER,
            FOREIGN KEY (class_id) REFERENCES classes(class_id)
        )
        """
    )

    # attendance table (one row per student per period)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            period_id INTEGER,
            reg_no TEXT,
            is_present INTEGER,
            PRIMARY KEY (period_id, reg_no),
            FOREIGN KEY (period_id) REFERENCES periods(period_id),
            FOREIGN KEY (reg_no) REFERENCES students(reg_no)
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


# ========== ROUTES FOR WEB PAGES ==========

@app.route('/')
@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/check')
def check_attendance_page():
    return render_template('check_attendance.html')



@app.route('/staff')
def staff_panel():
    return render_template('staff.html')


# ========== API ROUTES - CLASSES ==========

@app.route("/api/classes", methods=["POST"])
def add_class():
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO classes (class_id, class_name, department) VALUES (?, ?, ?)",
            (data["class_id"], data["class_name"], data.get("department", "")),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Class added"}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Class ID already exists"}), 400


@app.route("/api/classes", methods=["GET"])
def get_classes():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT class_id, class_name, department FROM classes")
    rows = c.fetchall()
    conn.close()
    return jsonify(
        [
            {"class_id": r[0], "class_name": r[1], "department": r[2]}
            for r in rows
        ]
    )


# ========== API ROUTES - STUDENTS ==========

@app.route("/api/students", methods=["POST"])
def add_student():
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO students (reg_no, student_name, class_id) VALUES (?, ?, ?)",
            (data["reg_no"], data["student_name"], data["class_id"]),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Student added"}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Student registration number already exists"}), 400


@app.route("/api/students", methods=["GET"])
def get_students():
    class_id = request.args.get("class_id")
    conn = get_conn()
    c = conn.cursor()
    if class_id:
        c.execute(
            "SELECT reg_no, student_name, class_id FROM students WHERE class_id = ?",
            (class_id,),
        )
    else:
        c.execute("SELECT reg_no, student_name, class_id FROM students")
    rows = c.fetchall()
    conn.close()
    return jsonify(
        [
            {"reg_no": r[0], "student_name": r[1], "class_id": r[2]}
            for r in rows
        ]
    )


# ========== API ROUTES - BULK UPLOAD ==========

@app.route('/api/students/bulk', methods=['POST'])
def bulk_add_students():
    import csv
    import io

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.reader(stream)

        # Skip header row
        next(csv_reader, None)

        conn = get_conn()
        c = conn.cursor()

        added = 0
        skipped = 0

        for row in csv_reader:
            if len(row) < 3:  # Skip incomplete rows
                continue
            try:
                c.execute(
                    'INSERT INTO students (reg_no, student_name, class_id) VALUES (?, ?, ?)',
                    (row[0].strip(), row[1].strip(), int(row[2].strip()))
                )
                added += 1
            except (sqlite3.IntegrityError, ValueError):
                skipped += 1
                continue

        conn.commit()
        conn.close()

        return jsonify({
            'message': f'{added} students added successfully, {skipped} skipped (duplicates or errors)'
        }), 201

    except Exception as e:
        return jsonify({'error': f'Error processing file: {str(e)}'}), 400


# ========== API ROUTES - PERIODS ==========

@app.route("/api/periods", methods=["POST"])
def create_period():
    data = request.json
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO periods (class_id, subject_name, period_date, period_number)
        VALUES (?, ?, ?, ?)
        """,
        (
            data["class_id"],
            data["subject_name"],
            data["period_date"],  # e.g. "2025-12-15"
            data["period_number"],  # 1,2,3,4...
        ),
    )
    period_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"message": "Period created", "period_id": period_id}), 201


# ========== API ROUTES - ATTENDANCE ==========

@app.route("/api/attendance", methods=["POST"])
def mark_attendance():
    """
    Body example:
    {
      "period_id": 1,
      "attendance": [
        {"reg_no": "21CS001", "is_present": 1},
        {"reg_no": "21CS002", "is_present": 0}
      ]
    }
    """
    data = request.json
    period_id = data["period_id"]
    attendance_list = data["attendance"]

    conn = get_conn()
    c = conn.cursor()
    for record in attendance_list:
        c.execute(
            """
            INSERT OR REPLACE INTO attendance (period_id, reg_no, is_present)
            VALUES (?, ?, ?)
            """,
            (period_id, record["reg_no"], record["is_present"]),
        )
    conn.commit()
    conn.close()
    return jsonify({"message": "Attendance saved"}), 200


@app.route("/api/attendance/<reg_no>", methods=["GET"])
def get_overall_attendance(reg_no):
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        SELECT
            s.reg_no,
            s.student_name,
            COUNT(a.period_id) as total_classes,
            SUM(CASE WHEN a.is_present = 1 THEN 1 ELSE 0 END) as attended_classes
        FROM students s
        LEFT JOIN attendance a ON s.reg_no = a.reg_no
        WHERE s.reg_no = ?
        GROUP BY s.reg_no, s.student_name
        """,
        (reg_no,),
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Student not found"}), 404

    total_classes = row[2]
    attended_classes = row[3] if row[3] is not None else 0

    if total_classes and total_classes > 0:
        percentage = round(attended_classes * 100.0 / total_classes, 2)
    else:
        percentage = 0.0

    return jsonify(
        {
            "reg_no": row[0],
            "student_name": row[1],
            "total_classes": total_classes,
            "attended_classes": attended_classes,
            "attendance_percentage": percentage,
        }
    )


# ========== RUN APP ==========

if __name__ == "__main__":
    app.run(debug=True, port=5000)
