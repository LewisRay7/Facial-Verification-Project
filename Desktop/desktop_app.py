from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import threading
from time import perf_counter
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

ASSET_DIR = ROOT_DIR / "Assets"

import cv2
from PIL import Image, ImageTk

from SRC.config import CAPTURE_DIR, PHOTO_DIR, ensure_directories
from SRC.database import (
    add_student,
    add_verification_log,
    dashboard_summary,
    get_student_by_number,
    init_db,
    list_logs,
    list_students,
    search_students,
    set_student_active,
    update_student_photo,
)
from SRC.face_matcher import (
    FaceMatchError,
    generate_face_embedding,
    identify_face_from_embeddings,
    verify_faces,
)


DEFAULT_IDENTIFY_THRESHOLD = 0.60
DEFAULT_MIN_DISTANCE_GAP = 0.08
SCANNER_SIZE = (640, 480)

COLORS = {
    "app_bg": "#0b1120",
    "panel": "#111827",
    "panel_alt": "#172554",
    "border": "#334155",
    "blue_border": "#2563eb",
    "muted": "#cbd5e1",
    "text": "#f8fafc",
    "subtle_text": "#e5e7eb",
    "input": "#0f172a",
    "primary": "#06b6d4",
    "primary_hover": "#22d3ee",
    "primary_text": "#082f49",
    "selected": "#0e7490",
    "ok": "#22c55e",
    "ok_text": "#052e16",
    "warn": "#facc15",
    "warn_text": "#422006",
    "blocked": "#f97316",
    "blocked_text": "#431407",
    "unknown": "#22d3ee",
    "unknown_text": "#083344",
}


class DesktopExamVerificationApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        ensure_directories()
        init_db()

        self.title("Exam Verification System")
        self.geometry("1120x720")
        self.minsize(980, 640)
        self.configure(bg=COLORS["app_bg"])
        self._set_window_icon()

        self.selected_photo_path: Path | None = None
        self.verify_camera = None
        self.scanner_camera = None
        self.scanner_running = False
        self.scanner_previous_box = None
        self.scanner_stable_start = None
        self.scanner_last_recognition = 0.0
        self.photo_refs: list[ImageTk.PhotoImage] = []

        self._style()
        self._build_layout()
        self.refresh_all()

    def _set_window_icon(self) -> None:
        logo_path = ASSET_DIR / "exam_verification_logo.png"
        if not logo_path.exists():
            return
        try:
            self.logo_image = tk.PhotoImage(file=str(logo_path))
            self.iconphoto(True, self.logo_image)
        except tk.TclError:
            pass

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=COLORS["app_bg"], foreground=COLORS["text"], fieldbackground=COLORS["panel"])
        style.configure("TNotebook", background=COLORS["app_bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#1e293b", foreground=COLORS["subtle_text"], padding=(16, 10))
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["primary"])],
            foreground=[("selected", "#ffffff")],
        )
        style.configure("TFrame", background=COLORS["app_bg"])
        style.configure("Hero.TFrame", background=COLORS["panel_alt"], relief="solid", borderwidth=1)
        style.configure("Panel.TFrame", background=COLORS["panel"], relief="solid", borderwidth=1)
        style.configure("TLabel", background=COLORS["app_bg"], foreground=COLORS["subtle_text"])
        style.configure("Title.TLabel", background=COLORS["panel_alt"], foreground="#ffffff", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["panel_alt"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"])
        style.configure("Metric.TLabel", background=COLORS["panel"], foreground="#ffffff", font=("Segoe UI", 18, "bold"))
        style.configure("StatusOk.TLabel", background=COLORS["ok"], foreground=COLORS["ok_text"], font=("Segoe UI", 10, "bold"), padding=(10, 5))
        style.configure("StatusWarn.TLabel", background=COLORS["warn"], foreground=COLORS["warn_text"], font=("Segoe UI", 10, "bold"), padding=(10, 5))
        style.configure("StatusBlocked.TLabel", background=COLORS["blocked"], foreground=COLORS["blocked_text"], font=("Segoe UI", 10, "bold"), padding=(10, 5))
        style.configure("StatusUnknown.TLabel", background=COLORS["unknown"], foreground=COLORS["unknown_text"], font=("Segoe UI", 10, "bold"), padding=(10, 5))
        style.configure("TButton", background=COLORS["primary"], foreground=COLORS["primary_text"], font=("Segoe UI", 10, "bold"), padding=8, borderwidth=1)
        style.map("TButton", background=[("active", COLORS["primary_hover"])])
        style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", COLORS["panel"])], foreground=[("active", COLORS["text"])])
        style.configure("TCombobox", fieldbackground=COLORS["input"], background=COLORS["input"], foreground=COLORS["text"])
        style.configure("Treeview", background=COLORS["panel"], foreground=COLORS["text"], fieldbackground=COLORS["panel"], rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background="#1e293b", foreground="#ffffff", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", COLORS["selected"])], foreground=[("selected", "#ffffff")])

    def _build_layout(self) -> None:
        header = ttk.Frame(self, style="Hero.TFrame", padding=(20, 16))
        header.pack(fill="x", padx=16, pady=(14, 8))
        ttk.Label(header, text="Automated Exam Verification System", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Offline desktop prototype for student face verification and exam eligibility checks.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=12)

        self.dashboard_tab = ttk.Frame(self.notebook)
        self.register_tab = ttk.Frame(self.notebook)
        self.students_tab = ttk.Frame(self.notebook)
        self.verify_tab = ttk.Frame(self.notebook)
        self.scanner_tab = ttk.Frame(self.notebook)
        self.logs_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.add(self.register_tab, text="Register")
        self.notebook.add(self.students_tab, text="Students")
        self.notebook.add(self.verify_tab, text="Verify")
        self.notebook.add(self.scanner_tab, text="Auto Scanner")
        self.notebook.add(self.logs_tab, text="Logs")

        self._build_dashboard()
        self._build_register()
        self._build_students()
        self._build_verify()
        self._build_scanner()
        self._build_logs()

    def _panel(self, parent) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        panel.pack(fill="both", expand=True, padx=8, pady=8)
        return panel

    def _build_dashboard(self) -> None:
        panel = self._panel(self.dashboard_tab)
        self.dashboard_labels = {}
        for label in ("Registered students", "Verification attempts", "Verified", "Not verified", "Errors"):
            row = ttk.Frame(panel, style="Panel.TFrame")
            row.pack(fill="x", pady=6)
            ttk.Label(row, text=label, style="Muted.TLabel", width=26).pack(side="left")
            value = ttk.Label(row, text="0", style="Metric.TLabel")
            value.pack(side="left")
            self.dashboard_labels[label] = value
        ttk.Button(panel, text="Refresh dashboard", command=self.refresh_all).pack(anchor="w", pady=14)

    def _build_register(self) -> None:
        panel = self._panel(self.register_tab)
        form = ttk.Frame(panel, style="Panel.TFrame")
        form.pack(anchor="nw", fill="x")

        self.reg_student_number = self._entry_row(form, "Student number")
        self.reg_full_name = self._entry_row(form, "Full name")
        self.reg_program = self._entry_row(form, "Program / class")
        self.reg_eligible = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Eligible to write exam", variable=self.reg_eligible).pack(anchor="w", pady=6)
        self.reg_note = self._entry_row(form, "Eligibility note")

        ttk.Button(form, text="Choose student photo", command=self.choose_registration_photo).pack(anchor="w", pady=8)
        self.reg_photo_label = ttk.Label(form, text="No photo selected", style="Muted.TLabel")
        self.reg_photo_label.pack(anchor="w")
        ttk.Button(form, text="Register student", command=self.register_student).pack(anchor="w", pady=12)

    def _entry_row(self, parent, label: str) -> tk.Entry:
        ttk.Label(parent, text=label, style="Panel.TLabel").pack(anchor="w", pady=(8, 2))
        entry = tk.Entry(
            parent,
            bg=COLORS["input"],
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["primary"],
            highlightthickness=1,
            width=48,
        )
        entry.pack(anchor="w", ipady=7)
        return entry

    def _build_students(self) -> None:
        panel = self._panel(self.students_tab)
        controls = ttk.Frame(panel, style="Panel.TFrame")
        controls.pack(fill="x")
        self.students_search = self._entry_row(controls, "Search")
        ttk.Button(controls, text="Search / refresh", command=self.refresh_students).pack(anchor="w", pady=8)

        columns = ("id", "student_number", "full_name", "program", "eligible", "active", "embedding")
        self.students_tree = ttk.Treeview(panel, columns=columns, show="headings", height=12)
        for column in columns:
            self.students_tree.heading(column, text=column.replace("_", " ").title())
            self.students_tree.column(column, width=135 if column != "id" else 50)
        self.students_tree.pack(fill="both", expand=True, pady=10)

        buttons = ttk.Frame(panel, style="Panel.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Generate / refresh embedding", command=self.refresh_selected_embedding).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Deactivate", command=lambda: self.set_selected_student_active(False)).pack(side="left", padx=8)
        ttk.Button(buttons, text="Reactivate", command=lambda: self.set_selected_student_active(True)).pack(side="left", padx=8)

    def _build_verify(self) -> None:
        panel = self._panel(self.verify_tab)
        top = ttk.Frame(panel, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Select student", style="Panel.TLabel").pack(anchor="w")
        self.verify_student = ttk.Combobox(top, state="readonly", width=58)
        self.verify_student.pack(anchor="w", pady=6)
        self.verify_status = ttk.Label(panel, text="Camera ready.", style="Muted.TLabel")
        self.verify_status.pack(anchor="w", pady=8)
        buttons = ttk.Frame(panel, style="Panel.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Start camera", command=self.start_verify_camera).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Capture and verify", command=self.capture_and_verify_selected).pack(side="left", padx=8)
        ttk.Button(buttons, text="Stop camera", command=self.stop_verify_camera).pack(side="left", padx=8)
        self.verify_image_label = ttk.Label(panel, style="Panel.TLabel")
        self.verify_image_label.pack(anchor="w", pady=10)
        self.verify_result = ttk.Label(panel, text="", style="Panel.TLabel", font=("Segoe UI", 12, "bold"))
        self.verify_result.pack(anchor="w", pady=8)

    def _build_scanner(self) -> None:
        panel = self._panel(self.scanner_tab)
        settings = ttk.Frame(panel, style="Panel.TFrame")
        settings.pack(fill="x")
        self.scan_threshold = tk.DoubleVar(value=DEFAULT_IDENTIFY_THRESHOLD)
        self.scan_gap = tk.DoubleVar(value=DEFAULT_MIN_DISTANCE_GAP)
        self.scan_stable = tk.DoubleVar(value=0.8)
        self.scan_cooldown = tk.DoubleVar(value=2.5)
        self._spin_row(settings, "Maximum L2 distance", self.scan_threshold, 0.1, 1.4)
        self._spin_row(settings, "Minimum gap", self.scan_gap, 0.0, 0.3)
        self._spin_row(settings, "Stable seconds", self.scan_stable, 0.5, 2.0)
        self._spin_row(settings, "Cooldown seconds", self.scan_cooldown, 1.0, 5.0)
        buttons = ttk.Frame(panel, style="Panel.TFrame")
        buttons.pack(fill="x", pady=8)
        ttk.Button(buttons, text="Start scanner", command=self.start_scanner).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Stop scanner", command=self.stop_scanner).pack(side="left", padx=8)
        self.scanner_status = ttk.Label(panel, text="Scanner stopped.", style="Muted.TLabel", font=("Segoe UI", 12, "bold"))
        self.scanner_status.pack(anchor="w", pady=8)
        self.scanner_image_label = ttk.Label(panel, style="Panel.TLabel")
        self.scanner_image_label.pack(anchor="w", pady=8)
        self.scanner_result = ttk.Label(panel, text="", style="Panel.TLabel", font=("Segoe UI", 12, "bold"))
        self.scanner_result.pack(anchor="w", pady=8)

    def _spin_row(self, parent, label: str, variable: tk.DoubleVar, from_: float, to: float) -> None:
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(anchor="w", pady=4)
        ttk.Label(row, text=label, style="Panel.TLabel", width=22).pack(side="left")
        tk.Spinbox(
            row,
            from_=from_,
            to=to,
            increment=0.01,
            textvariable=variable,
            width=8,
            bg=COLORS["input"],
            fg="#ffffff",
            insertbackground="#ffffff",
            buttonbackground=COLORS["primary"],
            relief="flat",
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["primary"],
            highlightthickness=1,
        ).pack(side="left")

    def _build_logs(self) -> None:
        panel = self._panel(self.logs_tab)
        ttk.Button(panel, text="Refresh logs", command=self.refresh_logs).pack(anchor="w", pady=(0, 10))
        columns = ("verified_at", "student_number", "full_name", "result", "score", "threshold", "backend")
        self.logs_tree = ttk.Treeview(panel, columns=columns, show="headings", height=18)
        for column in columns:
            self.logs_tree.heading(column, text=column.replace("_", " ").title())
            self.logs_tree.column(column, width=145)
        self.logs_tree.pack(fill="both", expand=True)

    def choose_registration_photo(self) -> None:
        filename = filedialog.askopenfilename(
            title="Choose student photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png")],
        )
        if filename:
            self.selected_photo_path = Path(filename)
            self.reg_photo_label.configure(text=str(self.selected_photo_path))

    def register_student(self) -> None:
        student_number = self.reg_student_number.get().strip()
        full_name = self.reg_full_name.get().strip()
        program = self.reg_program.get().strip()
        note = self.reg_note.get().strip()
        if not student_number or not full_name or self.selected_photo_path is None:
            messagebox.showerror("Missing details", "Student number, full name, and photo are required.")
            return

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        destination = PHOTO_DIR / f"{safe_file_part(student_number)}_{timestamp}.jpg"
        try:
            self._copy_resized_photo(self.selected_photo_path, destination)
            embedding_result = generate_face_embedding(destination)
            embedding, backend = embedding_result if embedding_result else (None, None)
            existing = get_student_by_number(student_number)
            if existing:
                update_student_photo(int(existing["id"]), destination, embedding, backend)
                messagebox.showinfo("Updated", "Student existed, so the stored photo was updated.")
            else:
                add_student(
                    student_number,
                    full_name,
                    program,
                    destination,
                    face_embedding=embedding,
                    embedding_backend=backend,
                    exam_eligible=self.reg_eligible.get(),
                    eligibility_note=note,
                )
                messagebox.showinfo("Registered", "Student registered successfully.")
            self.refresh_all()
        except Exception as exc:
            messagebox.showerror("Registration failed", str(exc))

    def _copy_resized_photo(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(exist_ok=True)
        image = Image.open(source).convert("RGB")
        image.thumbnail((900, 900))
        image.save(destination, format="JPEG", quality=88)

    def refresh_all(self) -> None:
        self.refresh_dashboard()
        self.refresh_students()
        self.refresh_verify_students()
        self.refresh_logs()

    def refresh_dashboard(self) -> None:
        summary = dashboard_summary()
        values = {
            "Registered students": summary["total_students"],
            "Verification attempts": summary["total_attempts"],
            "Verified": summary["verified_attempts"],
            "Not verified": summary["failed_attempts"],
            "Errors": summary["error_attempts"],
        }
        for label, value in values.items():
            self.dashboard_labels[label].configure(text=str(value))

    def refresh_students(self) -> None:
        self.students_tree.delete(*self.students_tree.get_children())
        rows = search_students(self.students_search.get(), active_only=False)
        for row in rows:
            self.students_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["student_number"],
                    row["full_name"],
                    row["program"] or "",
                    "Eligible" if row["exam_eligible"] else "Not eligible",
                    "Active" if row["active"] else "Inactive",
                    row["embedding_backend"] or "Missing",
                ),
            )

    def refresh_verify_students(self) -> None:
        self.active_students = [dict(row) for row in list_students(active_only=True)]
        values = [f"{row['id']} | {row['student_number']} | {row['full_name']}" for row in self.active_students]
        self.verify_student.configure(values=values)
        if values and not self.verify_student.get():
            self.verify_student.set(values[0])

    def refresh_logs(self) -> None:
        self.logs_tree.delete(*self.logs_tree.get_children())
        for row in list_logs(limit=200):
            self.logs_tree.insert(
                "",
                "end",
                values=(
                    row["verified_at"],
                    row["student_number"],
                    row["full_name"],
                    row["result"],
                    "" if row["score"] is None else f"{float(row['score']):.4f}",
                    "" if row["match_threshold"] is None else f"{float(row['match_threshold']):.2f}",
                    row["backend"],
                ),
            )

    def selected_student_id_from_tree(self) -> int | None:
        selection = self.students_tree.selection()
        if not selection:
            messagebox.showwarning("Select student", "Select a student first.")
            return None
        return int(self.students_tree.item(selection[0], "values")[0])

    def refresh_selected_embedding(self) -> None:
        student_id = self.selected_student_id_from_tree()
        if student_id is None:
            return
        student = next((dict(row) for row in list_students(active_only=False) if int(row["id"]) == student_id), None)
        if student is None:
            return
        photo_path = Path(student["photo_path"])
        if not photo_path.exists():
            messagebox.showerror("Missing photo", "The stored student photo is missing.")
            return
        self._run_background(
            "Generating embedding...",
            self._refresh_embedding_worker,
            student_id,
            photo_path,
        )

    def _refresh_embedding_worker(self, student_id: int, photo_path: Path) -> None:
        embedding_result = generate_face_embedding(photo_path)
        if not embedding_result:
            raise FaceMatchError("Could not generate FaceNet embedding.")
        embedding, backend = embedding_result
        update_student_photo(student_id, photo_path, embedding, backend)

    def set_selected_student_active(self, active: bool) -> None:
        student_id = self.selected_student_id_from_tree()
        if student_id is None:
            return
        set_student_active(student_id, active)
        self.refresh_all()

    def start_verify_camera(self) -> None:
        if self.verify_camera is None:
            self.verify_camera = cv2.VideoCapture(0)
        if not self.verify_camera.isOpened():
            self.verify_status.configure(text="Could not open webcam.")
            self.verify_camera = None
            return
        self.verify_status.configure(text="Camera running.")
        self.update_verify_frame()

    def update_verify_frame(self) -> None:
        if self.verify_camera is None:
            return
        ok, frame = self.verify_camera.read()
        if ok:
            frame = cv2.resize(frame, SCANNER_SIZE)
            self.latest_verify_frame = frame
            self._show_frame(self.verify_image_label, frame)
        self.after(80, self.update_verify_frame)

    def stop_verify_camera(self) -> None:
        if self.verify_camera is not None:
            self.verify_camera.release()
            self.verify_camera = None
        self.verify_status.configure(text="Camera stopped.")

    def capture_and_verify_selected(self) -> None:
        if not hasattr(self, "latest_verify_frame"):
            messagebox.showwarning("No frame", "Start the camera first.")
            return
        selected = self.verify_student.get()
        if not selected:
            messagebox.showwarning("No student", "Select a student first.")
            return
        student_id = int(selected.split("|", 1)[0].strip())
        student = next((row for row in self.active_students if int(row["id"]) == student_id), None)
        if student is None:
            return
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        capture_path = CAPTURE_DIR / f"desktop_verify_{timestamp}.jpg"
        cv2.imwrite(str(capture_path), self.latest_verify_frame)
        self._run_background(
            "Verifying selected student...",
            self._verify_worker,
            student,
            capture_path,
            status_label=self.verify_status,
        )

    def _verify_worker(self, student: dict, capture_path: Path) -> None:
        start = perf_counter()
        result = verify_faces(
            Path(student["photo_path"]),
            capture_path,
            reference_embedding=student["face_embedding"],
            facenet_threshold=0.45,
            backend_preference="auto",
        )
        duration_ms = (perf_counter() - start) * 1000
        status = "VERIFIED" if result.is_match else "NOT VERIFIED"
        add_verification_log(
            int(student["id"]),
            status,
            result.score,
            result.backend,
            capture_path,
            duration_ms=duration_ms,
            match_threshold=0.45,
        )
        message = f"{status} | Score: {result.score:.4f} | Time: {duration_ms / 1000:.2f}s"
        result_style = "StatusOk.TLabel" if result.is_match else "StatusBlocked.TLabel"
        self.after(0, lambda: self.verify_result.configure(text=message, style=result_style))

    def start_scanner(self) -> None:
        if self.scanner_running:
            return
        self.embedded_students = [dict(row) for row in list_students(active_only=True) if row["face_embedding"]]
        if not self.embedded_students:
            messagebox.showwarning("No embeddings", "Generate FaceNet embeddings first.")
            return
        self.scanner_camera = cv2.VideoCapture(0)
        if not self.scanner_camera.isOpened():
            self.scanner_camera = None
            messagebox.showerror("Camera error", "Could not open webcam.")
            return
        self.scanner_running = True
        self.scanner_status.configure(text="Scanning face...")
        self.update_scanner_frame()

    def stop_scanner(self) -> None:
        self.scanner_running = False
        if self.scanner_camera is not None:
            self.scanner_camera.release()
            self.scanner_camera = None
        self.scanner_status.configure(text="Scanner stopped.")

    def update_scanner_frame(self) -> None:
        if not self.scanner_running or self.scanner_camera is None:
            return
        ok, frame = self.scanner_camera.read()
        if not ok:
            self.scanner_status.configure(text="Could not read webcam frame.")
            self.stop_scanner()
            return

        frame = cv2.resize(frame, SCANNER_SIZE)
        face_box = detect_largest_face_box(frame)
        now = perf_counter()
        if face_box is None:
            self.scanner_previous_box = None
            self.scanner_stable_start = None
            self.scanner_status.configure(text="Scanning face...")
        else:
            x, y, width, height = face_box
            cv2.rectangle(frame, (x, y), (x + width, y + height), (34, 211, 238), 2)
            if face_box_is_stable(self.scanner_previous_box, face_box):
                if self.scanner_stable_start is None:
                    self.scanner_stable_start = now
                stable_duration = now - self.scanner_stable_start
                if stable_duration < self.scan_stable.get():
                    self.scanner_status.configure(text="Hold still...")
                elif now - self.scanner_last_recognition >= self.scan_cooldown.get():
                    self.scanner_status.configure(text="Processing face recognition...")
                    self.scanner_last_recognition = now
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    capture_path = CAPTURE_DIR / f"desktop_scanner_{timestamp}.jpg"
                    cv2.imwrite(str(capture_path), frame)
                    self._run_background(
                        "Processing face recognition...",
                        self._scanner_recognition_worker,
                        capture_path,
                    )
                    self.scanner_stable_start = None
                else:
                    remaining = self.scan_cooldown.get() - (now - self.scanner_last_recognition)
                    self.scanner_status.configure(text=f"Cooldown active: {remaining:.1f}s")
            else:
                self.scanner_stable_start = None
                self.scanner_status.configure(text="Hold still...")
            self.scanner_previous_box = face_box

        self._show_frame(self.scanner_image_label, frame)
        self.after(80, self.update_scanner_frame)

    def _scanner_recognition_worker(self, capture_path: Path) -> None:
        start = perf_counter()
        result = identify_face_from_embeddings(
            capture_path,
            self.embedded_students,
            facenet_threshold=self.scan_threshold.get(),
            min_distance_gap=self.scan_gap.get(),
        )
        duration_ms = (perf_counter() - start) * 1000
        student = next((row for row in self.embedded_students if int(row["id"]) == result.student_id), None)
        if result.status == "VERIFIED" and student:
            log_status = "VERIFIED"
            add_verification_log(
                int(student["id"]),
                log_status,
                result.score,
                result.backend,
                capture_path,
                duration_ms=duration_ms,
                match_threshold=self.scan_threshold.get(),
            )
            eligible = "Eligible" if student["exam_eligible"] else "Not eligible"
            message = (
                f"Verified: {student['full_name']} ({student['student_number']}) | "
                f"{eligible} | Distance {result.score:.4f} | Time {duration_ms / 1000:.2f}s"
            )
            result_style = "StatusOk.TLabel" if student["exam_eligible"] else "StatusBlocked.TLabel"
        elif result.status == "LOW_CONFIDENCE" and student:
            message = (
                f"Low confidence: {student['full_name']} ({student['student_number']}) | "
                f"Distance {result.score:.4f} | Suggested threshold {result.suggested_threshold:.2f}"
            )
            result_style = "StatusWarn.TLabel"
        else:
            message = (
                f"Unknown student | Best distance {result.score:.4f} | "
                f"Threshold {self.scan_threshold.get():.2f} | Suggested {result.suggested_threshold:.2f}"
            )
            result_style = "StatusUnknown.TLabel"
        self.after(0, lambda: self.scanner_result.configure(text=message, style=result_style))

    def _show_frame(self, label: ttk.Label, frame) -> None:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame_rgb)
        photo = ImageTk.PhotoImage(image=image)
        self.photo_refs.append(photo)
        self.photo_refs = self.photo_refs[-4:]
        label.configure(image=photo)

    def _run_background(self, status: str, worker, *args, status_label: ttk.Label | None = None) -> None:
        target_status = status_label or self.scanner_status
        target_status.configure(text=status)

        def wrapped() -> None:
            try:
                worker(*args)
                self.after(0, self.refresh_all)
                self.after(0, lambda: target_status.configure(text="Ready."))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Operation failed", str(exc)))
                self.after(0, lambda: target_status.configure(text="Operation failed."))

        threading.Thread(target=wrapped, daemon=True).start()

    def on_close(self) -> None:
        self.stop_verify_camera()
        self.stop_scanner()
        self.destroy()


def safe_file_part(value: str) -> str:
    cleaned = "".join(char for char in value.strip() if char.isalnum() or char in ("-", "_"))
    return cleaned or "student"


def detect_largest_face_box(frame) -> tuple[int, int, int, int] | None:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80),
    )
    if len(faces) == 0:
        return None
    x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
    return int(x), int(y), int(width), int(height)


def face_box_is_stable(
    previous_box: tuple[int, int, int, int] | None,
    current_box: tuple[int, int, int, int],
    max_shift: int = 35,
) -> bool:
    if previous_box is None:
        return False
    return all(abs(current - previous) <= max_shift for current, previous in zip(current_box, previous_box))


if __name__ == "__main__":
    app = DesktopExamVerificationApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
