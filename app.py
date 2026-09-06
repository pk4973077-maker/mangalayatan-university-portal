from flask import Flask, render_template, request, redirect, send_from_directory, send_file, session, url_for
import os
import io
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import json
from database import save_uploaded_file, get_uploaded_file, delete_uploaded_file


app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "development-secret-key")


# =========================================================
# GLOBAL BROWSER HISTORY + CACHE CONTROL
# =========================================================

@app.after_request
def global_navigation_control(response):

    # Browser ko purane pages cache karne se roko
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    # Sirf HTML pages par JavaScript add karo
    content_type = response.headers.get("Content-Type", "")

    if "text/html" in content_type:

        html = response.get_data(as_text=True)

        global_navigation_script = """
<script>
(function () {

    if (window.__globalNavigationInstalled) {
        return;
    }

    window.__globalNavigationInstalled = true;


    // =====================================================
    // POST FORMS
    // =====================================================

    document.addEventListener("submit", function (event) {

        const form = event.target;

        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const method = (
            form.getAttribute("method") || "GET"
        ).toLowerCase();

        if (method !== "post") {
            return;
        }

        if (
            form.target &&
            form.target !== "_self"
        ) {
            return;
        }

        const action = (
            form.getAttribute("action") ||
            window.location.href
        );

        const url = new URL(
            action,
            window.location.href
        );

        if (
            url.origin !== window.location.origin
        ) {
            return;
        }

        event.preventDefault();

        const submitButton = form.querySelector(
            "button[type='submit'], input[type='submit']"
        );

        if (submitButton) {
            submitButton.disabled = true;
        }

        fetch(
            url.href,
            {
                method: "POST",
                body: new FormData(form),
                credentials: "same-origin",
                redirect: "follow"
            }
        )
        .then(function (response) {

            if (response.redirected) {

                // History entry create nahi hogi
                window.location.replace(
                    response.url
                );

                return;
            }

            return response.text();

        })
        .then(function (html) {

            if (!html) {
                return;
            }

            document.open();
            document.write(html);
            document.close();

        })
        .catch(function () {

            form.submit();

        });

    }, true);



    // =====================================================
    // DELETE / RESET GET LINKS
    // =====================================================

    document.addEventListener("click", function (event) {

        const link = event.target.closest("a");

        if (!link) {
            return;
        }

        const href = link.getAttribute("href");

        if (!href) {
            return;
        }

        const url = new URL(
            href,
            window.location.href
        );


        // Sirf same website ke links
        if (
            url.origin !== window.location.origin
        ) {
            return;
        }


        const path = url.pathname;


        // =================================================
        // DATA DELETE / RESET ACTIONS
        // =================================================

        const isActionLink =
            path.startsWith("/delete-") ||
            path.startsWith("/reset-");


        if (!isActionLink) {
            return;
        }


        // Normal browser navigation rok do
        event.preventDefault();


        // Action request
        fetch(
            url.href,
            {
                method: "GET",
                credentials: "same-origin",
                redirect: "follow"
            }
        )
        .then(function (response) {

            /*
             * replace() use karne se
             * Delete/Reset ke liye
             * extra history entry nahi banegi.
             */

            window.location.replace(
                response.url
            );

        })
        .catch(function () {

            // Agar fetch fail ho to normal link
            window.location.href = url.href;

        });

    }, true);

})();
</script>
"""


        # </body> se pehle script insert karo
        lower_html = html.lower()

        body_position = lower_html.rfind(
            "</body>"
        )

        if body_position != -1:

            html = (
                html[:body_position]
                + global_navigation_script
                + html[body_position:]
            )

            response.set_data(html)


    return response

# =========================
# FOLDERS
# =========================

UPLOAD_FOLDER = "uploads"
SYLLABUS_FOLDER = "uploads/syllabus"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["SYLLABUS_FOLDER"] = SYLLABUS_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SYLLABUS_FOLDER, exist_ok=True)

# =========================
# ALLOWED FILES
# =========================

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


NOTES_FILE = "notes.json"
SYLLABUS_FILE = "syllabus.json"
SUBJECTS_FILE = "subjects.json"
DEPARTMENTS_FILE = "departments.json"
COURSES_FILE = "courses.json"

def get_admin_courses():

    courses = []

    if os.path.exists(COURSES_FILE):

        try:
            with open(COURSES_FILE, "r") as file:
                courses = json.load(file)

        except:
            courses = []

    return courses

@app.route("/admin-subjects", methods=["GET", "POST"])
def admin_subjects():

    subjects = []
    courses = []

    # =========================
    # SUBJECTS LOAD
    # =========================

    if os.path.exists(SUBJECTS_FILE):

        try:
            with open(SUBJECTS_FILE, "r") as file:
                subjects = json.load(file)

            if not isinstance(subjects, list):
                subjects = []

        except:
            subjects = []


    # =========================
    # COURSES LOAD
    # Course Management se
    # =========================

    courses = get_admin_courses()


    # =========================
    # ADD SUBJECT
    # =========================

    if request.method == "POST":

        subject_name = request.form.get(
            "subject_name", ""
        ).strip()

        course = request.form.get(
            "course", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()


        # =========================
        # VALIDATION
        # =========================

        if not subject_name or not course or not semester:

            return "Please fill all fields."


        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:

            return "Invalid Semester."


        # =========================
        # CHECK COURSE
        # Admin Course Management
        # se hi course allowed hoga
        # =========================

        valid_course = None

        for item in courses:

            if isinstance(item, dict):

                course_name = str(
                    item.get("name")
                    or item.get("course_name")
                    or item.get("course")
                    or ""
                ).strip()

            else:

                course_name = str(item).strip()


            if course_name.lower() == course.lower():

                valid_course = course_name
                break


        if not valid_course:

            return "Invalid Course."


        # =========================
        # DUPLICATE CHECK
        # =========================

        for subject in subjects:

            existing_course = str(
                subject.get("course", "")
            ).strip()

            # Purane records ke liye
            # department ko ignore kiya jayega

            if (
                str(
                    subject.get(
                        "subject_name", ""
                    )
                ).strip().lower()
                == subject_name.lower()

                and existing_course.lower()
                == valid_course.lower()

                and str(
                    subject.get(
                        "semester", ""
                    )
                ).strip()
                == semester
            ):

                return (
                    "This Subject already exists "
                    "for this Course and Semester."
                )


        # =========================
        # SUBJECT ID
        # =========================

        existing_ids = []

        for subject in subjects:

            existing_ids.append(
                str(
                    subject.get(
                        "subject_id", ""
                    )
                ).strip()
            )


        number = len(subjects) + 1

        subject_id = (
            "SUB" + str(number).zfill(3)
        )


        while subject_id in existing_ids:

            number += 1

            subject_id = (
                "SUB" + str(number).zfill(3)
            )


        # =========================
        # SUBJECT DATA
        # =========================

        subject = {

            "subject_id":
                subject_id,

            "subject_name":
                subject_name,

            "course":
                valid_course,

            "semester":
                semester
        }


        subjects.append(subject)


        # =========================
        # SAVE
        # =========================

        with open(
            SUBJECTS_FILE,
            "w"
        ) as file:

            json.dump(
                subjects,
                file,
                indent=4
            )


        return redirect(
            "/admin-subjects"
        )


    # =========================
    # SHOW PAGE
    # =========================

    return render_template(
        "admin_subjects.html",
        subjects=subjects,
        courses=courses
    )

@app.route("/delete-subject/<subject_id>")
def delete_subject(subject_id):

    subjects = []

    # Purane subjects read karo
    if os.path.exists(SUBJECTS_FILE):

        try:
            with open(SUBJECTS_FILE, "r") as file:
                subjects = json.load(file)

        except:
            subjects = []

    # Selected subject ko remove karo
    updated_subjects = []

    for subject in subjects:

        if str(subject.get("subject_id")).strip() != str(subject_id).strip():
            updated_subjects.append(subject)

    # Updated list save karo
    with open(SUBJECTS_FILE, "w") as file:

        json.dump(
            updated_subjects,
            file,
            indent=4
        )

    return redirect("/admin-subjects")

# =========================
# MAIN PAGE
# =========================

@app.route("/")
def home():
    return render_template("index.html")


# =========================
# STUDENT LOGIN
# =========================

@app.route("/student-login", methods=["GET", "POST"])
def student_login():

    if request.method == "POST":

        enrollment = request.form.get(
            "student_id", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        students = []

        # -------------------------
        # STUDENTS LOAD
        # -------------------------

        if os.path.exists(STUDENTS_FILE):

            try:

                with open(
                    STUDENTS_FILE,
                    "r"
                ) as file:

                    students = json.load(file)

                if not isinstance(students, list):
                    students = []

            except:

                students = []

        # -------------------------
        # FIND STUDENT
        # -------------------------

        student = None

        for item in students:

            old_enrollment = str(
                item.get(
                    "enrollment",
                    ""
                )
            ).strip()

            if old_enrollment.lower() == enrollment.lower():

                student = item
                break

        # -------------------------
        # INVALID STUDENT
        # -------------------------

        if student is None:

            return (
                "Invalid Enrollment Number "
                "or Password"
            )

        # -------------------------
        # STUDENT ID
        # -------------------------

        student_id = str(
            student.get(
                "student_id",
                ""
            )
        ).strip()

        if not student_id:

            return (
                "Invalid Enrollment Number "
                "or Password"
            )

        # -------------------------
        # PASSWORD CHECK
        # -------------------------

        login_success = False

        stored_hash = str(
            student.get(
                "password_hash",
                ""
            )
        ).strip()

        # Existing valid password
        if stored_hash:

            try:

                if check_password_hash(
                    stored_hash,
                    password
                ):

                    login_success = True

            except:

                login_success = False

        # -------------------------
        # DEFAULT PASSWORD
        # -------------------------

        # Student ID is default password
        # Example: STU001

        if not login_success and password == student_id:

            student["password_hash"] = (
                generate_password_hash(
                    student_id
                )
            )

            with open(
                STUDENTS_FILE,
                "w"
            ) as file:

                json.dump(
                    students,
                    file,
                    indent=4
                )

            login_success = True

        # -------------------------
        # FINAL PASSWORD CHECK
        # -------------------------

        if not login_success:

            return (
                "Invalid Enrollment Number "
                "or Password"
            )

        # -------------------------
        # STUDENT SESSION
        # -------------------------

        session["student_id"] = student_id

        session["student_enrollment"] = (
            str(
                student.get(
                    "enrollment",
                    ""
                )
            ).strip()
        )

        session["student_course"] = str(
            student.get(
                "course",
                ""
            )
        ).strip()

        session["student_semester"] = str(
            student.get(
                "semester",
                ""
            )
        ).strip()

        session["student_section"] = str(
            student.get(
                "section",
                ""
            )
        ).strip().upper()

        return redirect(
            "/student-dashboard"
        )

    return render_template(
        "student_login.html"
    )


# =========================
# STUDENT DASHBOARD
# =========================

@app.route("/student-dashboard")
def student_dashboard():

    # Student login check
    if "student_enrollment" not in session:
        return redirect(url_for("student_login"))

    student_enrollment = str(
        session.get("student_enrollment", "")
    ).strip()

    # Student data load
    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)
        except:
            students = []

    # Logged-in student find
    student = None

    for item in students:
        if str(
            item.get("enrollment", "")
        ).strip() == student_enrollment:

            student = item
            break

    if student is None:
        return "Student not found.", 404

    return render_template(
        "student_dashboard.html",
        student=student
    )

    # -------------------------
    # LOGIN CHECK
    # -------------------------

    if not session.get("student_id"):

        return redirect(
            "/student-login"
        )

    # -------------------------
    # STUDENT DATA LOAD
    # -------------------------

    students = []

    if os.path.exists(STUDENTS_FILE):

        try:

            with open(
                STUDENTS_FILE,
                "r"
            ) as file:

                students = json.load(file)

        except:

            students = []

    # -------------------------
    # CURRENT STUDENT
    # -------------------------

    student = None

    current_student_id = str(
        session.get(
            "student_id",
            ""
        )
    ).strip()

    for item in students:

        if str(
            item.get(
                "student_id",
                ""
            )
        ).strip() == current_student_id:

            student = item
            break

    # -------------------------
    # STUDENT NOT FOUND
    # -------------------------

    if student is None:

        session.pop(
            "student_id",
            None
        )

        session.pop(
            "student_enrollment",
            None
        )

        session.pop(
            "student_course",
            None
        )

        session.pop(
            "student_semester",
            None
        )

        session.pop(
            "student_section",
            None
        )

        return redirect(
            "/student-login"
        )

    # -------------------------
    # DASHBOARD
    # -------------------------

    return render_template(
        "student_dashboard.html",
        student=student
    )


   


# =========================
# STUDENT SYLLABUS
# =========================

@app.route("/syllabus")
def syllabus():

    # Student login check
    if "student_enrollment" not in session:
        return redirect(url_for("student_login"))

    student_enrollment = str(
        session.get("student_enrollment", "")
    ).strip()

    # =========================
    # STUDENTS LOAD
    # =========================

    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)
        except:
            students = []

    # =========================
    # CURRENT STUDENT FIND
    # =========================

    student = None

    for item in students:
        if (
            str(item.get("enrollment", "")).strip()
            == student_enrollment
        ):
            student = item
            break

    if not student:
        return "Student not found", 404

    # =========================
    # STUDENT DETAILS
    # =========================

    student_course = str(
        student.get("course", "")
    ).strip().lower()

    student_semester = str(
        student.get("semester", "")
    ).strip()

    student_section = str(
        student.get("section", "")
    ).strip().upper()

    # =========================
    # SYLLABUS LOAD
    # =========================

    all_syllabuses = []

    if os.path.exists(SYLLABUS_FILE):
        try:
            with open(SYLLABUS_FILE, "r") as file:
                all_syllabuses = json.load(file)
        except:
            all_syllabuses = []

    # =========================
    # FILTER SYLLABUS
    # Course + Semester + Section
    # =========================

    syllabuses = []

    for syllabus_item in all_syllabuses:

        syllabus_course = str(
            syllabus_item.get("course", "")
        ).strip().lower()

        syllabus_semester = str(
            syllabus_item.get("semester", "")
        ).strip()

        syllabus_section = str(
            syllabus_item.get("section", "")
        ).strip().upper()

        if (
            syllabus_course == student_course
            and syllabus_semester == student_semester
            and syllabus_section == student_section
        ):
            syllabuses.append(syllabus_item)

    # =========================
    # SHOW STUDENT SYLLABUS
    # =========================

    return render_template(
        "syllabus.html",
        syllabuses=syllabuses,
        student=student
    )


