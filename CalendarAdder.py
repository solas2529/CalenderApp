from __future__ import print_function
import os
import sys
import datetime
import json
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import threading
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google import genai
from zoneinfo import ZoneInfo

# Google Calendar scope
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Load config
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, 'config.json')

if not os.path.exists(config_path):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Setup Required",
        "config.json not found!\n\n"
        "Create a config.json file in the same folder as this script:\n\n"
        '{\n  "gemini_api_key": "your_key_here"\n}\n\n'
        "Get a free API key at aistudio.google.com\n\n"
        "See README.md for detailed instructions."
    )
    sys.exit(1)

with open(config_path, 'r') as f:
    config = json.load(f)

client = genai.Client(api_key=config["gemini_api_key"])

# Profiles directory
PROFILES_DIR = os.path.join(script_dir, 'profiles')
os.makedirs(PROFILES_DIR, exist_ok=True)


def get_event_json(nl_input: str):
    """Use Gemini to convert natural language input into Google Calendar event JSON"""
    today = datetime.datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
    Today's date and time is {today} (America/Chicago - Central Time).

    Convert this event description into a valid Google Calendar event JSON.
    Input: "{nl_input}"

    Rules:
    - Output ONLY valid JSON (no explanations, no markdown).
    - Include 'summary', 'description', 'start', 'end', 'timeZone', and 'location' if possible.
    - Use ISO 8601 datetime format (e.g., 2025-09-09T19:00:00).
    - Assume timeZone = 'America/Chicago' if not specified.
    - If no end time given, default duration = 1 hour.
    - IMPORTANT: The event must NOT be in the past. If the natural language date has passed,
      choose the next future occurrence.
    """

    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

    try:
        raw = response.text.strip()

        # Remove markdown fences if Gemini adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
        raw = raw.strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

        event_data = json.loads(raw)

        # ---- SAFEGUARD: ensure event is in the future ----
        now = datetime.datetime.now(datetime.timezone.utc)

        start_str = event_data["start"]["dateTime"]
        tz_str = event_data["start"].get("timeZone", "America/Chicago")

        start_dt = datetime.datetime.fromisoformat(start_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=ZoneInfo(tz_str))
        start_utc = start_dt.astimezone(datetime.timezone.utc)

        if start_utc < now:
            print("⚠️ Gemini suggested a past date. Adjusting to next year...")
            end_dt = datetime.datetime.fromisoformat(event_data["end"]["dateTime"])
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=ZoneInfo(tz_str))

            start_dt = start_dt.replace(year=start_dt.year + 1)
            end_dt = end_dt.replace(year=end_dt.year + 1)

            event_data["start"]["dateTime"] = start_dt.isoformat()
            event_data["end"]["dateTime"] = end_dt.isoformat()

        return event_data

    except Exception as e:
        print("Error parsing Gemini output:", e)
        print("Raw output:", response.text)
        return None


def parse_ics_file(filepath: str) -> list:
    """Parse a .ics file and return a list of Google Calendar event dicts."""
    events = []
    current_event = {}
    in_event = False
    description_lines = []

    def parse_dt(value: str, tzid: str = None):
        value = value.strip()
        if len(value) == 8 and value.isdigit():
            return {"date": f"{value[:4]}-{value[4:6]}-{value[6:8]}"}
        if value.endswith("Z"):
            dt = datetime.datetime.strptime(value, "%Y%m%dT%H%M%SZ")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            tz_label = "UTC"
        elif tzid:
            dt = datetime.datetime.strptime(value, "%Y%m%dT%H%M%S")
            dt = dt.replace(tzinfo=ZoneInfo(tzid))
            tz_label = tzid
        else:
            dt = datetime.datetime.strptime(value, "%Y%m%dT%H%M%S")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            tz_label = "UTC"
        return {"dateTime": dt.isoformat(), "timeZone": tz_label}

    def unescape_ics(text: str) -> str:
        return text.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    unfolded = []
    for line in lines:
        line = line.rstrip("\r\n")
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)

    for line in unfolded:
        if line == "BEGIN:VEVENT":
            in_event = True
            current_event = {}
            description_lines = []
            continue

        if line == "END:VEVENT":
            in_event = False
            if description_lines:
                current_event["description"] = unescape_ics(" ".join(description_lines))

            gc_event = {}
            if "summary" in current_event:
                gc_event["summary"] = unescape_ics(current_event["summary"])
            if "description" in current_event:
                gc_event["description"] = current_event["description"]
            if "location" in current_event:
                gc_event["location"] = unescape_ics(current_event["location"])
            if "start" in current_event:
                gc_event["start"] = current_event["start"]
            if "end" in current_event:
                gc_event["end"] = current_event["end"]
            elif "start" in current_event:
                start_info = current_event["start"]
                if "dateTime" in start_info:
                    start_dt = datetime.datetime.fromisoformat(start_info["dateTime"])
                    end_dt = start_dt + datetime.timedelta(hours=1)
                    gc_event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": start_info.get("timeZone", "UTC")}
                elif "date" in start_info:
                    start_d = datetime.date.fromisoformat(start_info["date"])
                    end_d = start_d + datetime.timedelta(days=1)
                    gc_event["end"] = {"date": end_d.isoformat()}

            if gc_event.get("start"):
                events.append(gc_event)
            continue

        if not in_event:
            continue

        if ":" not in line:
            continue
        prop_part, _, value = line.partition(":")

        tzid = None
        if ";" in prop_part:
            parts = prop_part.split(";")
            prop_name = parts[0].upper()
            for param in parts[1:]:
                if param.upper().startswith("TZID="):
                    tzid = param[5:]
        else:
            prop_name = prop_part.upper()

        if prop_name == "SUMMARY":
            current_event["summary"] = value
        elif prop_name == "DESCRIPTION":
            description_lines = [value]
        elif prop_name == "LOCATION":
            current_event["location"] = value
        elif prop_name == "DTSTART":
            current_event["start"] = parse_dt(value, tzid)
        elif prop_name == "DTEND":
            current_event["end"] = parse_dt(value, tzid)

    return events


def get_calendar_service(username: str):
    """Get authenticated Google Calendar service for the given user profile."""
    token_path = os.path.join(PROFILES_DIR, f'{username}_token.json')
    credentials_path = os.path.join(script_dir, 'credentials.json')

    if not os.path.exists(credentials_path):
        messagebox.showerror(
            "Setup Required",
            "credentials.json not found!\n\n"
            "To set up:\n"
            "1. Go to console.cloud.google.com\n"
            "2. Enable the Google Calendar API\n"
            "3. Create an OAuth 2.0 Desktop App credential\n"
            "4. Download it and rename to credentials.json\n"
            "5. Place it in the same folder as this script\n\n"
            "See README.md for detailed instructions."
        )
        return None

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def get_profiles() -> list:
    """Return a list of existing profile names."""
    files = os.listdir(PROFILES_DIR)
    return sorted([f.replace('_token.json', '') for f in files if f.endswith('_token.json')])


def delete_profile(username: str):
    """Delete a user profile token."""
    token_path = os.path.join(PROFILES_DIR, f'{username}_token.json')
    if os.path.exists(token_path):
        os.remove(token_path)


# ─────────────────────────────────────────────
#  Profile Selector Window
# ─────────────────────────────────────────────

class ProfileSelector:
    def __init__(self, root):
        self.root = root
        self.root.title("Select Profile")
        self.root.geometry("420x380")
        self.root.resizable(False, False)
        self.selected_user = None

        self._center_window(420, 380)

        try:
            self.root.tk.call('tk', 'scaling', 2.0)
        except:
            pass

        main = ttk.Frame(root, padding="30")
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="📅 Calendar Event Creator",
                  font=("Arial", 17, "bold")).pack(pady=(0, 4))
        ttk.Label(main, text="Choose your profile to continue",
                  font=("Arial", 10), foreground="gray").pack(pady=(0, 20))

        profiles = get_profiles()

        if profiles:
            ttk.Label(main, text="Existing profiles:", font=("Arial", 11)).pack(anchor=tk.W)
            self.profile_var = tk.StringVar(value=profiles[0])
            self.combo = ttk.Combobox(main, textvariable=self.profile_var,
                                      values=profiles, state="readonly", font=("Arial", 11))
            self.combo.pack(fill=tk.X, pady=(4, 6))

            btn_row = ttk.Frame(main)
            btn_row.pack(fill=tk.X, pady=(0, 4))
            btn_row.columnconfigure(0, weight=1)
            btn_row.columnconfigure(1, weight=0)

            ttk.Button(btn_row, text="▶  Continue as this user",
                       command=self.select_profile).grid(row=0, column=0, sticky=tk.EW, ipady=7, padx=(0, 6))
            ttk.Button(btn_row, text="🗑", width=3,
                       command=self.delete_selected).grid(row=0, column=1, ipady=7)
        else:
            self.profile_var = None
            self.combo = None

        ttk.Separator(main, orient="horizontal").pack(fill=tk.X, pady=16)

        ttk.Label(main, text="New profile name:", font=("Arial", 11)).pack(anchor=tk.W)
        self.new_name_var = tk.StringVar()
        name_entry = ttk.Entry(main, textvariable=self.new_name_var, font=("Arial", 11))
        name_entry.pack(fill=tk.X, pady=(4, 8))

        ttk.Button(main, text="➕  Create Profile & Sign in with Google",
                   command=self.new_profile).pack(fill=tk.X, ipady=7)

        # Allow Enter key to submit
        self.root.bind('<Return>', lambda e: self.new_profile()
                       if self.new_name_var.get().strip() else self.select_profile() if profiles else None)

    def _center_window(self, w, h):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'{w}x{h}+{x}+{y}')

    def select_profile(self):
        if self.profile_var:
            self.selected_user = self.profile_var.get()
            self.root.quit()

    def new_profile(self):
        name = self.new_name_var.get().strip()
        if not name:
            messagebox.showerror("Error", "Please enter a profile name.")
            return
        if name in get_profiles():
            messagebox.showerror("Error", f"A profile named '{name}' already exists.")
            return
        self.selected_user = name
        self.root.quit()

    def delete_selected(self):
        if not self.profile_var:
            return
        name = self.profile_var.get()
        confirm = messagebox.askyesno("Delete Profile",
                                      f"Delete profile '{name}'?\nThis will remove their saved login.")
        if confirm:
            delete_profile(name)
            profiles = get_profiles()
            if profiles:
                self.combo['values'] = profiles
                self.profile_var.set(profiles[0])
            else:
                # No profiles left — just close and restart
                self.selected_user = None
                self.root.quit()


# ─────────────────────────────────────────────
#  Main Calendar Event GUI
# ─────────────────────────────────────────────

class CalendarEventGUI:
    def __init__(self, root, username: str):
        self.root = root
        self.username = username
        self.root.title(f"Quick Calendar Event — {username}")
        self.root.geometry("700x520")
        self.root.resizable(True, True)

        try:
            self.root.tk.call('tk', 'scaling', 2.0)
        except:
            pass

        self._center_window()

        main_frame = ttk.Frame(root, padding="30")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        # Header row: title + switch user button
        header = ttk.Frame(main_frame)
        header.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 6))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="📅 Quick Calendar Event Creator",
                  font=("Arial", 18, "bold")).grid(row=0, column=0, sticky=tk.W)

        ttk.Button(header, text=f"👤 {username}  ⇄",
                   command=self.switch_user).grid(row=0, column=1, sticky=tk.E)

        ttk.Label(main_frame, text="Describe your event:",
                  font=("Arial", 12)).grid(row=1, column=0, sticky=tk.W, pady=(10, 6))

        self.text_input = tk.Text(main_frame, height=6, width=60, wrap=tk.WORD,
                                  font=("Arial", 11), padx=15, pady=15)
        self.text_input.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        self.text_input.focus_set()

        ttk.Label(main_frame,
                  text="Examples: 'Meeting with John tomorrow at 2pm' or 'Dentist appointment next Friday at 10am'",
                  foreground="gray", font=("Arial", 10)).grid(row=3, column=0, columnspan=2,
                                                               sticky=tk.W, pady=(0, 16))

        ttk.Separator(main_frame, orient="horizontal").grid(row=4, column=0, columnspan=2,
                                                             sticky=(tk.W, tk.E), pady=(0, 16))

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)

        self.create_button = ttk.Button(button_frame, text="✏️ Create Event",
                                        command=self.create_event_threaded)
        self.create_button.grid(row=0, column=0, padx=(0, 10), sticky=(tk.W, tk.E), ipady=8)

        self.ics_button = ttk.Button(button_frame, text="📂 Import .ics File",
                                     command=self.import_ics_threaded)
        self.ics_button.grid(row=0, column=1, padx=(0, 10), sticky=(tk.W, tk.E), ipady=8)

        ttk.Button(button_frame, text="Cancel",
                   command=self.root.quit).grid(row=0, column=2, sticky=(tk.W, tk.E), ipady=8)

        self.status_label = ttk.Label(main_frame, text="Ready", foreground="green",
                                      font=("Arial", 10))
        self.status_label.grid(row=6, column=0, columnspan=2, pady=(16, 0))

        self.root.bind('<Control-Return>', lambda e: self.create_event_threaded())

    def _center_window(self):
        self.root.update_idletasks()
        w, h = 700, 520
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'{w}x{h}+{x}+{y}')

    def set_buttons_state(self, state):
        self.create_button.config(state=state)
        self.ics_button.config(state=state)

    def switch_user(self):
        """Close main window and return to profile selector."""
        self.root.quit()

    def create_event_threaded(self):
        threading.Thread(target=self.create_event, daemon=True).start()

    def import_ics_threaded(self):
        threading.Thread(target=self.import_ics, daemon=True).start()

    def create_event(self):
        event_description = self.text_input.get("1.0", tk.END).strip()

        if not event_description:
            messagebox.showerror("Error", "Please enter an event description.")
            return

        self.status_label.config(text="Creating event...", foreground="orange")
        self.set_buttons_state("disabled")
        self.root.update()

        try:
            service = get_calendar_service(self.username)
            if service is None:
                return

            self.status_label.config(text="Processing with AI...", foreground="orange")
            self.root.update()

            event = get_event_json(event_description)

            if not event:
                messagebox.showerror("Error", "Failed to process event description. Please try rephrasing.")
                return

            self.status_label.config(text="Adding to calendar...", foreground="orange")
            self.root.update()

            created_event = service.events().insert(calendarId='primary', body=event).execute()

            event_title = event.get('summary', 'Event')
            event_date = event.get('start', {}).get('dateTime', 'Unknown time')

            messagebox.showinfo("Success",
                                f"✅ Event '{event_title}' created successfully!\n\n"
                                f"📅 {event_date}\n\n"
                                f"🔗 {created_event.get('htmlLink', '')}")

            self.text_input.delete("1.0", tk.END)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to create event:\n{str(e)}")
        finally:
            self.status_label.config(text="Ready", foreground="green")
            self.set_buttons_state("normal")

    def import_ics(self):
        filepath = filedialog.askopenfilename(
            title="Select .ics file",
            filetypes=[("iCalendar files", "*.ics"), ("All files", "*.*")]
        )
        if not filepath:
            return

        self.set_buttons_state("disabled")
        self.status_label.config(text="Parsing .ics file...", foreground="orange")
        self.root.update()

        try:
            events = parse_ics_file(filepath)

            if not events:
                messagebox.showwarning("No Events Found",
                                       "No valid events were found in the selected .ics file.")
                return

            confirm = messagebox.askyesno(
                "Confirm Import",
                f"Found {len(events)} event(s) in the file.\n\nImport all of them to your Google Calendar?"
            )
            if not confirm:
                return

            service = get_calendar_service(self.username)
            if service is None:
                return

            success_count = 0
            fail_count = 0

            for i, event in enumerate(events, 1):
                self.status_label.config(
                    text=f"Importing event {i} of {len(events)}...", foreground="orange")
                self.root.update()
                try:
                    service.events().insert(calendarId='primary', body=event).execute()
                    success_count += 1
                except Exception as e:
                    print(f"Failed to import event '{event.get('summary', '?')}': {e}")
                    fail_count += 1

            result_msg = f"✅ Successfully imported {success_count} event(s)."
            if fail_count:
                result_msg += f"\n⚠️ {fail_count} event(s) failed to import."

            messagebox.showinfo("Import Complete", result_msg)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to import .ics file:\n{str(e)}")
        finally:
            self.status_label.config(text="Ready", foreground="green")
            self.set_buttons_state("normal")


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────

def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    while True:
        # Step 1: Profile selection
        root = tk.Tk()
        selector = ProfileSelector(root)
        root.mainloop()
        username = selector.selected_user
        root.destroy()

        if not username:
            break  # User closed the window without selecting

        # Step 2: Main app
        root2 = tk.Tk()
        app = CalendarEventGUI(root2, username)
        root2.protocol("WM_DELETE_WINDOW", root2.quit)
        root2.mainloop()
        root2.destroy()

        # If user clicked "Switch User", loop back to profile selector
        # If user clicked Cancel/closed window, exit
        if not getattr(app, '_switch_user', False):
            break


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error", f"Application error:\n{str(e)}")
        sys.exit(1)