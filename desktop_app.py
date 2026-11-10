import os
import sys
import io
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Relax token scope check
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.me.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

def get_resource_path(relative_path):
    """Finds bundled files (like credentials.json) inside a compiled PyInstaller .exe"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_appdata_dir():
    """Stores token.json in Windows AppData (Required for Store apps)"""
    appdata = os.getenv('APPDATA') or os.path.expanduser('~')
    path = os.path.join(appdata, "ClassroomNotesDownloader")
    os.makedirs(path, exist_ok=True)
    return path

def sanitize_filename(name):
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ClassroomDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Google Classroom Notes Downloader")
        self.geometry("780x580")
        self.minsize(680, 500)

        self.creds = None
        self.courses_map = {}

        # Header
        self.title_label = ctk.CTkLabel(self, text="📚 Google Classroom Notes Downloader", font=("Segoe UI", 22, "bold"))
        self.title_label.pack(pady=(20, 5))

        self.sub_label = ctk.CTkLabel(self, text="Download all lecture PDFs, slides, and materials into a local folder.", text_color="gray")
        self.sub_label.pack(pady=(0, 15))

        # Top Frame: Auth & Course Selection
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.pack(fill="x", padx=20, pady=5)

        self.auth_btn = ctk.CTkButton(self.top_frame, text="🔑 Connect Google Account", command=self.start_auth_thread, width=220)
        self.auth_btn.grid(row=0, column=0, padx=15, pady=15)

        self.course_dropdown = ctk.CTkOptionMenu(self.top_frame, values=["Sign in to load courses..."], width=460)
        self.course_dropdown.grid(row=0, column=1, padx=15, pady=15, sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        # Middle Frame: Folder & Options
        self.mid_frame = ctk.CTkFrame(self)
        self.mid_frame.pack(fill="x", padx=20, pady=10)

        default_dir = os.path.join(os.path.expanduser("~"), "Downloads", "Classroom_Notes")
        self.folder_var = tk.StringVar(value=default_dir)

        self.folder_entry = ctk.CTkEntry(self.mid_frame, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, padx=(15, 10), pady=15, sticky="ew")

        self.browse_btn = ctk.CTkButton(self.mid_frame, text="📁 Browse Folder", width=140, command=self.browse_folder)
        self.browse_btn.grid(row=0, column=1, padx=(0, 15), pady=15)

        self.subfolder_var = tk.BooleanVar(value=False)
        self.subfolder_check = ctk.CTkCheckBox(
            self.mid_frame,
            text="Create a separate subfolder for each Lecture post",
            variable=self.subfolder_var
        )
        self.subfolder_check.grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 15), sticky="w")
        self.mid_frame.grid_columnconfigure(0, weight=1)

        # Download Button & Progress Bar
        self.download_btn = ctk.CTkButton(
            self, text="🚀 Download All Notes", font=("Segoe UI", 15, "bold"),
            height=42, fg_color="#28a745", hover_color="#218838",
            state="disabled", command=self.start_download_thread
        )
        self.download_btn.pack(fill="x", padx=20, pady=(5, 10))

        self.progress = ctk.CTkProgressBar(self)
        self.progress.pack(fill="x", padx=20, pady=5)
        self.progress.set(0)

        # Log Output Box
        self.log_box = ctk.CTkTextbox(self, height=200, font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(5, 20))

        # Auto-login if token already exists
        token_path = os.path.join(get_appdata_dir(), 'token.json')
        if os.path.exists(token_path):
            self.start_auth_thread()

    def log(self, message):
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")

    def browse_folder(self):
        selected = filedialog.askdirectory(initialdir=self.folder_var.get())
        if selected:
            self.folder_var.set(os.path.normpath(selected))

    def start_auth_thread(self):
        self.auth_btn.configure(state="disabled", text="Authenticating...")
        threading.Thread(target=self.authenticate_and_load, daemon=True).start()

    def authenticate_and_load(self):
        try:
            token_path = os.path.join(get_appdata_dir(), 'token.json')
            cred_path = get_resource_path('credentials.json')

            if os.path.exists(token_path):
                self.creds = Credentials.from_authorized_user_file(token_path, SCOPES)

            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    self.creds.refresh(Request())
                else:
                    if not os.path.exists(cred_path):
                        self.log("❌ Error: credentials.json not found!")
                        self.auth_btn.configure(state="normal", text="🔑 Connect Google Account")
                        return
                    flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
                    self.creds = flow.run_local_server(port=0)
                with open(token_path, 'w') as token:
                    token.write(self.creds.to_json())

            self.log("✅ Connected to Google Classroom! Fetching courses...")
            classroom_service = build('classroom', 'v1', credentials=self.creds)
            results = classroom_service.courses().list(pageSize=50).execute()
            courses = results.get('courses', [])

            if not courses:
                self.log("⚠️ No courses found in this Google account.")
            else:
                self.courses_map = {f"{c['name']} ({c.get('section', 'No Section')})": c['id'] for c in courses}
                course_names = list(self.courses_map.keys())
                self.course_dropdown.configure(values=course_names)
                self.course_dropdown.set(course_names[0])
                self.download_btn.configure(state="normal")
                self.log(f"📚 Loaded {len(course_names)} courses. Ready to download!")

            self.auth_btn.configure(state="normal", text="🔄 Switch / Refresh Account")
        except Exception as e:
            self.log(f"❌ Auth Error: {str(e)}")
            self.auth_btn.configure(state="normal", text="🔑 Connect Google Account")

    def start_download_thread(self):
        self.download_btn.configure(state="disabled", text="⏳ Downloading...")
        self.progress.set(0)
        threading.Thread(target=self.download_notes, daemon=True).start()

    def download_notes(self):
        try:
            course_label = self.course_dropdown.get()
            course_id = self.courses_map[course_label]
            base_dir = os.path.join(self.folder_var.get(), sanitize_filename(course_label))

            classroom_service = build('classroom', 'v1', credentials=self.creds)
            drive_service = build('drive', 'v3', credentials=self.creds)

            self.log(f"\n🔍 Scanning '{course_label}' for materials...")
            items = []

            page_token = None
            while True:
                res = classroom_service.courses().courseWorkMaterials().list(courseId=course_id, pageToken=page_token).execute()
                items.extend(res.get('courseWorkMaterial', []))
                page_token = res.get('nextPageToken')
                if not page_token:
                    break

            page_token = None
            while True:
                res = classroom_service.courses().courseWork().list(courseId=course_id, pageToken=page_token).execute()
                items.extend(res.get('courseWork', []))
                page_token = res.get('nextPageToken')
                if not page_token:
                    break

            if not items:
                self.log("ℹ️ No posts found in this course.")
                self.download_btn.configure(state="normal", text="🚀 Download All Notes")
                return

            total = len(items)
            count = 0
            for idx, post in enumerate(items):
                post_title = sanitize_filename(post.get('title', f'Untitled_{idx}'))
                for mat in post.get('materials', []):
                    if 'driveFile' in mat:
                        drive_info = mat['driveFile']['driveFile']
                        file_id = drive_info['id']
                        file_title = drive_info.get('title', f"{post_title}.pdf")

                        if self.subfolder_var.get():
                            target_dir = os.path.join(base_dir, post_title)
                            final_name = file_title
                        else:
                            target_dir = base_dir
                            final_name = f"{post_title} - {file_title}"

                        msg = self.download_single_file(drive_service, file_id, final_name, target_dir)
                        self.log(f"[{idx+1}/{total}] {post_title} -> {msg}")
                        count += 1

                self.progress.set((idx + 1) / total)

            self.log(f"\n🎉 Done! Processed {count} files into:\n{base_dir}")
            messagebox.showinfo("Download Complete", f"Processed {count} files!\nSaved in: {base_dir}")
        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
        finally:
            self.download_btn.configure(state="normal", text="🚀 Download All Notes")

    def download_single_file(self, drive_service, file_id, file_name, save_dir):
        os.makedirs(save_dir, exist_ok=True)
        safe_name = sanitize_filename(file_name)
        file_path = os.path.join(save_dir, safe_name)

        try:
            meta = drive_service.files().get(fileId=file_id, fields="mimeType").execute()
            mime = meta.get('mimeType', '')

            if mime.startswith('application/vnd.google-apps.'):
                request = drive_service.files().export_media(fileId=file_id, mimeType='application/pdf')
                if not file_path.lower().endswith('.pdf'):
                    file_path += '.pdf'
            else:
                request = drive_service.files().get_media(fileId=file_id)

            if os.path.exists(file_path):
                return "Skipped (Already exists)"

            fh = io.FileIO(file_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.close()
            return f"Downloaded ({os.path.basename(file_path)})"
        except Exception as e:
            return f"Failed ({str(e)})"

if __name__ == "__main__":
    app = ClassroomDownloaderApp()
    app.mainloop()