# =========================
# OPEN SYLLABUS FILE
# =========================

@app.route("/syllabus-file/<filename>")
def syllabus_file(filename):

    stored = get_uploaded_file(filename)
    if not stored:
        return "File not found", 404
    return send_file(
        io.BytesIO(bytes(stored["content"])),
        mimetype=stored["content_type"],
        download_name=filename
    )


# =========================
# STUDENT ATTENDANCE
# =========================

@app.route("/attendance")
def attendance():

    # Student login check
    if "student_enrollment" not in session:
        return redirect(url_for("student_login"))

    student_enrollment = str(
        session.get("student_enrollment", "")
    ).strip()

    # =========================
    # STUDENTS LOAD
    # =========================

    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)
        except:
            students = []

    # =========================
    # CURRENT STUDENT FIND
    # =========================

    student = None

    for item in students:
        if (
            str(item.get("enrollment", "")).strip()
            == student_enrollment
        ):
            student = item
            break

    if not student:
        return "Student not found", 404

    # =========================
    # STUDENT DETAILS
    # =========================

    student_course = str(
        student.get("course", "")
    ).strip().lower()

    student_semester = str(
        student.get("semester", "")
    ).strip()

    student_section = str(
        student.get("section", "")
    ).strip().upper()

    # =========================
    # ATTENDANCE LOAD
    # =========================

    all_attendance = []

    if os.path.exists("attendance.json"):
        try:
            with open("attendance.json", "r") as file:
                all_attendance = json.load(file)
        except:
            all_attendance = []

    # =========================
    # CURRENT STUDENT ATTENDANCE
    # =========================

    student_attendance = []

    for record in all_attendance:

        record_course = str(
            record.get("course", "")
        ).strip().lower()

        record_semester = str(
            record.get("semester", "")
        ).strip()

        record_section = str(
            record.get("section", "")
        ).strip().upper()

        record_student = str(
            record.get("student_id", "")
        ).strip()

        if (
            record_student == student_enrollment
            and record_course == student_course
            and record_semester == student_semester
            and record_section == student_section
        ):
            student_attendance.append(record)

    # =========================
    # SUBJECT WISE ATTENDANCE
    # =========================

    subject_attendance = {}

    total_classes = 0
    total_present = 0

    for record in student_attendance:

        subject = str(
            record.get("subject", "Unknown")
        ).strip()

        status = str(
            record.get("status", "")
        ).strip()

        if subject not in subject_attendance:
            subject_attendance[subject] = {
                "total": 0,
                "present": 0,
                "absent": 0,
                "percentage": 0
            }

        subject_attendance[subject]["total"] += 1
        total_classes += 1

        if status == "Present":
            subject_attendance[subject]["present"] += 1
            total_present += 1
        else:
            subject_attendance[subject]["absent"] += 1

    # =========================
    # PERCENTAGE
    # =========================

    for subject in subject_attendance:

        data = subject_attendance[subject]

        if data["total"] > 0:
            data["percentage"] = round(
                (data["present"] / data["total"]) * 100,
                2
            )

    if total_classes > 0:
        attendance_percentage = round(
            (total_present / total_classes) * 100,
            2
        )
    else:
        attendance_percentage = 0

    # =========================
    # SHOW ATTENDANCE
    # =========================

    return render_template(
        "attendance.html",
        student=student,
        subject_attendance=subject_attendance,
        total_classes=total_classes,
        total_present=total_present,
        attendance_percentage=attendance_percentage,
        daily_history=student_attendance
    )

# =========================
# MANAGE ATTENDANCE
# =========================

