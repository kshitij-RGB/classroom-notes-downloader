import os
import io
import re
import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Tell oauthlib not to panic if Google reorders or renames a scope
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.me.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]
def sanitize_filename(name):
    """Removes invalid characters like |, :, ?, *, <, > from folder and file names."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def authenticate():
    """Handles Google OAuth 2.0 authentication and creates token.json."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                st.error("Missing 'credentials.json'! Please place it in the project folder.")
                st.stop()
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def download_drive_file(drive_service, file_id, file_name, save_dir):
    """Downloads a file from Google Drive, or exports it as PDF if it's a Google Doc/Slide."""
    os.makedirs(save_dir, exist_ok=True)
    safe_name = sanitize_filename(file_name)
    file_path = os.path.join(save_dir, safe_name)

    try:
        # Check file metadata (to handle Google Docs/Slides vs regular PDFs/ZIPs)
        meta = drive_service.files().get(fileId=file_id, fields="mimeType, name").execute()
        mime_type = meta.get('mimeType', '')

        if mime_type.startswith('application/vnd.google-apps.'):
            # Export Google Docs, Slides, or Sheets as PDF
            request = drive_service.files().export_media(fileId=file_id, mimeType='application/pdf')
            if not file_path.lower().endswith('.pdf'):
                file_path += '.pdf'
        else:
            # Standard binary file download (PDF, PPTX, ZIP, etc.)
            request = drive_service.files().get_media(fileId=file_id)

        # Skip if already downloaded
        if os.path.exists(file_path):
            return f"Skipped (Already exists): {os.path.basename(file_path)}"

        fh = io.FileIO(file_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.close()
        return f"Downloaded: {os.path.basename(file_path)}"

    except Exception as e:
        return f"Error downloading {safe_name}: {str(e)}"

def fetch_all_items(classroom_service, course_id):
    """Fetches both CourseWorkMaterials (Notes/Handouts) and CourseWork (Assignments)."""
    items = []
    
    # 1. Fetch CourseWorkMaterials (The bookmark icons in your screenshot)
    page_token = None
    while True:
        response = classroom_service.courses().courseWorkMaterials().list(
            courseId=course_id, pageToken=page_token).execute()
        items.extend(response.get('courseWorkMaterial', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    # 2. Fetch CourseWork (Assignments that might also contain attached PDFs/notes)
    page_token = None
    while True:
        response = classroom_service.courses().courseWork().list(
            courseId=course_id, pageToken=page_token).execute()
        items.extend(response.get('courseWork', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return items

# --- STREAMLIT UI ---
st.set_page_config(page_title="Classroom Notes Downloader", layout="wide")
st.title("📚 Google Classroom Notes Downloader")
st.write("Download all lecture notes, handouts, and materials directly into a local folder.")

# Step 1: Authentication
if st.button("🔑 Connect / Refresh Google Classroom"):
    with st.spinner("Authenticating with Google..."):
        authenticate()
        st.success("Connected successfully!")

if os.path.exists('token.json'):
    creds = authenticate()
    classroom_service = build('classroom', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)

    # Fetch Courses
    results = classroom_service.courses().list(pageSize=50).execute()
    courses = results.get('courses', [])

    if not courses:
        st.warning("No courses found in your Google Classroom account.")
    else:
        course_dict = {f"{c['name']} ({c.get('section', 'No Section')})": c['id'] for c in courses}
        selected_course_label = st.selectbox("Select your Course:", list(course_dict.keys()))
        selected_course_id = course_dict[selected_course_label]

        # Define download path
        default_folder = os.path.join(os.getcwd(), "Downloaded_Notes", sanitize_filename(selected_course_label))
        save_directory = st.text_input("Local Folder Path to Save Files:", value=default_folder)

        create_subfolders = st.checkbox(
            "Create a separate subfolder for each Lecture post (e.g., 'Lecture 18 Bloom Filter/')", 
            value=False
        )

        if st.button("🚀 Download All Notes"):
            with st.spinner("Scanning Classwork tab for materials..."):
                all_posts = fetch_all_items(classroom_service, selected_course_id)

            if not all_posts:
                st.info("No materials or posts found in this course.")
            else:
                st.write(f"Found **{len(all_posts)}** posts in Classwork. Checking for Drive attachments...")
                progress_bar = st.progress(0)
                log_area = st.empty()
                logs = []

                total_posts = len(all_posts)
                downloaded_count = 0

                for idx, post in enumerate(all_posts):
                    post_title = sanitize_filename(post.get('title', f'Untitled_{idx}'))
                    materials = post.get('materials', [])

                    for mat in materials:
                        if 'driveFile' in mat:
                            drive_info = mat['driveFile']['driveFile']
                            file_id = drive_info['id']
                            file_title = drive_info.get('title', f"{post_title}.pdf")

                            # Prefix the file with the Lecture title so everything stays sorted
                            if create_subfolders:
                                target_dir = os.path.join(save_directory, post_title)
                                final_filename = file_title
                            else:
                                target_dir = save_directory
                                final_filename = f"{post_title} - {file_title}"

                            status_msg = download_drive_file(drive_service, file_id, final_filename, target_dir)
                            logs.append(f"**{post_title}** ➔ {status_msg}")
                            downloaded_count += 1
                            log_area.markdown("\n\n".join(logs[-10:])) # Show last 10 actions

                    progress_bar.progress((idx + 1) / total_posts)

                st.success(f"🎉 Complete! Processed {downloaded_count} files. Saved to: `{save_directory}`")
                with st.expander("View Full Download Log"):
                    for log in logs:
                        st.write(log)
else:
    st.info("Click **Connect / Refresh Google Classroom** above to sign in for the first time.")