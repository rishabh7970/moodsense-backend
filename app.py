from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from textblob import TextBlob
from datetime import datetime, timedelta
import random
import os
import nltk

# ==============================
# 0. NLP SETUP
# ==============================
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
    nltk.download('brown')

app = Flask(__name__)
CORS(app)

# ==============================
# 1. DATABASE CONFIG
# ==============================

DATABASE_URL = os.environ.get('DATABASE_URL')

# Fix for Render / Postgres (required)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///moodsense.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==============================
# 2. MODELS
# ==============================

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    role = db.Column(db.String(100))
    dept = db.Column(db.String(100))
    static_driver = db.Column(db.String(50), default="Unknown")

    entries = db.relationship(
        'VibeEntry',
        backref='employee',
        lazy=True,
        cascade="all, delete-orphan"
    )


class VibeEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)

    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    mood = db.Column(db.String(20))
    battery = db.Column(db.Integer)
    vent_text = db.Column(db.Text)
    sentiment = db.Column(db.Float)
    primary_driver = db.Column(db.String(50))


# ==============================
# 3. DATABASE SEEDING
# ==============================

def seed_data():
    if Employee.query.first():
        return

    print("🌱 Seeding database...")

    teams = [
        ("Manu Sharma", "Senior Dev", "Engineering"),
        ("Ishika Agarwal", "UX Lead", "Design"),
        ("Gurveer Singh", "Product Owner", "Product"),
        ("Puja Rao", "Sales Rep", "Sales"),
        ("Alex Chen", "Backend Dev", "Engineering"),
        ("Sarah Miller", "HR Manager", "HR"),
        ("David Park", "Data Analyst", "Product"),
        ("Elena Rodriguez", "QA Lead", "Engineering"),
        ("Sam Wilson", "Content Strategist", "Design"),
        ("Anita Desai", "Account Manager", "Sales")
    ]

    drivers = ["Deadlines", "Workload", "Management", "Pay/Comp", "Team"]
    moods = ["Energetic", "Tired", "Stressed", "Happy", "Bored", "Anxious"]

    sample_vents = [
        "Feeling great about the new release!",
        "Struggling with the workload lately.",
        "Management has been supportive.",
        "Communication on this project is unclear.",
        "Excited for the team outing!",
        "Worried about upcoming deadlines."
    ]

    for name, role, dept in teams:
        emp = Employee(
            name=name,
            role=role,
            dept=dept,
            static_driver=random.choice(drivers)
        )
        db.session.add(emp)
        db.session.flush()

        base_date = datetime.utcnow() - timedelta(days=7)

        for i in range(7):
            entry_date = base_date + timedelta(days=i)
            vent = random.choice(sample_vents)
            sentiment_score = TextBlob(vent).sentiment.polarity

            entry = VibeEntry(
                emp_id=emp.id,
                timestamp=entry_date,
                mood=random.choice(moods),
                battery=random.randint(25, 95),
                vent_text=vent,
                sentiment=sentiment_score,
                primary_driver=emp.static_driver
            )
            db.session.add(entry)

    db.session.commit()
    print("✅ Database seeded successfully!")


with app.app_context():
    db.create_all()
    seed_data()


# ==============================
# 4. HELPER LOGIC
# ==============================

def analyze_risk(avg_battery):
    if avg_battery < 30:
        return "High Risk"
    elif avg_battery < 60:
        return "Monitor"
    return "Stable"


# ==============================
# 5. API ROUTES
# ==============================

# ------------------------------
# Submit Vibe
# ------------------------------
@app.route('/api/submit-vibe', methods=['POST'])
def submit_vibe():
    data = request.json

    user_name = data.get('userName', 'Anonymous')
    role = data.get('role', "Team Member")
    dept = data.get('dept', "General")

    vent_text = data.get('ventText', '')
    sentiment = TextBlob(vent_text).sentiment.polarity

    primary_driver = data.get('pressureSource', 'Unknown')

    # Find or create employee
    target_emp = Employee.query.filter_by(name=user_name).first()

    if not target_emp:
        target_emp = Employee(
            name=user_name,
            role=role,
            dept=dept,
            static_driver=primary_driver
        )
        db.session.add(target_emp)
        db.session.commit()

    # Create entry
    new_entry = VibeEntry(
        emp_id=target_emp.id,
        mood=data.get('mood'),
        battery=int(data.get('battery', 50)),
        vent_text=vent_text,
        sentiment=sentiment,
        primary_driver=primary_driver
    )

    # Update current driver
    target_emp.static_driver = primary_driver

    db.session.add(new_entry)
    db.session.commit()

    return jsonify({
        "status": "success",
        "sentiment": sentiment
    })


# ------------------------------
# HR Dashboard Data
# ------------------------------
@app.route('/api/hr-dashboard', methods=['GET'])
def get_hr_dashboard():
    employees = Employee.query.all()

    employee_list = []
    dept_map = {}

    for emp in employees:
        entries = VibeEntry.query.filter_by(emp_id=emp.id)\
            .order_by(VibeEntry.timestamp.asc())\
            .all()

        formatted_history = []

        for e in entries:
            formatted_history.append({
                "timestamp": e.timestamp.isoformat(),
                "battery": e.battery,
                "sentiment": e.sentiment,
                "primary_driver": e.primary_driver,
                "vent_text": e.vent_text
            })

        if formatted_history:
            recent = formatted_history[-3:]
            avg_battery = int(sum(d['battery'] for d in recent) / len(recent))
            current_driver = formatted_history[-1]["primary_driver"]
        else:
            avg_battery = 50
            current_driver = emp.static_driver

        employee_list.append({
            "id": emp.id,
            "name": emp.name,
            "role": emp.role,
            "dept": emp.dept,
            "risk_status": analyze_risk(avg_battery),
            "avg_battery": avg_battery,
            "primary_driver": current_driver,
            "history": formatted_history
        })

        if emp.dept not in dept_map:
            dept_map[emp.dept] = []

        dept_map[emp.dept].append(avg_battery)

    final_dept_data = []

    for dept, batteries in dept_map.items():
        avg = int(sum(batteries) / len(batteries))
        final_dept_data.append({
            "name": dept,
            "energy": avg
        })

    return jsonify({
        "employees": employee_list,
        "department_data": final_dept_data
    })


# ==============================
# 6. RUN SERVER
# ==============================

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