@app.route("/manage-attendance", methods=["GET", "POST"])
def manage_attendance():

    # =========================
    # STUDENTS LOAD
    # =========================
    all_students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                all_students = json.load(file)
        except:
            all_students = []


    # =========================
    # SUBJECTS LOAD
    # =========================
    subjects = []

    if os.path.exists(SUBJECTS_FILE):
        try:
            with open(SUBJECTS_FILE, "r") as file:
                subjects = json.load(file)
        except:
            subjects = []


    # =========================
    # COURSES FROM ADMIN
    # =========================
    courses = get_admin_courses()


    # =========================
    # CURRENT FACULTY
    # =========================
    faculty_id = str(
        session.get("faculty_id", "")
    ).strip()

    faculty_name = str(
        session.get("faculty_name", "")
    ).strip()


    # =========================
    # POST - SAVE ATTENDANCE
    # =========================
    if request.method == "POST":

        course = request.form.get(
            "course", ""
        ).strip()

        subject = request.form.get(
            "subject", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()

        section = request.form.get(
            "section", ""
        ).strip()

        date = request.form.get(
            "date", ""
        ).strip()

        present_students = request.form.getlist(
            "present"
        )


        # =========================
        # LOGIN CHECK
        # =========================
        if not faculty_id:
            return redirect("/faculty-login")


        # =========================
        # BASIC VALIDATION
        # =========================
        if (
            not course
            or not subject
            or not semester
            or not section
            or not date
        ):
            return "Please fill all fields."


        # =========================
        # SEMESTER VALIDATION
        # =========================
        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:
            return "Invalid Semester."


        # =========================
        # SECTION VALIDATION
        # =========================
        if section not in [
            "A", "B", "C", "D"
        ]:
            return "Invalid Section."


        # =========================
        # COURSE VALIDATION
        # =========================
        valid_course = False

        for item in courses:

            if (
                str(item.get("name", "")).strip().lower()
                == course.lower()
            ):
                valid_course = True
                break

        if not valid_course:
            return "Invalid Course."


        # =========================
        # SUBJECT VALIDATION
        # COURSE + SEMESTER
        # =========================
        valid_subject = False

        for item in subjects:

            if (
                str(
                    item.get("subject_name", "")
                ).strip().lower()
                == subject.lower()

                and

                str(
                    item.get("course", "")
                ).strip().lower()
                == course.lower()

                and

                str(
                    item.get("semester", "")
                ).strip()
                == semester
            ):
                valid_subject = True
                break


        if not valid_subject:
            return "Invalid Subject for selected Course and Semester."


        # =========================
        # FIND STUDENTS
        # COURSE + SEMESTER + SECTION
        # =========================
        selected_students = []

        for student in all_students:

            student_course = str(
                student.get("course", "")
            ).strip()

            student_semester = str(
                student.get("semester", "")
            ).strip()

            student_section = str(
                student.get("section", "")
            ).strip().upper()


            if (
                student_course.lower()
                == course.lower()

                and

                student_semester
                == semester

                and

                student_section
                == section.upper()
            ):
                selected_students.append(student)


        # =========================
        # ATTENDANCE FILE LOAD
        # =========================
        attendance_data = []

        if os.path.exists("attendance.json"):

            try:
                with open(
                    "attendance.json",
                    "r"
                ) as file:

                    attendance_data = json.load(file)

            except:
                attendance_data = []


        # =========================
        # SAVE EACH STUDENT
        # =========================
        for student in selected_students:

            enrollment = str(
                student.get("enrollment", "")
            ).strip()

            student_name = str(
                student.get("name", "")
            ).strip()


            if enrollment in present_students:
                status = "Present"
            else:
                status = "Absent"


            record = {
                "faculty_id": faculty_id,
                "faculty_name": faculty_name,

                "date": date,

                "course": course,
                "subject": subject,

                "semester": semester,
                "section": section,

                "student_id": enrollment,
                "student_name": student_name,

                "status": status
            }


            attendance_data.append(record)


        # =========================
        # SAVE ATTENDANCE.JSON
        # =========================
        with open(
            "attendance.json",
            "w"
        ) as file:

            json.dump(
                attendance_data,
                file,
                indent=4
            )


        # =========================
        # AFTER SAVE
        # =========================
        return redirect(
            "/manage-attendance"
        )


    # =========================
    # SHOW ATTENDANCE PAGE
    # =========================
    return render_template(
        "manage_attendance.html",

        students=all_students,

        courses=courses,

        subjects=subjects,

        faculty_name=faculty_name
    )

# =========================
# FACULTY ATTENDANCE HISTORY
# =========================

@app.route("/faculty-attendance-history", methods=["GET", "POST"])
def faculty_attendance_history():

    # =========================
    # CURRENT FACULTY
    # =========================

    faculty_id = str(
        session.get("faculty_id", "")
    ).strip()

    faculty_name = str(
        session.get("faculty_name", "")
    ).strip()

    if not faculty_id:
        return redirect("/faculty-login")


    # =========================
    # ATTENDANCE LOAD
    # =========================

    attendance_data = []

    if os.path.exists("attendance.json"):
        try:
            with open("attendance.json", "r") as file:
                attendance_data = json.load(file)
        except:
            attendance_data = []


    # =========================
    # SELECTED FILTERS
    # =========================

    selected_date = request.values.get(
        "date", ""
    ).strip()

    selected_section = request.values.get(
        "section", ""
    ).strip()

    selected_subject = request.values.get(
        "subject", ""
    ).strip()


    # =========================
    # FACULTY SUBJECTS
    # =========================

    faculty_subjects = []

    for record in attendance_data:

        record_faculty = str(
            record.get("faculty_id", "")
        ).strip()

        if record_faculty != faculty_id:
            continue

        subject = str(
            record.get("subject", "")
        ).strip()

        if subject and subject not in faculty_subjects:
            faculty_subjects.append(subject)

    faculty_subjects.sort()


    # =========================
    # FACULTY SECTIONS
    # =========================

    faculty_sections = []

    for record in attendance_data:

        record_faculty = str(
            record.get("faculty_id", "")
        ).strip()

        if record_faculty != faculty_id:
            continue

        section = str(
            record.get("section", "")
        ).strip()

        if section and section not in faculty_sections:
            faculty_sections.append(section)

    faculty_sections.sort()


    # =========================
    # FILTER ATTENDANCE
    # =========================

    attendance_records = []

    if (
        selected_date
        and selected_section
        and selected_subject
    ):

        for record in attendance_data:

            record_faculty = str(
                record.get("faculty_id", "")
            ).strip()

            record_date = str(
                record.get("date", "")
            ).strip()

            record_section = str(
                record.get("section", "")
            ).strip()

            record_subject = str(
                record.get("subject", "")
            ).strip()


            if (
                record_faculty == faculty_id
                and record_date == selected_date
                and record_section.upper()
                == selected_section.upper()
                and record_subject.lower()
                == selected_subject.lower()
            ):

                attendance_records.append(record)


    # =========================
    # PAGE
    # =========================

    return render_template(
        "faculty_attendance_history.html",
        faculty_name=faculty_name,
        faculty_subjects=faculty_subjects,
        faculty_sections=faculty_sections,
        selected_date=selected_date,
        selected_section=selected_section,
        selected_subject=selected_subject,
        attendance_records=attendance_records
    )

# =========================
# STUDENT NOTES
# =========================

@app.route("/notes")
def student_notes():

    # Student login check
    if "student_enrollment" not in session:
        return redirect(url_for("student_login"))

    # Login ke time save hua enrollment number
    student_enrollment = str(
        session.get("student_enrollment", "")
    ).strip()

    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as f:
                students = json.load(f)
        except:
            students = []

    # Enrollment number se student find karo
    student = None

    for s in students:

        if str(
            s.get("enrollment", "")
        ).strip() == student_enrollment:

            student = s
            break

    if not student:
        return "Student not found", 404

    # Student ki Course + Semester + Section
    student_course = str(
        student.get("course", "")
    ).strip().lower()

    student_semester = str(
        student.get("semester", "")
    ).strip()

    student_section = str(
        student.get("section", "")
    ).strip().upper()

    notes = []

    if os.path.exists(NOTES_FILE):

        try:
            with open(NOTES_FILE, "r") as f:
                all_notes = json.load(f)
        except:
            all_notes = []

        # Sirf matching Course + Semester + Section
        for note in all_notes:

            note_course = str(
                note.get("course", "")
            ).strip().lower()

            note_semester = str(
                note.get("semester", "")
            ).strip()

            note_section = str(
                note.get("section", "")
            ).strip().upper()

            if (
                note_course == student_course
                and note_semester == student_semester
                and note_section == student_section
            ):
                notes.append(note)

    return render_template(
        "notes.html",
        notes=notes,
        student=student
    )


# =========================
# OPEN NOTES / UPLOADED FILE
# =========================

@app.route("/uploads/<filename>")
def uploaded_file(filename):

    # -----------------------------
    # STUDENT ACCESS
    # -----------------------------
    if "student_id" in session:

        student_id = str(
            session.get("student_id", "")
        ).strip()

        students = []

        if os.path.exists(STUDENTS_FILE):

            try:
                with open(STUDENTS_FILE, "r") as f:
                    students = json.load(f)
            except:
                students = []

        student = None

        for s in students:

            if str(
                s.get("enrollment", "")
            ).strip() == student_id:

                student = s
                break

        if not student:
            return "Unauthorized", 403

        student_course = str(
            student.get("course", "")
        ).strip().lower()

        student_semester = str(
            student.get("semester", "")
        ).strip()

        student_section = str(
            student.get("section", "")
        ).strip().upper()

        notes = []

        if os.path.exists(NOTES_FILE):

            try:
                with open(NOTES_FILE, "r") as f:
                    notes = json.load(f)
            except:
                notes = []

        # File ko matching note me dhundo
        for note in notes:

            if note.get("filename") != filename:
                continue

            note_course = str(
                note.get("course", "")
            ).strip().lower()

            note_semester = str(
                note.get("semester", "")
            ).strip()

            note_section = str(
                note.get("section", "")
            ).strip().upper()

            # Student is allowed only for exact match
            if (
                note_course == student_course
                and note_semester == student_semester
                and note_section == student_section
            ):

                stored = get_uploaded_file(filename)
                if not stored:
                    return "File not found", 404
                return send_file(
                    io.BytesIO(bytes(stored["content"])),
                    mimetype=stored["content_type"],
                    download_name=filename
                )

            return "Unauthorized", 403

        return "File not found", 404

    # -----------------------------
    # FACULTY ACCESS
    # -----------------------------
    if "faculty_id" in session:

        faculty_id = str(
            session.get("faculty_id", "")
        ).strip()

        notes = []

        if os.path.exists(NOTES_FILE):

            try:
                with open(NOTES_FILE, "r") as f:
                    notes = json.load(f)
            except:
                notes = []

        for note in notes:

            if (
                note.get("filename") == filename
                and str(
                    note.get("faculty_id", "")
                ).strip() == faculty_id
            ):

                stored = get_uploaded_file(filename)
                if not stored:
                    return "File not found", 404
                return send_file(
                    io.BytesIO(bytes(stored["content"])),
                    mimetype=stored["content_type"],
                    download_name=filename
                )

        return "Unauthorized", 403

    return redirect(url_for("student_login"))


# =========================
# ADMISSION LOGIN
# =========================

@app.route("/admission-login", methods=["GET", "POST"])
def admission_login():

    if request.method == "POST":

        admission_id = request.form.get(
            "admission_id",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        ).strip()

        if (
            admission_id.upper() == "ADM001"
            and password == "admission123"
        ):

            return redirect("/admission-dashboard")

        return "Invalid Admission ID or Password"

    return render_template("admission_login.html")


# =========================
# ADMISSION DASHBOARD
# =========================

@app.route("/admission-dashboard")
def admission_dashboard():

    applications = []

    try:

        with open("applications.json", "r") as file:
            applications = json.load(file)

    except:

        applications = []

    total_applications = len(applications)

    pending = 0
    approved = 0
    rejected = 0

    for application in applications:

        status = application.get(
            "status",
            "Pending"
        )

        if status == "Pending":
            pending += 1

        elif status == "Approved":
            approved += 1

        elif status == "Rejected":
            rejected += 1

    return render_template(
        "admission_dashboard.html",
        total_applications=total_applications,
        pending=pending,
        approved=approved,
        rejected=rejected
    )


# =========================
# NEW ADMISSION
# =========================

@app.route("/new-admission", methods=["GET", "POST"])
def new_admission():

    if request.method == "POST":

        applications = []

        try:

            with open("applications.json", "r") as file:
                applications = json.load(file)

        except:

            applications = []

        application = {

            "application_id":
                "APP" + str(
                    len(applications) + 1
                ).zfill(3),

            "student_name":
                request.form.get("student_name"),

            "father_name":
                request.form.get("father_name"),

            "dob":
                request.form.get("dob"),

            "gender":
                request.form.get("gender"),

            "course":
                request.form.get("course"),

            "mobile":
                request.form.get("mobile"),

            "email":
                request.form.get("email"),

            "address":
                request.form.get("address"),

            "tenth":
                request.form.get("tenth"),

            "twelfth":
                request.form.get("twelfth"),

            "status":
                "Pending"
        }

        applications.append(application)

        with open("applications.json", "w") as file:

            json.dump(
                applications,
                file,
                indent=4
            )

        return redirect("/applications")

    return render_template(
        "new_admission.html"
    )


# =========================
# APPLICATIONS
# =========================

@app.route("/applications")
def applications():

    application_data = []

    try:

        with open("applications.json", "r") as file:
            application_data = json.load(file)

    except:

        application_data = []

    return render_template(
        "applications.html",
        applications=application_data
    )


# =========================
# APPROVE APPLICATION
# =========================

@app.route("/approve-application/<application_id>")
def approve_application(application_id):

    applications = []

    try:

        with open("applications.json", "r") as file:
            applications = json.load(file)

    except:

        applications = []

    for application in applications:

        if application["application_id"] == application_id:

            application["status"] = "Approved"

            break

    with open("applications.json", "w") as file:

        json.dump(
            applications,
            file,
            indent=4
        )

    return redirect("/applications")


# =========================
# REJECT APPLICATION
# =========================

@app.route("/reject-application/<application_id>")
def reject_application(application_id):

    applications = []

    try:

        with open("applications.json", "r") as file:
            applications = json.load(file)

    except:

        applications = []

    for application in applications:

        if application["application_id"] == application_id:

            application["status"] = "Rejected"

            break

    with open("applications.json", "w") as file:

        json.dump(
            applications,
            file,
            indent=4
        )

    return redirect("/applications")


# =========================
# ADMISSION STATUS
# =========================

@app.route("/admission-status", methods=["GET", "POST"])
def admission_status():

    application = None
    not_found = False

    if request.method == "POST":

        application_id = request.form.get(
            "application_id",
            ""
        ).strip().upper()

        try:

            with open("applications.json", "r") as file:
                applications_data = json.load(file)

        except:

            applications_data = []

        for item in applications_data:

            if (
                item.get(
                    "application_id",
                    ""
                ).upper()
                == application_id
            ):

                application = item

                break

        if application is None:

            not_found = True

    return render_template(
        "admission_status.html",
        application=application,
        not_found=not_found
    )


# =========================
# ADMISSION DOCUMENTS
# =========================

@app.route(
    "/admission-documents",
    methods=["GET", "POST"]
)
def admission_documents():

    if request.method == "POST":

        application_id = request.form.get(
            "application_id",
            ""
        ).strip().upper()

        files = [

            (
                "tenth_marksheet",
                request.files.get(
                    "tenth_marksheet"
                )
            ),

            (
                "twelfth_marksheet",
                request.files.get(
                    "twelfth_marksheet"
                )
            ),

            (
                "identity_document",
                request.files.get(
                    "identity_document"
                )
            )
        ]

        for document_name, document_file in files:

            if (
                document_file
                and document_file.filename != ""
            ):

                filename = (
                    application_id
                    + "_"
                    + document_name
                    + "_"
                    + secure_filename(
                        document_file.filename
                    )
                )

                save_uploaded_file(document_file, filename)

        return "Documents Uploaded Successfully!"

    return render_template(
        "admission_documents.html"
    )


# =========================
# VIEW DOCUMENTS
# =========================

@app.route("/view-documents")
def view_documents():

    documents = []

    if os.path.exists("uploads"):

        for filename in os.listdir("uploads"):

            parts = filename.split("_", 2)

            if len(parts) == 3:

                application_id = parts[0]

                document_type = parts[1]

                documents.append({

                    "application_id":
                        application_id,

                    "document_type":
                        document_type,

                    "filename":
                        filename
                })

    return render_template(
        "view_documents.html",
        documents=documents
    )


# =========================
# FACULTY LOGIN
# =========================

@app.route(
    "/faculty-login",
    methods=["GET", "POST"]
)
def faculty_login():

    if request.method == "POST":

        faculty_id = request.form.get(
            "faculty_id", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        faculty_list = []

        if os.path.exists(FACULTY_FILE):

            try:

                with open(
                    FACULTY_FILE,
                    "r"
                ) as file:

                    faculty_list = json.load(file)

            except:

                faculty_list = []

        faculty = None

        # Faculty ID find karo
        for item in faculty_list:

            if str(
                item.get("faculty_id", "")
            ).strip() == faculty_id:

                faculty = item
                break

        if faculty is None:

            return "Invalid Faculty ID or Password"

        # Faculty ID
        actual_faculty_id = str(
            faculty.get("faculty_id", "")
        ).strip()

        # Password check
        if faculty.get("password_hash"):

            # Changed password
            if not check_password_hash(
                faculty["password_hash"],
                password
            ):

                return "Invalid Faculty ID or Password"

        else:

            # First login: password = Faculty ID
            if password != actual_faculty_id:

                return "Invalid Faculty ID or Password"

            # Password ko hash karke save karo
            faculty["password_hash"] = generate_password_hash(
                actual_faculty_id
            )

            # Purana plaintext password remove karo
            faculty.pop("password", None)

            with open(
                FACULTY_FILE,
                "w"
            ) as file:

                json.dump(
                    faculty_list,
                    file,
                    indent=4
                )

        # Faculty session

        session["faculty_id"] = actual_faculty_id
        session["faculty_name"] = str(
    faculty.get("name", "")
).strip()
        return redirect(
            "/faculty-dashboard"
        )

    return render_template(
        "faculty_login.html"
    )

@app.route("/faculty-change-password", methods=["GET", "POST"])
def faculty_change_password():

    # Faculty login hai ya nahi
    if "faculty_id" not in session:
        return redirect("/faculty-login")

    faculty_id = session["faculty_id"]

    faculty_list = []

    if os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)

        except:
            faculty_list = []

    faculty = None

    # Logged-in faculty find karo
    for item in faculty_list:

        if str(
            item.get("faculty_id", "")
        ).strip() == str(faculty_id).strip():

            faculty = item
            break

    if faculty is None:
        return "Faculty not found."

    if request.method == "POST":

        current_password = request.form.get(
            "current_password", ""
        )

        new_password = request.form.get(
            "new_password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if (
            not current_password
            or not new_password
            or not confirm_password
        ):
            return "Please fill all fields."

        # Current password check
        if not check_password_hash(
            faculty.get("password_hash", ""),
            current_password
        ):
            return "Current password is incorrect."

        # New password match
        if new_password != confirm_password:
            return "New passwords do not match."

        # Same password check
        if current_password == new_password:
            return "New password must be different from current password."

        # New password hash karo
        faculty["password_hash"] = generate_password_hash(
            new_password
        )

        # Purana plaintext password remove
        faculty.pop("password", None)

        with open(FACULTY_FILE, "w") as file:

            json.dump(
                faculty_list,
                file,
                indent=4
            )

        return redirect("/faculty-dashboard")

    return render_template(
        "faculty_change_password.html"
    )

@app.route("/reset-faculty-password/<faculty_id>")
def reset_faculty_password(faculty_id):

    faculty_list = []

    if os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)

        except:
            faculty_list = []

    faculty_found = False

    for faculty in faculty_list:

        if str(
            faculty.get("faculty_id", "")
        ).strip() == str(faculty_id).strip():

            # Password ko Faculty ID par reset karo
            faculty["password_hash"] = generate_password_hash(
                faculty_id
            )

            # Agar purana plaintext password hai
            # to remove kar do
            faculty.pop("password", None)

            faculty_found = True
            break

    if not faculty_found:
        return "Faculty not found."

    with open(FACULTY_FILE, "w") as file:

        json.dump(
            faculty_list,
            file,
            indent=4
        )

    return redirect("/admin-faculty")

