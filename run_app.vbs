Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\kshit\classroom_downloader"
WshShell.Run """C:\Users\kshit\classroom_downloader\venv\Scripts\pythonw.exe"" -m streamlit run app.py", 0, False
