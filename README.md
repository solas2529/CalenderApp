# 📅 Quick Calendar Event Creator

A desktop app that lets you create Google Calendar events using plain English — powered by **Gemini AI**. Supports multiple user profiles, each with their own Google account login.

---

## ✨ Features

- **Natural language event creation** — type "Dentist appointment next Friday at 10am" and it just works
- **Multi-user profiles** — multiple people can use the app on the same machine, each signed into their own Google account
- **Switch users** without restarting the app
- **Import `.ics` files** — bulk import events from any calendar export
- **Smart future-date correction** — if Gemini picks a past date, it automatically bumps it forward

---

## 🖥️ Requirements

- Python 3.11+
- A [Google Cloud project](https://console.cloud.google.com/) with the Calendar API enabled
- A [Gemini API key](https://aistudio.google.com/app/apikey)

---

## 📦 Installation

**1. Clone the repo**
```bash
git clone https://github.com/your-username/quick-calendar-event.git
cd quick-calendar-event
```

**2. Install dependencies**
```bash
pip install google-auth google-auth-oauthlib google-api-python-client google-genai
```

**3. Set up Google Calendar API credentials**

- Go to the [Google Cloud Console](https://console.cloud.google.com/)
- Create a new project (or use an existing one)
- Enable the **Google Calendar API**
- Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
- Choose **Desktop app** as the application type
- Download the credentials file and rename it to `credentials.json`
- Place it in the same folder as `calendar_app.py`

**4. Add your Gemini API key**

Create a `config.json` file in the same folder:
```json
{
  "gemini_api_key": "your_gemini_api_key_here"
}
```

Get a free API key at [Google AI Studio](https://aistudio.google.com/app/apikey).

---

## 🚀 Usage

```bash
python calendar_app.py
```

On first launch, you'll see the **Profile Selector**:

- **Existing users** — pick your name from the dropdown and click Continue
- **New users** — enter a profile name and click "Create Profile & Sign in with Google" — a browser window will open for Google OAuth

After signing in, your token is saved locally so you won't need to log in again.

### Creating an event

Type a description in plain English and press **Create Event** (or `Ctrl+Enter`):

```
Team standup every Monday at 9am
Lunch with Sarah tomorrow at noon at The Capital Grille
Flight to NYC on April 15th at 6:30am, terminal B
```

### Importing a .ics file

Click **Import .ics File**, select any `.ics` calendar export, and confirm. All events will be bulk-imported into your Google Calendar.

### Switching users

Click the **👤 username ⇄** button in the top-right corner to return to the profile selector without restarting.

---

## 📁 File Structure

```
quick-calendar-event/
├── calendar_app.py       # Main application
├── config.json           # Your Gemini API key (do not commit!)
├── credentials.json      # Google OAuth credentials (do not commit!)
├── profiles/             # Auto-created — stores per-user tokens
│   ├── alice_token.json
│   └── bob_token.json
└── README.md
```

---

## 🔒 Security Notes

> **Never commit `config.json`, `credentials.json`, or any `profiles/*.json` files to GitHub.**

Add this `.gitignore` to your repo:

```gitignore
config.json
credentials.json
profiles/
__pycache__/
*.pyc
```

---

## 🛠️ Troubleshooting

**`credentials.json not found`**
Make sure the file is in the same folder as `calendar_app.py`, not a subfolder.

**`ModuleNotFoundError`**
Run `pip install google-auth google-auth-oauthlib google-api-python-client google-genai` again.

**Event created in the wrong timezone**
The app defaults to `America/Chicago`. To change it, edit the `timeZone` default in the `get_event_json` prompt inside `calendar_app.py`.

**Google OAuth "App not verified" warning**
This is normal for personal/testing projects. Click **Advanced → Go to [app name] (unsafe)** to proceed.

---

## 📄 License

MIT License — free to use, modify, and distribute.