@app.route("/edit-faculty/<faculty_id>", methods=["GET", "POST"])
def edit_faculty(faculty_id):

    faculty_list = []

    if os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)

            if not isinstance(faculty_list, list):
                faculty_list = []

        except:
            faculty_list = []


    # ==============================
    # FIND FACULTY
    # ==============================

    faculty = None

    for item in faculty_list:

        if str(
            item.get("faculty_id", "")
        ).strip().lower() == str(
            faculty_id
        ).strip().lower():

            faculty = item
            break


    if faculty is None:
        return "Faculty not found."


    # ==============================
    # WHERE DID EDIT OPEN FROM?
    # ==============================

    from_page = request.args.get(
        "from",
        ""
    )

    search = request.args.get(
        "q",
        ""
    ).strip()


    # ==============================
    # UPDATE FACULTY
    # ==============================

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        department = request.form.get(
            "department",
            ""
        ).strip()


        if not name or not department:
            return "Please fill all fields."


        # ==============================
        # VALIDATE DEPARTMENT
        # ==============================

        departments = []

        if os.path.exists(DEPARTMENTS_FILE):

            try:
                with open(
                    DEPARTMENTS_FILE,
                    "r"
                ) as file:

                    departments = json.load(file)

                if not isinstance(
                    departments,
                    list
                ):
                    departments = []

            except:
                departments = []


        valid_department = None

        for dept in departments:

            dept_name = str(
                dept.get("name", "")
            ).strip()

            if dept_name.lower() == department.lower():

                valid_department = dept_name
                break


        if not valid_department:
            return "Invalid Department."


        faculty["name"] = name
        faculty["department"] = valid_department


        # ==============================
        # SAVE
        # ==============================

        with open(
            FACULTY_FILE,
            "w"
        ) as file:

            json.dump(
                faculty_list,
                file,
                indent=4
            )


        # ==============================
        # RETURN TO SEARCH
        # ==============================

        if from_page == "search":

            return redirect(
                "/admin-search-faculty?q="
                + search
            )


        # ==============================
        # RETURN TO FACULTY MANAGEMENT
        # ==============================

        return redirect(
            "/admin-faculty"
        )


    # ==============================
    # EDIT PAGE
    # ==============================

    return render_template(
        "edit_faculty.html",
        faculty=faculty,
        from_page=from_page,
        search=search
    )


# =========================
# FACULTY DASHBOARD
# =========================

@app.route("/faculty-dashboard")
def faculty_dashboard():

    # Faculty login check
    if "faculty_id" not in session:
        return redirect(url_for("faculty_login"))

    faculty_id = str(
        session.get("faculty_id", "")
    ).strip()

    # Faculty data load
    faculty_list = []

    if os.path.exists(FACULTY_FILE):
        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)
        except:
            faculty_list = []

    # Logged-in faculty find
    faculty = None

    for item in faculty_list:
        if str(
            item.get("faculty_id", "")
        ).strip() == faculty_id:
            faculty = item
            break

    if faculty is None:
        return "Faculty not found.", 404

    return render_template(
        "faculty_dashboard.html",
        faculty=faculty
    )


# =========================
# FACULTY PROFILE
# =========================

@app.route(
    "/faculty-profile",
    methods=["GET", "POST"]
)
def faculty_profile():

    profile_file = "faculty_profile.json"

    profile = {

        "faculty_id": "FAC001",

        "name": "Faculty Member",

        "department":
            "Computer Science & Engineering",

        "email":
            "faculty@university.com",

        "designation":
            "Assistant Professor"
    }

    if os.path.exists(profile_file):

        try:

            with open(profile_file, "r") as file:
                profile = json.load(file)

        except:

            pass

    if request.method == "POST":

        profile["name"] = request.form.get(
            "name"
        )

        profile["department"] = request.form.get(
            "department"
        )

        profile["email"] = request.form.get(
            "email"
        )

        profile["designation"] = request.form.get(
            "designation"
        )

        with open(profile_file, "w") as file:

            json.dump(
                profile,
                file,
                indent=4
            )

        return redirect(
            "/faculty-profile"
        )

    return render_template(
        "faculty_profile.html",
        profile=profile
    )


# =========================
# ATTENDANCE HISTORY
# =========================

@app.route("/attendance-history")
def attendance_history():

    attendance_records = []

    # Attendance data पढ़ना
    if os.path.exists("attendance.json"):

        try:
            with open("attendance.json", "r") as file:
                all_attendance = json.load(file)

        except:
            all_attendance = []

    else:
        all_attendance = []


    # फिलहाल logged-in student
    student_id = "STU001"


    # Students की information पढ़ना
    students = []

    if os.path.exists(STUDENTS_FILE):

        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

        except:
            students = []


    # Current student ढूँढना
    student = None

    for item in students:

        if item.get("student_id") == student_id:

            student = item
            break


    # Student की attendance
    if student:

        student_department = student.get(
            "department", ""
        )

        student_semester = student.get(
            "semester", ""
        )

        student_section = student.get(
            "section", ""
        )

        student_enrollment = student.get(
            "enrollment", ""
        )


        # सिर्फ current student की attendance
        for record in all_attendance:

            if (
                record.get("department")
                == student_department

                and

                record.get("semester")
                == student_semester

                and

                record.get("section")
                == student_section

                and

                record.get("student_id")
                == student_enrollment
            ):

                attendance_records.append(record)


    # Attendance percentage
    total_classes = len(attendance_records)

    present_classes = 0

    for record in attendance_records:

        if record.get("status") == "Present":
            present_classes += 1


    if total_classes > 0:

        attendance_percentage = round(
            (present_classes / total_classes) * 100,
            2
        )

    else:

        attendance_percentage = 0


    return render_template(
        "attendance_history.html",
        attendance_records=attendance_records,
        total_classes=total_classes,
        present_classes=present_classes,
        attendance_percentage=attendance_percentage
    )



# =========================
# UPLOAD NOTES - FACULTY + COURSE + SECTION
# =========================

@app.route("/upload-notes", methods=["GET", "POST"])
def upload_notes():

    # Faculty login check
    if "faculty_id" not in session:
        return redirect(url_for("faculty_login"))

    faculty_id = str(session.get("faculty_id", "")).strip()
    faculty_name = str(session.get("faculty_name", "")).strip()

    # Faculty name session me nahi hai to faculty file se lo
    if not faculty_name:

        faculties = []

        if os.path.exists(FACULTY_FILE):
            try:
                with open(FACULTY_FILE, "r") as file:
                    faculties = json.load(file)
            except:
                faculties = []

        for faculty in faculties:

            if str(faculty.get("faculty_id", "")).strip() == faculty_id:
                faculty_name = str(
                    faculty.get("name", "")
                ).strip()
                break

    # Admin courses
    courses = get_admin_courses()

    # Admin subjects
    subjects = []

    if os.path.exists(SUBJECTS_FILE):
        try:
            with open(SUBJECTS_FILE, "r") as file:
                subjects = json.load(file)
        except:
            subjects = []

    if request.method == "POST":

        course = str(
            request.form.get("course", "")
        ).strip()

        semester = str(
            request.form.get("semester", "")
        ).strip()

        section = str(
            request.form.get("section", "")
        ).strip().upper()

        subject = str(
            request.form.get("subject", "")
        ).strip()

        title = str(
            request.form.get("title", "")
        ).strip()

        file = request.files.get("file")

        # Validation
        valid_courses = []

        for c in courses:

            if isinstance(c, dict):
                name = c.get("course_name") or c.get("name")
            else:
                name = c

            if name:
                valid_courses.append(str(name).strip())

        valid_course = None

        for c in valid_courses:

            if c.lower() == course.lower():
                valid_course = c
                break

        if not valid_course:
            return "Invalid course"

        if semester not in [str(i) for i in range(1, 9)]:
            return "Invalid semester"

        if section not in ["A", "B", "C", "D"]:
            return "Invalid section"

        # Subject must belong to selected course + semester
        valid_subject = None

        for s in subjects:

            s_course = str(
                s.get("course", "")
            ).strip()

            s_semester = str(
                s.get("semester", "")
            ).strip()

            s_name = str(
                s.get("subject_name", "")
            ).strip()

            if (
                s_course.lower() == valid_course.lower()
                and s_semester == semester
                and s_name.lower() == subject.lower()
            ):
                valid_subject = s_name
                break

        if not valid_subject:
            return "Invalid subject"

        if not file or not file.filename:
            return "Please select a file"

        # Allowed file types
        if not allowed_file(file.filename):
            return "Only PDF, JPG, JPEG and PNG files are allowed"

        # Secure filename
        filename = secure_filename(file.filename)

        # Unique filename
        import uuid

        filename = str(uuid.uuid4()) + "_" + filename

        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        save_uploaded_file(file, filename)

        notes = []

        if os.path.exists(NOTES_FILE):
            try:
                with open(NOTES_FILE, "r") as f:
                    notes = json.load(f)
            except:
                notes = []

        # Save note
        notes.append({
            "faculty_id": faculty_id,
            "faculty_name": faculty_name,
            "course": valid_course,
            "semester": semester,
            "section": section,
            "subject": valid_subject,
            "title": title,
            "filename": filename
        })

        with open(NOTES_FILE, "w") as f:
            json.dump(notes, f, indent=4)

        return redirect(url_for("upload_notes"))

    # Only this faculty's notes
    my_notes = []

    if os.path.exists(NOTES_FILE):

        try:
            with open(NOTES_FILE, "r") as f:
                notes = json.load(f)
        except:
            notes = []

        for index, note in enumerate(notes):

            if str(
                note.get("faculty_id", "")
            ).strip() == faculty_id:

                note["_index"] = index
                my_notes.append(note)

    return render_template(
        "upload_notes.html",
        faculty_name=faculty_name,
        courses=courses,
        subjects=subjects,
        notes=my_notes
    )


@app.route("/delete-note/<int:note_index>", methods=["POST", "GET"])
def delete_note(note_index):

    # Faculty login check
    if "faculty_id" not in session:
        return redirect(url_for("faculty_login"))

    faculty_id = str(
        session.get("faculty_id", "")
    ).strip()

    notes = []

    if os.path.exists(NOTES_FILE):

        try:
            with open(NOTES_FILE, "r") as f:
                notes = json.load(f)
        except:
            notes = []

    if note_index < 0 or note_index >= len(notes):
        return redirect(url_for("upload_notes"))

    note = notes[note_index]

    # केवल अपना note delete कर सकता है
    if str(
        note.get("faculty_id", "")
    ).strip() != faculty_id:
        return "Unauthorized", 403

    filename = note.get("filename", "")

    # Delete physical file
    if filename:
        delete_uploaded_file(filename)

    notes.pop(note_index)

    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f, indent=4)

    return redirect(url_for("upload_notes"))

# =========================
# FACULTY SYLLABUS UPLOAD
# =========================

@app.route("/faculty-syllabus", methods=["GET", "POST"])
def faculty_syllabus():

    if "faculty_id" not in session:
        return redirect(url_for("faculty_login"))

    faculty_id = str(session.get("faculty_id", "")).strip()
    faculty_name = str(session.get("faculty_name", "")).strip()

    # Faculty name session में न हो तो file से लो
    if not faculty_name:

        faculties = []

        if os.path.exists(FACULTY_FILE):
            try:
                with open(FACULTY_FILE, "r") as file:
                    faculties = json.load(file)
            except:
                faculties = []

        for faculty in faculties:
            if str(
                faculty.get("faculty_id", "")
            ).strip() == faculty_id:

                faculty_name = str(
                    faculty.get("name", "")
                ).strip()

                break

    # Admin Course Management से courses
    courses = get_admin_courses()

    # Admin Subject Management से subjects
    subjects = []

    if os.path.exists(SUBJECTS_FILE):
        try:
            with open(SUBJECTS_FILE, "r") as file:
                subjects = json.load(file)
        except:
            subjects = []

    if request.method == "POST":

        course = str(
            request.form.get("course", "")
        ).strip()

        semester = str(
            request.form.get("semester", "")
        ).strip()

        section = str(
            request.form.get("section", "")
        ).strip().upper()

        subject = str(
            request.form.get("subject", "")
        ).strip()

        file = request.files.get("syllabus_file")

        # -----------------------------
        # COURSE VALIDATION
        # -----------------------------

        valid_courses = []

        for c in courses:

            if isinstance(c, dict):
                course_name = (
                    c.get("course_name")
                    or c.get("name")
                )
            else:
                course_name = c

            if course_name:
                valid_courses.append(
                    str(course_name).strip()
                )

        valid_course = None

        for c in valid_courses:

            if c.lower() == course.lower():
                valid_course = c
                break

        if not valid_course:
            return "Invalid course"

        # -----------------------------
        # SEMESTER VALIDATION
        # -----------------------------

        if semester not in [
            str(i) for i in range(1, 9)
        ]:
            return "Invalid semester"

        # -----------------------------
        # SECTION VALIDATION
        # -----------------------------

        if section not in ["A", "B", "C", "D"]:
            return "Invalid section"

        # -----------------------------
        # SUBJECT VALIDATION
        # Course + Semester के according
        # -----------------------------

        valid_subject = None

        for s in subjects:

            s_course = str(
                s.get("course", "")
            ).strip()

            s_semester = str(
                s.get("semester", "")
            ).strip()

            s_name = str(
                s.get("subject_name", "")
            ).strip()

            if (
                s_course.lower() == valid_course.lower()
                and s_semester == semester
                and s_name.lower() == subject.lower()
            ):
                valid_subject = s_name
                break

        if not valid_subject:
            return "Invalid subject"

        # -----------------------------
        # FILE VALIDATION
        # -----------------------------

        if not file or not file.filename:
            return "Please select a syllabus file"

        if not allowed_file(file.filename):
            return "Only PDF, JPG, JPEG and PNG files are allowed"

        filename = secure_filename(file.filename)

        import uuid

        filename = str(uuid.uuid4()) + "_" + filename

        os.makedirs(
            SYLLABUS_FOLDER,
            exist_ok=True
        )

        save_uploaded_file(file, filename)

        # -----------------------------
        # OLD SYLLABUS DATA
        # -----------------------------

        syllabuses = []

        if os.path.exists(SYLLABUS_FILE):

            try:
                with open(
                    SYLLABUS_FILE,
                    "r"
                ) as f:

                    syllabuses = json.load(f)

            except:
                syllabuses = []

        # -----------------------------
        # SAVE SYLLABUS
        # -----------------------------

        syllabuses.append({

            "faculty_id": faculty_id,

            "faculty_name": faculty_name,

            "course": valid_course,

            "semester": semester,

            "section": section,

            "subject": valid_subject,

            "filename": filename

        })

        with open(
            SYLLABUS_FILE,
            "w"
        ) as f:

            json.dump(
                syllabuses,
                f,
                indent=4
            )

        return redirect(
            url_for("faculty_syllabus")
        )

    # -----------------------------
    # ONLY OWN SYLLABUS
    # -----------------------------

    my_syllabuses = []

    if os.path.exists(SYLLABUS_FILE):

        try:
            with open(
                SYLLABUS_FILE,
                "r"
            ) as f:

                all_syllabuses = json.load(f)

        except:
            all_syllabuses = []

        for index, syllabus in enumerate(
            all_syllabuses
        ):

            if str(
                syllabus.get("faculty_id", "")
            ).strip() == faculty_id:

                syllabus["_index"] = index

                my_syllabuses.append(
                    syllabus
                )

    return render_template(
        "faculty_syllabus.html",
        faculty_name=faculty_name,
        courses=courses,
        subjects=subjects,
        syllabuses=my_syllabuses
    )


@app.route(
    "/delete-syllabus/<int:syllabus_index>",
    methods=["POST", "GET"]
)
def delete_syllabus(syllabus_index):

    if "faculty_id" not in session:
        return redirect(url_for("faculty_login"))

    faculty_id = str(
        session.get("faculty_id", "")
    ).strip()

    syllabuses = []

    if os.path.exists(SYLLABUS_FILE):

        try:
            with open(
                SYLLABUS_FILE,
                "r"
            ) as f:

                syllabuses = json.load(f)

        except:
            syllabuses = []

    if (
        syllabus_index < 0
        or syllabus_index >= len(syllabuses)
    ):
        return redirect(
            url_for("faculty_syllabus")
        )

    syllabus = syllabuses[syllabus_index]

    # केवल अपना syllabus delete कर सकता है
    if str(
        syllabus.get("faculty_id", "")
    ).strip() != faculty_id:

        return "Unauthorized", 403

    filename = syllabus.get(
        "filename",
        ""
    )

    if filename:
        delete_uploaded_file(filename)

    syllabuses.pop(syllabus_index)

    with open(
        SYLLABUS_FILE,
        "w"
    ) as f:

        json.dump(
            syllabuses,
            f,
            indent=4
        )

    return redirect(
        url_for("faculty_syllabus")
    )

# =========================
# FACULTY SEND NOTICE
# =========================

NOTICES_FILE = "notices.json"


# =========================
# FACULTY SEND NOTICE
# =========================

NOTICES_FILE = "notices.json"


@app.route("/send-notice", methods=["GET", "POST"])
def send_notice():

    # -------------------------
    # Faculty login check
    # -------------------------
    faculty_id = session.get("faculty_id")

    if not faculty_id:
        return redirect("/faculty-login")

    faculty_name = str(
        session.get("faculty_name", "")
    ).strip()

    # -------------------------
    # Faculty name fallback
    # -------------------------
    if not faculty_name:

        faculty_list = []

        if os.path.exists(FACULTY_FILE):
            try:
                with open(FACULTY_FILE, "r") as file:
                    faculty_list = json.load(file)
            except:
                faculty_list = []

        for faculty in faculty_list:

            if str(
                faculty.get("faculty_id", "")
            ).strip() == str(faculty_id).strip():

                faculty_name = str(
                    faculty.get("name", "")
                ).strip()

                session["faculty_name"] = faculty_name
                break

    # -------------------------
    # Admin Course Management
    # -------------------------
    courses = get_admin_courses()

    clean_courses = []

    for item in courses:

        if isinstance(item, dict):

            course_name = str(
                item.get("name")
                or item.get("course_name")
                or item.get("course")
                or ""
            ).strip()

        else:

            course_name = str(item).strip()

        if course_name:
            clean_courses.append(course_name)

    # -------------------------
    # SEND NEW NOTICE
    # -------------------------
    if request.method == "POST":

        course = request.form.get(
            "course", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()

        section = request.form.get(
            "section", ""
        ).strip().upper()

        title = request.form.get(
            "title", ""
        ).strip()

        message = request.form.get(
            "message", ""
        ).strip()

        # -------------------------
        # Required fields
        # -------------------------
        if (
            not course
            or not semester
            or not section
            or not title
            or not message
        ):
            return "Please fill all fields."

        # -------------------------
        # Semester validation
        # -------------------------
        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:
            return "Invalid Semester."

        # -------------------------
        # Section validation
        # -------------------------
        if section not in [
            "A", "B", "C", "D"
        ]:
            return "Invalid Section."

        # -------------------------
        # Course validation
        # Admin Course Management
        # -------------------------
        valid_course = None

        for item in clean_courses:

            if item.lower() == course.lower():

                valid_course = item
                break

        if not valid_course:
            return "Invalid Course."

        # -------------------------
        # Existing notices
        # -------------------------
        notices = []

        if os.path.exists(NOTICES_FILE):

            try:
                with open(
                    NOTICES_FILE,
                    "r"
                ) as file:

                    notices = json.load(file)

                if not isinstance(notices, list):
                    notices = []

            except:
                notices = []

        # -------------------------
        # New Notice
        # -------------------------
        notice = {

            "faculty_id":
                str(faculty_id).strip(),

            "faculty_name":
                faculty_name,

            "course":
                valid_course,

            "semester":
                semester,

            "section":
                section,

            "title":
                title,

            "message":
                message
        }

        notices.append(notice)

        # -------------------------
        # Save
        # -------------------------
        with open(
            NOTICES_FILE,
            "w"
        ) as file:

            json.dump(
                notices,
                file,
                indent=4
            )

        return redirect("/send-notice")

    # =========================
    # SHOW FACULTY'S OWN NOTICES
    # =========================

    all_notices = []

    if os.path.exists(NOTICES_FILE):

        try:
            with open(
                NOTICES_FILE,
                "r"
            ) as file:

                all_notices = json.load(file)

            if not isinstance(all_notices, list):
                all_notices = []

        except:
            all_notices = []

    notices = []

    for index, notice in enumerate(all_notices):

        if str(
            notice.get("faculty_id", "")
        ).strip() == str(faculty_id).strip():

            notice_copy = dict(notice)

            # Original JSON index
            # delete ke liye
            notice_copy["_index"] = index

            notices.append(notice_copy)

    return render_template(
        "send_notice.html",
        notices=notices,
        courses=clean_courses,
        faculty_name=faculty_name
    )


# =========================
# STUDENT NOTICE BOARD
# =========================

@app.route("/notices")
def student_notices():

    # Student login check
    if "student_enrollment" not in session:
        return redirect(url_for("student_login"))

    student_enrollment = str(
        session.get("student_enrollment", "")
    ).strip()

    # Students load
    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)
        except:
            students = []

    # Current student find
    student = None

    for item in students:
        if str(item.get("enrollment", "")).strip() == student_enrollment:
            student = item
            break

    if not student:
        return "Student not found", 404

    # Student Course + Semester + Section
    student_course = str(
        student.get("course", "")
    ).strip().lower()

    student_semester = str(
        student.get("semester", "")
    ).strip()

    student_section = str(
        student.get("section", "")
    ).strip().upper()

    # Notices load
    all_notices = []

    if os.path.exists(NOTICES_FILE):
        try:
            with open(NOTICES_FILE, "r") as file:
                all_notices = json.load(file)
        except:
            all_notices = []

    # Matching notices only
    filtered_notices = []

    for notice in all_notices:

        notice_course = str(
            notice.get("course", "")
        ).strip().lower()

        notice_semester = str(
            notice.get("semester", "")
        ).strip()

        notice_section = str(
            notice.get("section", "")
        ).strip().upper()

        if (
            notice_course == student_course
            and notice_semester == student_semester
            and notice_section == student_section
        ):
            filtered_notices.append(notice)

    return render_template(
        "notices.html",
        notices=filtered_notices,
        student=student
    )


# =========================
# DELETE NOTICE
# =========================

@app.route("/delete-notice/<int:notice_index>")
def delete_notice(notice_index):

    # -------------------------
    # Faculty login check
    # -------------------------
    faculty_id = session.get("faculty_id")

    if not faculty_id:
        return redirect("/faculty-login")

    # -------------------------
    # Notices load
    # -------------------------
    notices = []

    if os.path.exists(NOTICES_FILE):

        try:
            with open(
                NOTICES_FILE,
                "r"
            ) as file:

                notices = json.load(file)

        except:
            notices = []

    # -------------------------
    # Index validation
    # -------------------------
    if not (
        0 <= notice_index < len(notices)
    ):
        return redirect("/send-notice")

    notice = notices[notice_index]

    # -------------------------
    # OWNERSHIP CHECK
    # Faculty sirf apna
    # notice delete kar sakta hai
    # -------------------------
    notice_faculty_id = str(
        notice.get("faculty_id", "")
    ).strip()

    if notice_faculty_id != str(
        faculty_id
    ).strip():

        return redirect("/send-notice")

    # -------------------------
    # Delete
    # -------------------------
    notices.pop(notice_index)

    with open(
        NOTICES_FILE,
        "w"
    ) as file:

        json.dump(
            notices,
            file,
            indent=4
        )

    return redirect("/send-notice")

# =========================
# FACULTY HOLIDAY INFORMATION
# =========================

HOLIDAYS_FILE = "holidays.json"


@app.route("/holiday-information", methods=["GET", "POST"])
def holiday_information():

    # =========================
    # FACULTY LOGIN CHECK
    # =========================

    faculty_id = session.get("faculty_id", "").strip()
    faculty_name = session.get("faculty_name", "").strip()

    if not faculty_id:
        return redirect("/faculty-login")


    # =========================
    # FACULTY NAME FALLBACK
    # =========================

    if not faculty_name and os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculties = json.load(file)

            for faculty in faculties:

                if str(
                    faculty.get("faculty_id", "")
                ).strip() == faculty_id:

                    faculty_name = str(
                        faculty.get("name", "")
                    ).strip()

                    break

        except:
            pass


    # =========================
    # ADMIN COURSES READ
    # =========================

    courses = get_admin_courses()

    course_names = []

    for course in courses:

        if isinstance(course, dict):

            course_name = str(
                course.get("course", "")
                or course.get("name", "")
            ).strip()

        else:

            course_name = str(course).strip()

        if course_name:
            course_names.append(course_name)


    # =========================
    # HOLIDAY DATA READ
    # =========================

    holidays_data = []

    if os.path.exists(HOLIDAYS_FILE):

        try:

            with open(HOLIDAYS_FILE, "r") as file:
                holidays_data = json.load(file)

        except:

            holidays_data = []


    # =========================
    # ADD HOLIDAY
    # =========================

    if request.method == "POST":

        course = request.form.get(
            "course", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()

        section = request.form.get(
            "section", ""
        ).strip()

        holiday_date = request.form.get(
            "holiday_date", ""
        ).strip()

        holiday_name = request.form.get(
            "holiday_name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()


        # =========================
        # REQUIRED FIELDS
        # =========================

        if (
            not course
            or not semester
            or not section
            or not holiday_date
            or not holiday_name
        ):

            return "Please fill all required fields."


        # =========================
        # COURSE VALIDATION
        # ADMIN COURSE MANAGEMENT
        # =========================

        valid_course = None

        for admin_course in course_names:

            if admin_course.lower() == course.lower():

                valid_course = admin_course

                break


        if not valid_course:

            return "Invalid Course."


        # =========================
        # SEMESTER VALIDATION
        # =========================

        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:

            return "Invalid Semester."


        # =========================
        # SECTION VALIDATION
        # =========================

        if section not in [
            "A", "B", "C", "D"
        ]:

            return "Invalid Section."


        # =========================
        # SAVE HOLIDAY
        # =========================

        holiday = {

            "faculty_id": faculty_id,

            "faculty_name": faculty_name,

            "course": valid_course,

            "semester": semester,

            "section": section,

            "date": holiday_date,

            "name": holiday_name,

            "description": description
        }


        holidays_data.append(holiday)


        # =========================
        # SAVE JSON
        # =========================

        with open(
            HOLIDAYS_FILE,
            "w"
        ) as file:

            json.dump(
                holidays_data,
                file,
                indent=4
            )


        return redirect(
            "/holiday-information"
        )


    # =========================
    # SHOW ONLY CURRENT FACULTY
    # =========================

    my_holidays = []

    for index, holiday in enumerate(
        holidays_data
    ):

        if not isinstance(holiday, dict):
            continue

        if str(
            holiday.get("faculty_id", "")
        ).strip() == faculty_id:

            holiday_copy = dict(holiday)

            # Original JSON index
            holiday_copy["_index"] = index

            my_holidays.append(
                holiday_copy
            )


    # =========================
    # SHOW PAGE
    # =========================

    return render_template(
        "holiday_information.html",

        holidays=my_holidays,

        courses=course_names,

        faculty_name=faculty_name
    )




# =========================
# STUDENT HOLIDAY INFORMATION
# =========================

@app.route("/holidays")
def student_holidays():

    # Student login check
    if "student_enrollment" not in session:
        return redirect(url_for("student_login"))

    student_enrollment = str(
        session.get("student_enrollment", "")
    ).strip()

    # =========================
    # STUDENTS LOAD
    # =========================

    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)
        except:
            students = []

    # =========================
    # CURRENT STUDENT FIND
    # =========================

    student = None

    for item in students:
        if (
            str(item.get("enrollment", "")).strip()
            == student_enrollment
        ):
            student = item
            break

    if not student:
        return "Student not found", 404

    # =========================
    # STUDENT DETAILS
    # =========================

    student_course = str(
        student.get("course", "")
    ).strip().lower()

    student_semester = str(
        student.get("semester", "")
    ).strip()

    student_section = str(
        student.get("section", "")
    ).strip().upper()

    # =========================
    # HOLIDAYS LOAD
    # =========================

    all_holidays = []

    if os.path.exists(HOLIDAYS_FILE):
        try:
            with open(HOLIDAYS_FILE, "r") as file:
                all_holidays = json.load(file)
        except:
            all_holidays = []

    # =========================
    # FILTER HOLIDAYS
    # Course + Semester + Section
    # =========================

    holidays = []

    for holiday in all_holidays:

        holiday_course = str(
            holiday.get("course", "")
        ).strip().lower()

        holiday_semester = str(
            holiday.get("semester", "")
        ).strip()

        holiday_section = str(
            holiday.get("section", "")
        ).strip().upper()

        if (
            holiday_course == student_course
            and holiday_semester == student_semester
            and holiday_section == student_section
        ):
            holidays.append(holiday)

    # =========================
    # SHOW HOLIDAYS
    # =========================

    return render_template(
        "holidays.html",
        holidays=holidays,
        student=student
    )

# =========================
# STUDENT INFORMATION
# =========================

STUDENTS_FILE = "students.json"


@app.route("/student-information")
def student_information():

    students = []

    # students.json se data read karo
    if os.path.exists(STUDENTS_FILE):

        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

        except:
            students = []


    # Enrollment number search
    search_enrollment = request.args.get(
        "enrollment", ""
    ).strip()


    # Student initially None rahega
    student = None


    # Check ki search ki gayi hai ya nahi
    searched = False


    if search_enrollment:

        searched = True

        for item in students:

            if (
                str(item.get("enrollment", "")).strip()
                == search_enrollment
            ):

                student = item
                break


    return render_template(
        "student_information.html",

        student=student,

        search_enrollment=search_enrollment,

        searched=searched
    )

# =========================
# ADMIN LOGIN
# =========================

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        admin_id = request.form.get("admin_id", "").strip()
        password = request.form.get("password", "").strip()

        if admin_id == "ADMIN001" and password == "admin123":
            return redirect("/admin-dashboard")

        return "Invalid Admin ID or Password"

    return render_template("admin_login.html")


# =========================
# ADMIN DASHBOARD
# =========================

@app.route("/admin-dashboard")
def admin_dashboard():

    # =========================
    # STUDENTS COUNT
    # =========================

    students = []

    try:
        if os.path.exists(STUDENTS_FILE):

            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

            if not isinstance(students, list):
                students = []

    except Exception:
        students = []

    total_students = len(students)


    # =========================
    # FACULTY COUNT
    # =========================

    faculty_list = []

    try:
        if os.path.exists(FACULTY_FILE):

            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)

            if not isinstance(faculty_list, list):
                faculty_list = []

    except Exception:
        faculty_list = []

    total_faculty = len(faculty_list)


    # =========================
    # DASHBOARD
    # =========================

    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        total_faculty=total_faculty
    )

@app.route("/admin-search-faculty", methods=["GET"])
def admin_search_faculty():

    faculty_list = []

    # ==============================
    # Faculty data load
    # ==============================

    if os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)

            if not isinstance(faculty_list, list):
                faculty_list = []

        except:
            faculty_list = []


    # ==============================
    # Search value
    # ==============================

    query = request.args.get(
        "q",
        ""
    ).strip().lower()


    # ==============================
    # Search Faculty
    # ==============================

    results = []

    if query:

        for faculty in faculty_list:

            faculty_id = str(
                faculty.get(
                    "faculty_id",
                    ""
                )
            ).strip().lower()

            name = str(
                faculty.get(
                    "name",
                    ""
                )
            ).strip().lower()

            department = str(
                faculty.get(
                    "department",
                    ""
                )
            ).strip().lower()


            if (
                query in faculty_id
                or query in name
                or query in department
            ):

                results.append(faculty)


    # ==============================
    # Search result
    # ==============================

    return render_template(
        "admin_search_faculty.html",
        faculty_list=results,
        query=query
    )

# =========================
# ADMIN STUDENT MANAGEMENT
# =========================

STUDENTS_FILE = "students.json"


@app.route("/admin-students", methods=["GET", "POST"])
def admin_students():

    students = []
    courses = get_admin_courses()

    # -----------------------------
    # STUDENTS DATA LOAD
    # -----------------------------

    if os.path.exists(STUDENTS_FILE):

        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

            if not isinstance(students, list):
                students = []

        except:
            students = []

    # -----------------------------
    # COURSE NAME HELPER
    # -----------------------------

    def get_course_name(item):

        if isinstance(item, dict):

            return str(
                item.get("name")
                or item.get("course_name")
                or item.get("course")
                or item.get("Course Name")
                or ""
            ).strip()

        return str(item).strip()

    # -----------------------------
    # ADD NEW STUDENT
    # -----------------------------

    if request.method == "POST":

        student_name = request.form.get(
            "student_name", ""
        ).strip()

        enrollment = request.form.get(
            "enrollment", ""
        ).strip()

        course = request.form.get(
            "course", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()

        section = request.form.get(
            "section", ""
        ).strip().upper()

        # Required fields

        if (
            not student_name
            or not enrollment
            or not course
            or not semester
            or not section
        ):
            return "Please fill all fields."

        # Semester validation

        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:
            return "Invalid Semester."

        # Section validation

        if section not in [
            "A", "B", "C", "D"
        ]:
            return "Invalid Section."

        # -----------------------------
        # CHECK COURSE
        # -----------------------------

        valid_courses = []

        for item in courses:

            name = get_course_name(item)

            if name:
                valid_courses.append(name)

        course_found = False

        for valid_course in valid_courses:

            if valid_course.lower() == course.lower():

                course_found = True
                course = valid_course

                break

        if not course_found:
            return "Invalid Course."

        # -----------------------------
        # DUPLICATE ENROLLMENT CHECK
        # -----------------------------

        for student in students:

            old_enrollment = str(
                student.get("enrollment", "")
            ).strip()

            if old_enrollment.lower() == enrollment.lower():

                return "This Enrollment Number already exists."

        # -----------------------------
        # STUDENT ID
        # -----------------------------

        numbers = []

        for student in students:

            old_id = str(
                student.get("student_id", "")
            ).strip().upper()

            if old_id.startswith("STU"):

                try:

                    number = int(old_id[3:])
                    numbers.append(number)

                except:
                    pass

        if numbers:

            next_number = max(numbers) + 1

        else:

            next_number = 1

        student_id = (
            "STU"
            + str(next_number).zfill(3)
        )

        # -----------------------------
        # NEW STUDENT
        # -----------------------------

        student = {

            "student_id": student_id,

            "name": student_name,

            "enrollment": enrollment,

            "course": course,

            "semester": semester,

            "section": section

        }

        students.append(student)

        # -----------------------------
        # SAVE STUDENT
        # -----------------------------

        with open(STUDENTS_FILE, "w") as file:

            json.dump(
                students,
                file,
                indent=4
            )

        return redirect("/admin-students")

    # ==================================================
    # COURSE → SEMESTER → SECTION → STUDENTS
    # ==================================================

    course_structure = {}

    # -----------------------------
    # CREATE COURSES
    # -----------------------------

    for item in courses:

        course_name = get_course_name(item)

        if not course_name:
            continue

        course_key = course_name.lower().strip()

        if course_key not in course_structure:

            course_structure[course_key] = {

                "name": course_name,

                "semesters": {}

            }

            for sem in range(1, 9):

                course_structure[course_key][
                    "semesters"
                ][str(sem)] = {

                    "A": [],
                    "B": [],
                    "C": [],
                    "D": []

                }

    # -----------------------------
    # PUT STUDENTS
    # -----------------------------

    for student in students:

        student_course = str(
            student.get("course", "")
        ).strip()

        # Old data support

        if not student_course:

            student_course = str(
                student.get("department", "")
            ).strip()

        semester = str(
            student.get("semester", "")
        ).strip()

        section = str(
            student.get("section", "")
        ).strip().upper()

        if not student_course:
            continue

        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:
            continue

        if section not in [
            "A", "B", "C", "D"
        ]:
            continue

        course_key = student_course.lower()

        if course_key in course_structure:

            course_structure[course_key][
                "semesters"
            ][semester][section].append(student)

        else:

            course_structure[course_key] = {

                "name": student_course,

                "semesters": {}

            }

            for sem in range(1, 9):

                course_structure[course_key][
                    "semesters"
                ][str(sem)] = {

                    "A": [],
                    "B": [],
                    "C": [],
                    "D": []

                }

            course_structure[course_key][
                "semesters"
            ][semester][section].append(student)

    # -----------------------------
    # SHOW PAGE
    # -----------------------------

    return render_template(
        "admin_students.html",
        students=students,
        courses=courses,
        course_structure=course_structure
    )


@app.route(
    "/student-change-password",
    methods=["GET", "POST"]
)
def student_change_password():

    # Check student login
    if "student_enrollment" not in session:
        return redirect("/student-login")

    enrollment = session[
        "student_enrollment"
    ]

    students = []

    # students.json read
    if os.path.exists(
        STUDENTS_FILE
    ):

        try:

            with open(
                STUDENTS_FILE,
                "r"
            ) as file:

                students = json.load(
                    file
                )

        except:

            students = []

    student = None

    # Logged-in student find
    for item in students:

        if (
            str(
                item.get(
                    "enrollment",
                    ""
                )
            ).strip()
            ==
            str(
                enrollment
            ).strip()
        ):

            student = item
            break

    if student is None:
        return "Student not found."

    # -----------------------------
    # PASSWORD CHANGE
    # -----------------------------
    if request.method == "POST":

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        # Empty fields
        if (
            not current_password
            or not new_password
            or not confirm_password
        ):
            return "Please fill all fields."

        # Current password check
        if not check_password_hash(
            student.get(
                "password_hash",
                ""
            ),
            current_password
        ):
            return "Current password is incorrect."

        # New password confirmation
        if (
            new_password
            != confirm_password
        ):
            return "New passwords do not match."

        # New password same as old
        if (
            current_password
            == new_password
        ):
            return "New password must be different from current password."

        # New password save as HASH
        student[
            "password_hash"
        ] = generate_password_hash(
            new_password
        )

        # students.json update
        with open(
            STUDENTS_FILE,
            "w"
        ) as file:

            json.dump(
                students,
                file,
                indent=4
            )

        return redirect(
            "/student-dashboard"
        )

    return render_template(
        "student_change_password.html"
    )



@app.route("/edit-student/<student_id>", methods=["GET", "POST"])
def edit_student(student_id):

    students = []

    if os.path.exists(STUDENTS_FILE):
        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

            if not isinstance(students, list):
                students = []

        except:
            students = []


    # =========================
    # STUDENT FIND
    # =========================

    student = None

    for item in students:

        if str(
            item.get("student_id", "")
        ).strip() == str(student_id).strip():

            student = item
            break


    if student is None:
        return "Student not found."


    # =========================
    # UPDATE STUDENT
    # =========================

    if request.method == "POST":

        student_name = request.form.get(
            "student_name", ""
        ).strip()

        enrollment = request.form.get(
            "enrollment", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()

        section = request.form.get(
            "section", ""
        ).strip().upper()


        if not student_name or not enrollment or not semester or not section:

            return "Please fill all fields."


        if semester not in [
            "1", "2", "3", "4",
            "5", "6", "7", "8"
        ]:

            return "Invalid Semester."


        if section not in [
            "A", "B", "C", "D"
        ]:

            return "Invalid Section."


        # =========================
        # ENROLLMENT DUPLICATE CHECK
        # =========================

        for item in students:

            if (
                str(
                    item.get("student_id", "")
                ).strip()
                != str(student_id).strip()

                and

                str(
                    item.get("enrollment", "")
                ).strip().lower()
                == enrollment.lower()
            ):

                return "This Enrollment Number already exists."


        # =========================
        # UPDATE
        # =========================

        student["name"] = student_name

        student["enrollment"] = enrollment

        student["semester"] = semester

        student["section"] = section


        # =========================
        # SAVE
        # =========================

        with open(
            STUDENTS_FILE,
            "w"
        ) as file:

            json.dump(
                students,
                file,
                indent=4
            )


        # Search Student page par wapas
        return redirect(
            "/admin-search-student?q="
            + enrollment
        )


    # =========================
    # EDIT PAGE
    # =========================

    return render_template(
        "edit_student.html",
        student=student
    )

@app.route("/reset-student-password/<student_id>")
def reset_student_password(student_id):

    students = []

    # students.json read
    if os.path.exists(STUDENTS_FILE):

        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

        except:
            students = []

    student_found = False

    # Student find
    for student in students:

        if str(student.get("student_id", "")).strip() == str(student_id).strip():

            # Student ID ko new password banakar hash karna
            student["password_hash"] = generate_password_hash(
                student_id
            )

            student_found = True

            break

    if not student_found:
        return "Student not found."

    # Updated data save
    with open(STUDENTS_FILE, "w") as file:

        json.dump(
            students,
            file,
            indent=4
        )

    return redirect("/admin-students")

@app.route("/admin-search-student")
def admin_search_student():

    search = request.args.get("q", "").strip().lower()

    students = []

    if os.path.exists(STUDENTS_FILE):

        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)

        except:
            students = []

    results = []

    if search:

        for student in students:

            name = str(student.get("name", "")).lower()
            enrollment = str(student.get("enrollment", "")).lower()
            student_id = str(student.get("student_id", "")).lower()

            if (
                search in name
                or search in enrollment
                or search in student_id
            ):
                results.append(student)

    return render_template(
        "admin_student_search.html",
        results=results,
        search=search
    )

def fix_student_ids():

    if not os.path.exists(STUDENTS_FILE):
        print("students.json file nahi mili.")
        return

    try:
        with open(STUDENTS_FILE, "r") as file:
            students = json.load(file)
    except:
        print("students.json read nahi ho rahi.")
        return

    # Har student ko unique sequential ID do
    for i, student in enumerate(students, start=1):
        student["student_id"] = "STU" + str(i).zfill(3)

    with open(STUDENTS_FILE, "w") as file:
        json.dump(students, file, indent=4)

    print("Student IDs successfully fixed.")
    print("Total students:", len(students))

# =========================
# DELETE STUDENT
# =========================

@app.route("/delete-student/<student_id>")
def delete_student(student_id):

    students = []

    if os.path.exists(STUDENTS_FILE):

        try:
            with open(STUDENTS_FILE, "r") as file:
                students = json.load(file)
        except:
            students = []

    # जिस student की ID match हो उसे छोड़कर बाकी रखेंगे
    students = [
        student
        for student in students
        if student.get("student_id") != student_id
    ]

    # Updated data save
    with open(STUDENTS_FILE, "w") as file:
        json.dump(
            students,
            file,
            indent=4
        )

    return redirect("/admin-students")

# =========================
# ADMIN FACULTY MANAGEMENT
# =========================

FACULTY_FILE = "faculty.json"


@app.route("/admin-faculty", methods=["GET", "POST"])
def admin_faculty():

    faculty_list = []
    departments = []

    # ==============================
    # Faculty data load
    # ==============================

    if os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)

            if not isinstance(faculty_list, list):
                faculty_list = []

        except:
            faculty_list = []


    # ==============================
    # Department data load
    # ==============================

    if os.path.exists(DEPARTMENTS_FILE):

        try:
            with open(DEPARTMENTS_FILE, "r") as file:
                departments = json.load(file)

            if not isinstance(departments, list):
                departments = []

        except:
            departments = []


    # ==============================
    # ADD FACULTY
    # ==============================

    if request.method == "POST":

        name = request.form.get(
            "name", ""
        ).strip()

        department = request.form.get(
            "department", ""
        ).strip()


        if not name or not department:

            return "Please fill all fields."


        # ==============================
        # Validate Department
        # ==============================

        valid_department = None

        for dept in departments:

            dept_name = str(
                dept.get("name", "")
            ).strip()

            if dept_name.lower() == department.lower():

                valid_department = dept_name
                break


        if not valid_department:

            return "Invalid Department."


        # ==============================
        # Generate Faculty ID
        # ==============================

        existing_ids = []

        for faculty in faculty_list:

            existing_ids.append(
                str(
                    faculty.get(
                        "faculty_id", ""
                    )
                ).strip()
            )


        number = len(faculty_list) + 1

        faculty_id = (
            "FAC"
            + str(number).zfill(3)
        )


        while faculty_id in existing_ids:

            number += 1

            faculty_id = (
                "FAC"
                + str(number).zfill(3)
            )


        # ==============================
        # Initial Password
        # ==============================

        password = faculty_id


        # ==============================
        # Faculty data
        # ==============================

        faculty = {

            "faculty_id": faculty_id,

            "name": name,

            "department": valid_department,

            "password": password

        }


        faculty_list.append(faculty)


        # ==============================
        # Save Faculty
        # ==============================

        with open(
            FACULTY_FILE,
            "w"
        ) as file:

            json.dump(
                faculty_list,
                file,
                indent=4
            )


        return redirect("/admin-faculty")


    # ==============================
    # FACULTY SEARCH
    # ==============================

    search = request.args.get(
        "search",
        ""
    ).strip().lower()


    if search:

        filtered_faculty = []

        for faculty in faculty_list:

            faculty_id = str(
                faculty.get(
                    "faculty_id",
                    ""
                )
            ).lower()

            name = str(
                faculty.get(
                    "name",
                    ""
                )
            ).lower()

            department = str(
                faculty.get(
                    "department",
                    ""
                )
            ).lower()


            if (
                search in faculty_id
                or search in name
                or search in department
            ):

                filtered_faculty.append(
                    faculty
                )


        faculty_list = filtered_faculty


    # ==============================
    # Faculty page
    # ==============================

    return render_template(
        "admin_faculty.html",
        faculty_list=faculty_list,
        departments=departments,
        search=search
    )


# =========================
# DELETE FACULTY
# =========================

@app.route("/delete-faculty/<faculty_id>")
def delete_faculty(faculty_id):

    faculty_list = []

    if os.path.exists(FACULTY_FILE):

        try:
            with open(FACULTY_FILE, "r") as file:
                faculty_list = json.load(file)
        except:
            faculty_list = []

    faculty_list = [
        faculty
        for faculty in faculty_list
        if faculty.get("faculty_id") != faculty_id
    ]

    with open(FACULTY_FILE, "w") as file:

        json.dump(
            faculty_list,
            file,
            indent=4
        )

    return redirect("/admin-faculty")

@app.route("/admin-departments", methods=["GET", "POST"])
def admin_departments():

    departments = []

    if os.path.exists(DEPARTMENTS_FILE):

        try:
            with open(DEPARTMENTS_FILE, "r") as file:
                departments = json.load(file)

        except:
            departments = []

    if request.method == "POST":

        department_name = request.form.get(
            "department_name", ""
        ).strip()

        if not department_name:
            return "Please enter department name."

        # Duplicate check
        for department in departments:

            if str(
                department.get("name", "")
            ).strip().lower() == department_name.lower():

                return "This Department already exists."

        department_id = "DEPT" + str(
            len(departments) + 1
        ).zfill(3)

        department = {
            "department_id": department_id,
            "name": department_name
        }

        departments.append(department)

        with open(DEPARTMENTS_FILE, "w") as file:

            json.dump(
                departments,
                file,
                indent=4
            )

        return redirect("/admin-departments")

    return render_template(
        "admin_departments.html",
        departments=departments
    )

@app.route("/admin-courses", methods=["GET", "POST"])
def admin_courses():

    courses = []
    departments = []

    # Courses पढ़ना
    if os.path.exists(COURSES_FILE):
        try:
            with open(COURSES_FILE, "r") as file:
                courses = json.load(file)
        except:
            courses = []

    # Departments पढ़ना
    if os.path.exists(DEPARTMENTS_FILE):
        try:
            with open(DEPARTMENTS_FILE, "r") as file:
                departments = json.load(file)
        except:
            departments = []

    # नया Course add करना
    if request.method == "POST":

        course_name = request.form.get(
            "course_name", ""
        ).strip()

        department = request.form.get(
            "department", ""
        ).strip()

        if not course_name or not department:
            return "Please fill all fields."

        # Duplicate Course check
        for course in courses:

            if (
                str(course.get("name", "")).strip().lower()
                == course_name.lower()
                and
                str(course.get("department", "")).strip().lower()
                == department.lower()
            ):
                return "This Course already exists in this Department."

        # Automatic Course ID
        course_id = "COURSE" + str(
            len(courses) + 1
        ).zfill(3)

        existing_ids = []

        for course in courses:
            existing_ids.append(
                str(course.get("course_id", "")).strip()
            )

        number = len(courses) + 1

        while course_id in existing_ids:

            number += 1

            course_id = "COURSE" + str(
                number
            ).zfill(3)

        course = {
            "course_id": course_id,
            "name": course_name,
            "department": department
        }

        courses.append(course)

        with open(COURSES_FILE, "w") as file:

            json.dump(
                courses,
                file,
                indent=4
            )

        return redirect("/admin-courses")

    return render_template(
        "admin_courses.html",
        courses=courses,
        departments=departments
    )

@app.route("/edit-course/<course_id>", methods=["GET", "POST"])
def edit_course(course_id):

    courses = []
    departments = []

    if os.path.exists(COURSES_FILE):
        try:
            with open(COURSES_FILE, "r") as file:
                courses = json.load(file)
        except:
            courses = []

    if os.path.exists(DEPARTMENTS_FILE):
        try:
            with open(DEPARTMENTS_FILE, "r") as file:
                departments = json.load(file)
        except:
            departments = []

    course = None

    for item in courses:
        if str(item.get("course_id", "")).strip() == str(course_id).strip():
            course = item
            break

    if course is None:
        return "Course not found."

    if request.method == "POST":

        course_name = request.form.get("course_name", "").strip()
        department = request.form.get("department", "").strip()

        if not course_name or not department:
            return "Please fill all fields."

        for item in courses:

            if (
                str(item.get("course_id", "")).strip() != str(course_id).strip()
                and
                str(item.get("name", "")).strip().lower() == course_name.lower()
                and
                str(item.get("department", "")).strip().lower() == department.lower()
            ):
                return "This Course already exists in this Department."

        course["name"] = course_name
        course["department"] = department

        with open(COURSES_FILE, "w") as file:
            json.dump(courses, file, indent=4)

        return redirect("/admin-courses")

    return render_template(
        "edit_course.html",
        course=course,
        departments=departments
    )


@app.route("/delete-course/<course_id>")
def delete_course(course_id):

    courses = []

    if os.path.exists(COURSES_FILE):
        try:
            with open(COURSES_FILE, "r") as file:
                courses = json.load(file)
        except:
            courses = []

    courses = [
        course
        for course in courses
        if str(course.get("course_id", "")).strip()
        != str(course_id).strip()
    ]

    with open(COURSES_FILE, "w") as file:
        json.dump(courses, file, indent=4)

    return redirect("/admin-courses")

# =========================
# RUN APPLICATION
# =========================

if __name__ == "__main__":
    fix_student_ids()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)